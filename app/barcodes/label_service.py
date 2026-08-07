"""Label composition, preview, hardware printing, and print audit services."""

from datetime import datetime
from html import escape

from auth import require_inventory_management
from app.barcodes.renderers import DEFAULT_RENDERER, BarcodeRenderer
from app.barcodes.templates import get_template, list_templates
from app.core.config import get_config
from app.core.exceptions import LabelError
from app.core.logging_utils import get_logger, log_event
from app.database.db_manager import get_connection
from app.database.transactions import transaction
from app.hardware.manager import get_hardware_manager
from app.hardware.profiles import get_printer_profile


logger = get_logger("labels")


def supported_templates() -> list[dict]:
    """Return reusable built-in template metadata."""
    return list_templates()


def preview_label(session, product_id: int, template_code: str | None = None,
                  store_id: int | None = None, width_mm: float | None = None,
                  height_mm: float | None = None, include_cost: bool = False,
                  renderer: BarcodeRenderer | None = None) -> dict:
    """Build structured, text, SVG, and PNG-placeholder label output."""
    session = require_inventory_management(session, store_id=store_id)
    store_id = int(store_id or session.store_id)
    settings = get_config().barcodes
    template = get_template(template_code or settings.default_label_template, width_mm, height_mm)
    with get_connection() as conn:
        row = conn.execute(
            """SELECT p.*, c.name AS category_name, s.name AS store_name,
                      si.average_cost AS store_cost,
                      pi.id AS identifier_id, pi.value AS identifier_value,
                      pi.format AS identifier_format
               FROM products p JOIN stores s ON s.id = ?
               LEFT JOIN store_inventory si ON si.product_id = p.id AND si.store_id = s.id
               LEFT JOIN categories c ON c.id = p.category_id
               LEFT JOIN product_identifiers pi ON pi.product_id = p.id AND pi.is_active = 1
                    AND ((? = 'QR' AND pi.identifier_type = 'QR')
                         OR (? <> 'QR' AND pi.is_primary = 1))
               WHERE p.id = ?""",
            (store_id, template.code, template.code, product_id),
        ).fetchone()
    if not row:
        raise LabelError("Product not found.")
    product = dict(row)
    value = product["identifier_value"] or product["barcode"] or product["sku"]
    barcode_format = product["identifier_format"] or "CODE128"
    if template.code == "QR" and barcode_format != "QR":
        raise LabelError("Product does not have an active QR identifier.")
    rendering = (renderer or DEFAULT_RENDERER).render(value, barcode_format)
    content = {
        "business_name": get_config().company.name,
        "store_name": product["store_name"],
        "product_name": product["name"],
        "sku": product["sku"],
        "barcode": value,
        "qr_code": value if barcode_format == "QR" else None,
        "selling_price": round(float(product["selling_price"]), 2),
        "cost_price": round(float(product["store_cost"] or product["cost_price"] or 0), 2) if include_cost else None,
        "promotion_price": product["promotion_price"],
        "category": product["category_name"] or "",
        "unit": product["unit"] or "each",
        "printed_date": datetime.now().isoformat(timespec="seconds"),
    }
    visible = {field: content.get(field) for field in template.fields}
    if include_cost:
        visible["cost_price"] = content["cost_price"]
    return {
        "template": template.to_dict(), "product_id": product_id, "store_id": store_id,
        "identifier_id": product["identifier_id"], "structured": visible,
        "text": _render_text(template.name, visible),
        "svg": _render_label_svg(template, visible, rendering["svg"]),
        "barcode_render": rendering, "png": rendering["png"],
    }


def print_labels(session, items: list[dict], template_code: str | None = None,
                 store_id: int | None = None, printer_profile: str | None = None,
                 original_job_id: int | None = None) -> dict:
    """Print one or more products and record failure without propagating device errors."""
    session = require_inventory_management(session, store_id=store_id)
    store_id = int(store_id or session.store_id)
    if not items:
        raise LabelError("At least one label item is required.")
    normalized, rendered = [], []
    for item in items:
        product_id, quantity = int(item.get("product_id", 0)), int(item.get("quantity", 1))
        if product_id <= 0 or quantity <= 0:
            raise LabelError("Product IDs and label quantities must be positive.")
        preview = preview_label(session, product_id, template_code, store_id)
        normalized.append((product_id, preview["identifier_id"], quantity))
        rendered.extend([preview["text"]] * quantity)
    settings = get_config().barcodes
    template_code = (template_code or settings.default_label_template).upper()
    profile_name = (printer_profile or settings.default_printer_profile).lower()
    profile = get_printer_profile(profile_name)
    with transaction() as conn:
        reference = _next_job_reference(conn)
        cursor = conn.execute(
            """INSERT INTO label_print_jobs
               (job_reference, store_id, template_code, printer_profile, status,
                is_reprint, original_job_id, requested_by)
               VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?)""",
            (reference, store_id, template_code, profile_name, int(original_job_id is not None),
             original_job_id, session.user_id),
        )
        job_id = cursor.lastrowid
        conn.executemany(
            "INSERT INTO label_print_items (job_id, product_id, identifier_id, quantity) VALUES (?, ?, ?, ?)",
            [(job_id, product_id, identifier_id, quantity)
             for product_id, identifier_id, quantity in normalized],
        )
    try:
        get_hardware_manager().printer.print_text("\n\n".join(rendered), profile, f"labels-{reference}")
    except Exception as exc:
        message = str(exc)[:250] or "Label printer unavailable."
        _finish_job(job_id, "FAILED", message)
        log_event(logger, "label_print_failed", job_id=job_id, user_id=session.user_id,
                  error_type=type(exc).__name__)
        return {"success": False, "job_id": job_id, "job_reference": reference, "error": message}
    _finish_job(job_id, "PRINTED")
    log_event(logger, "labels_printed", job_id=job_id, item_count=len(normalized),
              label_count=len(rendered), user_id=session.user_id)
    return {"success": True, "job_id": job_id, "job_reference": reference,
            "item_count": len(normalized), "label_count": len(rendered)}


def print_label(session, product_id: int, quantity: int = 1, **kwargs) -> dict:
    return print_labels(session, [{"product_id": product_id, "quantity": quantity}], **kwargs)


def reprint_label_job(session, job_id: int, printer_profile: str | None = None) -> dict:
    """Reprint the immutable item selection from an earlier label job."""
    session = require_inventory_management(session)
    with get_connection() as conn:
        job = conn.execute("SELECT * FROM label_print_jobs WHERE id = ?", (job_id,)).fetchone()
        items = conn.execute(
            "SELECT product_id, quantity FROM label_print_items WHERE job_id = ? ORDER BY id", (job_id,)
        ).fetchall()
    if not job:
        raise LabelError("Label print job not found.")
    return print_labels(session, [dict(item) for item in items], job["template_code"],
                        job["store_id"], printer_profile or job["printer_profile"], job_id)


def print_low_stock_labels(session, store_id: int | None = None,
                           template_code: str | None = None) -> dict:
    from app.inventory.inventory_service import get_low_stock_products
    session = require_inventory_management(session, store_id=store_id)
    store_id = int(store_id or session.store_id)
    items = [{"product_id": product["id"], "quantity": 1}
             for product in get_low_stock_products(store_id=store_id)]
    if not items:
        return {"success": True, "skipped": True, "reason": "No low-stock products."}
    return print_labels(session, items, template_code, store_id)


def print_inventory_count_labels(session, store_id: int | None = None,
                                 template_code: str = "WAREHOUSE") -> dict:
    from app.inventory.inventory_service import search_products
    session = require_inventory_management(session, store_id=store_id)
    store_id = int(store_id or session.store_id)
    items = [{"product_id": product["id"], "quantity": 1}
             for product in search_products(store_id=store_id)]
    if not items:
        return {"success": True, "skipped": True, "reason": "No active products."}
    return print_labels(session, items, template_code, store_id)


def print_labels_for_purchase_receipt(session, receipt_id: int,
                                      template_code: str | None = None) -> dict:
    """Print one label per received unit for a procurement receipt."""
    session = require_inventory_management(session)
    with get_connection() as conn:
        receipt = conn.execute(
            """SELECT pr.id, po.store_id FROM purchase_receipts pr
               JOIN purchase_orders po ON po.id = pr.purchase_order_id WHERE pr.id = ?""",
            (receipt_id,),
        ).fetchone()
        items = conn.execute(
            """SELECT poi.product_id, pri.quantity
               FROM purchase_receipt_items pri
               JOIN purchase_order_items poi ON poi.id = pri.purchase_order_item_id
               WHERE pri.receipt_id = ?""",
            (receipt_id,),
        ).fetchall()
    if not receipt:
        raise LabelError("Purchase receipt not found.")
    return print_labels(session, [dict(item) for item in items], template_code, receipt["store_id"])


def _render_text(title: str, content: dict) -> str:
    lines = [title.upper()]
    for key, value in content.items():
        if value is not None and value != "":
            lines.append(f"{key.replace('_', ' ').title()}: {value}")
    return "\n".join(lines)


def _render_label_svg(template, content, barcode_svg: str) -> str:
    lines = "".join(
        f'<text x="8" y="{18 + index * 15}" font-family="sans-serif" font-size="11">'
        f'{escape(key.replace("_", " ").title())}: {escape(str(value))}</text>'
        for index, (key, value) in enumerate(content.items()) if value not in (None, "")
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{template.width_mm}mm" '
        f'height="{template.height_mm}mm" viewBox="0 0 400 240">'
        f'<rect width="100%" height="100%" fill="white" stroke="black"/>{lines}'
        f'<g transform="translate(110,140) scale(.64)">{barcode_svg}</g></svg>'
    )


def _next_job_reference(conn) -> str:
    date = datetime.now().strftime("%Y%m%d")
    prefix = f"LBL-{date}-"
    row = conn.execute(
        "SELECT job_reference FROM label_print_jobs WHERE job_reference LIKE ? ORDER BY id DESC LIMIT 1",
        (f"{prefix}%",),
    ).fetchone()
    sequence = int(row["job_reference"].rsplit("-", 1)[-1]) + 1 if row else 1
    return f"{prefix}{sequence:04d}"


def _finish_job(job_id: int, status: str, error: str | None = None) -> None:
    with transaction() as conn:
        conn.execute(
            """UPDATE label_print_jobs SET status = ?, error_message = ?,
                      completed_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (status, error, job_id),
        )
