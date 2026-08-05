from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import re
import json

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
PAYMENT_REFERENCE_MAX_LENGTH = 80
PAYMENT_REFERENCE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9 ._:/#-]*$")


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
    if payment_method != PAYMENT_CASH and amount_paid > total_amount:
        raise SalesError("Non-cash payment cannot exceed the amount due.")
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
    source_cart_id=None,
    payment_reference=None,
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
            payment_reference=payment_reference,
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
                loyalty_redemption_amount, wallet_amount, credit_amount, tender_type,
                source_cart_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                int(source_cart_id) if source_cart_id is not None else None,
            )
        )
        sale_id = cursor.lastrowid
        conn.executemany(
            "INSERT INTO sale_payments (sale_id, payment_method, amount, reference) VALUES (?, ?, ?, ?)",
            [(sale_id, item["payment_method"], item["amount"], item.get("reference")) for item in payment["payments"]],
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
        from app.finance.posting_service import post_sale
        post_sale(session, sale_id, conn)
        if source_cart_id is not None:
            updated = conn.execute(
                """UPDATE checkout_carts SET status='COMPLETED',completed_sale_id=?,
                   updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='ACTIVE'""",
                (sale_id, int(source_cart_id)),
            )
            if updated.rowcount != 1:
                raise SalesError("Checkout cart is no longer active.")
            conn.execute(
                "INSERT INTO checkout_events(cart_id,user_id,event_type,details) VALUES(?,?,?,?)",
                (int(source_cart_id), session.user_id, "CHECKOUT_COMPLETED",
                 json.dumps({"sale_id": sale_id}, sort_keys=True)),
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
    payments=None, redeem_points=0, payment_reference=None,
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
    customer_backed_allocation = bool(payments) and any(
        str(item.get("payment_method", "")).upper() in {PAYMENT_WALLET, PAYMENT_CREDIT}
        for item in payments
    )
    if customer is None and (
        redeem_points or customer_backed_allocation
        or payment_method in {PAYMENT_WALLET, PAYMENT_CREDIT}
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
            reference = normalize_payment_reference(item.get("reference"), method)
            allocations.append({"payment_method": method, "amount": amount, "reference": reference})
        tendered = money_round(sum(item["amount"] for item in allocations))
        if tendered < amount_due:
            raise SalesError("Insufficient payment.")
        change = money_round(tendered - amount_due)
        if change:
            cash_indexes = [i for i, item in enumerate(allocations) if item["payment_method"] == PAYMENT_CASH]
            if not cash_indexes:
                raise SalesError("Non-cash payment allocations cannot exceed the amount due.")
            cash_index = cash_indexes[-1]
            if allocations[cash_index]["amount"] < change:
                raise SalesError("Cash change cannot exceed the cash tendered.")
            allocations[cash_index]["amount"] = money_round(
                allocations[cash_index]["amount"] - change
            )
            if allocations[cash_index]["amount"] <= 0:
                raise SalesError("Cash payment allocation must remain positive after change.")
        actual_paid = money_round(tendered + loyalty_amount)
    elif amount_due == 0:
        allocations, actual_paid, change = [], loyalty_amount, 0.0
    elif payment_method == PAYMENT_MIXED:
        raise SalesError("Mixed payment requires tender allocations.")
    elif payment_method in {PAYMENT_WALLET, PAYMENT_CREDIT}:
        allocations = [{"payment_method": payment_method, "amount": amount_due,
                        "reference": normalize_payment_reference(payment_reference, payment_method)}]
        actual_paid, change = total_amount, 0.0
    else:
        legacy = process_payment(amount_due, payment_method, amount_paid)
        allocations = [{"payment_method": payment_method, "amount": amount_due,
                        "reference": normalize_payment_reference(payment_reference, payment_method)}]
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
            "SELECT id, payment_method, amount, reference FROM sale_payments WHERE sale_id = ? ORDER BY id",
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


def process_return(session, sale_id, return_items, reason, *, refund_method="ORIGINAL_TENDER",
                   payment_id=None, idempotency_key=None):
    session = require_return_management(session)
    if not reason or not reason.strip():
        raise SalesError("Return reason is required.")
    if not return_items:
        raise SalesError("Return must contain at least one item.")

    with transaction() as conn:
        idempotency_key = str(idempotency_key).strip() if idempotency_key else None
        if idempotency_key:
            existing = conn.execute("SELECT id FROM sales_returns WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if existing:
                return get_return_data(existing["id"])
        sale = conn.execute("SELECT * FROM sales WHERE sale_id = ?", (sale_id,)).fetchone()
        if not sale:
            raise SalesError("Sale not found.")
        session = require_store_access(session, sale["store_id"], manage=True)
        refund_method = str(refund_method or "ORIGINAL_TENDER").strip().upper()
        if refund_method not in PAYMENT_METHODS - {PAYMENT_MIXED} | {"ORIGINAL_TENDER"}:
            raise SalesError("Invalid refund method.")
        if payment_id is not None:
            linked = conn.execute("SELECT id FROM sale_payments WHERE id=? AND sale_id=?", (int(payment_id), sale_id)).fetchone()
            if not linked:
                raise SalesError("Refund payment does not belong to the original sale.")

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
            """INSERT INTO sales_returns
               (sale_id, user_id, store_id, reason, total_refunded, refund_method, payment_id, idempotency_key)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (sale_id, session.user_id, sale["store_id"], reason.strip(), money_round(total_refunded),
             refund_method, int(payment_id) if payment_id is not None else None, idempotency_key)
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
        from app.finance.posting_service import post_return
        post_return(session, return_id, conn)

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


def refund_sale(session, sale_id, reason="Full sale refund", **refund_options):
    with get_connection() as conn:
        rows = conn.execute("SELECT id, quantity FROM sale_items WHERE sale_id = ?", (sale_id,)).fetchall()
    if not rows:
        raise SalesError("Sale has no refundable items.")
    return process_return(
        session,
        sale_id,
        [{"sale_item_id": row["id"], "quantity": row["quantity"]} for row in rows],
        reason,
        **refund_options,
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


def search_sales(
    session, store_id=None, customer_id=None, date_from=None, date_to=None,
):
    """Return store-scoped sale headers for integration and administration clients."""
    session = require_session(session)
    store_id = int(store_id or session.store_id)
    require_store_access(session, store_id)
    filters = ["s.store_id = ?"]
    params = [store_id]
    if customer_id is not None:
        filters.append("s.customer_id = ?")
        params.append(int(customer_id))
    if date_from:
        filters.append("DATE(COALESCE(s.created_at, s.timestamp)) >= DATE(?)")
        params.append(str(date_from))
    if date_to:
        filters.append("DATE(COALESCE(s.created_at, s.timestamp)) <= DATE(?)")
        params.append(str(date_to))
    with get_connection() as conn:
        return [
            dict(row)
            for row in conn.execute(
                f"""SELECT s.*, st.code AS store_code, c.customer_code,
                           c.first_name AS customer_first_name,
                           c.last_name AS customer_last_name,
                           COALESCE((SELECT SUM(sr.total_refunded)
                                     FROM sales_returns sr
                                     WHERE sr.sale_id = s.sale_id), 0) AS refund_total
                    FROM sales s
                    JOIN stores st ON st.id = s.store_id
                    LEFT JOIN customers c ON c.id = s.customer_id
                    WHERE {' AND '.join(filters)}
                    ORDER BY COALESCE(s.created_at, s.timestamp) DESC, s.sale_id DESC""",
                params,
            ).fetchall()
        ]


def validate_payment_method(payment_method):
    if payment_method not in PAYMENT_METHODS:
        raise SalesError("Invalid payment method.")


def normalize_payment_reference(value, payment_method):
    """Return a safe operational reference; no gateway verification is implied."""
    if value is None or not str(value).strip():
        return None
    if payment_method not in {PAYMENT_CARD, PAYMENT_TRANSFER}:
        raise SalesError("Payment references are only supported for card and transfer tenders.")
    reference = " ".join(str(value).strip().upper().split())
    if len(reference) > PAYMENT_REFERENCE_MAX_LENGTH or not PAYMENT_REFERENCE_PATTERN.fullmatch(reference):
        raise SalesError("Payment reference is malformed or too long.")
    return reference


def require_session(session):
    return validate_session(session)


def require_return_management(session):
    session = validate_session(session)
    if session.role not in INVENTORY_ROLES:
        raise AuthorizationError("Only admin and manager users can process returns.")
    return session


def money_round(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
