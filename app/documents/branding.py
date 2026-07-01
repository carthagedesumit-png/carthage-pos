from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping, Optional

from app.core.config import get_config


@dataclass(frozen=True)
class BrandingConfig:
    """Company-level defaults used by every generated document."""

    business_name: str = "Point of Sale"
    tax_id: str = ""
    receipt_footer: str = "Thank you for your business."
    invoice_footer: str = "Thank you for your business."
    logo_path: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def load_branding(
    overrides: Optional[Mapping[str, Any]] = None,
) -> BrandingConfig:
    """Load branding from environment variables and optional request overrides."""
    app_config = get_config()
    config = BrandingConfig(
        business_name=app_config.company.name,
        tax_id=app_config.company.tax_id,
        receipt_footer=app_config.receipt.footer,
        invoice_footer=app_config.receipt.invoice_footer,
        logo_path=app_config.company.logo_path,
        address=app_config.company.address,
        phone=app_config.company.phone,
        email=app_config.company.email,
    )
    if not overrides:
        return config
    allowed = set(config.to_dict())
    changes = {
        key: str(value or "").strip()
        for key, value in overrides.items()
        if key in allowed
    }
    return replace(config, **changes)
