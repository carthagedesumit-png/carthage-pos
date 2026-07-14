"""Authorized user, assignment, password, session, and audit operations."""
import json, re
from datetime import UTC, datetime

from auth import (ROLE_ADMIN, ROLE_CASHIER, ROLE_MANAGER, _insert_user, hash_password,
                  validate_role, validate_session, verify_password)
from app.core.token_utils import token_hash
from app.core.exceptions import AuthorizationError, ValidationError
from app.core.validation import normalized_email, required_text
from app.database.db_manager import get_connection
from app.database.transactions import transaction
from app.stores.store_service import search_stores

ROLE_AUDITOR, ROLE_INVENTORY_OFFICER = "auditor", "inventory_officer"
MANAGER_ROLES = {ROLE_CASHIER, ROLE_AUDITOR, ROLE_INVENTORY_OFFICER}
PERMISSIONS = {
    ROLE_ADMIN: ["administration.manage", "users.manage", "stores.all", "inventory.manage", "reports.view"],
    ROLE_MANAGER: ["administration.limited", "users.manage_non_privileged", "stores.assigned", "inventory.manage"],
    ROLE_CASHIER: ["sales.process", "store.home"],
    ROLE_AUDITOR: ["reports.view", "audit.view", "stores.assigned_read"],
    ROLE_INVENTORY_OFFICER: ["inventory.manage", "stores.assigned"],
}

def require_administration_access(session):
    session = validate_session(session)
    if session.role not in {ROLE_ADMIN, ROLE_MANAGER}:
        raise AuthorizationError("Administration access is limited to administrators and managers.")
    return session

def create_managed_user(session, *, username, password, full_name, role, email=None,
                        store_ids=None, home_store_id=None, force_password_change=True):
    session = require_administration_access(session); validate_role(role); _require_role(session, role)
    validate_password_strength(password); email = normalized_email(email)
    stores, home = _validate_assignments(role, store_ids, home_store_id)
    user = _insert_user(username, password, full_name, role, home_store_id=home)
    try:
        with transaction() as conn:
            _unique_email(conn, email)
            conn.execute("UPDATE users SET email=?, force_password_change=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         (email, int(bool(force_password_change)), user["id"]))
            _replace_assignments(conn, user["id"], role, stores, home)
            _audit(conn, user["id"], session.user_id, "USER_CREATED", {"role": role})
    except Exception:
        with transaction() as conn:
            conn.execute("DELETE FROM user_store_access WHERE user_id=?", (user["id"],))
            conn.execute("DELETE FROM users WHERE id=?", (user["id"],))
        raise
    return get_managed_user(session, user["id"])

def update_managed_user(session, user_id, *, full_name, role, email=None,
                        store_ids=None, home_store_id=None):
    session = require_administration_access(session); current = _target(session, user_id)
    validate_role(role); _require_role(session, role); full_name = required_text(full_name, "Full name")
    email = normalized_email(email); stores, home = _validate_assignments(role, store_ids, home_store_id)
    with transaction() as conn:
        _unique_email(conn, email, user_id)
        conn.execute("UPDATE users SET full_name=?,role=?,email=?,home_store_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (full_name, role, email, home, user_id))
        _replace_assignments(conn, user_id, role, stores, home)
        _audit(conn, user_id, session.user_id, "USER_UPDATED", {"old_role": current["role"], "new_role": role})
    return get_managed_user(session, user_id)

def set_user_active(session, user_id, active):
    session = require_administration_access(session); _target(session, user_id)
    if session.user_id == int(user_id) and not active: raise AuthorizationError("You cannot deactivate your own account.")
    with transaction() as conn:
        conn.execute("UPDATE users SET is_active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (int(bool(active)), user_id))
        if not active: _revoke_user_sessions(conn, user_id)
        _audit(conn, user_id, session.user_id, "USER_ACTIVATED" if active else "USER_DEACTIVATED")
    return get_managed_user(session, user_id)

def set_user_locked(session, user_id, locked):
    session = require_administration_access(session); _target(session, user_id)
    if session.user_id == int(user_id) and locked: raise AuthorizationError("You cannot lock your own account.")
    with transaction() as conn:
        conn.execute("UPDATE users SET is_locked=?,failed_login_count=CASE WHEN ? THEN failed_login_count ELSE 0 END,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (int(bool(locked)), int(bool(locked)), user_id))
        if locked: _revoke_user_sessions(conn, user_id)
        _audit(conn, user_id, session.user_id, "USER_LOCKED" if locked else "USER_UNLOCKED")
    return get_managed_user(session, user_id)

def reset_user_password(session, user_id, temporary_password=None):
    session = require_administration_access(session); _target(session, user_id)
    password = temporary_password
    if not password: raise ValidationError("A temporary password is required.")
    validate_password_strength(password)
    with transaction() as conn:
        current = conn.execute("SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
        recent = conn.execute("SELECT password_hash FROM user_password_history WHERE user_id=? ORDER BY id DESC LIMIT 5", (user_id,)).fetchall()
        if verify_password(password, current["password_hash"]) or any(verify_password(password, r["password_hash"]) for r in recent):
            raise ValidationError("The temporary password must not reuse a recent password.")
        conn.execute("INSERT INTO user_password_history(user_id,password_hash,changed_by) VALUES(?,?,?)",
                     (user_id, current["password_hash"], session.user_id))
        conn.execute("UPDATE users SET password_hash=?,force_password_change=1,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (hash_password(password), user_id)); _revoke_user_sessions(conn, user_id)
        _audit(conn, user_id, session.user_id, "PASSWORD_RESET")
    return {"force_password_change": True}

def change_own_password(session, current_password, new_password, current_token):
    session = validate_session(session); validate_password_strength(new_password)
    with transaction() as conn:
        current = conn.execute("SELECT password_hash FROM users WHERE id=?", (session.user_id,)).fetchone()
        if not current or not verify_password(current_password, current["password_hash"]):
            raise ValidationError("Current password is incorrect.")
        recent = conn.execute("SELECT password_hash FROM user_password_history WHERE user_id=? ORDER BY id DESC LIMIT 5", (session.user_id,)).fetchall()
        if verify_password(new_password,current["password_hash"]) or any(verify_password(new_password,r["password_hash"]) for r in recent):
            raise ValidationError("The new password must not reuse a recent password.")
        conn.execute("INSERT INTO user_password_history(user_id,password_hash,changed_by) VALUES(?,?,?)",(session.user_id,current["password_hash"],session.user_id))
        conn.execute("UPDATE users SET password_hash=?,force_password_change=0,updated_at=CURRENT_TIMESTAMP WHERE id=?",(hash_password(new_password),session.user_id))
        conn.execute("UPDATE api_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE user_id=? AND token_hash!=? AND revoked_at IS NULL",(session.user_id,token_hash(current_token)))
        _audit(conn,session.user_id,session.user_id,"PASSWORD_CHANGED")

def list_user_sessions(session, user_id):
    session = require_administration_access(session); _target(session, user_id, True); now = datetime.now(UTC)
    with get_connection() as conn:
        rows = conn.execute("SELECT session_reference,store_id,created_at,expires_at,last_used_at,revoked_at FROM api_sessions WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()
    return [{**dict(r), "is_active": not r["revoked_at"] and datetime.fromisoformat(r["expires_at"]) > now} for r in rows]

def terminate_session(session, user_id, reference):
    session = require_administration_access(session); _target(session, user_id, True)
    with transaction() as conn:
        changed = conn.execute("UPDATE api_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE user_id=? AND session_reference=? AND revoked_at IS NULL", (user_id, reference)).rowcount
        if not changed: raise ValidationError("Active session not found.")
        _audit(conn, user_id, session.user_id, "SESSION_TERMINATED")

def terminate_other_sessions(session, current_token):
    session = require_administration_access(session)
    with transaction() as conn:
        count = conn.execute("UPDATE api_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE user_id=? AND token_hash!=? AND revoked_at IS NULL", (session.user_id, token_hash(current_token))).rowcount
        _audit(conn, session.user_id, session.user_id, "OTHER_SESSIONS_TERMINATED", {"count": count})
    return count

def get_managed_user(session, user_id):
    session = require_administration_access(session); target = _target(session, user_id, True)
    with get_connection() as conn:
        stores = [dict(r) for r in conn.execute("SELECT s.id,s.code,s.name FROM stores s JOIN user_store_access a ON a.store_id=s.id WHERE a.user_id=? ORDER BY s.name", (user_id,)).fetchall()]
        audit = [dict(r) for r in conn.execute("SELECT event_type,details,created_at FROM user_audit_events WHERE user_id=? ORDER BY id DESC LIMIT 20", (user_id,)).fetchall()]
        history = conn.execute("SELECT COUNT(*) FROM user_password_history WHERE user_id=?", (user_id,)).fetchone()[0]
    target["active_status"] = "locked" if target["is_locked"] else ("active" if target["is_active"] else "inactive")
    target["home_store"] = next((s["name"] for s in stores if s["id"] == target["home_store_id"]), "")
    target["assigned_stores"] = ", ".join(s["name"] for s in stores)
    return {**target, "stores": stores, "permissions": PERMISSIONS.get(target["role"], []), "audit": audit,
            "password_history_count": history, "sessions": list_user_sessions(session, user_id)}

def administration_form_options(session):
    session = require_administration_access(session)
    return {"roles": sorted(PERMISSIONS) if session.role == ROLE_ADMIN else sorted(MANAGER_ROLES),
            "stores": search_stores(), "permissions": PERMISSIONS}

def validate_password_strength(password):
    password = str(password or "")
    if len(password)<12 or not re.search(r"[A-Z]",password) or not re.search(r"[a-z]",password) or not re.search(r"\d",password) or not re.search(r"[^A-Za-z0-9]",password):
        raise ValidationError("Password must be at least 12 characters and include upper-case, lower-case, number, and symbol.")
    return password

def _target(session, user_id, allow_self=False):
    with get_connection() as conn:
        row = conn.execute("SELECT id,username,full_name,role,email,is_active,is_locked,failed_login_count,force_password_change,home_store_id,created_at,updated_at,last_login FROM users WHERE id=? AND username!='system'", (user_id,)).fetchone()
    if not row: raise ValidationError("User does not exist.")
    target = dict(row)
    if session.role==ROLE_MANAGER and target["role"] in {ROLE_ADMIN,ROLE_MANAGER} and not (allow_self and session.user_id==target["id"]):
        raise AuthorizationError("Managers cannot manage administrator or manager accounts.")
    return target

def _require_role(session, role):
    if session.role==ROLE_MANAGER and role not in MANAGER_ROLES: raise AuthorizationError("Managers cannot grant administrator or manager privileges.")

def _validate_assignments(role, store_ids, home_store_id):
    ids=sorted({int(x) for x in (store_ids or [])}); home=int(home_store_id) if home_store_id else (ids[0] if ids else None)
    if role==ROLE_ADMIN: return [], home or 1
    if not ids or home not in ids: raise ValidationError("A home store must be selected from the assigned stores.")
    if role==ROLE_CASHIER and len(ids)!=1: raise ValidationError("Cashiers must be assigned to exactly one store.")
    with get_connection() as conn: count=conn.execute(f"SELECT COUNT(*) FROM stores WHERE is_active=1 AND id IN ({','.join('?' for _ in ids)})",ids).fetchone()[0]
    if count!=len(ids): raise ValidationError("One or more assigned stores are inactive or unavailable.")
    return ids,home

def _replace_assignments(conn,user_id,role,ids,home):
    conn.execute("DELETE FROM user_store_access WHERE user_id=?",(user_id,))
    if role!=ROLE_ADMIN:
        conn.executemany("INSERT INTO user_store_access(user_id,store_id) VALUES(?,?)",[(user_id,x) for x in ids])
        conn.execute("UPDATE users SET home_store_id=? WHERE id=?",(home,user_id))

def _unique_email(conn,email,exclude=None):
    if not email:return
    params=[email]; clause=""
    if exclude: clause=" AND id!=?";params.append(exclude)
    if conn.execute(f"SELECT 1 FROM users WHERE email=? COLLATE NOCASE{clause}",params).fetchone(): raise ValidationError("Email already exists.")

def _revoke_user_sessions(conn,user_id): conn.execute("UPDATE api_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE user_id=? AND revoked_at IS NULL",(user_id,))
def _audit(conn,user,actor,event,details=None): conn.execute("INSERT INTO user_audit_events(user_id,acting_user_id,event_type,details) VALUES(?,?,?,?)",(user,actor,event,json.dumps(details or {},sort_keys=True)))
