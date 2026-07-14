"""Category lifecycle operations owned by the inventory domain."""

from sqlite3 import IntegrityError

from auth import require_inventory_management
from app.core.exceptions import InventoryError
from app.core.logging_utils import get_logger, log_event
from app.core.validation import optional_text, required_text
from app.database.db_manager import get_connection
from app.database.transactions import transaction


logger = get_logger("inventory.categories")


def list_categories(include_inactive=False):
    where = "" if include_inactive else "WHERE c.is_active = 1"
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(
            f"""SELECT c.*, COUNT(p.id) AS product_count
                FROM categories c LEFT JOIN products p ON p.category_id = c.id
                {where} GROUP BY c.id ORDER BY c.name COLLATE NOCASE"""
        ).fetchall()]


def get_category(category_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,)).fetchone()
    return dict(row) if row else None


def create_category(session, name, description=None):
    session = require_inventory_management(session)
    name = required_text(name, "Category name", error_type=InventoryError)
    description = optional_text(description)
    try:
        with transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO categories (name, description, is_active) VALUES (?, ?, 1)",
                (name, description),
            )
            category_id = cursor.lastrowid
    except IntegrityError as exc:
        raise InventoryError("Category name already exists.") from exc
    log_event(logger, "category_created", category_id=category_id, user_id=session.user_id)
    return get_category(category_id)


def update_category(session, category_id, name, description=None):
    session = require_inventory_management(session)
    name = required_text(name, "Category name", error_type=InventoryError)
    description = optional_text(description)
    try:
        with transaction() as conn:
            cursor = conn.execute(
                """UPDATE categories SET name = ?, description = ?,
                   updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (name, description, category_id),
            )
            if not cursor.rowcount:
                raise InventoryError("Category not found.")
    except IntegrityError as exc:
        raise InventoryError("Category name already exists.") from exc
    log_event(logger, "category_updated", category_id=category_id, user_id=session.user_id)
    return get_category(category_id)


def deactivate_category(session, category_id):
    session = require_inventory_management(session)
    with transaction() as conn:
        referenced = conn.execute(
            "SELECT COUNT(*) FROM products WHERE category_id = ? AND is_active = 1", (category_id,)
        ).fetchone()[0]
        if referenced:
            raise InventoryError("Category cannot be deactivated while active products reference it.")
        cursor = conn.execute(
            "UPDATE categories SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (category_id,),
        )
        if not cursor.rowcount:
            raise InventoryError("Category not found.")
    log_event(logger, "category_deactivated", category_id=category_id, user_id=session.user_id)
    return get_category(category_id)


def reactivate_category(session, category_id):
    session = require_inventory_management(session)
    with transaction() as conn:
        cursor = conn.execute(
            "UPDATE categories SET is_active = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (category_id,),
        )
        if not cursor.rowcount:
            raise InventoryError("Category not found.")
    log_event(logger, "category_reactivated", category_id=category_id, user_id=session.user_id)
    return get_category(category_id)
