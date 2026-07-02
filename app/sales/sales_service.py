from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from auth import AuthorizationError, INVENTORY_ROLES, require_store_access, validate_session
from app.core.config import get_config
from app.core.exceptions import SalesError
from app.core.logging_utils import get_logger, log_event
from app.customers.common import require_customer
from app.customers.credit_service import get_credit_outstanding, record_credit_transaction
from app.customers.loyalty_service import (
    calculate_earned_points,
    get_loyalty_balance,
    record_loyalty_transaction,
    redemption_value,
)
from app.customers.wallet_service import get_wallet_balance, record_wallet_transaction
from app.database.db_manager import get_connection
from app.database.transactions import transaction
from app.inventory.inventory_service import (
    MOVEMENT_RETURN,
    get_product_by_id,
    log_stock_movement,
    record_sale_stock_movement,
    validate_positive_quantity,
)

PAYMENT_CASH = "CASH"
PAYMENT_CARD = "CARD"
PAYMENT_TRANSFER = "TRANSFER"
PAYMENT_MIXED = "MIXED"
PAYMENT_WALLET = "WALLET"
PAYMENT_CREDIT = "CREDIT"
PAYMENT_METHODS = {
    PAYMENT_CASH, PAYMENT_CARD, PAYMENT_TRANSFER, PAYMENT_WALLET,
    PAYMENT_CREDIT, PAYMENT_MIXED,
}
PAYMENT_STATUS_PAID = "PAID"
DISCOUNT_PERCENTAGE = "PERCENTAGE"
DISCOUNT_FIXED = "FIXED"
logger = get_logger("sales")


def calculate_totals(
    items, discount_type=None, discount_value=0, tax_rate=None, store_id=None, conn=None,
):
    if not items:
        raise SalesError("Sale must contain at least one item.")

    subtotal = 0.0
    normalized_items = []
    close_conn = conn is None
    if close_conn:
        conn = get_connection()
    try:
        for item in items:
            product_id = item.get("product_id")
            quantity = int(item.get("quantity", 0))
            validate_positive_quantity(quantity)
            product = get_product_by_id(product_id, conn=conn, store_id=store_id)
            if not product or not product["is_active"]:
                raise SalesError("Product not found or inactive.")
            unit_price = float(product["selling_price"])
            if unit_price < 0:
                raise SalesError("Unit price cannot be negative.")
            line_total = unit_price * quantity
            subtotal += line_total
            normalized_items.append({
                "product_id": product["id"],
                "sku": product["sku"],
                "name": product["name"],
                "quantity": quantity,
                "unit_price": unit_price,
                "unit_cost": float(product.get("cost_price") or 0),
                "line_total": line_total,
            })
    finally:
        if close_conn:
            conn.close()

    discount_amount = calculate_discount(subtotal, discount_type, discount_value)
    taxable_amount = subtotal - discount_amount
    tax_rate = get_config().tax_rate if tax_rate is None else tax_rate
    if tax_rate < 0:
        raise SalesError("Tax rate cannot be negative.")
    tax_amount = taxable_amount * float(tax_rate)
    total_amount = taxable_amount + tax_amount

    return {
        "items": normalized_items,
        "subtotal": money_round(subtotal),
        "discount_amount": money_round(discount_amount),
        "tax_amount": money_round(tax_amount),
        "total_amount": money_round(total_amount),
    }


def calculate_discount(subtotal, discount_type=None, discount_value=0):
    discount_value = float(discount_value or 0)
    if discount_value < 0:
        raise SalesError("Discount cannot be negative.")
    if not discount_type or discount_value == 0:
        return 0.0
    if discount_type == DISCOUNT_PERCENTAGE:
        if discount_value > 100:
            raise SalesError("Percentage discount cannot exceed 100.")
        return subtotal * (discount_value / 100)
    if discount_type == DISCOUNT_FIXED:
        if discount_value > subtotal:
            raise SalesError("Fixed discount cannot exceed subtotal.")
        return discount_value
    raise SalesError("Invalid discount type.")


def process_payment(total_amount, payment_method, amount_paid=None):
    validate_payment_method(payment_method)
    total_amount = money_round(total_amount)
    if amount_paid is None:
        amount_paid = total_amount if payment_method in {
            PAYMENT_CARD, PAYMENT_TRANSFER, PAYMENT_WALLET, PAYMENT_CREDIT,
        } else 0
    amount_paid = money_round(amount_paid)
    if amount_paid < total_amount:
        raise SalesError("Insufficient payment.")
    return {
        "payment_method": payment_method,
        "payment_status": PAYMENT_STATUS_PAID,
        "amount_paid": amount_paid,
        "change_given": money_round(amount_paid - total_amount),
    }


def generate_receipt_number(conn=None, created_at=None):
    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True
    try:
        date_key = (created_at or datetime.now()).strftime("%Y%m%d")
        prefix = f"{get_config().numbering.receipt_prefix}-{date_key}-"
        row = conn.execute(
            "SELECT receipt_number FROM sales WHERE receipt_number LIKE ? ORDER BY receipt_number DESC LIMIT 1",
            (f"{prefix}%",)
        ).fetchone()
        sequence = int(row["receipt_number"].split("-")[-1]) + 1 if row else 1
        return f"{prefix}{sequence:04d}"
    finally:
        if close_conn:
            conn.close()


def create_sale(
    session,
    items,
    payment_method=PAYMENT_CASH,
    amount_paid=None,
    discount_type=None,
    discount_value=0,
    tax_rate=None,
    store_id=None,
    register_name=None,
    customer_id=None,
    redeem_points=0,
    payments=None,
):
    session = require_session(session)
    store_id = int(store_id or session.store_id)
    session = require_store_access(session, store_id)
    if discount_value and session.role not in INVENTORY_ROLES:
        raise AuthorizationError("Only admin and manager users can apply sale discounts.")
    with transaction() as conn:
        customer = None
        customer_group_id = None
        effective_discount_type = discount_type
        effective_discount_value = discount_value
        if customer_id is not None:
            customer = require_customer(conn, int(customer_id))
            customer_group_id = customer["group_id"]
            if customer_group_id is not None and not discount_type and not discount_value:
                group = conn.execute(
                    "SELECT default_discount FROM customer_groups WHERE id = ? AND is_active = 1",
                    (customer_group_id,),
                ).fetchone()
                if not group:
                    raise SalesError("Customer group not found or inactive.")
                if float(group["default_discount"] or 0) > 0:
                    effective_discount_type = DISCOUNT_PERCENTAGE
                    effective_discount_value = float(group["default_discount"])
        totals = calculate_totals(
            items,
            discount_type=effective_discount_type,
            discount_value=effective_discount_value,
            tax_rate=tax_rate,
            store_id=store_id,
            conn=conn,
        )
        payment = _prepare_sale_payments(
            conn, customer, totals["total_amount"], payment_method,
            amount_paid=amount_paid, payments=payments, redeem_points=redeem_points,
        )
        points_earned = calculate_earned_points(
            totals["total_amount"] - payment["loyalty_redemption_amount"]
        ) if customer else 0
        receipt_number = generate_receipt_number(conn)
        cursor = conn.execute(
            """INSERT INTO sales (
                receipt_number, user_id, store_id, register_name, username, cashier_name,
                subtotal, discount_amount,
                tax, tax_amount, total, total_amount, payment_method, payment_status,
                amount_paid, change_given, customer_id, customer_group_id,
                loyalty_points_earned, loyalty_points_redeemed,
                loyalty_redemption_amount, wallet_amount, credit_amount, tender_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                receipt_number,
                session.user_id,
                store_id,
                str(register_name or get_config().receipt.register_name).strip()
                or get_config().receipt.register_name,
                session.username,
                session.username,
                totals["subtotal"],
                totals["discount_amount"],
                totals["tax_amount"],
                totals["tax_amount"],
                totals["total_amount"],
                totals["total_amount"],
                payment["legacy_payment_method"],
                payment["payment_status"],
                payment["amount_paid"],
                payment["change_given"],
                customer["id"] if customer else None,
                customer_group_id,
                points_earned,
                payment["loyalty_points_redeemed"],
                payment["loyalty_redemption_amount"],
                payment["wallet_amount"],
                payment["credit_amount"],
                payment["payment_method"],
            )
        )
        sale_id = cursor.lastrowid
        conn.executemany(
            "INSERT INTO sale_payments (sale_id, payment_method, amount) VALUES (?, ?, ?)",
            [(sale_id, item["payment_method"], item["amount"]) for item in payment["payments"]],
        )
        if customer:
            if payment["loyalty_points_redeemed"]:
                record_loyalty_transaction(
                    conn, customer["id"], -payment["loyalty_points_redeemed"],
                    "REDEEM", session.user_id, store_id=store_id, sale_id=sale_id,
                    notes=f"Redeemed on sale {receipt_number}",
                )
            if payment["wallet_amount"]:
                record_wallet_transaction(
                    conn, customer["id"], -payment["wallet_amount"], "SALE",
                    session.user_id, store_id=store_id, sale_id=sale_id,
                    notes=f"Wallet payment for sale {receipt_number}",
                )
            if payment["credit_amount"]:
                record_credit_transaction(
                    conn, customer["id"], payment["credit_amount"], "CHARGE",
                    session.user_id, store_id=store_id, sale_id=sale_id,
                    notes=f"Credit charge for sale {receipt_number}",
                )
            if points_earned:
                record_loyalty_transaction(
                    conn, customer["id"], points_earned, "EARN", session.user_id,
                    store_id=store_id, sale_id=sale_id,
                    notes=f"Earned on sale {receipt_number}",
                )
        for item in totals["items"]:
            record_sale_stock_movement(
                conn,
                item["product_id"],
                item["quantity"],
                session.user_id,
                notes=f"Sale {receipt_number}",
                store_id=store_id,
            )
            conn.execute(
                """INSERT INTO sale_items (
                       sale_id, product_id, quantity, price_at_sale, unit_cost_at_sale
                   ) VALUES (?, ?, ?, ?, ?)""",
                (
                    sale_id,
                    str(item["product_id"]),
                    item["quantity"],
                    item["unit_price"],
                    item["unit_cost"],
                )
            )

    log_event(
        logger,
        "sale_created",
        sale_id=sale_id,
        receipt_number=receipt_number,
        store_id=store_id,
        user_id=session.user_id,
        total_amount=totals["total_amount"],
        customer_id=customer["id"] if customer else None,
    )
    return print_receipt_data(sale_id)


def _prepare_sale_payments(
    conn, customer, total_amount, payment_method, amount_paid=None,
    payments=None, redeem_points=0,
):
    """Normalize tender allocations and validate customer-backed balances."""
    validate_payment_method(payment_method)
    total_amount = money_round(total_amount)
    try:
        redeem_points = int(redeem_points or 0)
    except (TypeError, ValueError) as exc:
        raise SalesError("Redeemed points must be a whole number.") from exc
    if redeem_points < 0:
        raise SalesError("Redeemed points cannot be negative.")
    if customer is None and (
        redeem_points or payments or payment_method in {PAYMENT_WALLET, PAYMENT_CREDIT}
    ):
        raise SalesError("Customer-backed payments require an active customer.")
    loyalty_amount = 0.0
    if redeem_points:
        if redeem_points > get_loyalty_balance(customer["id"], conn=conn):
            raise SalesError("Insufficient loyalty points.")
        loyalty_amount = redemption_value(redeem_points)
        if loyalty_amount > total_amount:
            raise SalesError("Redeemed points cannot exceed the sale total.")
    amount_due = money_round(total_amount - loyalty_amount)

    if payments is not None:
        if not isinstance(payments, (list, tuple)) or not payments:
            raise SalesError("Mixed payment requires at least one tender allocation.")
        allocations = []
        for item in payments:
            method = str(item.get("payment_method", "")).upper()
            if method not in PAYMENT_METHODS - {PAYMENT_MIXED}:
                raise SalesError("Invalid payment allocation method.")
            try:
                amount = money_round(item.get("amount"))
            except Exception as exc:
                raise SalesError("Payment allocation amount is invalid.") from exc
            if amount <= 0:
                raise SalesError("Payment allocation amount must be positive.")
            allocations.append({"payment_method": method, "amount": amount})
        tendered = money_round(sum(item["amount"] for item in allocations))
        if tendered < amount_due:
            raise SalesError("Insufficient payment.")
        change = money_round(tendered - amount_due)
        if change:
            allocations[-1]["amount"] = money_round(allocations[-1]["amount"] - change)
            if allocations[-1]["amount"] <= 0:
                raise SalesError("Payment allocation exceeds the amount due.")
        actual_paid = money_round(tendered + loyalty_amount)
    elif amount_due == 0:
        allocations, actual_paid, change = [], loyalty_amount, 0.0
    elif payment_method == PAYMENT_MIXED:
        raise SalesError("Mixed payment requires tender allocations.")
    elif payment_method in {PAYMENT_WALLET, PAYMENT_CREDIT}:
        allocations = [{"payment_method": payment_method, "amount": amount_due}]
        actual_paid, change = total_amount, 0.0
    else:
        legacy = process_payment(amount_due, payment_method, amount_paid)
        allocations = [{"payment_method": payment_method, "amount": amount_due}]
        actual_paid = money_round(legacy["amount_paid"] + loyalty_amount)
        change = legacy["change_given"]

    wallet_amount = money_round(sum(
        item["amount"] for item in allocations if item["payment_method"] == PAYMENT_WALLET
    ))
    credit_amount = money_round(sum(
        item["amount"] for item in allocations if item["payment_method"] == PAYMENT_CREDIT
    ))
    if customer:
        if wallet_amount > get_wallet_balance(customer["id"], conn=conn):
            raise SalesError("Insufficient wallet balance.")
        available_credit = money_round(
            float(customer["credit_limit"] or 0)
            - get_credit_outstanding(customer["id"], conn=conn)
        )
        if credit_amount > available_credit:
            raise SalesError("Credit limit exceeded.")
    methods = {item["payment_method"] for item in allocations}
    tender_type = next(iter(methods)) if len(methods) == 1 else PAYMENT_MIXED
    legacy_method = tender_type if tender_type in {
        PAYMENT_CASH, PAYMENT_CARD, PAYMENT_TRANSFER, PAYMENT_MIXED,
    } else PAYMENT_MIXED
    return {
        "payment_method": tender_type,
        "legacy_payment_method": legacy_method,
        "payment_status": PAYMENT_STATUS_PAID,
        "amount_paid": actual_paid,
        "change_given": change,
        "payments": allocations,
        "wallet_amount": wallet_amount,
        "credit_amount": credit_amount,
        "loyalty_points_redeemed": redeem_points,
        "loyalty_redemption_amount": loyalty_amount,
    }


def print_receipt_data(sale_id):
    with get_connection() as conn:
        sale = conn.execute("SELECT * FROM sales WHERE sale_id = ?", (sale_id,)).fetchone()
        if not sale:
            raise SalesError("Sale not found.")
        items = [dict(row) for row in conn.execute(
            """SELECT si.id, si.product_id, p.sku, p.name, si.quantity, si.price_at_sale,
                      (si.quantity * si.price_at_sale) AS line_total
               FROM sale_items si
               LEFT JOIN products p ON CAST(si.product_id AS INTEGER) = p.id
               WHERE si.sale_id = ?
               ORDER BY si.id""",
            (sale_id,)
        ).fetchall()]
        payments = [dict(row) for row in conn.execute(
            "SELECT payment_method, amount FROM sale_payments WHERE sale_id = ? ORDER BY id",
            (sale_id,),
        ).fetchall()]
        customer = None
        if sale["customer_id"] is not None:
            row = conn.execute(
                """SELECT id, customer_code, first_name, last_name, business_name
                   FROM customers WHERE id = ?""",
                (sale["customer_id"],),
            ).fetchone()
            customer = dict(row) if row else None
    sale_data = dict(sale)
    sale_data["payment_method"] = sale_data.get("tender_type") or sale_data["payment_method"]
    return {"sale": sale_data, "items": items, "payments": payments, "customer": customer}


def process_return(session, sale_id, return_items, reason):
    session = require_return_management(session)
    if not reason or not reason.strip():
        raise SalesError("Return reason is required.")
    if not return_items:
        raise SalesError("Return must contain at least one item.")

    with transaction() as conn:
        sale = conn.execute("SELECT * FROM sales WHERE sale_id = ?", (sale_id,)).fetchone()
        if not sale:
            raise SalesError("Sale not found.")
        session = require_store_access(session, sale["store_id"], manage=True)

        prepared_items = []
        total_refunded = 0.0
        for item in return_items:
            sale_item_id = item.get("sale_item_id")
            quantity = int(item.get("quantity", 0))
            validate_positive_quantity(quantity)
            sale_item = conn.execute(
                "SELECT * FROM sale_items WHERE id = ? AND sale_id = ?",
                (sale_item_id, sale_id)
            ).fetchone()
            if not sale_item:
                raise SalesError("Sale item not found.")
            returned_qty = conn.execute(
                """SELECT COALESCE(SUM(sri.quantity), 0) AS qty
                   FROM sales_return_items sri
                   JOIN sales_returns sr ON sr.id = sri.return_id
                   WHERE sr.sale_id = ? AND sri.sale_item_id = ?""",
                (sale_id, sale_item_id)
            ).fetchone()["qty"]
            if returned_qty + quantity > sale_item["quantity"]:
                raise SalesError("Refund quantity cannot exceed sold quantity.")
            refund_amount = money_round(quantity * float(sale_item["price_at_sale"]))
            total_refunded += refund_amount
            prepared_items.append({
                "sale_item": dict(sale_item),
                "quantity": quantity,
                "refund_amount": refund_amount,
            })

        cursor = conn.execute(
            "INSERT INTO sales_returns (sale_id, user_id, reason, total_refunded) VALUES (?, ?, ?, ?)",
            (sale_id, session.user_id, reason.strip(), money_round(total_refunded))
        )
        return_id = cursor.lastrowid
        for item in prepared_items:
            sale_item = item["sale_item"]
            conn.execute(
                """INSERT INTO sales_return_items (return_id, sale_item_id, quantity, refund_amount)
                   VALUES (?, ?, ?, ?)""",
                (return_id, sale_item["id"], item["quantity"], item["refund_amount"])
            )
            restore_return_stock(
                conn,
                int(sale_item["product_id"]),
                item["quantity"],
                session.user_id,
                notes=f"Return #{return_id} for sale #{sale_id}",
                store_id=sale["store_id"],
            )
        if sale["customer_id"] is not None:
            _reverse_customer_sale_value(
                conn, sale, return_id, money_round(total_refunded), session.user_id
            )

    log_event(
        logger,
        "sale_return_created",
        return_id=return_id,
        sale_id=sale_id,
        store_id=sale["store_id"],
        user_id=session.user_id,
        total_refunded=money_round(total_refunded),
    )
    return get_return_data(return_id)


def _reverse_customer_sale_value(conn, sale, return_id, refund_amount, user_id):
    """Apply cumulative, idempotent customer-ledger reversals for a return."""
    subtotal = float(sale["subtotal"] or 0)
    if subtotal <= 0:
        return
    cumulative_refund = float(conn.execute(
        "SELECT COALESCE(SUM(total_refunded), 0) FROM sales_returns WHERE sale_id = ?",
        (sale["sale_id"],),
    ).fetchone()[0])
    fraction = min(1.0, cumulative_refund / subtotal)
    customer_id = sale["customer_id"]
    common = {
        "user_id": user_id,
        "store_id": sale["store_id"],
        "sale_id": sale["sale_id"],
        "sales_return_id": return_id,
        "notes": f"Customer value reversal for return #{return_id}",
    }

    redeemed_target = int(round(int(sale["loyalty_points_redeemed"] or 0) * fraction))
    redeemed_done = int(conn.execute(
        """SELECT COALESCE(SUM(points_delta), 0) FROM loyalty_transactions
           WHERE sale_id = ? AND sales_return_id IS NOT NULL AND points_delta > 0""",
        (sale["sale_id"],),
    ).fetchone()[0])
    if redeemed_target > redeemed_done:
        record_loyalty_transaction(
            conn, customer_id, redeemed_target - redeemed_done, "REFUND", **common
        )

    earned_target = int(round(int(sale["loyalty_points_earned"] or 0) * fraction))
    earned_done = abs(int(conn.execute(
        """SELECT COALESCE(SUM(points_delta), 0) FROM loyalty_transactions
           WHERE sale_id = ? AND sales_return_id IS NOT NULL AND points_delta < 0""",
        (sale["sale_id"],),
    ).fetchone()[0]))
    earned_to_reverse = min(
        max(0, earned_target - earned_done),
        get_loyalty_balance(customer_id, conn=conn),
    )
    if earned_to_reverse:
        record_loyalty_transaction(
            conn, customer_id, -earned_to_reverse, "REFUND", **common
        )

    wallet_target = money_round(float(sale["wallet_amount"] or 0) * fraction)
    wallet_done = float(conn.execute(
        """SELECT COALESCE(SUM(amount_delta), 0) FROM wallet_transactions
           WHERE sale_id = ? AND sales_return_id IS NOT NULL AND amount_delta > 0""",
        (sale["sale_id"],),
    ).fetchone()[0])
    wallet_refund = money_round(wallet_target - wallet_done)
    if wallet_refund > 0:
        record_wallet_transaction(
            conn, customer_id, wallet_refund, "REFUND", **common
        )

    credit_target = money_round(float(sale["credit_amount"] or 0) * fraction)
    credit_done = abs(float(conn.execute(
        """SELECT COALESCE(SUM(amount_delta), 0) FROM credit_transactions
           WHERE sale_id = ? AND sales_return_id IS NOT NULL AND amount_delta < 0""",
        (sale["sale_id"],),
    ).fetchone()[0]))
    credit_refund = min(
        money_round(max(0, credit_target - credit_done)),
        get_credit_outstanding(customer_id, conn=conn),
    )
    if credit_refund > 0:
        record_credit_transaction(
            conn, customer_id, -credit_refund, "REFUND", **common
        )


def refund_sale(session, sale_id, reason="Full sale refund"):
    with get_connection() as conn:
        rows = conn.execute("SELECT id, quantity FROM sale_items WHERE sale_id = ?", (sale_id,)).fetchall()
    if not rows:
        raise SalesError("Sale has no refundable items.")
    return process_return(
        session,
        sale_id,
        [{"sale_item_id": row["id"], "quantity": row["quantity"]} for row in rows],
        reason,
    )


def restore_return_stock(conn, product_id, quantity, user_id, notes=None, store_id=None):
    product = get_product_by_id(product_id, conn=conn, store_id=store_id)
    if not product:
        raise SalesError("Product not found.")
    previous_quantity = product["quantity_in_stock"]
    new_quantity = previous_quantity + int(quantity)
    from app.inventory.inventory_service import update_store_inventory_balance

    update_store_inventory_balance(conn, store_id, product_id, new_quantity)
    log_stock_movement(
        conn, product_id, MOVEMENT_RETURN, int(quantity), previous_quantity,
        new_quantity, user_id, notes, store_id=store_id,
    )


def get_return_data(return_id):
    with get_connection() as conn:
        sales_return = conn.execute("SELECT * FROM sales_returns WHERE id = ?", (return_id,)).fetchone()
        if not sales_return:
            raise SalesError("Return not found.")
        items = [dict(row) for row in conn.execute(
            "SELECT * FROM sales_return_items WHERE return_id = ? ORDER BY id",
            (return_id,)
        ).fetchall()]
    return {"return": dict(sales_return), "items": items}


def validate_payment_method(payment_method):
    if payment_method not in PAYMENT_METHODS:
        raise SalesError("Invalid payment method.")


def require_session(session):
    return validate_session(session)


def require_return_management(session):
    session = validate_session(session)
    if session.role not in INVENTORY_ROLES:
        raise AuthorizationError("Only admin and manager users can process returns.")
    return session


def money_round(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
