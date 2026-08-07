"""Customer credit limits, charges, and payment history."""

from typing import Any, Optional

from app.core.exceptions import CreditError
from app.core.logging_utils import get_logger, log_event
from app.core.validation import iso_date
from app.customers.common import ledger_balance, money, positive_amount, require_customer
from app.customers.permissions import require_customer_management
from app.database.db_manager import get_connection
from app.database.transactions import transaction


logger = get_logger("customer.credit")


def get_credit_outstanding(customer_id: int, conn: Any = None) -> float:
    close_conn = conn is None
    if close_conn:
        conn = get_connection()
    try:
        require_customer(conn, customer_id, active=False)
        return money(ledger_balance(conn, "credit_transactions", "amount_delta", customer_id), CreditError)
    finally:
        if close_conn:
            conn.close()


def set_credit_terms(session: Any, customer_id: int, credit_limit: float,
                     due_date: Optional[str] = None):
    session = require_customer_management(session)
    credit_limit = money(credit_limit, CreditError)
    if credit_limit < 0:
        raise CreditError("Credit limit cannot be negative.")
    due_date = iso_date(due_date, "Credit due date", error_type=CreditError)
    with transaction() as conn:
        require_customer(conn, customer_id, active=False)
        outstanding = get_credit_outstanding(customer_id, conn=conn)
        if credit_limit < outstanding:
            raise CreditError("Credit limit cannot be lower than the outstanding balance.")
        conn.execute(
            "UPDATE customers SET credit_limit = ?, credit_due_date = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (credit_limit, due_date, customer_id),
        )
    log_event(logger, "credit_terms_updated", customer_id=customer_id,
              credit_limit=credit_limit, user_id=session.user_id)
    from app.customers.customer_service import get_customer_by_id
    return get_customer_by_id(customer_id)


def make_credit_payment(session: Any, customer_id: int, amount: float,
                        notes: Optional[str] = None):
    session = require_customer_management(session)
    amount = positive_amount(amount, CreditError)
    with transaction() as conn:
        outstanding = get_credit_outstanding(customer_id, conn=conn)
        if amount > outstanding:
            raise CreditError("Credit payment cannot exceed the outstanding balance.")
        row = record_credit_transaction(
            conn, customer_id, -amount, "PAYMENT", session.user_id,
            store_id=session.store_id, notes=notes,
        )
        from app.finance.posting_service import post_credit_payment
        post_credit_payment(session, row["transaction_id"], conn)
    log_event(logger, "credit_payment_recorded", customer_id=customer_id,
              amount=amount, user_id=session.user_id, balance=row["balance_after"])
    return row


def record_credit_transaction(
    conn: Any, customer_id: int, amount_delta: float, transaction_type: str,
    user_id: int, store_id: Optional[int] = None, sale_id: Optional[int] = None,
    sales_return_id: Optional[int] = None, due_date: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict[str, Any]:
    customer = require_customer(conn, customer_id)
    amount_delta = money(amount_delta, CreditError)
    if amount_delta == 0:
        raise CreditError("Credit transaction amount cannot be zero.")
    balance = get_credit_outstanding(customer_id, conn=conn)
    new_balance = money(balance + amount_delta, CreditError)
    if new_balance < 0:
        raise CreditError("Credit transaction cannot create a negative balance.")
    if amount_delta > 0 and new_balance > float(customer["credit_limit"] or 0):
        raise CreditError("Credit limit exceeded.")
    cursor = conn.execute(
        """INSERT INTO credit_transactions (
               customer_id, transaction_type, amount_delta, balance_after,
               sale_id, sales_return_id, store_id, user_id, due_date, notes
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (customer_id, transaction_type, amount_delta, new_balance, sale_id,
         sales_return_id, store_id, user_id, due_date or customer["credit_due_date"], notes),
    )
    return {"transaction_id": cursor.lastrowid, "amount_delta": amount_delta,
            "balance_after": new_balance, "transaction_type": transaction_type}
