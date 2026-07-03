"""Portable JSON/CSV exports and transactional imports for recovery workflows."""

import csv
import io
import json
from dataclasses import asdict
from datetime import datetime, timezone

from app.backup.permissions import require_backup_access, require_backup_admin
from app.backup.storage import append_audit, backup_directory, write_json_atomic
from app.core.config import get_config
from app.core.exceptions import BackupError
from app.core.logging_utils import get_logger, log_event
from app.database.db_manager import get_connection
from app.database.transactions import transaction


VALID_RESOURCES = {
    "products", "customers", "suppliers", "stores", "inventory",
    "reports_metadata", "configuration",
}
VALID_FORMATS = {"JSON", "CSV"}
MAX_IMPORT_ROWS = 10000
logger = get_logger("backup.transfer")


def export_resource(session, resource: str, output_format: str = "JSON") -> dict:
    """Export one supported business resource without exposing credentials."""
    session = require_backup_access(session)
    resource, output_format = _validate_request(resource, output_format)
    records = _export_records(resource)
    if output_format == "CSV" and resource in {"configuration", "reports_metadata"}:
        raise BackupError("Configuration and report metadata exports require JSON.")
    content = json.dumps(records, indent=2, default=str) if output_format == "JSON" \
        else _to_csv(records)
    append_audit("data_exported", session, resource=resource, format=output_format,
                 record_count=len(records) if isinstance(records, list) else 1)
    log_event(logger, "data_exported", resource=resource, format=output_format,
              user_id=session.user_id)
    return {
        "resource": resource,
        "format": output_format,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "record_count": len(records) if isinstance(records, list) else 1,
        "content": content,
    }


def import_resource(session, resource: str, content: str,
                    input_format: str = "JSON") -> dict:
    """Import portable records atomically; configuration imports are staged."""
    session = require_backup_admin(session)
    resource, input_format = _validate_request(resource, input_format)
    records = _parse_content(content, input_format)
    if resource in {"configuration", "reports_metadata"}:
        if input_format != "JSON" or not isinstance(records, dict):
            raise BackupError(f"{resource.replace('_', ' ').title()} import requires a JSON object.")
        path = backup_directory() / f"imported-{resource.replace('_', '-')}.json"
        write_json_atomic(path, records)
        result = {"resource": resource, "staged": True, "path": str(path),
                  "requires_operator_application": resource == "configuration"}
    else:
        if not isinstance(records, list) or not records:
            raise BackupError("Import must contain at least one record.")
        if len(records) > MAX_IMPORT_ROWS:
            raise BackupError(f"Import cannot exceed {MAX_IMPORT_ROWS} records per operation.")
        with transaction() as conn:
            imported = _import_records(conn, resource, records, session.user_id)
        result = {"resource": resource, "imported": imported, "staged": False}
    append_audit("data_imported", session, resource=resource,
                 record_count=len(records) if isinstance(records, list) else 1)
    log_event(logger, "data_imported", resource=resource, user_id=session.user_id)
    return result


def _validate_request(resource, data_format):
    resource = str(resource or "").strip().lower()
    data_format = str(data_format or "JSON").strip().upper()
    if resource not in VALID_RESOURCES:
        raise BackupError("Unsupported export/import resource.")
    if data_format not in VALID_FORMATS:
        raise BackupError("Export/import format must be JSON or CSV.")
    return resource, data_format


def _export_records(resource):
    if resource == "configuration":
        config = asdict(get_config())
        config["backup"]["directory"] = "<deployment-specific>"
        config["hardware"]["printer_path"] = "<deployment-specific>"
        return config
    if resource == "reports_metadata":
        return {
            "default_limit": get_config().reports.default_limit,
            "slow_moving_days": get_config().reports.slow_moving_days,
            "available_report_groups": [
                "sales", "inventory", "cashier", "store", "customer",
                "credit", "wallet", "loyalty", "barcodes",
            ],
        }
    queries = {
        "stores": """SELECT code, name, address, phone, email, is_active,
                            created_at, updated_at FROM stores ORDER BY code""",
        "suppliers": """SELECT name, phone, email, address, is_active,
                               created_at, updated_at FROM suppliers ORDER BY name""",
        "products": """SELECT p.sku, p.barcode, p.name, p.description,
                              c.name AS category_name, s.name AS supplier_name,
                              p.cost_price, p.selling_price, p.reorder_level,
                              p.is_active, p.unit, p.promotion_price,
                              p.created_at, p.updated_at
                       FROM products p LEFT JOIN categories c ON c.id = p.category_id
                       LEFT JOIN suppliers s ON s.id = p.supplier_id ORDER BY p.sku""",
        "customers": """SELECT customer_code, first_name, last_name, business_name,
                               phone_number, email, address, city, state, country,
                               date_of_birth, gender, tax_number, notes, credit_limit,
                               credit_due_date, is_active, created_at, updated_at
                        FROM customers ORDER BY customer_code""",
        "inventory": """SELECT s.code AS store_code, p.sku,
                               si.quantity_on_hand, si.reorder_level, si.average_cost,
                               si.updated_at
                        FROM store_inventory si JOIN stores s ON s.id = si.store_id
                        JOIN products p ON p.id = si.product_id ORDER BY s.code, p.sku""",
    }
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(queries[resource]).fetchall()]


def _parse_content(content, data_format):
    if not isinstance(content, str) or not content.strip():
        raise BackupError("Import content is required.")
    try:
        if data_format == "JSON":
            return json.loads(content)
        return [dict(row) for row in csv.DictReader(io.StringIO(content))]
    except (json.JSONDecodeError, csv.Error) as exc:
        raise BackupError("Import content is malformed.") from exc


def _to_csv(records):
    if not records:
        return ""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(records[0].keys()), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(records)
    return output.getvalue()


def _import_records(conn, resource, records, user_id):
    handlers = {
        "stores": _import_stores,
        "suppliers": _import_suppliers,
        "products": _import_products,
        "customers": _import_customers,
        "inventory": _import_inventory,
    }
    return handlers[resource](conn, records, user_id)


def _import_stores(conn, records, _user_id):
    for row in records:
        code, name = _required(row, "code"), _required(row, "name")
        conn.execute(
            """INSERT INTO stores (code, name, address, phone, email, is_active)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(code) DO UPDATE SET name=excluded.name, address=excluded.address,
                   phone=excluded.phone, email=excluded.email, is_active=excluded.is_active,
                   updated_at=CURRENT_TIMESTAMP""",
            (code, name, _optional(row, "address"), _optional(row, "phone"),
             _optional(row, "email"), _boolean(row.get("is_active", 1))),
        )
    return len(records)


def _import_suppliers(conn, records, _user_id):
    for row in records:
        name = _required(row, "name")
        conn.execute(
            """INSERT INTO suppliers (name, phone, email, address, is_active)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET phone=excluded.phone, email=excluded.email,
                   address=excluded.address, is_active=excluded.is_active,
                   updated_at=CURRENT_TIMESTAMP""",
            (name, _optional(row, "phone"), _optional(row, "email"),
             _optional(row, "address"), _boolean(row.get("is_active", 1))),
        )
    return len(records)


def _import_products(conn, records, user_id):
    for row in records:
        sku, name = _required(row, "sku"), _required(row, "name")
        category_id = _named_id(conn, "categories", row.get("category_name"), "General")
        supplier_id = _named_id(conn, "suppliers", row.get("supplier_name"), "Default Supplier")
        selling_price = _non_negative(row.get("selling_price"), "selling_price")
        cost_price = _non_negative(row.get("cost_price", 0), "cost_price")
        reorder_level = int(_non_negative(row.get("reorder_level", 0), "reorder_level"))
        promotion = _optional_number(row.get("promotion_price"), "promotion_price")
        barcode = _optional(row, "barcode")
        conn.execute(
            """INSERT INTO products
               (category_id, supplier_id, sku, barcode, name, description, cost_price,
                selling_price, reorder_level, is_active, unit, promotion_price)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(sku) DO UPDATE SET category_id=excluded.category_id,
                   supplier_id=excluded.supplier_id, barcode=excluded.barcode,
                   name=excluded.name, description=excluded.description,
                   cost_price=excluded.cost_price, selling_price=excluded.selling_price,
                   reorder_level=excluded.reorder_level, is_active=excluded.is_active,
                   unit=excluded.unit, promotion_price=excluded.promotion_price,
                   updated_at=CURRENT_TIMESTAMP""",
            (category_id, supplier_id, sku, barcode, name, _optional(row, "description"),
             cost_price, selling_price, reorder_level, _boolean(row.get("is_active", 1)),
             _optional(row, "unit") or "each", promotion),
        )
        product_id = conn.execute("SELECT id FROM products WHERE sku = ?", (sku,)).fetchone()[0]
        conn.execute(
            """INSERT OR IGNORE INTO store_inventory
               (store_id, product_id, quantity_on_hand, reorder_level, average_cost)
               SELECT id, ?, 0, ?, ? FROM stores""",
            (product_id, reorder_level, cost_price),
        )
        if barcode:
            conn.execute(
                """INSERT OR IGNORE INTO product_identifiers
                   (product_id, identifier_type, format, value, is_primary, created_by)
                   VALUES (?, 'PRIMARY', 'CODE128', ?, 1, ?)""",
                (product_id, barcode, user_id),
            )
    return len(records)


def _import_customers(conn, records, user_id):
    for row in records:
        code = _required(row, "customer_code")
        first_name, last_name = _required(row, "first_name"), _required(row, "last_name")
        conn.execute(
            """INSERT INTO customers
               (customer_code, first_name, last_name, business_name, phone_number,
                email, address, city, state, country, date_of_birth, gender,
                tax_number, notes, credit_limit, credit_due_date, created_by, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(customer_code) DO UPDATE SET first_name=excluded.first_name,
                   last_name=excluded.last_name, business_name=excluded.business_name,
                   phone_number=excluded.phone_number, email=excluded.email,
                   address=excluded.address, city=excluded.city, state=excluded.state,
                   country=excluded.country, date_of_birth=excluded.date_of_birth,
                   gender=excluded.gender, tax_number=excluded.tax_number,
                   notes=excluded.notes, credit_limit=excluded.credit_limit,
                   credit_due_date=excluded.credit_due_date, is_active=excluded.is_active,
                   updated_at=CURRENT_TIMESTAMP""",
            (code, first_name, last_name, _optional(row, "business_name"),
             _optional(row, "phone_number"), _optional(row, "email"),
             _optional(row, "address"), _optional(row, "city"), _optional(row, "state"),
             _optional(row, "country"), _optional(row, "date_of_birth"),
             _optional(row, "gender"), _optional(row, "tax_number"),
             _optional(row, "notes"), _non_negative(row.get("credit_limit", 0), "credit_limit"),
             _optional(row, "credit_due_date"), user_id, _boolean(row.get("is_active", 1))),
        )
    return len(records)


def _import_inventory(conn, records, user_id):
    for row in records:
        store = conn.execute("SELECT id FROM stores WHERE code = ? COLLATE NOCASE",
                             (_required(row, "store_code"),)).fetchone()
        product = conn.execute("SELECT id FROM products WHERE sku = ? COLLATE NOCASE",
                               (_required(row, "sku"),)).fetchone()
        if not store or not product:
            raise BackupError("Inventory import references an unknown store or product.")
        quantity = int(_non_negative(row.get("quantity_on_hand", 0), "quantity_on_hand"))
        reorder = int(_non_negative(row.get("reorder_level", 0), "reorder_level"))
        cost = _non_negative(row.get("average_cost", 0), "average_cost")
        previous_row = conn.execute(
            "SELECT quantity_on_hand FROM store_inventory WHERE store_id = ? AND product_id = ?",
            (store[0], product[0]),
        ).fetchone()
        previous = int(previous_row[0]) if previous_row else 0
        conn.execute(
            """INSERT INTO store_inventory
               (store_id, product_id, quantity_on_hand, reorder_level, average_cost)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(store_id, product_id) DO UPDATE SET
                   quantity_on_hand=excluded.quantity_on_hand,
                   reorder_level=excluded.reorder_level,
                   average_cost=excluded.average_cost, updated_at=CURRENT_TIMESTAMP""",
            (store[0], product[0], quantity, reorder, cost),
        )
        if quantity != previous:
            conn.execute(
                """INSERT INTO stock_movements
                   (product_id, movement_type, quantity, previous_quantity, new_quantity,
                    user_id, store_id, notes)
                   VALUES (?, 'ADJUSTMENT', ?, ?, ?, ?, ?, ?)""",
                (product[0], quantity - previous, previous, quantity, user_id, store[0],
                 "Disaster recovery inventory import"),
            )
        aggregate = conn.execute(
            """SELECT COALESCE(SUM(quantity_on_hand), 0),
                      COALESCE(SUM(quantity_on_hand * average_cost), 0),
                      COALESCE(MAX(reorder_level), 0)
               FROM store_inventory WHERE product_id = ?""",
            (product[0],),
        ).fetchone()
        total = int(aggregate[0])
        average = float(aggregate[1] / total) if total else 0.0
        conn.execute(
            """UPDATE products SET quantity_in_stock = ?, cost_price = ?, reorder_level = ?,
                      updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (total, average, int(aggregate[2]), product[0]),
        )
    return len(records)


def _named_id(conn, table, value, fallback):
    name = str(value or fallback).strip()
    row = conn.execute(f"SELECT id FROM {table} WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    if row:
        return row[0]
    cursor = conn.execute(f"INSERT INTO {table} (name) VALUES (?)", (name,))
    return cursor.lastrowid


def _required(row, field):
    value = str(row.get(field) or "").strip()
    if not value:
        raise BackupError(f"Import field is required: {field}.")
    return value


def _optional(row, field):
    value = row.get(field)
    return None if value is None or str(value).strip() == "" else str(value).strip()


def _non_negative(value, field):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise BackupError(f"Import field must be numeric: {field}.") from exc
    if number < 0:
        raise BackupError(f"Import field cannot be negative: {field}.")
    return number


def _optional_number(value, field):
    if value is None or str(value).strip() == "":
        return None
    return _non_negative(value, field)


def _boolean(value):
    if isinstance(value, bool):
        return int(value)
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return 1
    if normalized in {"0", "false", "no", "off"}:
        return 0
    raise BackupError("Import boolean value is invalid.")
