"""Replaceable license status provider interfaces."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from app.core.version import APP_VERSION
from app.licensing.editions import DEVELOPER


LICENSE_STATES = {"TRIAL", "ACTIVE", "EXPIRED", "SUSPENDED", "INVALID", "DEVELOPER"}


class LicenseStatusProvider(Protocol):
    def status(self) -> dict:
        """Return a sanitized license status document."""


@dataclass(frozen=True)
class DevelopmentLicenseProvider:
    """Local provider for development and automated tests."""

    edition: str = DEVELOPER
    days: int = 30

    def status(self) -> dict:
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=self.days)
        return {
            "state": "DEVELOPER",
            "valid": True,
            "edition": self.edition,
            "license_type": "DEVELOPER",
            "read_only": False,
            "issued_at": now.isoformat(),
            "expires_at": expires.isoformat(),
            "application_version": APP_VERSION,
            "notifications": ["Local development license provider is active."],
            "license": None,
            "error": None,
        }


def validate_license_status_document(status: dict) -> dict:
    state = str(status.get("state") or "").upper()
    valid = state in LICENSE_STATES and isinstance(status.get("valid"), bool)
    return {
        "valid": valid,
        "state": state,
        "known_state": state in LICENSE_STATES,
        "read_only": bool(status.get("read_only")),
    }
