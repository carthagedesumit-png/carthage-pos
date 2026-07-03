"""Issuer-side helpers. Production builds contain no private key material."""

import secrets
from datetime import datetime, timezone
from uuid import uuid4

from app.core.exceptions import LicenseError
from app.core.version import APP_VERSION
from app.licensing.crypto import load_private_key, sign_payload
from app.licensing.editions import DEVELOPER, ENTERPRISE, PROFESSIONAL, get_edition


VALID_LICENSE_TYPES = {
    "TRIAL", "PROFESSIONAL", "ENTERPRISE", "DEVELOPER",
    "OFFLINE_PERPETUAL", "SUBSCRIPTION",
}


def issue_license(*, private_key, license_type: str, edition: str,
                  customer_name: str, company_name: str,
                  bound_identifiers: list[str], expires_at: str | None = None,
                  activation_limit: int = 1, activation_number: int = 1,
                  license_key: str | None = None) -> dict:
    """Create a signed activation response for offline distribution."""
    license_type = str(license_type).upper()
    edition = get_edition(edition).name
    if license_type not in VALID_LICENSE_TYPES:
        raise LicenseError("Unknown license type.")
    if license_type == "PROFESSIONAL" and edition != PROFESSIONAL:
        raise LicenseError("Professional licenses require the Professional edition.")
    if license_type == "ENTERPRISE" and edition != ENTERPRISE:
        raise LicenseError("Enterprise licenses require the Enterprise edition.")
    if license_type == "DEVELOPER" and edition != DEVELOPER:
        raise LicenseError("Developer licenses require the Developer edition.")
    if license_type in {"TRIAL", "SUBSCRIPTION"} and not expires_at:
        raise LicenseError("Time-limited licenses require an expiration date.")
    if activation_limit <= 0 or not 1 <= activation_number <= activation_limit:
        raise LicenseError("Activation count is invalid.")
    signing_key = load_private_key(private_key)
    payload = {
        "format_version": 1,
        "license_id": str(uuid4()),
        "license_key": license_key or generate_license_key(edition),
        "license_type": license_type,
        "edition": edition,
        "customer_name": str(customer_name).strip(),
        "company_name": str(company_name).strip(),
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires_at,
        "perpetual": license_type in {"PROFESSIONAL", "ENTERPRISE", "DEVELOPER", "OFFLINE_PERPETUAL"},
        "activation_limit": int(activation_limit),
        "activation_number": int(activation_number),
        "activation_id": str(uuid4()),
        "bound_identifiers": sorted(set(bound_identifiers)),
        "minimum_application_version": APP_VERSION,
        "key_id": signing_key.key_id,
    }
    if not payload["customer_name"] or not payload["company_name"] or not payload["bound_identifiers"]:
        raise LicenseError("Customer, company, and machine binding are required.")
    return {"payload": payload, "signature": sign_payload(payload, signing_key)}


def issue_activation_response(request_document: dict, *, private_key,
                              license_type: str, edition: str,
                              expires_at: str | None = None,
                              activation_limit: int = 1,
                              activation_number: int = 1) -> dict:
    """Issue a signed response for a validated offline activation request."""
    if not isinstance(request_document, dict) or request_document.get("format_version") != 1:
        raise LicenseError("Activation request is malformed or unsupported.")
    machine = request_document.get("machine") or {}
    identifiers = machine.get("identifiers") or {}
    if not isinstance(identifiers, dict):
        raise LicenseError("Activation request machine identifiers are invalid.")
    return issue_license(
        private_key=private_key,
        license_type=license_type,
        edition=edition,
        customer_name=request_document.get("customer_name", ""),
        company_name=request_document.get("company_name", ""),
        bound_identifiers=list(identifiers.values()),
        expires_at=expires_at,
        activation_limit=activation_limit,
        activation_number=activation_number,
        license_key=request_document.get("license_key"),
    )


def generate_license_key(edition: str) -> str:
    prefix = {"COMMUNITY": "COM", "PROFESSIONAL": "PRO", "ENTERPRISE": "ENT", "DEVELOPER": "DEV"}[
        get_edition(edition).name
    ]
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    groups = ["".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(4)]
    return "-".join(["CTG", prefix, *groups])
