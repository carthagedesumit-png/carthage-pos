"""Reusable label template registry."""

from dataclasses import asdict, dataclass

from app.core.exceptions import LabelError


@dataclass(frozen=True)
class LabelTemplate:
    code: str
    name: str
    width_mm: float
    height_mm: float
    fields: tuple[str, ...]

    def to_dict(self) -> dict:
        value = asdict(self)
        value["fields"] = list(self.fields)
        return value


TEMPLATES = {
    "SHELF": LabelTemplate("SHELF", "Shelf Label", 80, 38, ("business_name", "store_name", "product_name", "selling_price", "barcode")),
    "SMALL_PRODUCT": LabelTemplate("SMALL_PRODUCT", "Small Product Label", 50, 30, ("product_name", "selling_price", "sku", "barcode")),
    "LARGE_PRODUCT": LabelTemplate("LARGE_PRODUCT", "Large Product Label", 80, 50, ("business_name", "store_name", "product_name", "selling_price", "promotion_price", "sku", "barcode", "category", "unit")),
    "WAREHOUSE": LabelTemplate("WAREHOUSE", "Warehouse Label", 100, 70, ("store_name", "product_name", "sku", "barcode", "category", "unit", "printed_date")),
    "BARCODE_ONLY": LabelTemplate("BARCODE_ONLY", "Barcode-only Label", 50, 25, ("barcode", "sku")),
    "QR": LabelTemplate("QR", "QR Label", 50, 50, ("product_name", "qr_code", "sku")),
}


def get_template(code: str, width_mm: float | None = None, height_mm: float | None = None) -> LabelTemplate:
    normalized = str(code or "").strip().upper()
    if normalized not in TEMPLATES:
        raise LabelError(f"Unknown label template: {normalized or 'empty'}.")
    template = TEMPLATES[normalized]
    if width_mm is None and height_mm is None:
        return template
    width = float(width_mm if width_mm is not None else template.width_mm)
    height = float(height_mm if height_mm is not None else template.height_mm)
    if width <= 0 or height <= 0:
        raise LabelError("Label dimensions must be positive.")
    return LabelTemplate(template.code, template.name, width, height, template.fields)


def list_templates() -> list[dict]:
    return [template.to_dict() for template in TEMPLATES.values()]
