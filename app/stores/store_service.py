from sqlite3 import IntegrityError
from typing import Any, Optional

from auth import (
    ROLE_ADMIN,
    ROLE_MANAGER,
    AuthorizationError,
    require_store_access,
    require_user_management,
    validate_session,
)
from app.core.exceptions import StoreError
from app.core.logging_utils import get_logger, log_event
from app.core.validation import normalized_email, optional_text, required_text
from app.database.db_manager import get_connection
from app.database.transactions import transaction


Store = dict[str, Any]
logger = get_logger("stores")


def create_store(
    session: Any,
    code: str,
    name: str,
    address: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    manager_user_id: Optional[int] = None,
) -> Store:
    """Create an active store; only administrators may expand the company."""
    session = require_user_management(session)
    code = _required(code, "Store code").upper()
    name = _required(name, "Store name")
    with transaction() as conn:
        _validate_manager(conn, manager_user_id)
        try:
            cursor = conn.execute(
                """INSERT INTO stores (
                       code, name, address, phone, email, manager_user_id, is_active
                   ) VALUES (?, ?, ?, ?, ?, ?, 1)""",
                (
                    code,
                    name,
                    _optional(address),
                    _optional(phone),
                    _normalize_email(email),
                    manager_user_id,
                ),
            )
            store_id = cursor.lastrowid
            conn.execute(
                """INSERT OR IGNORE INTO store_inventory (
                       store_id, product_id, quantity_on_hand, reorder_level, average_cost
                   )
                   SELECT ?, id, 0, reorder_level, COALESCE(cost_price, 0)
                   FROM products""",
                (store_id,),
            )
            if manager_user_id:
                conn.execute(
                    "INSERT OR IGNORE INTO user_store_access (user_id, store_id) VALUES (?, ?)",
                    (manager_user_id, store_id),
                )
        except IntegrityError as exc:
            raise StoreError("Store code already exists.") from exc
    log_event(logger, "store_created", store_id=store_id, code=code, user_id=session.user_id)
    return get_store_by_id(store_id)


def update_store(session: Any, store_id: int, **updates: Any) -> Store:
    """Update an accessible store without replacing historical references."""
    session = validate_session(session)
    if session.role != ROLE_ADMIN:
        require_store_access(session, store_id, manage=True)
    allowed = {"code", "name", "address", "phone", "email", "manager_user_id"}
    changes = {key: value for key, value in updates.items() if key in allowed}
    if not changes:
        store = get_store_by_id(store_id)
        if not store:
            raise StoreError("Store not found.")
        return store
    if session.role != ROLE_ADMIN and ("code" in changes or "manager_user_id" in changes):
        raise AuthorizationError("Only administrators can change store codes or managers.")
    if "code" in changes:
        changes["code"] = _required(changes["code"], "Store code").upper()
    if "name" in changes:
        changes["name"] = _required(changes["name"], "Store name")
    for field in ("address", "phone"):
        if field in changes:
            changes[field] = _optional(changes[field])
    if "email" in changes:
        changes["email"] = _normalize_email(changes["email"])

    with transaction() as conn:
        if not conn.execute("SELECT 1 FROM stores WHERE id = ?", (store_id,)).fetchone():
            raise StoreError("Store not found.")
        if "manager_user_id" in changes:
            _validate_manager(conn, changes["manager_user_id"])
        assignments = ", ".join(f"{field} = ?" for field in changes)
        try:
            conn.execute(
                f"UPDATE stores SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [*changes.values(), store_id],
            )
            if changes.get("manager_user_id"):
                conn.execute(
                    "INSERT OR IGNORE INTO user_store_access (user_id, store_id) VALUES (?, ?)",
                    (changes["manager_user_id"], store_id),
                )
        except IntegrityError as exc:
            raise StoreError("Store code already exists.") from exc
    log_event(logger, "store_updated", store_id=store_id, user_id=session.user_id)
    return get_store_by_id(store_id)


def deactivate_store(session: Any, store_id: int) -> Store:
    """Soft-deactivate a non-default store while retaining all history."""
    session = require_user_management(session)
    with transaction() as conn:
        store = conn.execute("SELECT code FROM stores WHERE id = ?", (store_id,)).fetchone()
        if not store:
            raise StoreError("Store not found.")
        if store["code"].upper() == "MAIN":
            raise StoreError("The default MAIN store cannot be deactivated.")
        conn.execute(
            "UPDATE stores SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (store_id,),
        )
    log_event(logger, "store_deactivated", store_id=store_id, user_id=session.user_id)
    return get_store_by_id(store_id)


def reactivate_store(session: Any, store_id: int) -> Store:
    """Reactivate a historical store record."""
    session = require_user_management(session)
    with transaction() as conn:
        cursor = conn.execute(
            "UPDATE stores SET is_active = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (store_id,),
        )
        if cursor.rowcount == 0:
            raise StoreError("Store not found.")
    log_event(logger, "store_reactivated", store_id=store_id, user_id=session.user_id)
    return get_store_by_id(store_id)


def assign_user_to_store(
    session: Any,
    user_id: int,
    store_id: int,
    make_home: bool = False,
) -> dict[str, Any]:
    """Grant store access and optionally make it the user's home store."""
    session = require_user_management(session)
    with transaction() as conn:
        user = conn.execute("SELECT id, role FROM users WHERE id = ?", (user_id,)).fetchone()
        store = conn.execute(
            "SELECT id FROM stores WHERE id = ? AND is_active = 1", (store_id,)
        ).fetchone()
        if not user:
            raise StoreError("User not found.")
        if not store:
            raise StoreError("Store not found or inactive.")
        if user["role"] == "cashier" and not make_home:
            raise StoreError("Cashier assignment must set the cashier's home store.")
        conn.execute(
            "INSERT OR IGNORE INTO user_store_access (user_id, store_id) VALUES (?, ?)",
            (user_id, store_id),
        )
        if make_home:
            conn.execute("UPDATE users SET home_store_id = ? WHERE id = ?", (store_id, user_id))
            if user["role"] == "cashier":
                conn.execute(
                    "DELETE FROM user_store_access WHERE user_id = ? AND store_id != ?",
                    (user_id, store_id),
                )
    log_event(
        logger,
        "user_store_assigned",
        user_id=user_id,
        store_id=store_id,
        acting_user_id=session.user_id,
        make_home=make_home,
    )
    return get_user_store_assignment(user_id)


def get_user_store_assignment(user_id: int) -> dict[str, Any]:
    """Return a user's home store and explicit accessible stores."""
    with get_connection() as conn:
        user = conn.execute(
            "SELECT id, username, role, home_store_id FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not user:
            raise ValueError("User not found.")
        stores = [
            dict(row)
            for row in conn.execute(
                """SELECT s.* FROM stores s
                   JOIN user_store_access usa ON usa.store_id = s.id
                   WHERE usa.user_id = ? ORDER BY s.name""",
                (user_id,),
            ).fetchall()
        ]
    return {"user": dict(user), "stores": stores}


def search_stores(term: Optional[str] = None, include_inactive: bool = False) -> list[Store]:
    """Search stores by code, name, or contact details."""
    filters = []
    params: list[Any] = []
    if not include_inactive:
        filters.append("s.is_active = 1")
    if term and term.strip():
        pattern = f"%{term.strip()}%"
        filters.append("(s.code LIKE ? OR s.name LIKE ? OR s.address LIKE ? OR s.phone LIKE ?)")
        params.extend([pattern, pattern, pattern, pattern])
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    with get_connection() as conn:
        return [
            dict(row)
            for row in conn.execute(
                f"""SELECT s.*, u.username AS manager_username
                    FROM stores s LEFT JOIN users u ON u.id = s.manager_user_id
                    {where_clause} ORDER BY s.name""",
                params,
            ).fetchall()
        ]


def get_store_by_id(store_id: int) -> Optional[Store]:
    """Return one store regardless of active state."""
    with get_connection() as conn:
        row = conn.execute(
            """SELECT s.*, u.username AS manager_username
               FROM stores s LEFT JOIN users u ON u.id = s.manager_user_id
               WHERE s.id = ?""",
            (store_id,),
        ).fetchone()
    return dict(row) if row else None


def get_default_store_id() -> int:
    """Return the compatibility MAIN store id."""
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM stores WHERE code = 'MAIN' COLLATE NOCASE").fetchone()
    if not row:
        raise ValueError("Default MAIN store is not configured.")
    return row["id"]


def _validate_manager(conn: Any, manager_user_id: Optional[int]) -> None:
    if manager_user_id is None:
        return
    row = conn.execute(
        "SELECT role, is_active FROM users WHERE id = ?", (manager_user_id,)
    ).fetchone()
    if not row or not row["is_active"] or row["role"] not in {ROLE_ADMIN, ROLE_MANAGER}:
        raise ValueError("Store manager must be an active manager or administrator.")


def _required(value: Any, label: str) -> str:
    return required_text(value, label, error_type=StoreError)


def _optional(value: Any) -> Optional[str]:
    return optional_text(value)


def _normalize_email(value: Any) -> Optional[str]:
    return normalized_email(value)
