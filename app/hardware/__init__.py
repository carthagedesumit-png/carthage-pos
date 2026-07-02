"""Hardware abstraction and peripheral orchestration exports."""

from app.hardware.hardware_service import (
    clear_display,
    display_test_message,
    get_hardware_status,
    lookup_scanned_product,
    maybe_open_drawer_after_sale,
    open_cash_drawer,
    print_credit_note,
    print_invoice,
    print_receipt,
    print_test_page,
    show_cart_item,
    show_payment_confirmation,
    show_totals,
    show_welcome,
)
from app.hardware.manager import (
    HardwareManager,
    configure_hardware_manager,
    get_hardware_manager,
    reset_hardware_manager,
)

__all__ = [
    "HardwareManager", "clear_display", "configure_hardware_manager",
    "display_test_message", "get_hardware_manager", "get_hardware_status",
    "lookup_scanned_product", "maybe_open_drawer_after_sale", "open_cash_drawer",
    "print_credit_note", "print_invoice", "print_receipt", "print_test_page",
    "reset_hardware_manager", "show_cart_item", "show_payment_confirmation",
    "show_totals", "show_welcome",
]
