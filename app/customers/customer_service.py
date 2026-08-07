"""Customer directory and customer-group management services."""

from sqlite3 import IntegrityError
from typing import Any, Optional

from app.core.config import get_config
from app.core.exceptions import CustomerError
from app.core.logging_utils import get_logger, log_event
from app.core.validation import iso_date, normalized_email, optional_text, required_text
from app.customers.common import ledger_balance, require_customer
from app.customers.permissions import require_customer_access, require_customer_management
from app.database.db_manager import get_connection
from app.database.transactions import transaction


logger = get_logger("customers")


def create_customer(
    session: Any, first_name: str, last_name: str,
    business_name: Optional[str] = None, phone_number: Optional[str] = None,
    email: Optional[str] = None, address: Optional[str] = None,
    city: Optional[str] = None, state: Optional[str] = None,
    country: Optional[str] = None, date_of_birth: Optional[str] = None,
    gender: Optional[str] = None, tax_number: Optional[str] = None,
    notes: Optional[str] = None, group_id: Optional[int] = None,
) -> dict[str, Any]:
    """Create an active customer; cashiers and management may use this service."""
    session = require_customer_access(session)
    values = _customer_values(
        first_name=first_name, last_name=last_name, business_name=business_name,
        phone_number=phone_number, email=email, address=address, city=city,
        state=state, country=country, date_of_birth=date_of_birth, gender=gender,
        tax_number=tax_number, notes=notes, group_id=group_id,
    )
    try:
        with transaction() as conn:
            _validate_group(conn, group_id)
            customer_code = _next_customer_code(conn)
            cursor = conn.execute(
                """INSERT INTO customers (
                       customer_code, first_name, last_name, business_name,
                       phone_number, email, address, city, state, country,
                       date_of_birth, gender, tax_number, notes, group_id, created_by
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    customer_code, values["first_name"], values["last_name"],
                    values["business_name"], values["phone_number"], values["email"],
                    values["address"], values["city"], values["state"], values["country"],
                    values["date_of_birth"], values["gender"], values["tax_number"],
                    values["notes"], group_id, session.user_id,
                ),
            )
            customer_id = cursor.lastrowid
    except IntegrityError as exc:
        raise _duplicate_error(exc) from exc
    log_event(logger, "customer_created", customer_id=customer_id, customer_code=customer_code,
              user_id=session.user_id, store_id=session.store_id)
    return get_customer_by_id(customer_id)


def update_customer(session: Any, customer_id: int, **updates: Any) -> dict[str, Any]:
    """Update customer profile fields without replacing financial history."""
    session = require_customer_management(session)
    allowed = {
        "first_name", "last_name", "business_name", "phone_number", "email",
        "address", "city", "state", "country", "date_of_birth", "gender",
        "tax_number", "notes", "group_id",
    }
    changes = {key: value for key, value in updates.items() if key in allowed}
    if not changes:
        customer = get_customer_by_id(customer_id)
        if not customer:
            raise CustomerError("Customer not found.")
        return customer
    changes = _normalize_updates(changes)
    try:
        with transaction() as conn:
            require_customer(conn, customer_id, active=False)
            if "group_id" in changes:
                _validate_group(conn, changes["group_id"])
            assignments = ", ".join(f"{field} = ?" for field in changes)
            conn.execute(
                f"UPDATE customers SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [*changes.values(), customer_id],
            )
    except IntegrityError as exc:
        raise _duplicate_error(exc) from exc
    log_event(logger, "customer_updated", customer_id=customer_id, user_id=session.user_id)
    return get_customer_by_id(customer_id)


def deactivate_customer(session: Any, customer_id: int) -> dict[str, Any]:
    session = require_customer_management(session)
    with transaction() as conn:
        require_customer(conn, customer_id, active=False)
        conn.execute("UPDATE customers SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (customer_id,))
    log_event(logger, "customer_deactivated", customer_id=customer_id, user_id=session.user_id)
    return get_customer_by_id(customer_id)


def reactivate_customer(session: Any, customer_id: int) -> dict[str, Any]:
    session = require_customer_management(session)
    with transaction() as conn:
        require_customer(conn, customer_id, active=False)
        conn.execute("UPDATE customers SET is_active = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (customer_id,))
    log_event(logger, "customer_reactivated", customer_id=customer_id, user_id=session.user_id)
    return get_customer_by_id(customer_id)


def get_customer_by_id(customer_id: int) -> Optional[dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT c.*, cg.name AS group_name,
                      cg.default_discount AS group_default_discount,
                      cg.pricing_priority AS group_pricing_priority
               FROM customers c LEFT JOIN customer_groups cg ON cg.id = c.group_id
               WHERE c.id = ?""", (customer_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["loyalty_balance"] = int(ledger_balance(conn, "loyalty_transactions", "points_delta", customer_id))
        result["wallet_balance"] = float(ledger_balance(conn, "wallet_transactions", "amount_delta", customer_id))
        result["credit_outstanding"] = float(ledger_balance(conn, "credit_transactions", "amount_delta", customer_id))
    return result


def search_customers(session: Any, term: Optional[str] = None, include_inactive: bool = False):
    """Search by code, person/business name, phone, or email."""
    require_customer_access(session)
    filters, params = [], []
    if not include_inactive:
        filters.append("c.is_active = 1")
    if term and term.strip():
        pattern = f"%{term.strip()}%"
        filters.append("(c.customer_code LIKE ? OR c.first_name LIKE ? OR c.last_name LIKE ? OR c.business_name LIKE ? OR c.phone_number LIKE ? OR c.email LIKE ?)")
        params.extend([pattern] * 6)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(
            f"""SELECT c.*, cg.name AS group_name
                FROM customers c LEFT JOIN customer_groups cg ON cg.id = c.group_id
                {where} ORDER BY c.first_name COLLATE NOCASE, c.last_name COLLATE NOCASE""", params,
        ).fetchall()]


def create_customer_group(session: Any, name: str, default_discount: float = 0,
                          pricing_priority: int = 0, description: Optional[str] = None):
    session = require_customer_management(session)
    values = _group_values(name, default_discount, pricing_priority, description)
    try:
        with transaction() as conn:
            cursor = conn.execute("INSERT INTO customer_groups (name, default_discount, pricing_priority, description) VALUES (?, ?, ?, ?)", values)
            group_id = cursor.lastrowid
    except IntegrityError as exc:
        raise CustomerError("Customer group name already exists.") from exc
    log_event(logger, "customer_group_created", group_id=group_id, user_id=session.user_id)
    return _get_group(group_id)


def update_customer_group(session: Any, group_id: int, **updates: Any):
    session = require_customer_management(session)
    current = _get_group(group_id)
    if not current:
        raise CustomerError("Customer group not found.")
    values = _group_values(updates.get("name", current["name"]), updates.get("default_discount", current["default_discount"]),
                           updates.get("pricing_priority", current["pricing_priority"]), updates.get("description", current["description"]))
    is_active = int(bool(updates.get("is_active", current["is_active"])))
    try:
        with transaction() as conn:
            conn.execute("""UPDATE customer_groups SET name = ?, default_discount = ?, pricing_priority = ?,
                            description = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""", (*values, is_active, group_id))
    except IntegrityError as exc:
        raise CustomerError("Customer group name already exists.") from exc
    log_event(logger, "customer_group_updated", group_id=group_id, user_id=session.user_id)
    return _get_group(group_id)


def assign_customer_group(session: Any, customer_id: int, group_id: Optional[int]):
    return update_customer(session, customer_id, group_id=group_id)


def search_customer_groups(session: Any, term: Optional[str] = None):
    require_customer_access(session)
    params, clause = [], "WHERE is_active = 1"
    if term and term.strip():
        pattern = f"%{term.strip()}%"
        clause += " AND (name LIKE ? OR description LIKE ?)"
        params.extend([pattern, pattern])
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(
            f"SELECT * FROM customer_groups {clause} ORDER BY pricing_priority DESC, name", params,
        ).fetchall()]


def _get_group(group_id: int):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM customer_groups WHERE id = ?", (group_id,)).fetchone()
    return dict(row) if row else None


def _validate_group(conn: Any, group_id: Optional[int]) -> None:
    if group_id is not None and not conn.execute("SELECT 1 FROM customer_groups WHERE id = ? AND is_active = 1", (group_id,)).fetchone():
        raise CustomerError("Customer group not found or inactive.")


def _next_customer_code(conn: Any) -> str:
    next_id = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM customers").fetchone()[0]
    return f"{get_config().numbering.customer_prefix}-{int(next_id):08d}"


def _customer_values(**values: Any) -> dict[str, Any]:
    values["first_name"] = required_text(values.get("first_name"), "First name", error_type=CustomerError)
    values["last_name"] = required_text(values.get("last_name"), "Last name", error_type=CustomerError)
    values["email"] = normalized_email(values.get("email"))
    values["phone_number"] = optional_text(values.get("phone_number"))
    values["date_of_birth"] = iso_date(values.get("date_of_birth"), "Date of birth", error_type=CustomerError)
    for field in ("business_name", "address", "city", "state", "country", "gender", "tax_number", "notes"):
        values[field] = optional_text(values.get(field))
    return values


def _normalize_updates(changes: dict[str, Any]) -> dict[str, Any]:
    if "first_name" in changes:
        changes["first_name"] = required_text(changes["first_name"], "First name", error_type=CustomerError)
    if "last_name" in changes:
        changes["last_name"] = required_text(changes["last_name"], "Last name", error_type=CustomerError)
    if "email" in changes:
        changes["email"] = normalized_email(changes["email"])
    if "date_of_birth" in changes:
        changes["date_of_birth"] = iso_date(changes["date_of_birth"], "Date of birth", error_type=CustomerError)
    for field in ("business_name", "phone_number", "address", "city", "state", "country", "gender", "tax_number", "notes"):
        if field in changes:
            changes[field] = optional_text(changes[field])
    return changes


def _group_values(name: Any, discount: Any, priority: Any, description: Any):
    name = required_text(name, "Customer group name", error_type=CustomerError)
    try:
        discount, priority = float(discount), int(priority)
    except (TypeError, ValueError) as exc:
        raise CustomerError("Customer group pricing values are invalid.") from exc
    if discount < 0 or discount > 100:
        raise CustomerError("Default discount must be between 0 and 100.")
    if priority < 0:
        raise CustomerError("Pricing priority cannot be negative.")
    return name, discount, priority, optional_text(description)


def _duplicate_error(exc: IntegrityError) -> CustomerError:
    message = str(exc).lower()
    if "phone" in message:
        return CustomerError("Phone number already exists.")
    if "email" in message:
        return CustomerError("Email address already exists.")
    return CustomerError("Customer already exists.")
