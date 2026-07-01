from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from auth import AuthorizationError, INVENTORY_ROLES, require_store_access, validate_session
from app.database.db_manager import get_connection
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
PAYMENT_METHODS = {PAYMENT_CASH, PAYMENT_CARD, PAYMENT_TRANSFER, PAYMENT_MIXED}
PAYMENT_STATUS_PAID = "PAID"
DISCOUNT_PERCENTAGE = "PERCENTAGE"
DISCOUNT_FIXED = "FIXED"


def calculate_totals(items, discount_type=None, discount_value=0, tax_rate=0, store_id=None):
    if not items:
        raise ValueError("Sale must contain at least one item.")

    subtotal = 0.0
    normalized_items = []
    with get_connection() as conn:
        for item in items:
            product_id = item.get("product_id")
            quantity = int(item.get("quantity", 0))
            validate_positive_quantity(quantity)
            product = get_product_by_id(product_id, conn=conn, store_id=store_id)
            if not product or not product["is_active"]:
                raise ValueError("Product not found or inactive.")
            unit_price = float(product["selling_price"])
            if unit_price < 0:
                raise ValueError("Unit price cannot be negative.")
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

    discount_amount = calculate_discount(subtotal, discount_type, discount_value)
    taxable_amount = subtotal - discount_amount
    if tax_rate < 0:
        raise ValueError("Tax rate cannot be negative.")
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
        raise ValueError("Discount cannot be negative.")
    if not discount_type or discount_value == 0:
        return 0.0
    if discount_type == DISCOUNT_PERCENTAGE:
        if discount_value > 100:
            raise ValueError("Percentage discount cannot exceed 100.")
        return subtotal * (discount_value / 100)
    if discount_type == DISCOUNT_FIXED:
        if discount_value > subtotal:
            raise ValueError("Fixed discount cannot exceed subtotal.")
        return discount_value
    raise ValueError("Invalid discount type.")


def process_payment(total_amount, payment_method, amount_paid=None):
    validate_payment_method(payment_method)
    total_amount = money_round(total_amount)
    if amount_paid is None:
        amount_paid = total_amount if payment_method in {PAYMENT_CARD, PAYMENT_TRANSFER} else 0
    amount_paid = money_round(amount_paid)
    if amount_paid < total_amount:
        raise ValueError("Insufficient payment.")
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
        prefix = f"POS-{date_key}-"
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
    tax_rate=0,
    store_id=None,
    register_name="REGISTER-1",
):
    session = require_session(session)
    store_id = int(store_id or session.store_id)
    session = require_store_access(session, store_id)
    if discount_value and session.role not in INVENTORY_ROLES:
        raise AuthorizationError("Only admin and manager users can apply sale discounts.")
    totals = calculate_totals(
        items,
        discount_type=discount_type,
        discount_value=discount_value,
        tax_rate=tax_rate,
        store_id=store_id,
    )
    payment = process_payment(totals["total_amount"], payment_method, amount_paid)

    with get_connection() as conn:
        receipt_number = generate_receipt_number(conn)
        cursor = conn.execute(
            """INSERT INTO sales (
                receipt_number, user_id, store_id, register_name, username, cashier_name,
                subtotal, discount_amount,
                tax, tax_amount, total, total_amount, payment_method, payment_status,
                amount_paid, change_given
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                receipt_number,
                session.user_id,
                store_id,
                str(register_name or "REGISTER-1").strip() or "REGISTER-1",
                session.username,
                session.username,
                totals["subtotal"],
                totals["discount_amount"],
                totals["tax_amount"],
                totals["tax_amount"],
                totals["total_amount"],
                totals["total_amount"],
                payment["payment_method"],
                payment["payment_status"],
                payment["amount_paid"],
                payment["change_given"],
            )
        )
        sale_id = cursor.lastrowid
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

    return print_receipt_data(sale_id)


def print_receipt_data(sale_id):
    with get_connection() as conn:
        sale = conn.execute("SELECT * FROM sales WHERE sale_id = ?", (sale_id,)).fetchone()
        if not sale:
            raise ValueError("Sale not found.")
        items = [dict(row) for row in conn.execute(
            """SELECT si.id, si.product_id, p.sku, p.name, si.quantity, si.price_at_sale,
                      (si.quantity * si.price_at_sale) AS line_total
               FROM sale_items si
               LEFT JOIN products p ON CAST(si.product_id AS INTEGER) = p.id
               WHERE si.sale_id = ?
               ORDER BY si.id""",
            (sale_id,)
        ).fetchall()]
    return {"sale": dict(sale), "items": items}


def process_return(session, sale_id, return_items, reason):
    session = require_return_management(session)
    if not reason or not reason.strip():
        raise ValueError("Return reason is required.")
    if not return_items:
        raise ValueError("Return must contain at least one item.")

    with get_connection() as conn:
        sale = conn.execute("SELECT * FROM sales WHERE sale_id = ?", (sale_id,)).fetchone()
        if not sale:
            raise ValueError("Sale not found.")
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
                raise ValueError("Sale item not found.")
            returned_qty = conn.execute(
                """SELECT COALESCE(SUM(sri.quantity), 0) AS qty
                   FROM sales_return_items sri
                   JOIN sales_returns sr ON sr.id = sri.return_id
                   WHERE sr.sale_id = ? AND sri.sale_item_id = ?""",
                (sale_id, sale_item_id)
            ).fetchone()["qty"]
            if returned_qty + quantity > sale_item["quantity"]:
                raise ValueError("Refund quantity cannot exceed sold quantity.")
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

    return get_return_data(return_id)


def refund_sale(session, sale_id, reason="Full sale refund"):
    with get_connection() as conn:
        rows = conn.execute("SELECT id, quantity FROM sale_items WHERE sale_id = ?", (sale_id,)).fetchall()
    if not rows:
        raise ValueError("Sale has no refundable items.")
    return process_return(
        session,
        sale_id,
        [{"sale_item_id": row["id"], "quantity": row["quantity"]} for row in rows],
        reason,
    )


def restore_return_stock(conn, product_id, quantity, user_id, notes=None, store_id=None):
    product = get_product_by_id(product_id, conn=conn, store_id=store_id)
    if not product:
        raise ValueError("Product not found.")
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
            raise ValueError("Return not found.")
        items = [dict(row) for row in conn.execute(
            "SELECT * FROM sales_return_items WHERE return_id = ? ORDER BY id",
            (return_id,)
        ).fetchall()]
    return {"return": dict(sales_return), "items": items}


def validate_payment_method(payment_method):
    if payment_method not in PAYMENT_METHODS:
        raise ValueError("Invalid payment method.")


def require_session(session):
    return validate_session(session)


def require_return_management(session):
    session = validate_session(session)
    if session.role not in INVENTORY_ROLES:
        raise AuthorizationError("Only admin and manager users can process returns.")
    return session


def money_round(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
