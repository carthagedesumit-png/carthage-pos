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


def sales_last_30_days():
    with get_connection() as conn:
        if not _table_exists(conn, "sales"):
            return {"labels": [], "values": []}

        columns = _columns(conn, "sales")
        date_col = "created_at" if "created_at" in columns else "timestamp" if "timestamp" in columns else None

        if not date_col or "total_amount" not in columns:
            return {"labels": [], "values": []}

        rows = conn.execute(
            f"""
            SELECT DATE({date_col}) AS sale_day,
                   COALESCE(SUM(total_amount), 0) AS total
            FROM sales
            GROUP BY DATE({date_col})
            ORDER BY DATE({date_col}) DESC
            LIMIT 30
            """
        ).fetchall()

    rows = list(reversed(rows))
    return {
        "labels": [r["sale_day"] for r in rows],
        "values": [float(r["total"]) for r in rows],
    }
