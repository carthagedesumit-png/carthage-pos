"""Null, file, keyboard, and in-memory peripheral adapters."""

from pathlib import Path

from app.core.exceptions import HardwareUnavailableError, PrinterError, ScannerError
from app.hardware.interfaces import BarcodeScanner, CashDrawer, CustomerDisplay, DeviceStatus, ReceiptPrinter
from app.hardware.profiles import PrinterProfile


class UnavailablePrinter(ReceiptPrinter):
    def __init__(self, enabled: bool = False, detail: str = "Printer is not configured."):
        self.enabled = enabled
        self.detail = detail

    def status(self):
        return DeviceStatus("printer", self.enabled, False, type(self).__name__, self.detail)

    def print_text(self, text, profile, job_name):
        raise HardwareUnavailableError(self.detail)


class TextFilePrinter(ReceiptPrinter):
    """Stable spool-file adapter useful for integrations and acceptance testing."""

    def __init__(self, path: str, name: str = ""):
        self.path = Path(path)
        self.name = name or str(self.path)

    def status(self):
        available = self.path.parent.exists()
        detail = self.name if available else "Printer spool directory does not exist."
        return DeviceStatus("printer", True, available, type(self).__name__, detail)

    def print_text(self, text, profile, job_name):
        if not self.path.parent.exists():
            raise PrinterError("Printer spool directory does not exist.")
        try:
            with self.path.open("a", encoding="utf-8") as spool:
                spool.write(f"\n--- {job_name} [{profile.name}] ---\n{text}\n")
        except OSError as exc:
            raise PrinterError("Printer spool write failed.") from exc

    def pulse_drawer(self):
        try:
            with self.path.open("a", encoding="utf-8") as spool:
                spool.write("\n--- CASH DRAWER PULSE ---\n")
        except OSError as exc:
            raise HardwareUnavailableError("Printer cash-drawer pulse failed.") from exc


class MockPrinter(ReceiptPrinter):
    def __init__(self, available: bool = True):
        self.available = available
        self.jobs: list[dict] = []
        self.drawer_pulses = 0
        self.fail_next = False

    def status(self):
        return DeviceStatus("printer", True, self.available, type(self).__name__)

    def print_text(self, text, profile, job_name):
        if not self.available:
            raise HardwareUnavailableError("Mock printer is unavailable.")
        if self.fail_next:
            self.fail_next = False
            raise PrinterError("Mock print job failed.")
        self.jobs.append({"text": text, "profile": profile.name, "job_name": job_name})

    def pulse_drawer(self):
        if not self.available:
            raise HardwareUnavailableError("Mock printer is unavailable.")
        self.drawer_pulses += 1


class PrinterPulseDrawer(CashDrawer):
    def __init__(self, printer: ReceiptPrinter, enabled: bool = True):
        self.printer = printer
        self.enabled = enabled

    def status(self):
        printer_status = self.printer.status()
        return DeviceStatus(
            "cash_drawer", self.enabled,
            self.enabled and printer_status.available,
            type(self).__name__, printer_status.detail,
        )

    def open(self):
        if not self.enabled:
            raise HardwareUnavailableError("Cash drawer is disabled.")
        self.printer.pulse_drawer()


class MockCashDrawer(CashDrawer):
    def __init__(self, available: bool = True, enabled: bool = True):
        self.available = available
        self.enabled = enabled
        self.open_count = 0

    def status(self):
        return DeviceStatus("cash_drawer", self.enabled, self.available and self.enabled, type(self).__name__)

    def open(self):
        if not self.enabled or not self.available:
            raise HardwareUnavailableError("Mock cash drawer is unavailable.")
        self.open_count += 1


class UnavailableCashDrawer(MockCashDrawer):
    def __init__(self, enabled: bool = False):
        super().__init__(available=False, enabled=enabled)


class KeyboardBarcodeScanner(BarcodeScanner):
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def status(self):
        return DeviceStatus("scanner", self.enabled, self.enabled, type(self).__name__)

    def normalize(self, raw_value):
        if not self.enabled:
            raise HardwareUnavailableError("Barcode scanner is disabled.")
        return normalize_barcode(raw_value)


class MockBarcodeScanner(KeyboardBarcodeScanner):
    pass


class UnavailableDisplay(CustomerDisplay):
    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    def status(self):
        return DeviceStatus("customer_display", self.enabled, False, type(self).__name__, "Display driver unavailable.")

    def _raise(self):
        raise HardwareUnavailableError("Customer display is unavailable.")

    def show_welcome(self, message): self._raise()
    def show_item(self, name, quantity, price): self._raise()
    def show_total(self, subtotal, total): self._raise()
    def show_payment(self, message, total): self._raise()
    def clear(self): self._raise()


class MockCustomerDisplay(CustomerDisplay):
    def __init__(self, available: bool = True, enabled: bool = True):
        self.available = available
        self.enabled = enabled
        self.state = {"mode": "clear"}
        self.history: list[dict] = []

    def status(self):
        return DeviceStatus("customer_display", self.enabled, self.available and self.enabled, type(self).__name__)

    def _set(self, **state):
        if not self.enabled or not self.available:
            raise HardwareUnavailableError("Mock customer display is unavailable.")
        self.state = state
        self.history.append(dict(state))

    def show_welcome(self, message): self._set(mode="welcome", message=message)
    def show_item(self, name, quantity, price): self._set(mode="item", name=name, quantity=quantity, price=price)
    def show_total(self, subtotal, total): self._set(mode="total", subtotal=subtotal, total=total)
    def show_payment(self, message, total): self._set(mode="payment", message=message, total=total)
    def clear(self): self._set(mode="clear")


def normalize_barcode(raw_value: str) -> str:
    normalized = str(raw_value or "").strip()
    if not normalized:
        raise ScannerError("Barcode or SKU is required.")
    if len(normalized) > 128 or any(ord(character) < 32 for character in normalized):
        raise ScannerError("Barcode or SKU contains invalid characters.")
    return normalized
