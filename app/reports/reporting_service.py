from app.database.db_manager import get_connection


def get_sales_summary():
    """
    Returns overall sales statistics.
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            WITH sale_totals AS (
                SELECT COUNT(*) AS transaction_count,
                       COALESCE(SUM(total_amount), 0) AS gross_sales,
                       COALESCE(SUM(tax_amount), 0) AS total_tax
                FROM sales
            ), refund_totals AS (
                SELECT COALESCE(SUM(total_refunded), 0) AS total_refunds
                FROM sales_returns
            )
            SELECT transaction_count, gross_sales, total_refunds,
                   gross_sales - total_refunds AS total_sales,
                   total_tax,
                   CASE WHEN transaction_count = 0 THEN 0
                        ELSE (gross_sales - total_refunds) / transaction_count END AS average_sale
            FROM sale_totals CROSS JOIN refund_totals
            """
        ).fetchone()

    return {
        "transaction_count": row["transaction_count"],
        "gross_sales": float(row["gross_sales"]),
        "total_refunds": float(row["total_refunds"]),
        "total_sales": float(row["total_sales"]),
        "total_tax": float(row["total_tax"]),
        "average_sale": float(row["average_sale"]),
    }


def get_daily_sales_report():
    """
    Returns today's sales statistics.
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            WITH sale_totals AS (
                SELECT COUNT(*) AS transaction_count,
                       COALESCE(SUM(total_amount), 0) AS gross_sales,
                       COALESCE(SUM(tax_amount), 0) AS total_tax
                FROM sales WHERE DATE(created_at) = DATE('now', 'localtime')
            ), refund_totals AS (
                SELECT COALESCE(SUM(total_refunded), 0) AS total_refunds
                FROM sales_returns WHERE DATE(created_at) = DATE('now', 'localtime')
            )
            SELECT transaction_count, gross_sales, total_refunds,
                   gross_sales - total_refunds AS total_sales,
                   total_tax,
                   CASE WHEN transaction_count = 0 THEN 0
                        ELSE (gross_sales - total_refunds) / transaction_count END AS average_sale
            FROM sale_totals CROSS JOIN refund_totals
            """
        ).fetchone()

    return {
        "transaction_count": row["transaction_count"],
        "gross_sales": float(row["gross_sales"]),
        "total_refunds": float(row["total_refunds"]),
        "total_sales": float(row["total_sales"]),
        "total_tax": float(row["total_tax"]),
        "average_sale": float(row["average_sale"]),
    }


def get_top_selling_products(limit=10):
    """
    Returns the best-selling products ordered by units sold.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            WITH returned AS (
                SELECT sale_item_id, SUM(quantity) AS quantity
                FROM sales_return_items GROUP BY sale_item_id
            )
            SELECT
                p.id,
                p.sku,
                p.name,
                SUM(si.quantity - COALESCE(r.quantity, 0)) AS units_sold,
                SUM((si.quantity - COALESCE(r.quantity, 0)) * si.price_at_sale) AS revenue
            FROM sale_items si
            LEFT JOIN returned r ON r.sale_item_id = si.id
            JOIN products p
                ON CAST(si.product_id AS INTEGER) = p.id
            GROUP BY p.id, p.sku, p.name
            HAVING SUM(si.quantity - COALESCE(r.quantity, 0)) > 0
            ORDER BY units_sold DESC, revenue DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [
        {
            "id": row["id"],
            "sku": row["sku"],
            "name": row["name"],
            "units_sold": int(row["units_sold"]),
            "revenue": float(row["revenue"]),
        }
        for row in rows
    ]


def get_sales_report(start_date, end_date):
    """
    Returns sales statistics for an inclusive date range.

    Dates should be supplied as YYYY-MM-DD strings.
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            WITH sale_totals AS (
                SELECT COUNT(*) AS transaction_count,
                       COALESCE(SUM(total_amount), 0) AS gross_sales,
                       COALESCE(SUM(tax_amount), 0) AS total_tax
                FROM sales
                WHERE DATE(created_at) BETWEEN DATE(?) AND DATE(?)
            ), refund_totals AS (
                SELECT COALESCE(SUM(total_refunded), 0) AS total_refunds
                FROM sales_returns
                WHERE DATE(created_at) BETWEEN DATE(?) AND DATE(?)
            )
            SELECT transaction_count, gross_sales, total_refunds,
                   gross_sales - total_refunds AS total_sales,
                   total_tax,
                   CASE WHEN transaction_count = 0 THEN 0
                        ELSE (gross_sales - total_refunds) / transaction_count END AS average_sale
            FROM sale_totals CROSS JOIN refund_totals
            """,
            (start_date, end_date, start_date, end_date),
        ).fetchone()

    return {
        "transaction_count": row["transaction_count"],
        "gross_sales": float(row["gross_sales"]),
        "total_refunds": float(row["total_refunds"]),
        "total_sales": float(row["total_sales"]),
        "total_tax": float(row["total_tax"]),
        "average_sale": float(row["average_sale"]),
    }


def get_low_stock_products():
    """
    Returns products whose stock quantity is less than or equal
    to their configured reorder level.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                sku,
                barcode,
                name,
                quantity_in_stock,
                reorder_level
            FROM products
            WHERE is_active = 1 AND quantity_in_stock <= reorder_level
            ORDER BY quantity_in_stock ASC, name ASC
            """
        ).fetchall()

    return [
        {
            "id": row["id"],
            "sku": row["sku"],
            "barcode": row["barcode"],
            "name": row["name"],
            "quantity_in_stock": row["quantity_in_stock"],
            "reorder_level": row["reorder_level"],
        }
        for row in rows
    ]


def get_payment_method_report():
    """
    Returns sales grouped by payment method.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            WITH refunds AS (
                SELECT sale_id, SUM(total_refunded) AS total_refunded
                FROM sales_returns GROUP BY sale_id
            )
            SELECT
                s.payment_method,
                COUNT(*) AS transaction_count,
                COALESCE(SUM(s.total_amount), 0) AS gross_sales,
                COALESCE(SUM(r.total_refunded), 0) AS total_refunds,
                COALESCE(SUM(s.total_amount - COALESCE(r.total_refunded, 0)), 0) AS total_sales
            FROM sales s
            LEFT JOIN refunds r ON r.sale_id = s.sale_id
            GROUP BY s.payment_method
            ORDER BY total_sales DESC
            """
        ).fetchall()

    return [
        {
            "payment_method": row["payment_method"],
            "transaction_count": row["transaction_count"],
            "gross_sales": float(row["gross_sales"]),
            "total_refunds": float(row["total_refunds"]),
            "total_sales": float(row["total_sales"]),
        }
        for row in rows
    ]

def get_inventory_valuation():
    """
    Returns overall inventory valuation.
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_products,
                COALESCE(SUM(quantity_in_stock), 0) AS total_units,
                COALESCE(
                    SUM(quantity_in_stock * cost_price),
                    0
                ) AS inventory_cost,
                COALESCE(
                    SUM(quantity_in_stock * selling_price),
                    0
                ) AS inventory_retail
            FROM products
            """
        ).fetchone()

    inventory_cost = float(row["inventory_cost"])
    inventory_retail = float(row["inventory_retail"])

    return {
        "total_products": int(row["total_products"]),
        "total_units": int(row["total_units"]),
        "inventory_cost": inventory_cost,
        "inventory_retail": inventory_retail,
        "potential_profit": inventory_retail - inventory_cost,
    }
