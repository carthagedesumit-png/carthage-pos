from app.database.db_manager import get_connection


def get_sales_summary():
    """
    Returns overall sales statistics.
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS transaction_count,
                COALESCE(SUM(total_amount), 0) AS total_sales,
                COALESCE(SUM(tax_amount), 0) AS total_tax,
                COALESCE(AVG(total_amount), 0) AS average_sale
            FROM sales
            """
        ).fetchone()

    return {
        "transaction_count": row["transaction_count"],
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
            SELECT
                COUNT(*) AS transaction_count,
                COALESCE(SUM(total_amount), 0) AS total_sales,
                COALESCE(SUM(tax_amount), 0) AS total_tax,
                COALESCE(AVG(total_amount), 0) AS average_sale
            FROM sales
            WHERE DATE(created_at) = DATE('now', 'localtime')
            """
        ).fetchone()

    return {
        "transaction_count": row["transaction_count"],
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
            SELECT
                p.id,
                p.sku,
                p.name,
                SUM(si.quantity) AS units_sold,
                SUM(si.quantity * si.price_at_sale) AS revenue
            FROM sale_items si
            JOIN products p
                ON CAST(si.product_id AS INTEGER) = p.id
            GROUP BY p.id, p.sku, p.name
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
            SELECT
                COUNT(*) AS transaction_count,
                COALESCE(SUM(total_amount), 0) AS total_sales,
                COALESCE(SUM(tax_amount), 0) AS total_tax,
                COALESCE(AVG(total_amount), 0) AS average_sale
            FROM sales
            WHERE DATE(created_at)
                  BETWEEN DATE(?) AND DATE(?)
            """,
            (start_date, end_date),
        ).fetchone()

    return {
        "transaction_count": row["transaction_count"],
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
            WHERE quantity_in_stock <= reorder_level
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
            SELECT
                payment_method,
                COUNT(*) AS transaction_count,
                COALESCE(SUM(total_amount), 0) AS total_sales
            FROM sales
            GROUP BY payment_method
            ORDER BY total_sales DESC
            """
        ).fetchall()

    return [
        {
            "payment_method": row["payment_method"],
            "transaction_count": row["transaction_count"],
            "total_sales": float(row["total_sales"]),
        }
        for row in rows
    ]