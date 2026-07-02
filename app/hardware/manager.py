"""Peripheral composition root and injectable hardware manager."""

from dataclasses import dataclass
from typing import Optional

from app.core.config import HardwareSettings, get_config
from app.hardware.adapters import (
    KeyboardBarcodeScanner,
    PrinterPulseDrawer,
    TextFilePrinter,
    UnavailableCashDrawer,
    UnavailableDisplay,
    UnavailablePrinter,
)
from app.hardware.interfaces import BarcodeScanner, CashDrawer, CustomerDisplay, ReceiptPrinter
from app.hardware.profiles import PrinterProfile, get_printer_profile


@dataclass
class HardwareManager:
    settings: HardwareSettings
    printer: ReceiptPrinter
    cash_drawer: CashDrawer
    scanner: BarcodeScanner
    customer_display: CustomerDisplay

    @property
    def printer_profile(self) -> PrinterProfile:
        return get_printer_profile(self.settings.printer_profile)

    def status(self) -> dict:
        profile = self.printer_profile
        return {
            "printer": {**self.printer.status().to_dict(), "profile": profile.name,
                        "paper_width_mm": profile.width_mm,
                        "configured_name": self.settings.printer_name},
            "cash_drawer": self.cash_drawer.status().to_dict(),
            "scanner": self.scanner.status().to_dict(),
            "customer_display": self.customer_display.status().to_dict(),
            "open_drawer_after_cash_sale": self.settings.open_drawer_after_cash_sale,
        }


def build_hardware_manager(settings: Optional[HardwareSettings] = None) -> HardwareManager:
    settings = settings or get_config().hardware
    get_printer_profile(settings.printer_profile)
    if settings.printer_enabled and settings.printer_path:
        printer = TextFilePrinter(settings.printer_path, settings.printer_name)
    else:
        detail = "Printer driver unavailable." if settings.printer_enabled else "Printer is disabled."
        printer = UnavailablePrinter(settings.printer_enabled, detail)
    drawer = (
        PrinterPulseDrawer(printer, enabled=True)
        if settings.cash_drawer_enabled
        else UnavailableCashDrawer(enabled=False)
    )
    scanner = KeyboardBarcodeScanner(enabled=settings.scanner_enabled)
    display = UnavailableDisplay(enabled=settings.customer_display_enabled)
    return HardwareManager(settings, printer, drawer, scanner, display)


_manager: Optional[HardwareManager] = None


def get_hardware_manager() -> HardwareManager:
    global _manager
    if _manager is None:
        _manager = build_hardware_manager()
    return _manager


def configure_hardware_manager(manager: HardwareManager) -> None:
    """Inject a composed manager, primarily for tests or application drivers."""
    global _manager
    _manager = manager


def reset_hardware_manager() -> None:
    global _manager
    _manager = None
