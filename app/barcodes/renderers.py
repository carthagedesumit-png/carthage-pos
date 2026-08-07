"""Dependency-free label renderers with a replaceable barcode engine contract."""

from abc import ABC, abstractmethod
from html import escape


class BarcodeRenderer(ABC):
    @abstractmethod
    def render(self, value: str, barcode_format: str, width: int = 280, height: int = 90) -> dict:
        """Return portable barcode render representations."""


class PlaceholderBarcodeRenderer(BarcodeRenderer):
    """Safe preview renderer; production drivers may replace this adapter."""

    def render(self, value: str, barcode_format: str, width: int = 280, height: int = 90) -> dict:
        safe_value = escape(value)
        safe_format = escape(barcode_format)
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-label="{safe_format} {safe_value}">'
            f'<rect width="100%" height="100%" fill="white" stroke="black"/>'
            f'<text x="50%" y="35%" text-anchor="middle" font-family="monospace" font-size="12">{safe_format}</text>'
            f'<text x="50%" y="68%" text-anchor="middle" font-family="monospace" font-size="14">{safe_value}</text>'
            '</svg>'
        )
        return {
            "value": value,
            "format": barcode_format,
            "svg": svg,
            "png": {"status": "placeholder", "media_type": "image/png", "data": None},
            "production_ready": False,
        }


DEFAULT_RENDERER = PlaceholderBarcodeRenderer()
