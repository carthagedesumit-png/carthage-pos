import os
from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping, Optional


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
    config = BrandingConfig(
        business_name=os.environ.get("POS_BUSINESS_NAME", "Point of Sale"),
        tax_id=os.environ.get("POS_TAX_ID", ""),
        receipt_footer=os.environ.get(
            "POS_RECEIPT_FOOTER", "Thank you for your business."
        ),
        invoice_footer=os.environ.get(
            "POS_INVOICE_FOOTER", "Thank you for your business."
        ),
        logo_path=os.environ.get("POS_LOGO_PATH", ""),
        address=os.environ.get("POS_BUSINESS_ADDRESS", ""),
        phone=os.environ.get("POS_BUSINESS_PHONE", ""),
        email=os.environ.get("POS_BUSINESS_EMAIL", ""),
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
