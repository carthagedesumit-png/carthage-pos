"""Configurable loyalty points backed by an immutable signed ledger."""

from datetime import datetime, timedelta
from math import floor
from typing import Any, Optional

from app.core.config import get_config
from app.core.exceptions import LoyaltyError
from app.core.logging_utils import get_logger, log_event
from app.customers.common import ledger_balance, require_customer
from app.customers.permissions import require_customer_management
from app.database.db_manager import get_connection
from app.database.transactions import transaction


logger = get_logger("customer.loyalty")


def get_loyalty_balance(customer_id: int, conn: Any = None) -> int:
    close_conn = conn is None
    if close_conn:
        conn = get_connection()
    try:
        require_customer(conn, customer_id, active=False)
        return int(ledger_balance(conn, "loyalty_transactions", "points_delta", customer_id))
    finally:
        if close_conn:
            conn.close()


def calculate_earned_points(amount: float) -> int:
    settings = get_config().loyalty
    amount = float(amount)
    if amount < settings.minimum_purchase:
        return 0
    return max(0, floor(amount * settings.points_per_currency))


def redemption_value(points: int) -> float:
    return round(int(points) / get_config().loyalty.redemption_ratio, 2)


def adjust_loyalty_points(session: Any, customer_id: int, points: int, notes: Optional[str] = None):
    session = require_customer_management(session)
    with transaction() as conn:
        transaction_row = record_loyalty_transaction(
            conn, customer_id, int(points), "ADJUSTMENT", session.user_id,
            store_id=session.store_id, notes=notes,
        )
    log_event(logger, "loyalty_adjusted", customer_id=customer_id, points=points,
              user_id=session.user_id, balance=transaction_row["balance_after"])
    return transaction_row


def redeem_loyalty_points(session: Any, customer_id: int, points: int, notes: Optional[str] = None):
    session = require_customer_management(session)
    with transaction() as conn:
        transaction_row = record_loyalty_transaction(
            conn, customer_id, -_positive_points(points), "REDEEM", session.user_id,
            store_id=session.store_id, notes=notes,
        )
    log_event(logger, "loyalty_redeemed", customer_id=customer_id, points=points,
              user_id=session.user_id, balance=transaction_row["balance_after"])
    return transaction_row


def record_loyalty_transaction(
    conn: Any, customer_id: int, points_delta: int, transaction_type: str,
    user_id: int, store_id: Optional[int] = None, sale_id: Optional[int] = None,
    sales_return_id: Optional[int] = None, notes: Optional[str] = None,
) -> dict[str, Any]:
    require_customer(conn, customer_id)
    points_delta = int(points_delta)
    if points_delta == 0:
        raise LoyaltyError("Loyalty point change cannot be zero.")
    balance = get_loyalty_balance(customer_id, conn=conn)
    new_balance = balance + points_delta
    if new_balance < 0:
        raise LoyaltyError("Insufficient loyalty points.")
    expiration_days = get_config().loyalty.expiration_days
    expires_at = None
    if points_delta > 0 and expiration_days:
        expires_at = (datetime.now() + timedelta(days=expiration_days)).isoformat(timespec="seconds")
    cursor = conn.execute(
        """INSERT INTO loyalty_transactions (
               customer_id, transaction_type, points_delta, balance_after,
               sale_id, sales_return_id, store_id, user_id, notes, expires_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (customer_id, transaction_type, points_delta, new_balance, sale_id,
         sales_return_id, store_id, user_id, notes, expires_at),
    )
    return {"transaction_id": cursor.lastrowid, "points_delta": points_delta,
            "balance_after": new_balance, "transaction_type": transaction_type}


def _positive_points(points: Any) -> int:
    try:
        points = int(points)
    except (TypeError, ValueError) as exc:
        raise LoyaltyError("Points must be a positive whole number.") from exc
    if points <= 0:
        raise LoyaltyError("Points must be a positive whole number.")
    return points
