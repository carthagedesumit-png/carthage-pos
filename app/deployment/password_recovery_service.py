"""Elevated local recovery using the shared administration password policy."""
import ctypes
import os
from pathlib import Path

from auth import ROLE_ADMIN, hash_password, normalize_username, verify_password
from app.administration.user_service import validate_password_strength
from app.core.config import parse_environment_file, reset_config_cache
from app.core.exceptions import InstallationError, ValidationError
from app.database.transactions import transaction
from app.deployment.audit import record_deployment_event
from app.deployment.installer_service import get_deployment_state


def reset_local_admin_password(installation_directory, username, new_password, *, elevated=None):
    if elevated is None:
        elevated = _is_elevated()
    if not elevated:
        raise InstallationError("Administrator password recovery requires an elevated local operator.")
    validate_password_strength(new_password)
    state = get_deployment_state(installation_directory)
    if not state.get("installed"):
        raise InstallationError("Installed deployment state was not found.")
    environment = parse_environment_file(state["configuration_file"])
    previous = os.environ.get("CARTHAGE_POS_DB")
    try:
        os.environ["CARTHAGE_POS_DB"] = environment["CARTHAGE_POS_DB"]
        reset_config_cache()
        with transaction() as conn:
            row = conn.execute(
                "SELECT id,password_hash,role,is_active FROM users WHERE username=?",
                (normalize_username(username),),
            ).fetchone()
            if not row or row["role"] != ROLE_ADMIN:
                raise ValidationError("The specified local administrator account is unavailable.")
            if verify_password(new_password, row["password_hash"]):
                raise ValidationError("The new password must differ from the current password.")
            conn.execute("INSERT INTO user_password_history(user_id,password_hash,changed_by) VALUES(?,?,?)",
                         (row["id"], row["password_hash"], row["id"]))
            conn.execute("UPDATE users SET password_hash=?,force_password_change=1,failed_login_count=0,is_locked=0,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         (hash_password(new_password), row["id"]))
            conn.execute("UPDATE api_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE user_id=? AND revoked_at IS NULL", (row["id"],))
            conn.execute("INSERT INTO user_audit_events(user_id,acting_user_id,event_type,details) VALUES(?,?,?,?)",
                         (row["id"], row["id"], "LOCAL_ADMIN_PASSWORD_RECOVERY", "{}"))
    finally:
        if previous is None:
            os.environ.pop("CARTHAGE_POS_DB", None)
        else:
            os.environ["CARTHAGE_POS_DB"] = previous
        reset_config_cache()
    record_deployment_event(str(Path(installation_directory)), "administrator_password_recovered", username=normalize_username(username))
    return {"reset": True, "username": normalize_username(username), "sessions_revoked": True,
            "force_password_change": True}


def _is_elevated():
    if os.name == "nt":
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return hasattr(os, "geteuid") and os.geteuid() == 0
