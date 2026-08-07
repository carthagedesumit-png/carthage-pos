"""Product identifier management and scanner-compatible lookup."""

import re
from sqlite3 import IntegrityError

from auth import require_inventory_management, require_store_access, require_user_management, validate_session
from app.core.config import get_config
from app.core.exceptions import BarcodeError
from app.core.logging_utils import get_logger, log_event
from app.database.db_manager import get_connection
from app.database.transactions import transaction


VALID_FORMATS = {"CODE39", "CODE128", "EAN8", "EAN13", "UPCA", "QR"}
VALID_TYPES = {"PRIMARY", "SECONDARY", "SUPPLIER", "QR"}
logger = get_logger("barcodes")


def _checksum(payload: str) -> str:
    total = sum((3 if index % 2 == 0 else 1) * int(digit) for index, digit in enumerate(reversed(payload)))
    return str((10 - total % 10) % 10)


def validate_identifier(value: str, barcode_format: str) -> str:
    """Normalize and validate an identifier, including retail checksums."""
    barcode_format = str(barcode_format or "").strip().upper().replace("-", "")
    if barcode_format not in VALID_FORMATS:
        raise BarcodeError(f"Unsupported barcode format: {barcode_format or 'empty'}.")
    value = str(value or "").strip()
    if not value:
        raise BarcodeError("Barcode value is required.")
    if barcode_format == "CODE39":
        value = value.upper()
        if not re.fullmatch(r"[0-9A-Z. $/+%-]+", value):
            raise BarcodeError("Code 39 contains unsupported characters.")
    elif barcode_format == "CODE128":
        if len(value) > 128 or any(ord(char) < 32 or ord(char) > 126 for char in value):
            raise BarcodeError("Code 128 must contain 1-128 printable ASCII characters.")
    elif barcode_format in {"EAN8", "EAN13", "UPCA"}:
        length = {"EAN8": 8, "EAN13": 13, "UPCA": 12}[barcode_format]
        if not value.isdigit() or len(value) != length:
            raise BarcodeError(f"{barcode_format} must contain exactly {length} digits.")
        if _checksum(value[:-1]) != value[-1]:
            raise BarcodeError(f"{barcode_format} checksum is invalid.")
    elif len(value) > 2048:
        raise BarcodeError("QR identifier cannot exceed 2048 characters.")
    return value


def _generated_value(product: dict, barcode_format: str, generation_index: int = 0) -> str:
    settings = get_config().barcodes
    prefix = settings.company_prefix or "POS"
    if barcode_format in {"EAN8", "EAN13", "UPCA"}:
        payload_length = {"EAN8": 7, "EAN13": 12, "UPCA": 11}[barcode_format]
        digits = "".join(char for char in prefix if char.isdigit())
        seed = f"{digits}{product['id']}{generation_index}"[-payload_length:].zfill(payload_length)
        return seed + _checksum(seed)
    if barcode_format == "QR":
        return f"{prefix}:PRODUCT:{product['id']}:{product['sku']}:{generation_index}"
    safe_prefix = re.sub(r"[^A-Z0-9]", "", prefix.upper()) or "POS"
    return f"{safe_prefix}-{product['id']:08d}-{generation_index}"


def generate_identifier(session, product_id: int, barcode_format: str | None = None,
                        identifier_type: str = "PRIMARY", regenerate: bool = False) -> dict:
    """Generate a unique product identifier; managers and admins may generate."""
    session = require_inventory_management(session)
    barcode_format = (barcode_format or get_config().barcodes.default_format).upper().replace("-", "")
    identifier_type = str(identifier_type).upper()
    if identifier_type not in VALID_TYPES:
        raise BarcodeError("Invalid identifier type.")
    if barcode_format == "QR" and not get_config().barcodes.qr_enabled:
        raise BarcodeError("QR identifiers are disabled.")
    with get_connection() as conn:
        product = conn.execute("SELECT id, sku FROM products WHERE id = ?", (product_id,)).fetchone()
        generation_index = conn.execute(
            "SELECT COUNT(*) FROM product_identifiers WHERE product_id = ?", (product_id,)
        ).fetchone()[0]
    if not product:
        raise BarcodeError("Product not found.")
    value = validate_identifier(
        _generated_value(dict(product), barcode_format, generation_index), barcode_format
    )
    return _store_identifier(session, product_id, value, barcode_format, identifier_type,
                             primary=identifier_type == "PRIMARY", regenerate=regenerate)


def assign_identifier(session, product_id: int, value: str, barcode_format: str,
                      identifier_type: str = "PRIMARY", primary: bool | None = None) -> dict:
    """Manually assign an identifier; reserved for administrators."""
    session = require_user_management(session)
    identifier_type = str(identifier_type).upper()
    if identifier_type not in VALID_TYPES:
        raise BarcodeError("Invalid identifier type.")
    barcode_format = str(barcode_format).upper().replace("-", "")
    value = validate_identifier(value, barcode_format)
    return _store_identifier(session, product_id, value, barcode_format, identifier_type,
                             primary=identifier_type == "PRIMARY" if primary is None else bool(primary))


def _store_identifier(session, product_id, value, barcode_format, identifier_type,
                      primary=False, regenerate=False):
    try:
        with transaction() as conn:
            product = conn.execute("SELECT id FROM products WHERE id = ?", (product_id,)).fetchone()
            if not product:
                raise BarcodeError("Product not found.")
            old_value = None
            if primary:
                current = conn.execute(
                    "SELECT id, value FROM product_identifiers WHERE product_id = ? AND is_primary = 1 AND is_active = 1",
                    (product_id,),
                ).fetchone()
                if current and not regenerate:
                    if current["value"].casefold() == value.casefold():
                        return dict(conn.execute("SELECT * FROM product_identifiers WHERE id = ?", (current["id"],)).fetchone())
                    raise BarcodeError("Product already has a primary barcode; request regeneration to replace it.")
                if current:
                    old_value = current["value"]
                    conn.execute(
                        "UPDATE product_identifiers SET is_primary = 0, is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (current["id"],),
                    )
            cursor = conn.execute(
                """INSERT INTO product_identifiers
                   (product_id, identifier_type, format, value, is_primary, created_by)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (product_id, identifier_type, barcode_format, value, int(primary), session.user_id),
            )
            identifier_id = cursor.lastrowid
            if primary:
                conn.execute("UPDATE products SET barcode = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (value, product_id))
            action = "REGENERATED" if old_value else "ASSIGNED"
            conn.execute(
                """INSERT INTO barcode_audit
                   (product_id, identifier_id, action, old_value, new_value, format, user_id, store_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (product_id, identifier_id, action, old_value, value, barcode_format, session.user_id, session.store_id),
            )
            result = dict(conn.execute("SELECT * FROM product_identifiers WHERE id = ?", (identifier_id,)).fetchone())
    except IntegrityError as exc:
        raise BarcodeError("Barcode or identifier already exists.") from exc
    log_event(logger, "barcode_stored", product_id=product_id, identifier_type=identifier_type,
              barcode_format=barcode_format, user_id=session.user_id)
    return result


def get_product_identifiers(product_id: int, include_inactive: bool = False) -> list[dict]:
    clause = "" if include_inactive else "AND is_active = 1"
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(
            f"SELECT * FROM product_identifiers WHERE product_id = ? {clause} ORDER BY is_primary DESC, id",
            (product_id,),
        ).fetchall()]


def lookup_product(value: str, store_id: int | None = None, session=None) -> dict | None:
    """Resolve SKU, legacy barcode, or any active normalized identifier."""
    value = str(value or "").strip()
    if not value:
        raise BarcodeError("Identifier is required.")
    if session is not None:
        session = validate_session(session)
        store_id = require_store_access(session, int(store_id or session.store_id)).store_id
    with get_connection() as conn:
        if store_id is None:
            store_id = conn.execute("SELECT id FROM stores WHERE code = 'MAIN' COLLATE NOCASE").fetchone()[0]
        row = conn.execute(
            """SELECT p.id, p.sku AS product_id, p.name, p.selling_price AS price,
                      si.quantity_on_hand AS stock, si.average_cost AS cost_price, si.store_id
               FROM products p
               JOIN store_inventory si ON si.product_id = p.id AND si.store_id = ?
               LEFT JOIN product_identifiers pi ON pi.product_id = p.id AND pi.is_active = 1
               WHERE p.is_active = 1 AND
                     (p.sku = ? COLLATE NOCASE OR p.barcode = ? COLLATE NOCASE
                      OR pi.value = ? COLLATE NOCASE OR CAST(p.id AS TEXT) = ?)
               ORDER BY pi.is_primary DESC LIMIT 1""",
            (store_id, value, value, value, value),
        ).fetchone()
    return dict(row) if row else None
