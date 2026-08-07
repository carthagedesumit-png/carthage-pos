"""Authorized, audited, fault-tolerant peripheral orchestration."""

from typing import Callable, Optional

from auth import UserSession, require_inventory_management, require_store_access, validate_session
from app.core.exceptions import HardwareError, HardwareUnavailableError, ScannerError
from app.core.logging_utils import get_logger, log_event
from app.database.transactions import transaction
from app.documents.document_service import (
    generate_credit_note,
    generate_sales_invoice,
    generate_sales_receipt,
)
from app.hardware.adapters import normalize_barcode
from app.hardware.manager import get_hardware_manager
from app.inventory.inventory_service import fetch_product_for_sale
from app.sales.sales_service import get_return_data, print_receipt_data


logger = get_logger("hardware")


def get_hardware_status(session: UserSession) -> dict:
    validate_session(session)
    return get_hardware_manager().status()


def print_receipt(session: UserSession, sale_id: int, *, reprint: bool = False) -> dict:
    sale = print_receipt_data(sale_id)["sale"]
    session = require_store_access(validate_session(session), sale["store_id"])
    if reprint:
        session = require_inventory_management(session, store_id=sale["store_id"])
    manager = get_hardware_manager()
    profile = manager.printer_profile
    width = profile.width_mm or 80
    document = generate_sales_receipt(sale_id, width_mm=width)
    text = document["text"]
    if reprint:
        text = "*** REPRINT - COPY OF COMPLETED SALE ***\n" + text
    return _print_document(session, text, f"receipt-{sale['receipt_number']}",
                           copies=manager.settings.receipt_copies, sale_id=sale_id,
                           attempt_type="REPRINT" if reprint else "ORIGINAL")


def print_invoice(session: UserSession, sale_id: int) -> dict:
    sale = print_receipt_data(sale_id)["sale"]
    require_store_access(validate_session(session), sale["store_id"])
    document = generate_sales_invoice(sale_id)
    return _print_document(session, document["text"], f"invoice-{sale_id}")


def print_credit_note(session: UserSession, return_id: int) -> dict:
    sales_return = get_return_data(return_id)["return"]
    sale = print_receipt_data(sales_return["sale_id"])["sale"]
    require_store_access(validate_session(session), sale["store_id"])
    manager = get_hardware_manager()
    width = manager.printer_profile.width_mm or 80
    document = generate_credit_note(return_id, width_mm=width)
    return _print_document(session, document["text"], f"credit-note-{return_id}")


def print_test_page(session: UserSession) -> dict:
    session = require_inventory_management(session)
    manager = get_hardware_manager()
    profile = manager.printer_profile
    lines = [
        "CARTHAGE POS HARDWARE TEST",
        f"Profile: {profile.name}",
        f"Columns: {profile.columns}",
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "0123456789",
        "Printer test completed.",
    ]
    return _print_document(session, "\n".join(lines), "printer-test")


def open_cash_drawer(session: UserSession, *, automatic: bool = False, reason: str = "") -> dict:
    session = validate_session(session)
    if not automatic:
        session = require_inventory_management(session, store_id=session.store_id)
        reason = str(reason or "").strip()
        if len(reason) < 3 or len(reason) > 200:
            raise HardwareError("A manual drawer-open reason between 3 and 200 characters is required.")
    else:
        reason = "Eligible committed cash sale"
    manager = get_hardware_manager()
    if not manager.settings.cash_drawer_enabled:
        result = _failure("Cash drawer is disabled.")
        _record_event(session, "drawer_unavailable", "cash_drawer", "open", False,
                      result["error"], reason=reason)
        return result
    return _device_action(session, "cash_drawer", "open", manager.cash_drawer.open, reason=reason)


def maybe_open_drawer_after_sale(session: UserSession, receipt_data: dict) -> dict:
    manager = get_hardware_manager()
    sale = receipt_data.get("sale", {})
    if not manager.settings.open_drawer_after_cash_sale or sale.get("payment_method") != "CASH":
        return {"success": True, "skipped": True}
    return open_cash_drawer(session, automatic=True)


def lookup_scanned_product(
    session: UserSession,
    raw_value: str,
    store_id: Optional[int] = None,
    *,
    allow_manual_fallback: bool = False,
) -> dict:
    session = validate_session(session)
    selected_store = require_store_access(session, int(store_id or session.store_id)).store_id
    manager = get_hardware_manager()
    scanner_status = manager.scanner.status()
    if scanner_status.available:
        normalized = manager.scanner.normalize(raw_value)
    elif allow_manual_fallback:
        normalized = normalize_barcode(raw_value)
    else:
        raise HardwareUnavailableError("Barcode scanner is disabled or unavailable.")
    from app.barcodes.barcode_service import lookup_product
    product = lookup_product(normalized, store_id=selected_store, session=session)
    if not product:
        _record_event(session, "scanner_lookup_failed", "scanner", "lookup", False, "Product not found")
        raise ScannerError("Product not found for barcode or SKU.")
    _record_event(session, "scanner_lookup_succeeded", "scanner", "lookup", True,
                  f"identifier_length={len(normalized)}")
    return product


def show_welcome(session: UserSession, message: str = "Welcome") -> dict:
    validate_session(session)
    return _display_action(session, "welcome", lambda: get_hardware_manager().customer_display.show_welcome(str(message)))


def show_cart_item(session: UserSession, name: str, quantity: int, price: float) -> dict:
    validate_session(session)
    return _display_action(session, "cart_item", lambda: get_hardware_manager().customer_display.show_item(name, int(quantity), float(price)))


def show_totals(session: UserSession, subtotal: float, total: float) -> dict:
    validate_session(session)
    return _display_action(session, "totals", lambda: get_hardware_manager().customer_display.show_total(float(subtotal), float(total)))


def show_payment_confirmation(session: UserSession, total: float) -> dict:
    validate_session(session)
    return _display_action(session, "payment", lambda: get_hardware_manager().customer_display.show_payment("Payment approved", float(total)))


def clear_display(session: UserSession) -> dict:
    validate_session(session)
    return _display_action(session, "clear", get_hardware_manager().customer_display.clear)


def display_test_message(session: UserSession, message: str) -> dict:
    session = require_inventory_management(session)
    if not str(message or "").strip():
        raise HardwareError("Display message is required.")
    return _display_action(session, "test", lambda: get_hardware_manager().customer_display.show_welcome(str(message).strip()))


def _print_document(session: UserSession, text: str, job_name: str, *, copies: int = 1,
                    sale_id: Optional[int] = None, attempt_type: str = "DIAGNOSTIC") -> dict:
    manager = get_hardware_manager()
    for copy_number in range(1, copies + 1):
        result = _device_action(
            session, "printer", "print",
            lambda n=copy_number: manager.printer.print_text(
                text, manager.printer_profile, f"{job_name}-copy-{n}"
            ),
            details=f"profile={manager.printer_profile.name};copy={copy_number}/{copies}",
            sale_id=sale_id, attempt_type=attempt_type,
        )
        if not result["success"]:
            return {**result, "retryable": True, "copies_completed": copy_number - 1}
    return {**result, "retryable": False, "copies_completed": copies}


def _display_action(session, operation, action):
    manager = get_hardware_manager()
    if not manager.settings.customer_display_enabled:
        return {"success": True, "skipped": True, "reason": "Customer display is disabled."}
    return _device_action(session, "customer_display", operation, action)


def _device_action(
    session: UserSession,
    device_type: str,
    operation: str,
    action: Callable[[], None],
    details: str = "",
    sale_id: Optional[int] = None,
    reason: str = "",
    attempt_type: str = "",
) -> dict:
    try:
        action()
    except Exception as exc:
        message = str(exc) if isinstance(exc, HardwareError) else "Hardware operation failed."
        _record_event(session, f"{device_type}_{operation}_failed", device_type, operation, False,
                      message, sale_id=sale_id, reason=reason, attempt_type=attempt_type)
        log_event(logger, "hardware_operation_failed", device_type=device_type,
                  operation=operation, error_type=type(exc).__name__)
        return _failure(message)
    _record_event(session, f"{device_type}_{operation}_succeeded", device_type, operation, True,
                  details, sale_id=sale_id, reason=reason, attempt_type=attempt_type)
    log_event(logger, "hardware_operation_succeeded", device_type=device_type, operation=operation)
    return {"success": True, "device_type": device_type, "operation": operation}


def _failure(message: str) -> dict:
    return {"success": False, "error": message}


def _record_event(session, event_type, device_type, operation, success, details="", *,
                  sale_id=None, reason="", attempt_type=""):
    safe_details = str(details or "")[:250]
    safe_reason = str(reason or "").replace("\r", " ").replace("\n", " ")[:200]
    try:
        with transaction() as conn:
            conn.execute(
                """INSERT INTO hardware_events (
                       event_type, device_type, operation, success,
                       user_id, store_id, details, sale_id, reason, attempt_type
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (event_type, device_type, operation, int(bool(success)),
                 session.user_id, session.store_id, safe_details, sale_id,
                 safe_reason, str(attempt_type or "")[:32]),
            )
    except Exception:
        log_event(logger, "hardware_audit_unavailable", device_type=device_type, operation=operation)
