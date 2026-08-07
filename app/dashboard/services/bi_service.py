from datetime import date, timedelta

from app.database.db_manager import get_connection


def money(value):
    return f"₦{float(value or 0):,.2f}"


def table_exists(conn, table):
    return conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def columns(conn, table):
    if not table_exists(conn, table):
        return set()
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def sales_trend(days=7):
    result = []
    today = date.today()

    with get_connection() as conn:
        if not table_exists(conn, "sales"):
            return []

        cols = columns(conn, "sales")
        date_col = "created_at" if "created_at" in cols else "timestamp"

        for i in range(days - 1, -1, -1):
            day = today - timedelta(days=i)
            row = conn.execute(
                f"""
                SELECT COALESCE(SUM(total_amount), 0) AS total,
                       COUNT(*) AS count
                FROM sales
                WHERE DATE({date_col}) = DATE(?)
                """,
                (day.isoformat(),),
            ).fetchone()

            result.append({
                "date": day.isoformat(),
                "sales": float(row["total"] or 0),
                "transactions": row["count"],
            })

    return result


def top_products(limit=5):
    with get_connection() as conn:
        if not table_exists(conn, "sale_items") or not table_exists(conn, "products"):
            return []

        try:
            rows = conn.execute(
                """
                SELECT p.name,
                       SUM(si.quantity) AS quantity,
                       SUM(si.quantity * si.price_at_sale) AS revenue
                FROM sale_items si
                JOIN products p ON p.id = CAST(si.product_id AS INTEGER)
                GROUP BY p.name
                ORDER BY quantity DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

            return [
                {
                    "name": row["name"],
                    "quantity": row["quantity"],
                    "revenue": money(row["revenue"]),
                }
                for row in rows
            ]
        except Exception:
            return []


def business_insights():
    trend = sales_trend(2)
    products = top_products(1)

    insights = []

    if len(trend) == 2:
        yesterday = trend[0]["sales"]
        today = trend[1]["sales"]

        if today > yesterday:
            insights.append("Sales are higher than yesterday.")
        elif today < yesterday:
            insights.append("Sales are lower than yesterday.")
        else:
            insights.append("Sales are stable compared with yesterday.")

    if products:
        insights.append(f"Top selling product is {products[0]['name']}.")

    if not insights:
        insights.append("No major business insight yet. More data will improve recommendations.")

    return insights
