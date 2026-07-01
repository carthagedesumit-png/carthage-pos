"""Printable and API-ready business document generation."""

from app.documents.document_service import (
    generate_credit_note,
    generate_goods_received_note,
    generate_purchase_order_document,
    generate_sales_invoice,
    generate_sales_receipt,
    generate_stock_transfer_document,
)

__all__ = [
    "generate_sales_receipt",
    "generate_sales_invoice",
    "generate_credit_note",
    "generate_purchase_order_document",
    "generate_goods_received_note",
    "generate_stock_transfer_document",
]
