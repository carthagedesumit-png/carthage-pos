from sqlite3 import IntegrityError
from typing import Any, Optional

from auth import require_inventory_management
from app.core.exceptions import ProcurementError
from app.core.logging_utils import get_logger, log_event
from app.core.validation import normalized_email, optional_text, required_text
from app.database.db_manager import get_connection
from app.database.transactions import transaction


Supplier = dict[str, Any]
logger = get_logger("suppliers")


def create_supplier(
    session: Any,
    name: str,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    address: Optional[str] = None,
) -> Supplier:
    """Create an active supplier after manager-level authorization."""
    session = require_inventory_management(session)
    normalized_name = _required(name, "Supplier name")
    normalized_email = _normalize_email(email)

    with transaction() as conn:
        _ensure_unique_supplier(conn, normalized_name, normalized_email)
        try:
            cursor = conn.execute(
                """INSERT INTO suppliers (name, phone, email, address, is_active)
                   VALUES (?, ?, ?, ?, 1)""",
                (normalized_name, _optional(phone), normalized_email, _optional(address)),
            )
            supplier_id = cursor.lastrowid
        except IntegrityError as exc:
            raise ProcurementError("Supplier name already exists.") from exc
    log_event(logger, "supplier_created", supplier_id=supplier_id, user_id=session.user_id)
    return get_supplier_by_id(supplier_id)


def update_supplier(session: Any, supplier_id: int, **updates: Any) -> Supplier:
    """Update supplier contact details without replacing purchase history."""
    session = require_inventory_management(session)
    allowed = {"name", "phone", "email", "address"}
    changes = {key: value for key, value in updates.items() if key in allowed}
    if not changes:
        supplier = get_supplier_by_id(supplier_id)
        if not supplier:
            raise ProcurementError("Supplier not found.")
        return supplier

    if "name" in changes:
        changes["name"] = _required(changes["name"], "Supplier name")
    for field in ("phone", "address"):
        if field in changes:
            changes[field] = _optional(changes[field])
    if "email" in changes:
        changes["email"] = _normalize_email(changes["email"])

    with transaction() as conn:
        current = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        if not current:
            raise ProcurementError("Supplier not found.")
        _ensure_unique_supplier(
            conn,
            changes.get("name", current["name"]),
            changes.get("email", current["email"]),
            exclude_id=supplier_id,
        )
        assignments = ", ".join(f"{field} = ?" for field in changes)
        conn.execute(
            f"UPDATE suppliers SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [*changes.values(), supplier_id],
        )
    log_event(logger, "supplier_updated", supplier_id=supplier_id, user_id=session.user_id)
    return get_supplier_by_id(supplier_id)


def deactivate_supplier(session: Any, supplier_id: int) -> Supplier:
    """Soft-deactivate a supplier while preserving all purchase references."""
    session = require_inventory_management(session)
    with transaction() as conn:
        cursor = conn.execute(
            "UPDATE suppliers SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (supplier_id,),
        )
        if cursor.rowcount == 0:
            raise ProcurementError("Supplier not found.")
    log_event(logger, "supplier_deactivated", supplier_id=supplier_id, user_id=session.user_id)
    return get_supplier_by_id(supplier_id)


def reactivate_supplier(session: Any, supplier_id: int) -> Supplier:
    """Reactivate an existing supplier record."""
    session = require_inventory_management(session)
    with transaction() as conn:
        cursor = conn.execute(
            "UPDATE suppliers SET is_active = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (supplier_id,),
        )
        if cursor.rowcount == 0:
            raise ProcurementError("Supplier not found.")
    log_event(logger, "supplier_reactivated", supplier_id=supplier_id, user_id=session.user_id)
    return get_supplier_by_id(supplier_id)


def search_suppliers(
    term: Optional[str] = None,
    include_inactive: bool = False,
) -> list[Supplier]:
    """Search suppliers by name, phone, email, or address."""
    filters = []
    params: list[Any] = []
    if not include_inactive:
        filters.append("is_active = 1")
    if term and term.strip():
        pattern = f"%{term.strip()}%"
        filters.append("(name LIKE ? OR phone LIKE ? OR email LIKE ? OR address LIKE ?)")
        params.extend([pattern, pattern, pattern, pattern])
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    with get_connection() as conn:
        return [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM suppliers {where_clause} ORDER BY name COLLATE NOCASE",
                params,
            ).fetchall()
        ]


def get_supplier_by_id(supplier_id: int) -> Optional[Supplier]:
    """Return a supplier regardless of active state."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
    return dict(row) if row else None


def _ensure_unique_supplier(
    conn: Any,
    name: str,
    email: Optional[str],
    exclude_id: Optional[int] = None,
) -> None:
    params: list[Any] = [name]
    exclusion = ""
    if exclude_id is not None:
        exclusion = " AND id != ?"
        params.append(exclude_id)
    if conn.execute(
        f"SELECT id FROM suppliers WHERE name = ? COLLATE NOCASE{exclusion}", params
    ).fetchone():
        raise ProcurementError("Supplier name already exists.")

    if email:
        email_params: list[Any] = [email]
        if exclude_id is not None:
            email_params.append(exclude_id)
        if conn.execute(
            f"SELECT id FROM suppliers WHERE email = ? COLLATE NOCASE{exclusion}",
            email_params,
        ).fetchone():
            raise ProcurementError("Supplier email already exists.")


def _required(value: Any, label: str) -> str:
    return required_text(value, label, error_type=ProcurementError)


def _optional(value: Any) -> Optional[str]:
    return optional_text(value)


def _normalize_email(value: Any) -> Optional[str]:
    return normalized_email(value)
