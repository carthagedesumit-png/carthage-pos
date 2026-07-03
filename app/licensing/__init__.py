"""Offline-first licensing, activation, and product edition services."""

from app.licensing.license_service import get_license_status

__all__ = ["get_license_status"]
