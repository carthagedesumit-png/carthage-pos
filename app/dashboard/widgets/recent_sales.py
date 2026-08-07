from app.database.db_manager import get_connection


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


def recent_sales(limit=10):
    with get_connection() as conn:
        if not _table_exists(conn, "sales"):
            return []

        columns = _columns(conn, "sales")

        sale_ref = "receipt_number" if "receipt_number" in columns else "sale_number" if "sale_number" in columns else "sale_id"
        amount_col = "total_amount" if "total_amount" in columns else "total"
        cashier_col = "cashier_name" if "cashier_name" in columns else "created_by"
        order_col = "id" if "id" in columns else "sale_id"

        if sale_ref not in columns or amount_col not in columns:
            return []

        rows = conn.execute(
            f"""
            SELECT {sale_ref} AS sale_reference,
                   {amount_col} AS total_amount,
                   {cashier_col} AS cashier_name
            FROM sales
            ORDER BY {order_col} DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(r) for r in rows]
