from sqlite3 import IntegrityError
from typing import Any, Optional

from auth import require_inventory_management
from app.database.db_manager import get_connection


Supplier = dict[str, Any]


def create_supplier(
    session: Any,
    name: str,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    address: Optional[str] = None,
) -> Supplier:
    """Create an active supplier after manager-level authorization."""
    require_inventory_management(session)
    normalized_name = _required(name, "Supplier name")
    normalized_email = _normalize_email(email)

    with get_connection() as conn:
        _ensure_unique_supplier(conn, normalized_name, normalized_email)
        try:
            cursor = conn.execute(
                """INSERT INTO suppliers (name, phone, email, address, is_active)
                   VALUES (?, ?, ?, ?, 1)""",
                (normalized_name, _optional(phone), normalized_email, _optional(address)),
            )
            supplier_id = cursor.lastrowid
        except IntegrityError as exc:
            raise ValueError("Supplier name already exists.") from exc
    return get_supplier_by_id(supplier_id)


def update_supplier(session: Any, supplier_id: int, **updates: Any) -> Supplier:
    """Update supplier contact details without replacing purchase history."""
    require_inventory_management(session)
    allowed = {"name", "phone", "email", "address"}
    changes = {key: value for key, value in updates.items() if key in allowed}
    if not changes:
        supplier = get_supplier_by_id(supplier_id)
        if not supplier:
            raise ValueError("Supplier not found.")
        return supplier

    if "name" in changes:
        changes["name"] = _required(changes["name"], "Supplier name")
    for field in ("phone", "address"):
        if field in changes:
            changes[field] = _optional(changes[field])
    if "email" in changes:
        changes["email"] = _normalize_email(changes["email"])

    with get_connection() as conn:
        current = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        if not current:
            raise ValueError("Supplier not found.")
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
    return get_supplier_by_id(supplier_id)


def deactivate_supplier(session: Any, supplier_id: int) -> Supplier:
    """Soft-deactivate a supplier while preserving all purchase references."""
    require_inventory_management(session)
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE suppliers SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (supplier_id,),
        )
        if cursor.rowcount == 0:
            raise ValueError("Supplier not found.")
    return get_supplier_by_id(supplier_id)


def reactivate_supplier(session: Any, supplier_id: int) -> Supplier:
    """Reactivate an existing supplier record."""
    require_inventory_management(session)
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE suppliers SET is_active = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (supplier_id,),
        )
        if cursor.rowcount == 0:
            raise ValueError("Supplier not found.")
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
        raise ValueError("Supplier name already exists.")

    if email:
        email_params: list[Any] = [email]
        if exclude_id is not None:
            email_params.append(exclude_id)
        if conn.execute(
            f"SELECT id FROM suppliers WHERE email = ? COLLATE NOCASE{exclusion}",
            email_params,
        ).fetchone():
            raise ValueError("Supplier email already exists.")


def _required(value: Any, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{label} is required.")
    return normalized


def _optional(value: Any) -> Optional[str]:
    normalized = str(value or "").strip()
    return normalized or None


def _normalize_email(value: Any) -> Optional[str]:
    normalized = _optional(value)
    return normalized.lower() if normalized else None
