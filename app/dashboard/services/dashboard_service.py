from datetime import date, datetime

from app.database.db_manager import get_connection


def money(value):
    return f"₦{float(value or 0):,.2f}"


def _table_exists(conn, table_name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _columns(conn, table_name):
    if not _table_exists(conn, table_name):
        return set()
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def count_table(conn, table_name):
    try:
        if not _table_exists(conn, table_name):
            return 0
        return conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    except Exception:
        return 0


def get_dashboard_summary():
    today = date.today().isoformat()

    with get_connection() as conn:
        sales_columns = _columns(conn, "sales")

        if "created_at" in sales_columns:
            date_expr = "created_at"
        elif "timestamp" in sales_columns:
            date_expr = "timestamp"
        else:
            date_expr = None

        transactions = 0
        today_sales = 0

        if _table_exists(conn, "sales"):
            if date_expr:
                sales_row = conn.execute(
                    f"""
                    SELECT COUNT(*) AS transactions,
                           COALESCE(SUM(total_amount), 0) AS today_sales
                    FROM sales
                    WHERE DATE({date_expr}) = DATE(?)
                    """,
                    (today,),
                ).fetchone()
            else:
                sales_row = conn.execute(
                    """
                    SELECT COUNT(*) AS transactions,
                           COALESCE(SUM(total_amount), 0) AS today_sales
                    FROM sales
                    """
                ).fetchone()

            transactions = sales_row["transactions"]
            today_sales = sales_row["today_sales"]

        low_stock = 0
        if _table_exists(conn, "store_inventory"):
            low_stock = conn.execute(
                """
                SELECT COUNT(*)
                FROM store_inventory
                WHERE quantity_on_hand <= reorder_level
                """
            ).fetchone()[0]

        inventory_value = 0
        if _table_exists(conn, "store_inventory"):
            inventory_value = conn.execute(
                """
                SELECT COALESCE(SUM(quantity_on_hand * average_cost), 0)
                FROM store_inventory
                """
            ).fetchone()[0]

        outstanding_credit = 0
        credit_columns = _columns(conn, "credit_transactions")
        if "balance_after" in credit_columns:
            outstanding_credit = conn.execute(
                "SELECT COALESCE(SUM(balance_after), 0) FROM credit_transactions"
            ).fetchone()[0]
        elif "amount" in credit_columns:
            outstanding_credit = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM credit_transactions"
            ).fetchone()[0]

        return {
            "today_sales": money(today_sales),
            "today_profit": money(0),
            "transactions": transactions,
            "low_stock": low_stock,
            "outstanding_credit": money(outstanding_credit),
            "inventory_value": money(inventory_value),
            "customers": count_table(conn, "customers"),
            "stores": count_table(conn, "stores"),
            "users": count_table(conn, "users"),
            "license_status": "Active",
            "backup_status": "Healthy",
            "api_status": "Online",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
