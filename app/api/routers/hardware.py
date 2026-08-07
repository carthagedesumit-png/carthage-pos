"""Authenticated peripheral control and diagnostic endpoints."""

from fastapi import APIRouter, Depends

from auth import UserSession
from app.api.dependencies import get_current_session
from app.api.pagination import data_response
from app.api.schemas import DisplayMessageRequest, DrawerOpenRequest, ScannerLookupRequest
from app.hardware.hardware_service import (
    clear_display,
    display_test_message,
    get_hardware_status,
    lookup_scanned_product,
    open_cash_drawer,
    print_credit_note,
    print_invoice,
    print_receipt,
    print_test_page,
)


router = APIRouter(prefix="/hardware", tags=["hardware"])


@router.get("/status")
def hardware_status(session: UserSession = Depends(get_current_session)):
    return data_response(get_hardware_status(session))


@router.post("/printer/test")
def printer_test(session: UserSession = Depends(get_current_session)):
    return data_response(print_test_page(session))


@router.post("/printer/receipts/{sale_id}")
def printer_receipt(sale_id: int, session: UserSession = Depends(get_current_session)):
    return data_response(print_receipt(session, sale_id, reprint=True))


@router.post("/printer/invoices/{sale_id}")
def printer_invoice(sale_id: int, session: UserSession = Depends(get_current_session)):
    return data_response(print_invoice(session, sale_id))


@router.post("/printer/credit-notes/{return_id}")
def printer_credit_note(return_id: int, session: UserSession = Depends(get_current_session)):
    return data_response(print_credit_note(session, return_id))


@router.post("/cash-drawer/open")
def drawer_open(payload: DrawerOpenRequest, session: UserSession = Depends(get_current_session)):
    return data_response(open_cash_drawer(session, reason=payload.reason))


@router.post("/scanner/lookup")
def scanner_lookup(
    payload: ScannerLookupRequest,
    session: UserSession = Depends(get_current_session),
):
    return data_response(lookup_scanned_product(session, payload.value, payload.store_id))


@router.post("/display/test")
def display_test(
    payload: DisplayMessageRequest,
    session: UserSession = Depends(get_current_session),
):
    return data_response(display_test_message(session, payload.message))


@router.post("/display/clear")
def display_clear(session: UserSession = Depends(get_current_session)):
    return data_response(clear_display(session))
