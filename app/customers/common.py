"""Shared customer persistence and value-normalization helpers."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from app.core.exceptions import CustomerError


def require_customer(conn: Any, customer_id: int, *, active: bool = True):
    row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if not row:
        raise CustomerError("Customer not found.")
    if active and not row["is_active"]:
        raise CustomerError("Inactive customers cannot be used.")
    return row


def ledger_balance(conn: Any, table: str, column: str, customer_id: int):
    allowed = {
        ("loyalty_transactions", "points_delta"),
        ("wallet_transactions", "amount_delta"),
        ("credit_transactions", "amount_delta"),
    }
    if (table, column) not in allowed:
        raise ValueError("Unsupported customer ledger.")
    return conn.execute(
        f"SELECT COALESCE(SUM({column}), 0) FROM {table} WHERE customer_id = ?",
        (customer_id,),
    ).fetchone()[0]


def money(value: Any, error_type, message: str = "Amount must be a valid number.") -> float:
    """Normalize finite monetary input to two decimal places."""
    try:
        normalized = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise error_type(message) from exc
    if not normalized.is_finite():
        raise error_type(message)
    return float(normalized)


def positive_amount(value: Any, error_type) -> float:
    normalized = money(value, error_type)
    if normalized <= 0:
        raise error_type("Amount must be positive.")
    return normalized
