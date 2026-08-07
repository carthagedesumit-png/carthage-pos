"""Printer profile definitions independent of concrete device drivers."""

from dataclasses import dataclass

from app.core.exceptions import PrinterError


@dataclass(frozen=True)
class PrinterProfile:
    name: str
    width_mm: int | None
    columns: int


PRINTER_PROFILES = {
    "58mm": PrinterProfile("58mm", 58, 32),
    "80mm": PrinterProfile("80mm", 80, 48),
    "generic": PrinterProfile("generic", None, 80),
}


def get_printer_profile(name: str) -> PrinterProfile:
    normalized = str(name or "").strip().lower()
    if normalized not in PRINTER_PROFILES:
        raise PrinterError("Invalid printer profile. Use 58mm, 80mm, or generic.")
    return PRINTER_PROFILES[normalized]
