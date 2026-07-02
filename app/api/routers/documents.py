"""Printable and structured business document endpoints."""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, PlainTextResponse

from auth import AuthorizationError, UserSession
from app.api.dependencies import accessible_store_ids, get_current_session, require_management, resolve_store_scope
from app.api.pagination import data_response
from app.documents.document_service import (
    generate_credit_note,
    generate_goods_received_note,
    generate_purchase_order_document,
    generate_sales_invoice,
    generate_sales_receipt,
    generate_stock_transfer_document,
)
from app.procurement.purchase_service import get_purchase_order, get_purchase_receipt
from app.sales.sales_service import get_return_data, print_receipt_data
from app.stores.transfer_service import get_transfer


router = APIRouter(prefix="/documents", tags=["documents"])
OutputFormat = Literal["json", "text", "html"]


def _render(document: dict, output_format: OutputFormat):
    if output_format == "text":
        return PlainTextResponse(document["text"])
    if output_format == "html":
        return HTMLResponse(document["html"])
    return data_response(document)


@router.get("/receipts/{sale_id}")
def receipt_document(
    sale_id: int,
    output_format: OutputFormat = Query("json", alias="format"),
    width_mm: int = Query(80),
    session: UserSession = Depends(get_current_session),
):
    sale = print_receipt_data(sale_id)["sale"]
    resolve_store_scope(session, sale["store_id"])
    return _render(generate_sales_receipt(sale_id, width_mm=width_mm), output_format)


@router.get("/invoices/{sale_id}")
def invoice_document(
    sale_id: int,
    output_format: OutputFormat = Query("json", alias="format"),
    session: UserSession = Depends(get_current_session),
):
    sale = print_receipt_data(sale_id)["sale"]
    resolve_store_scope(session, sale["store_id"])
    return _render(generate_sales_invoice(sale_id), output_format)


@router.get("/credit-notes/{return_id}")
def credit_note_document(
    return_id: int,
    output_format: OutputFormat = Query("json", alias="format"),
    width_mm: int = Query(80),
    session: UserSession = Depends(get_current_session),
):
    sales_return = get_return_data(return_id)["return"]
    sale = print_receipt_data(sales_return["sale_id"])["sale"]
    resolve_store_scope(session, sale["store_id"])
    return _render(generate_credit_note(return_id, width_mm=width_mm), output_format)


@router.get("/purchase-orders/{purchase_order_id}")
def purchase_order_document(
    purchase_order_id: int,
    output_format: OutputFormat = Query("json", alias="format"),
    session: UserSession = Depends(get_current_session),
):
    require_management(session)
    order = get_purchase_order(purchase_order_id)
    if not order:
        raise ValueError("Purchase order not found.")
    resolve_store_scope(session, order["purchase_order"]["store_id"], manage=True)
    return _render(generate_purchase_order_document(purchase_order_id), output_format)


@router.get("/goods-received/{receipt_id}")
def goods_received_document(
    receipt_id: int,
    output_format: OutputFormat = Query("json", alias="format"),
    session: UserSession = Depends(get_current_session),
):
    require_management(session)
    receipt = get_purchase_receipt(receipt_id)
    if not receipt:
        raise ValueError("Goods receipt not found.")
    order = get_purchase_order(receipt["receipt"]["purchase_order_id"])
    resolve_store_scope(session, order["purchase_order"]["store_id"], manage=True)
    return _render(generate_goods_received_note(receipt_id), output_format)


@router.get("/transfers/{transfer_id}")
def transfer_document(
    transfer_id: int,
    output_format: OutputFormat = Query("json", alias="format"),
    session: UserSession = Depends(get_current_session),
):
    require_management(session)
    transfer = get_transfer(transfer_id)
    if not transfer:
        raise ValueError("Transfer not found.")
    header = transfer["transfer"]
    allowed = accessible_store_ids(session)
    if allowed is not None and not ({header["source_store_id"], header["destination_store_id"]} & set(allowed)):
        raise AuthorizationError("Transfer is outside this user's store access.")
    return _render(generate_stock_transfer_document(transfer_id), output_format)
