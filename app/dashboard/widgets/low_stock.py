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


def low_stock():
    with get_connection() as conn:
        if not _table_exists(conn, "store_inventory"):
            return []

        columns = _columns(conn, "store_inventory")
        required = {"quantity_on_hand", "reorder_level"}
        if not required.issubset(columns):
            return []

        rows = conn.execute(
            """
            SELECT quantity_on_hand,
                   reorder_level
            FROM store_inventory
            WHERE quantity_on_hand <= reorder_level
            ORDER BY quantity_on_hand
            LIMIT 25
            """
        ).fetchall()

    return [dict(r) for r in rows]
