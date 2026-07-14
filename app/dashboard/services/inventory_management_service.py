"""Form composition and orchestration for the inventory dashboard."""

from app.barcodes.barcode_service import assign_identifier, generate_identifier
from app.barcodes.label_service import preview_label, print_label
from app.dashboard.services.dashboard_service import get_dashboard_product_detail
from app.inventory.category_service import (
    create_category, deactivate_category, get_category, list_categories,
    reactivate_category, update_category,
)
from app.inventory.inventory_service import (
    adjust_stock, create_product, deactivate_product, get_product_by_id,
    receive_stock, update_product,
)
from app.procurement.supplier_service import search_suppliers
from app.stores.store_service import search_stores
from auth import ROLE_ADMIN


BARCODE_FORMATS = ["CODE39", "CODE128", "EAN8", "EAN13", "UPCA", "QR"]


def product_form_context(session, product_id=None, values=None):
    product = get_product_by_id(product_id, store_id=session.store_id) if product_id else None
    if product_id and not product:
        return None
    stores = search_stores()
    if session.role != ROLE_ADMIN:
        from app.stores.store_service import get_user_store_assignment
        allowed = {item["id"] for item in get_user_store_assignment(session.user_id)["stores"]}
        stores = [item for item in stores if item["id"] in allowed]
    initial = dict(product or {})
    initial["store_id"] = initial.get("store_id") or session.store_id
    if values:
        initial.update(values)
    return {
        "product": product,
        "values": initial,
        "categories": list_categories(),
        "suppliers": search_suppliers(),
        "stores": stores,
        "barcode_formats": BARCODE_FORMATS,
    }


def save_product(session, values, product_id=None):
    data = {
        "sku": values.get("sku"), "name": values.get("name"),
        "barcode": values.get("barcode") or None,
        "category_id": _optional_int(values.get("category_id")),
        "supplier_id": _optional_int(values.get("supplier_id")),
        "selling_price": _number(values, "selling_price", float),
        "cost_price": _number(values, "cost_price", float, 0),
        "reorder_level": _number(values, "reorder_level", int, 0),
        "description": values.get("description") or None,
        "unit": values.get("unit") or "each",
        "promotion_price": _optional_float(values.get("promotion_price")),
    }
    store_id = _number(values, "store_id", int)
    if product_id:
        return update_product(session, product_id, store_id=store_id, **data)
    data.update(
        quantity_in_stock=_number(values, "quantity_in_stock", int, 0),
        store_id=store_id,
        barcode_format=values.get("barcode_format") or None,
    )
    return create_product(session, **data)


def set_product_active(session, product_id, active, store_id):
    if active:
        return update_product(session, product_id, store_id=store_id, is_active=1)
    return deactivate_product(session, product_id, store_id=store_id)


def receive_product_stock(session, product_id, values):
    note = _stock_note(values)
    return receive_stock(
        session, product_id, _number(values, "quantity", int), note,
        _number(values, "store_id", int),
    )


def adjust_product_stock(session, product_id, values):
    return adjust_stock(
        session, product_id, _number(values, "new_quantity", int), _stock_note(values),
        _number(values, "store_id", int),
    )


def product_operation_context(session, product_id, store_id=None):
    selected = int(store_id or session.store_id)
    product = get_product_by_id(product_id, store_id=selected)
    if not product:
        return None
    form = product_form_context(session, product_id)
    return {"product": product, "stores": form["stores"], "store_id": selected}


def category_context(category_id=None):
    return {"categories": list_categories(include_inactive=True),
            "category": get_category(category_id) if category_id else None}


def save_category(session, values, category_id=None):
    if category_id:
        return update_category(session, category_id, values.get("name"), values.get("description"))
    return create_category(session, values.get("name"), values.get("description"))


def set_category_active(session, category_id, active):
    return reactivate_category(session, category_id) if active else deactivate_category(session, category_id)


def barcode_operation(session, product_id, values):
    operation = values.get("operation")
    store_id = _number(values, "store_id", int, session.store_id)
    if operation == "generate":
        return generate_identifier(session, product_id, values.get("barcode_format") or "CODE128")
    if operation == "assign":
        return assign_identifier(
            session, product_id, values.get("barcode"),
            values.get("barcode_format") or "CODE128", primary=True,
        )
    if operation == "print":
        return print_label(session, product_id, _number(values, "quantity", int, 1), store_id=store_id)
    return preview_label(session, product_id, store_id=store_id)


def product_detail_for_session(session, product_id):
    return get_dashboard_product_detail(product_id, session=session)


def _number(values, field, converter, default=None):
    raw = values.get(field)
    if (raw is None or str(raw).strip() == "") and default is not None:
        return default
    try:
        return converter(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field.replace('_', ' ').title()} must be a valid number.") from exc


def _optional_int(value):
    return None if value is None or str(value).strip() == "" else int(value)


def _optional_float(value):
    return None if value is None or str(value).strip() == "" else float(value)


def _stock_note(values):
    parts = [values.get("reason"), values.get("supplier_reference"), values.get("note")]
    return " | ".join(str(item).strip() for item in parts if item and str(item).strip()) or None
