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
    customer_prefix: str = "CUS"


@dataclass(frozen=True)
class LoyaltySettings:
    points_per_currency: float = 1.0
    minimum_purchase: float = 0.0
    redemption_ratio: float = 100.0
    expiration_days: int = 0


@dataclass(frozen=True)
class ApiSettings:
    session_hours: int = 12


@dataclass(frozen=True)
class HardwareSettings:
    printer_enabled: bool = False
    printer_profile: str = "80mm"
    printer_name: str = ""
    printer_path: str = ""
    cash_drawer_enabled: bool = False
    open_drawer_after_cash_sale: bool = False
    scanner_enabled: bool = True
    customer_display_enabled: bool = False


@dataclass(frozen=True)
class BarcodeSettings:
    default_format: str = "CODE128"
    default_label_template: str = "SMALL_PRODUCT"
    default_printer_profile: str = "generic"
    default_label_width_mm: float = 50.0
    default_label_height_mm: float = 30.0
    company_prefix: str = "POS"
    auto_generate: bool = False
    qr_enabled: bool = True


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
    loyalty: LoyaltySettings = field(default_factory=LoyaltySettings)
    api: ApiSettings = field(default_factory=ApiSettings)
    hardware: HardwareSettings = field(default_factory=HardwareSettings)
    barcodes: BarcodeSettings = field(default_factory=BarcodeSettings)


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


def _positive_float_setting(name: str, default: float) -> float:
    value = _float_setting(name, default)
    if value == 0:
        raise ConfigurationError(f"{name} must be positive.")
    return value


def _prefix(name: str, default: str) -> str:
    value = os.environ.get(name, default).strip().upper()
    if not value or not value.replace("-", "").isalnum():
        raise ConfigurationError(f"{name} must contain letters, numbers, or hyphens.")
    return value


def _bool_setting(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean value.")


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Return validated process configuration; cache may be cleared in tests."""
    width = _int_setting("POS_RECEIPT_WIDTH_MM", 80, positive=True)
    if width not in {58, 80}:
        raise ConfigurationError("POS_RECEIPT_WIDTH_MM must be 58 or 80.")
    barcode_format = os.environ.get("POS_DEFAULT_BARCODE_FORMAT", "CODE128").strip().upper().replace("-", "")
    if barcode_format not in {"CODE39", "CODE128", "EAN8", "EAN13", "UPCA", "QR"}:
        raise ConfigurationError("POS_DEFAULT_BARCODE_FORMAT is unsupported.")
    label_template = os.environ.get("POS_DEFAULT_LABEL_TEMPLATE", "SMALL_PRODUCT").strip().upper()
    if label_template not in {"SHELF", "SMALL_PRODUCT", "LARGE_PRODUCT", "WAREHOUSE", "BARCODE_ONLY", "QR"}:
        raise ConfigurationError("POS_DEFAULT_LABEL_TEMPLATE is unsupported.")
    label_profile = os.environ.get("POS_LABEL_PRINTER_PROFILE", "generic").strip().lower()
    if label_profile not in {"58mm", "80mm", "generic"}:
        raise ConfigurationError("POS_LABEL_PRINTER_PROFILE must be 58mm, 80mm, or generic.")
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
            customer_prefix=_prefix("POS_CUSTOMER_PREFIX", "CUS"),
        ),
        reports=ReportSettings(
            default_limit=_int_setting("POS_REPORT_DEFAULT_LIMIT", 10, positive=True),
            slow_moving_days=_int_setting("POS_SLOW_MOVING_DAYS", 30, positive=True),
        ),
        loyalty=LoyaltySettings(
            points_per_currency=_float_setting("POS_LOYALTY_POINTS_PER_CURRENCY", 1.0),
            minimum_purchase=_float_setting("POS_LOYALTY_MINIMUM_PURCHASE", 0.0),
            redemption_ratio=_positive_float_setting("POS_LOYALTY_REDEMPTION_RATIO", 100.0),
            expiration_days=_int_setting("POS_LOYALTY_EXPIRATION_DAYS", 0),
        ),
        api=ApiSettings(
            session_hours=_int_setting("POS_API_SESSION_HOURS", 12, positive=True),
        ),
        hardware=HardwareSettings(
            printer_enabled=_bool_setting("POS_PRINTER_ENABLED", False),
            printer_profile=os.environ.get("POS_PRINTER_PROFILE", "80mm").strip().lower(),
            printer_name=os.environ.get("POS_RECEIPT_PRINTER_NAME", "").strip(),
            printer_path=os.environ.get("POS_RECEIPT_PRINTER_PATH", "").strip(),
            cash_drawer_enabled=_bool_setting("POS_CASH_DRAWER_ENABLED", False),
            open_drawer_after_cash_sale=_bool_setting("POS_OPEN_DRAWER_AFTER_CASH_SALE", False),
            scanner_enabled=_bool_setting("POS_SCANNER_ENABLED", True),
            customer_display_enabled=_bool_setting("POS_CUSTOMER_DISPLAY_ENABLED", False),
        ),
        barcodes=BarcodeSettings(
            default_format=barcode_format,
            default_label_template=label_template,
            default_printer_profile=label_profile,
            default_label_width_mm=_positive_float_setting("POS_LABEL_WIDTH_MM", 50.0),
            default_label_height_mm=_positive_float_setting("POS_LABEL_HEIGHT_MM", 30.0),
            company_prefix=os.environ.get("POS_BARCODE_COMPANY_PREFIX", "POS").strip().upper(),
            auto_generate=_bool_setting("POS_AUTO_GENERATE_BARCODES", False),
            qr_enabled=_bool_setting("POS_QR_ENABLED", True),
        ),
    )


def reset_config_cache() -> None:
    """Reload environment configuration on the next access."""
    get_config.cache_clear()
