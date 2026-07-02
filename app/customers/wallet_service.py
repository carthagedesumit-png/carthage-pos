"""Customer wallet operations backed by an immutable money ledger."""

from typing import Any, Optional

from app.core.exceptions import WalletError
from app.core.logging_utils import get_logger, log_event
from app.customers.common import ledger_balance, money, positive_amount, require_customer
from app.customers.permissions import require_customer_management
from app.database.db_manager import get_connection
from app.database.transactions import transaction


logger = get_logger("customer.wallet")


def get_wallet_balance(customer_id: int, conn: Any = None) -> float:
    close_conn = conn is None
    if close_conn:
        conn = get_connection()
    try:
        require_customer(conn, customer_id, active=False)
        return money(ledger_balance(conn, "wallet_transactions", "amount_delta", customer_id), WalletError)
    finally:
        if close_conn:
            conn.close()


def deposit_wallet(session: Any, customer_id: int, amount: float, notes: Optional[str] = None):
    return _public_wallet_change(session, customer_id, positive_amount(amount, WalletError), "DEPOSIT", notes)


def withdraw_wallet(session: Any, customer_id: int, amount: float, notes: Optional[str] = None):
    return _public_wallet_change(session, customer_id, -positive_amount(amount, WalletError), "WITHDRAWAL", notes)


def adjust_wallet(session: Any, customer_id: int, amount_delta: float, notes: Optional[str] = None):
    amount_delta = money(amount_delta, WalletError)
    if amount_delta == 0:
        raise WalletError("Wallet adjustment cannot be zero.")
    return _public_wallet_change(session, customer_id, amount_delta, "ADJUSTMENT", notes)


def _public_wallet_change(session, customer_id, amount_delta, transaction_type, notes):
    session = require_customer_management(session)
    with transaction() as conn:
        row = record_wallet_transaction(
            conn, customer_id, amount_delta, transaction_type, session.user_id,
            store_id=session.store_id, notes=notes,
        )
    log_event(logger, "wallet_changed", customer_id=customer_id, amount_delta=amount_delta,
              user_id=session.user_id, balance=row["balance_after"])
    return row


def record_wallet_transaction(
    conn: Any, customer_id: int, amount_delta: float, transaction_type: str,
    user_id: int, store_id: Optional[int] = None, sale_id: Optional[int] = None,
    sales_return_id: Optional[int] = None, notes: Optional[str] = None,
) -> dict[str, Any]:
    require_customer(conn, customer_id)
    amount_delta = money(amount_delta, WalletError)
    if amount_delta == 0:
        raise WalletError("Wallet transaction amount cannot be zero.")
    balance = get_wallet_balance(customer_id, conn=conn)
    new_balance = money(balance + amount_delta, WalletError)
    if new_balance < 0:
        raise WalletError("Insufficient wallet balance.")
    cursor = conn.execute(
        """INSERT INTO wallet_transactions (
               customer_id, transaction_type, amount_delta, balance_after,
               sale_id, sales_return_id, store_id, user_id, notes
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (customer_id, transaction_type, amount_delta, new_balance, sale_id,
         sales_return_id, store_id, user_id, notes),
    )
    return {"transaction_id": cursor.lastrowid, "amount_delta": amount_delta,
            "balance_after": new_balance, "transaction_type": transaction_type}
