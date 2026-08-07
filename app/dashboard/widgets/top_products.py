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


def top_products(limit=10):
    with get_connection() as conn:
        if not _table_exists(conn, "sale_items"):
            return []

        columns = _columns(conn, "sale_items")
        name_col = "product_name" if "product_name" in columns else "product_id"
        qty_col = "quantity" if "quantity" in columns else None

        if not qty_col:
            return []

        rows = conn.execute(
            f"""
            SELECT {name_col} AS product_name,
                   SUM({qty_col}) AS qty
            FROM sale_items
            GROUP BY {name_col}
            ORDER BY qty DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(r) for r in rows]
