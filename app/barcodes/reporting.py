"""Operational reports for product identification and label printing."""

from auth import require_inventory_management
from app.database.db_manager import get_connection


def products_without_barcode(session, store_id: int | None = None) -> list[dict]:
    session = require_inventory_management(session, store_id=store_id)
    store_id = int(store_id or session.store_id)
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(
            """SELECT p.id, p.sku, p.name, si.quantity_on_hand, si.store_id
               FROM products p JOIN store_inventory si ON si.product_id = p.id
               WHERE p.is_active = 1 AND si.store_id = ?
                 AND NOT EXISTS (SELECT 1 FROM product_identifiers pi
                                 WHERE pi.product_id = p.id AND pi.is_active = 1
                                   AND pi.identifier_type = 'PRIMARY')
               ORDER BY p.name""",
            (store_id,),
        ).fetchall()]


def duplicate_identifiers(session) -> list[dict]:
    require_inventory_management(session)
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(
            """SELECT value, COUNT(*) AS occurrences
               FROM product_identifiers WHERE is_active = 1
               GROUP BY value COLLATE NOCASE HAVING COUNT(*) > 1 ORDER BY value"""
        ).fetchall()]


def labels_printed(session, store_id: int | None = None) -> list[dict]:
    session = require_inventory_management(session, store_id=store_id)
    store_id = int(store_id or session.store_id)
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(
            """SELECT j.id, j.job_reference, j.template_code, j.printer_profile,
                      j.status, j.is_reprint, j.requested_at, j.completed_at,
                      u.username, COALESCE(SUM(i.quantity), 0) AS label_count
               FROM label_print_jobs j JOIN users u ON u.id = j.requested_by
               LEFT JOIN label_print_items i ON i.job_id = j.id
               WHERE j.store_id = ? GROUP BY j.id ORDER BY j.id DESC""",
            (store_id,),
        ).fetchall()]


def last_print_dates(session, store_id: int | None = None) -> list[dict]:
    session = require_inventory_management(session, store_id=store_id)
    store_id = int(store_id or session.store_id)
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(
            """SELECT p.id AS product_id, p.sku, p.name,
                      MAX(j.completed_at) AS last_printed_at,
                      COALESCE(SUM(CASE WHEN j.status = 'PRINTED' THEN i.quantity ELSE 0 END), 0) AS labels_printed
               FROM products p
               LEFT JOIN label_print_items i ON i.product_id = p.id
               LEFT JOIN label_print_jobs j ON j.id = i.job_id AND j.store_id = ?
               WHERE p.is_active = 1 GROUP BY p.id ORDER BY p.name""",
            (store_id,),
        ).fetchall()]


def barcode_audit(session, product_id: int | None = None) -> list[dict]:
    require_inventory_management(session)
    clause, params = ("WHERE a.product_id = ?", [product_id]) if product_id else ("", [])
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(
            f"""SELECT a.*, p.sku, p.name, u.username
                FROM barcode_audit a JOIN products p ON p.id = a.product_id
                LEFT JOIN users u ON u.id = a.user_id {clause}
                ORDER BY a.id DESC""",
            params,
        ).fetchall()]
