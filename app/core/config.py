"""Central immutable application configuration loaded from the environment."""

import os
from dataclasses import dataclass, field
from functools import lru_cache

from app.core.exceptions import ConfigurationError


@dataclass(frozen=True)
class CompanySettings:
    name: str = "Point of Sale"
    tax_id: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    logo_path: str = ""


@dataclass(frozen=True)
class ReceiptSettings:
    width_mm: int = 80
    footer: str = "Thank you for your business."
    invoice_footer: str = "Thank you for your business."
    register_name: str = "REGISTER-1"


@dataclass(frozen=True)
class InventorySettings:
    reorder_level: int = 0


@dataclass(frozen=True)
class NumberingSettings:
    receipt_prefix: str = "POS"
    invoice_prefix: str = "INV"
    credit_note_prefix: str = "CN"
    purchase_order_prefix: str = "PO"
    transfer_prefix: str = "TRN"


@dataclass(frozen=True)
class ReportSettings:
    default_limit: int = 10
    slow_moving_days: int = 30


@dataclass(frozen=True)
class AppConfig:
    tax_rate: float = 0.0
    company: CompanySettings = field(default_factory=CompanySettings)
    receipt: ReceiptSettings = field(default_factory=ReceiptSettings)
    inventory: InventorySettings = field(default_factory=InventorySettings)
    numbering: NumberingSettings = field(default_factory=NumberingSettings)
    reports: ReportSettings = field(default_factory=ReportSettings)


def _int_setting(name: str, default: int, *, positive: bool = False) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer.") from exc
    if value < 0 or (positive and value == 0):
        qualifier = "positive" if positive else "non-negative"
        raise ConfigurationError(f"{name} must be {qualifier}.")
    return value


def _float_setting(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number.") from exc
    if value < 0:
        raise ConfigurationError(f"{name} must be non-negative.")
    return value


def _prefix(name: str, default: str) -> str:
    value = os.environ.get(name, default).strip().upper()
    if not value or not value.replace("-", "").isalnum():
        raise ConfigurationError(f"{name} must contain letters, numbers, or hyphens.")
    return value


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Return validated process configuration; cache may be cleared in tests."""
    width = _int_setting("POS_RECEIPT_WIDTH_MM", 80, positive=True)
    if width not in {58, 80}:
        raise ConfigurationError("POS_RECEIPT_WIDTH_MM must be 58 or 80.")
    return AppConfig(
        tax_rate=_float_setting("POS_DEFAULT_TAX_RATE", 0.0),
        company=CompanySettings(
            name=os.environ.get("POS_BUSINESS_NAME", "Point of Sale").strip(),
            tax_id=os.environ.get("POS_TAX_ID", "").strip(),
            address=os.environ.get("POS_BUSINESS_ADDRESS", "").strip(),
            phone=os.environ.get("POS_BUSINESS_PHONE", "").strip(),
            email=os.environ.get("POS_BUSINESS_EMAIL", "").strip(),
            logo_path=os.environ.get("POS_LOGO_PATH", "").strip(),
        ),
        receipt=ReceiptSettings(
            width_mm=width,
            footer=os.environ.get("POS_RECEIPT_FOOTER", "Thank you for your business.").strip(),
            invoice_footer=os.environ.get("POS_INVOICE_FOOTER", "Thank you for your business.").strip(),
            register_name=os.environ.get("POS_DEFAULT_REGISTER", "REGISTER-1").strip() or "REGISTER-1",
        ),
        inventory=InventorySettings(
            reorder_level=_int_setting("POS_DEFAULT_REORDER_LEVEL", 0),
        ),
        numbering=NumberingSettings(
            receipt_prefix=_prefix("POS_RECEIPT_PREFIX", "POS"),
            invoice_prefix=_prefix("POS_INVOICE_PREFIX", "INV"),
            credit_note_prefix=_prefix("POS_CREDIT_NOTE_PREFIX", "CN"),
            purchase_order_prefix=_prefix("POS_PURCHASE_ORDER_PREFIX", "PO"),
            transfer_prefix=_prefix("POS_TRANSFER_PREFIX", "TRN"),
        ),
        reports=ReportSettings(
            default_limit=_int_setting("POS_REPORT_DEFAULT_LIMIT", 10, positive=True),
            slow_moving_days=_int_setting("POS_SLOW_MOVING_DAYS", 30, positive=True),
        ),
    )


def reset_config_cache() -> None:
    """Reload environment configuration on the next access."""
    get_config.cache_clear()
