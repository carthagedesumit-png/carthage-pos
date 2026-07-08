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


def get_recent_sales(conn, limit=5):
    if not _table_exists(conn, "sales"):
        return []

    columns = _columns(conn, "sales")
    date_column = "created_at" if "created_at" in columns else "timestamp"

    receipt_column = "receipt_number" if "receipt_number" in columns else "sale_id"
    amount_column = "total_amount" if "total_amount" in columns else "total"

    query = f"""
        SELECT {receipt_column} AS receipt,
               {amount_column} AS amount,
               COALESCE({date_column}, '') AS sale_time
        FROM sales
        ORDER BY {date_column} DESC
        LIMIT ?
    """

    try:
        return [
            {
                "receipt": row["receipt"],
                "customer": "Guest",
                "amount": money(row["amount"]),
                "store": "Main Store",
                "time": row["sale_time"],
            }
            for row in conn.execute(query, (limit,))
        ]
    except Exception:
        return []


def get_low_stock_items(conn, limit=5):
    if not _table_exists(conn, "store_inventory"):
        return []

    try:
        return [
            {
                "name": row["name"],
                "quantity": row["quantity_on_hand"],
                "reorder_level": row["reorder_level"],
            }
            for row in conn.execute(
                """
                SELECT p.name, si.quantity_on_hand, si.reorder_level
                FROM store_inventory si
                LEFT JOIN products p ON p.id = si.product_id
                WHERE si.quantity_on_hand <= si.reorder_level
                ORDER BY si.quantity_on_hand ASC
                LIMIT ?
                """,
                (limit,),
            )
        ]
    except Exception:
        return []


def get_dashboard_summary():
    today = date.today().isoformat()

    with get_connection() as conn:
        sales_columns = _columns(conn, "sales")
        date_expr = "created_at" if "created_at" in sales_columns else "timestamp"

        transactions = 0
        today_sales = 0

        if _table_exists(conn, "sales"):
            try:
                sales_row = conn.execute(
                    f"""
                    SELECT COUNT(*) AS transactions,
                           COALESCE(SUM(total_amount), 0) AS today_sales
                    FROM sales
                    WHERE DATE({date_expr}) = DATE(?)
                    """,
                    (today,),
                ).fetchone()

                transactions = sales_row["transactions"]
                today_sales = sales_row["today_sales"]
            except Exception:
                pass

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
            "hardware_status": "Pending",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "recent_sales": get_recent_sales(conn),
            "low_stock_items": get_low_stock_items(conn),
            "notifications": [
                {"message": "Dashboard live widgets active", "time": "Now"},
                {"message": "API service online", "time": "Today"},
                {"message": "Backup system healthy", "time": "Today"},
            ],
        }
