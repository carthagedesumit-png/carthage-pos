import re
from typing import Any, Mapping, Optional

from app.core.config import get_config
from app.core.exceptions import DocumentError
from app.core.logging_utils import get_logger, log_event
from app.database.db_manager import get_connection
from app.documents.branding import load_branding
from app.documents.renderers import attach_outputs


logger = get_logger("documents")


def generate_sales_receipt(
    sale_id: int,
    width_mm: int = 80,
    branding: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Generate a structured, text, and HTML sales receipt."""
    sale, items = _load_sale(sale_id)
    config = load_branding(branding)
    document = _sale_document(sale, items, config.to_dict())
    document.update(
        {
            "document_type": "sales_receipt",
            "title": "Sales Receipt",
            "document_number": sale["receipt_number"],
            "footer": config.receipt_footer,
        }
    )
    return _finalize(document, width_mm)


def generate_sales_invoice(
    sale_id: int,
    customer: Optional[Mapping[str, Any]] = None,
    branding: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Generate an A4-oriented invoice with safe customer placeholders."""
    sale, items = _load_sale(sale_id)
    config = load_branding(branding)
    document = _sale_document(sale, items, config.to_dict())
    document.update(
        {
            "document_type": "sales_invoice",
            "title": "Sales Invoice",
            "document_number": document_number(
                "invoice", sale_id, sale["store_code"]
            ),
            "customer": _customer_fields(customer),
            "footer": config.invoice_footer,
            "page_layout": "A4",
        }
    )
    return _finalize(document, 80)


def generate_credit_note(
    return_id: int,
    width_mm: int = 80,
    branding: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Generate a refund receipt and credit note for one recorded return."""
    with get_connection() as conn:
        header = conn.execute(
            """SELECT sr.*, s.receipt_number, s.sale_id, s.store_id,
                      st.code AS store_code, st.name AS store_name,
                      st.address AS store_address, st.phone AS store_phone,
                      st.email AS store_email,
                      u.username AS processed_by_username,
                      u.full_name AS processed_by_name
               FROM sales_returns sr
               JOIN sales s ON s.sale_id = sr.sale_id
               JOIN stores st ON st.id = s.store_id
               JOIN users u ON u.id = sr.user_id
               WHERE sr.id = ?""",
            (return_id,),
        ).fetchone()
        if not header:
            raise DocumentError("Sales return not found.")
        items = [
            dict(row)
            for row in conn.execute(
                """SELECT sri.sale_item_id, CAST(si.product_id AS INTEGER) AS product_id,
                          COALESCE(p.sku, si.product_id) AS sku,
                          COALESCE(p.name, 'Historical Product') AS description,
                          sri.quantity, si.price_at_sale AS unit_price,
                          sri.refund_amount AS line_total
                   FROM sales_return_items sri
                   JOIN sale_items si ON si.id = sri.sale_item_id
                   LEFT JOIN products p ON p.id = CAST(si.product_id AS INTEGER)
                   WHERE sri.return_id = ? ORDER BY sri.id""",
                (return_id,),
            ).fetchall()
        ]
    header = dict(header)
    config = load_branding(branding)
    document = {
        "document_type": "credit_note",
        "title": "Credit Note / Refund Receipt",
        "document_number": document_number(
            "credit_note", return_id, header["store_code"]
        ),
        "business": config.to_dict(),
        "store": _store_from_row(header),
        "metadata": {
            "return_reference": f"RETURN-{return_id:08d}",
            "original_receipt": header["receipt_number"],
            "sale_reference": header["sale_id"],
            "processed_at": header["created_at"],
            "processed_by": header["processed_by_name"]
            or header["processed_by_username"],
            "reason": header["reason"],
        },
        "line_items": items,
        "totals": {"total_refunded": float(header["total_refunded"])},
        "footer": config.receipt_footer,
    }
    return _finalize(document, width_mm)


def generate_purchase_order_document(
    purchase_order_id: int,
    branding: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Generate a purchase order document with supplier and pending balances."""
    with get_connection() as conn:
        header = conn.execute(
            """SELECT po.*, s.name AS supplier_name, s.phone AS supplier_phone,
                      s.email AS supplier_email, s.address AS supplier_address,
                      st.code AS store_code, st.name AS store_name,
                      st.address AS store_address, st.phone AS store_phone,
                      st.email AS store_email,
                      u.username AS created_by_username, u.full_name AS created_by_name
               FROM purchase_orders po
               JOIN suppliers s ON s.id = po.supplier_id
               JOIN stores st ON st.id = po.store_id
               JOIN users u ON u.id = po.created_by
               WHERE po.id = ?""",
            (purchase_order_id,),
        ).fetchone()
        if not header:
            raise DocumentError("Purchase order not found.")
        items = [
            dict(row)
            for row in conn.execute(
                """SELECT poi.product_id, p.sku,
                          COALESCE(p.name, 'Historical Product') AS description,
                          poi.ordered_quantity, poi.received_quantity,
                          poi.ordered_quantity - poi.received_quantity AS pending_quantity,
                          poi.unit_cost, poi.subtotal
                   FROM purchase_order_items poi
                   LEFT JOIN products p ON p.id = poi.product_id
                   WHERE poi.purchase_order_id = ? ORDER BY poi.id""",
                (purchase_order_id,),
            ).fetchall()
        ]
    header = dict(header)
    config = load_branding(branding)
    document = {
        "document_type": "purchase_order",
        "title": "Purchase Order",
        "document_number": document_number(
            "purchase_order", purchase_order_id, header["store_code"]
        ),
        "business": config.to_dict(),
        "store": _store_from_row(header),
        "supplier": _supplier_from_row(header),
        "metadata": {
            "po_reference": header["reference_number"],
            "status": header["status"],
            "created_at": header["created_at"],
            "expected_delivery_date": header["expected_delivery_date"] or "Not specified",
            "created_by": header["created_by_name"] or header["created_by_username"],
            "notes": header["notes"] or "",
            "supplier": header["supplier_name"],
            "supplier_contact": _contact_summary(
                header["supplier_phone"], header["supplier_email"], header["supplier_address"]
            ),
        },
        "line_items": items,
        "totals": {
            "ordered_total": _sum(items, "subtotal"),
            "ordered_units": _sum(items, "ordered_quantity", integer=True),
            "received_units": _sum(items, "received_quantity", integer=True),
            "pending_units": _sum(items, "pending_quantity", integer=True),
        },
        "footer": config.invoice_footer,
        "page_layout": "A4",
    }
    return _finalize(document, 80)


def generate_goods_received_note(
    receipt_id: int,
    branding: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Generate a goods received note with receipt-time pending quantities."""
    with get_connection() as conn:
        header = conn.execute(
            """SELECT pr.*, po.reference_number, po.id AS purchase_order_id,
                      po.created_by, s.name AS supplier_name,
                      s.phone AS supplier_phone, s.email AS supplier_email,
                      s.address AS supplier_address,
                      st.code AS store_code, st.name AS store_name,
                      st.address AS store_address, st.phone AS store_phone,
                      st.email AS store_email,
                      u.username AS received_by_username, u.full_name AS received_by_name
               FROM purchase_receipts pr
               JOIN purchase_orders po ON po.id = pr.purchase_order_id
               JOIN suppliers s ON s.id = po.supplier_id
               JOIN stores st ON st.id = po.store_id
               JOIN users u ON u.id = pr.received_by
               WHERE pr.id = ?""",
            (receipt_id,),
        ).fetchone()
        if not header:
            raise DocumentError("Goods receipt not found.")
        items = [
            dict(row)
            for row in conn.execute(
                """SELECT pri.purchase_order_item_id, poi.product_id, p.sku,
                          COALESCE(p.name, 'Historical Product') AS description,
                          pri.quantity AS received_quantity, pri.unit_cost, pri.subtotal,
                          poi.ordered_quantity - COALESCE((
                              SELECT SUM(previous_pri.quantity)
                              FROM purchase_receipt_items previous_pri
                              JOIN purchase_receipts previous_pr
                                ON previous_pr.id = previous_pri.receipt_id
                              WHERE previous_pri.purchase_order_item_id = poi.id
                                AND previous_pr.purchase_order_id = pr.purchase_order_id
                                AND previous_pr.id <= pr.id
                          ), 0) AS pending_quantity
                   FROM purchase_receipt_items pri
                   JOIN purchase_receipts pr ON pr.id = pri.receipt_id
                   JOIN purchase_order_items poi ON poi.id = pri.purchase_order_item_id
                   LEFT JOIN products p ON p.id = poi.product_id
                   WHERE pri.receipt_id = ? ORDER BY pri.id""",
                (receipt_id,),
            ).fetchall()
        ]
    header = dict(header)
    config = load_branding(branding)
    document = {
        "document_type": "goods_received_note",
        "title": "Goods Received Note",
        "document_number": header["receipt_number"],
        "business": config.to_dict(),
        "store": _store_from_row(header),
        "supplier": _supplier_from_row(header),
        "metadata": {
            "po_reference": header["reference_number"],
            "purchase_document": document_number(
                "purchase_order", header["purchase_order_id"], header["store_code"]
            ),
            "received_at": header["received_at"],
            "received_by": header["received_by_name"] or header["received_by_username"],
            "receiving_store": header["store_name"],
            "supplier": header["supplier_name"],
            "notes": header["notes"] or "",
        },
        "line_items": items,
        "totals": {
            "received_total": _sum(items, "subtotal"),
            "received_units": _sum(items, "received_quantity", integer=True),
            "pending_units": _sum(items, "pending_quantity", integer=True),
        },
        "footer": config.invoice_footer,
        "page_layout": "A4",
    }
    return _finalize(document, 80)


def generate_stock_transfer_document(
    transfer_id: int,
    branding: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Generate a transfer manifest with quantities, users, and event history."""
    with get_connection() as conn:
        header = conn.execute(
            """SELECT t.*, source.code AS source_store_code,
                      source.name AS source_store_name,
                      source.address AS source_store_address,
                      source.phone AS source_store_phone,
                      destination.code AS destination_store_code,
                      destination.name AS destination_store_name,
                      requester.username AS requested_by_username,
                      requester.full_name AS requested_by_name,
                      approver.username AS approved_by_username,
                      approver.full_name AS approved_by_name
               FROM stock_transfers t
               JOIN stores source ON source.id = t.source_store_id
               JOIN stores destination ON destination.id = t.destination_store_id
               JOIN users requester ON requester.id = t.requested_by
               LEFT JOIN users approver ON approver.id = t.approved_by
               WHERE t.id = ?""",
            (transfer_id,),
        ).fetchone()
        if not header:
            raise DocumentError("Stock transfer not found.")
        items = [
            dict(row)
            for row in conn.execute(
                """SELECT sti.product_id, p.sku,
                          COALESCE(p.name, 'Historical Product') AS description,
                          sti.requested_quantity,
                          sti.dispatched_quantity,
                          sti.received_quantity,
                          sti.requested_quantity - sti.received_quantity AS pending_quantity,
                          sti.dispatched_quantity - sti.received_quantity AS in_transit_quantity
                   FROM stock_transfer_items sti
                   LEFT JOIN products p ON p.id = sti.product_id
                   WHERE sti.transfer_id = ? ORDER BY sti.id""",
                (transfer_id,),
            ).fetchall()
        ]
        events = [
            dict(row)
            for row in conn.execute(
                """SELECT e.from_status, e.to_status, e.created_at, e.notes,
                          u.username, u.full_name
                   FROM stock_transfer_events e
                   JOIN users u ON u.id = e.user_id
                   WHERE e.transfer_id = ? ORDER BY e.id""",
                (transfer_id,),
            ).fetchall()
        ]
    header = dict(header)
    config = load_branding(branding)
    event_summary = [
        {
            "from_status": event["from_status"],
            "to_status": event["to_status"],
            "user": event["full_name"] or event["username"],
            "timestamp": event["created_at"],
            "notes": event["notes"] or "",
        }
        for event in events
    ]
    document = {
        "document_type": "stock_transfer",
        "title": "Stock Transfer Document",
        "document_number": document_number(
            "stock_transfer", transfer_id, header["source_store_code"]
        ),
        "business": config.to_dict(),
        "store": {
            "code": header["source_store_code"],
            "name": header["source_store_name"],
            "address": header["source_store_address"] or "",
            "phone": header["source_store_phone"] or "",
            "email": "",
        },
        "metadata": {
            "transfer_reference": header["reference_number"],
            "source_store": header["source_store_name"],
            "destination_store": header["destination_store_name"],
            "status": header["status"],
            "requested_by": header["requested_by_name"] or header["requested_by_username"],
            "approved_by": header["approved_by_name"] or header["approved_by_username"] or "Pending",
            "created_at": header["created_at"],
            "notes": header["notes"] or "",
        },
        "line_items": items,
        "event_history": event_summary,
        "totals": {
            "requested_units": _sum(items, "requested_quantity", integer=True),
            "dispatched_units": _sum(items, "dispatched_quantity", integer=True),
            "received_units": _sum(items, "received_quantity", integer=True),
            "pending_units": _sum(items, "pending_quantity", integer=True),
        },
        "footer": config.invoice_footer,
        "page_layout": "A4",
    }
    return _finalize(document, 80)


def _finalize(document: dict[str, Any], width_mm: int) -> dict[str, Any]:
    """Render and log a generated document without exposing document contents."""
    rendered = attach_outputs(document, width_mm=width_mm)
    log_event(
        logger,
        "document_generated",
        document_type=document.get("document_type"),
        document_number=document.get("document_number"),
        store_code=(document.get("store") or {}).get("code"),
        width_mm=width_mm,
    )
    return rendered


def document_number(
    document_type: str,
    entity_id: int,
    store_code: str,
) -> str:
    """Return a deterministic unique document number for a persisted entity."""
    numbering = get_config().numbering
    prefixes = {
        "invoice": numbering.invoice_prefix,
        "credit_note": numbering.credit_note_prefix,
        "purchase_order": numbering.purchase_order_prefix,
        "stock_transfer": numbering.transfer_prefix,
    }
    if document_type not in prefixes:
        raise DocumentError("Unsupported generated document number type.")
    try:
        entity_id = int(entity_id)
    except (TypeError, ValueError) as exc:
        raise DocumentError("Document entity id must be an integer.") from exc
    if entity_id <= 0:
        raise DocumentError("Document entity id must be positive.")
    normalized_store = re.sub(r"[^A-Z0-9]+", "-", str(store_code).upper()).strip("-")
    normalized_store = normalized_store or "STORE"
    return f"{prefixes[document_type]}-{normalized_store}-{entity_id:08d}"


def _load_sale(sale_id: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with get_connection() as conn:
        sale = conn.execute(
            """SELECT s.*, st.code AS store_code, st.name AS store_name,
                      st.address AS store_address, st.phone AS store_phone,
                      st.email AS store_email,
                      u.full_name AS cashier_full_name
               FROM sales s
               JOIN stores st ON st.id = s.store_id
               LEFT JOIN users u ON u.id = s.user_id
               WHERE s.sale_id = ?""",
            (sale_id,),
        ).fetchone()
        if not sale:
            raise DocumentError("Sale not found.")
        items = [
            dict(row)
            for row in conn.execute(
                """SELECT si.id AS sale_item_id,
                          CAST(si.product_id AS INTEGER) AS product_id,
                          COALESCE(p.sku, si.product_id) AS sku,
                          COALESCE(p.name, 'Historical Product') AS description,
                          si.quantity, si.price_at_sale AS unit_price,
                          si.quantity * si.price_at_sale AS subtotal
                   FROM sale_items si
                   LEFT JOIN products p ON p.id = CAST(si.product_id AS INTEGER)
                   WHERE si.sale_id = ? ORDER BY si.id""",
                (sale_id,),
            ).fetchall()
        ]
    return dict(sale), items


def _sale_document(
    sale: dict[str, Any],
    items: list[dict[str, Any]],
    business: dict[str, str],
) -> dict[str, Any]:
    subtotal = float(sale["subtotal"] or 0)
    discount_total = float(sale["discount_amount"] or 0)
    tax_total = float(sale["tax_amount"] or 0)
    normalized_items = []
    for item in items:
        ratio = float(item["subtotal"]) / subtotal if subtotal else 0
        line_discount = round(discount_total * ratio, 2)
        line_tax = round(tax_total * ratio, 2)
        normalized_items.append(
            {
                **item,
                "discount": line_discount,
                "tax": line_tax,
                "line_total": round(float(item["subtotal"]) - line_discount + line_tax, 2),
            }
        )
    return {
        "business": business,
        "store": _store_from_row(sale),
        "metadata": {
            "sale_reference": sale["sale_id"],
            "receipt_number": sale["receipt_number"],
            "date_time": sale["created_at"] or sale["timestamp"],
            "cashier": sale["cashier_full_name"] or sale["username"],
            "register": sale["register_name"],
            "payment_method": sale["payment_method"],
            "payment_status": sale["payment_status"],
        },
        "line_items": normalized_items,
        "totals": {
            "subtotal": subtotal,
            "discount": discount_total,
            "tax": tax_total,
            "total": float(sale["total_amount"] or 0),
            "amount_paid": float(sale["amount_paid"] or 0),
            "change_due": float(sale["change_given"] or 0),
        },
    }


def _store_from_row(row: Mapping[str, Any]) -> dict[str, str]:
    return {
        "id": row.get("store_id"),
        "code": str(row.get("store_code") or ""),
        "name": str(row.get("store_name") or ""),
        "address": str(row.get("store_address") or ""),
        "phone": str(row.get("store_phone") or ""),
        "email": str(row.get("store_email") or ""),
    }


def _supplier_from_row(row: Mapping[str, Any]) -> dict[str, str]:
    return {
        "name": str(row.get("supplier_name") or ""),
        "phone": str(row.get("supplier_phone") or ""),
        "email": str(row.get("supplier_email") or ""),
        "address": str(row.get("supplier_address") or ""),
    }


def _customer_fields(customer: Optional[Mapping[str, Any]]) -> dict[str, str]:
    customer = customer or {}
    return {
        "name": str(customer.get("name") or "Walk-in Customer"),
        "address": str(customer.get("address") or ""),
        "phone": str(customer.get("phone") or ""),
        "email": str(customer.get("email") or ""),
        "tax_id": str(customer.get("tax_id") or ""),
    }


def _contact_summary(phone: Any, email: Any, address: Any) -> str:
    return " | ".join(str(value) for value in (phone, email, address) if value)


def _sum(items: list[dict[str, Any]], key: str, integer: bool = False):
    value = sum(float(item.get(key) or 0) for item in items)
    return int(value) if integer else round(value, 2)
