"""License validation, trial/grace lifecycle, and sanitized status reporting."""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import get_config
from app.core.exceptions import LicenseError, LicenseValidationError
from app.core.logging_utils import get_logger, log_event
from app.core.version import APP_VERSION, compare_versions
from app.licensing.crypto import load_public_key, verify_payload
from app.licensing.editions import DEVELOPER, get_edition
from app.licensing.fingerprint import (
    FingerprintProvider, SystemFingerprintProvider, fingerprint_matches,
)
from app.licensing.issuer import VALID_LICENSE_TYPES
from app.licensing.storage import (
    active_license_path, append_audit, license_directory, read_json, write_json_atomic,
)


LICENSE_KEY_PATTERN = re.compile(r"^CTG-(COM|PRO|ENT|DEV)(-[A-HJ-NP-Z2-9]{5}){4}$")
logger = get_logger("licensing")


def validate_license_document(document: dict, *, provider: FingerprintProvider | None = None,
                              now: datetime | None = None) -> dict:
    """Verify signature, schema, machine binding, activation count, and lifecycle."""
    if not isinstance(document, dict) or not isinstance(document.get("payload"), dict):
        raise LicenseValidationError("License document is malformed.")
    payload = document["payload"]
    signature = document.get("signature")
    public_key_path = Path(get_config().licensing.public_key_file)
    public_key = load_public_key(str(public_key_path))
    if payload.get("key_id") != public_key.key_id or not verify_payload(payload, signature, public_key):
        raise LicenseValidationError("License signature verification failed.")
    _validate_payload(payload)
    if compare_versions(APP_VERSION, payload["minimum_application_version"]) < 0:
        raise LicenseValidationError("License requires a newer application version.")
    if payload["edition"] == DEVELOPER and not get_config().licensing.developer_mode:
        raise LicenseValidationError("Developer licenses require explicit developer mode.")
    current = (provider or SystemFingerprintProvider()).fingerprint()
    binding = fingerprint_matches(
        payload["bound_identifiers"], current,
        get_config().licensing.fingerprint_min_matches,
    )
    if not binding["matched"]:
        raise LicenseValidationError("License is not activated for this machine.")
    status = _signed_lifecycle(payload, now or datetime.now(timezone.utc))
    status["machine_binding"] = binding
    status["license"] = _safe_license(payload)
    return status


def get_license_status(*, provider: FingerprintProvider | None = None,
                       now: datetime | None = None) -> dict:
    """Return a non-secret status, falling back to developer mode or local trial."""
    now = _aware(now or datetime.now(timezone.utc))
    settings = get_config().licensing
    if settings.developer_mode:
        return _base_status(
            state="DEVELOPER", valid=True, edition=DEVELOPER,
            license_type="DEVELOPER", read_only=False,
            notifications=["Developer mode is enabled and must not be used for production."],
        )
    path = active_license_path()
    if path.is_file():
        try:
            status = validate_license_document(read_json(path), provider=provider, now=now)
            append_audit("license_validated", state=status["state"],
                         edition=status["edition"], license_id=status["license"]["license_id"])
            return status
        except LicenseError as exc:
            append_audit("license_validation_failed", error_type=type(exc).__name__)
            log_event(logger, "license_validation_failed", error_type=type(exc).__name__)
            return _base_status(
                state="INVALID", valid=False, edition=settings.default_edition,
                license_type="INVALID", read_only=True,
                notifications=["The installed license is invalid. Contact an administrator."],
                error="License validation failed.",
            )
    return _trial_status(now)


def get_current_license(*, provider=None, now=None) -> dict:
    return get_license_status(provider=provider, now=now)


def _trial_status(now):
    settings = get_config().licensing
    state_path = license_directory() / "trial-state.json"
    try:
        if state_path.is_file():
            state = read_json(state_path)
        else:
            state = {"first_seen_at": now.isoformat(), "last_seen_at": now.isoformat()}
        first_seen = _parse_time(state.get("first_seen_at"), "trial first-seen time")
        last_seen = _parse_time(state.get("last_seen_at"), "trial last-seen time")
    except (LicenseError, OSError, ValueError):
        append_audit("trial_state_invalid")
        return _base_status(
            state="INVALID", valid=False, edition=settings.default_edition,
            license_type="TRIAL", read_only=True,
            notifications=["Evaluation state is invalid. Administrator action is required."],
        )
    if now < last_seen - timedelta(minutes=5):
        return _base_status(
            state="CLOCK_ROLLBACK", valid=False, edition=settings.default_edition,
            license_type="TRIAL", read_only=True,
            notifications=["System clock rollback detected. Administrator action is required."],
        )
    state["last_seen_at"] = max(now, last_seen).isoformat()
    write_json_atomic(state_path, state)
    trial_end = first_seen + timedelta(days=settings.evaluation_days)
    grace_end = trial_end + timedelta(days=settings.grace_period_days)
    if now <= trial_end:
        days = max((trial_end - now).days + 1, 0)
        return _base_status(
            state="TRIAL", valid=True, edition=settings.trial_edition,
            license_type="TRIAL", read_only=False, expires_at=trial_end.isoformat(),
            grace_ends_at=grace_end.isoformat(), days_remaining=days,
            notifications=[f"Evaluation license expires in {days} day(s)."],
        )
    if now <= grace_end:
        days = max((grace_end - now).days + 1, 0)
        return _base_status(
            state="GRACE", valid=True, edition=settings.trial_edition,
            license_type="TRIAL", read_only=False, expires_at=trial_end.isoformat(),
            grace_ends_at=grace_end.isoformat(), days_remaining=days,
            notifications=[f"Evaluation expired; grace period ends in {days} day(s)."],
        )
    return _base_status(
        state="EXPIRED", valid=False, edition=settings.default_edition,
        license_type="TRIAL", read_only=True, expires_at=trial_end.isoformat(),
        grace_ends_at=grace_end.isoformat(), days_remaining=0,
        notifications=["Evaluation and grace period expired. The installation is read-only."],
    )


def _signed_lifecycle(payload, now):
    expires_at = payload.get("expires_at")
    if not expires_at:
        return _base_status(
            state="ACTIVE", valid=True, edition=payload["edition"],
            license_type=payload["license_type"], read_only=False,
        )
    expiration = _parse_time(expires_at, "license expiration")
    grace_end = expiration + timedelta(days=get_config().licensing.grace_period_days)
    if now <= expiration:
        days = max((expiration - now).days + 1, 0)
        return _base_status(
            state="ACTIVE", valid=True, edition=payload["edition"],
            license_type=payload["license_type"], read_only=False,
            expires_at=expiration.isoformat(), grace_ends_at=grace_end.isoformat(),
            days_remaining=days,
            notifications=[f"License expires in {days} day(s)."] if days <= 30 else [],
        )
    if now <= grace_end:
        days = max((grace_end - now).days + 1, 0)
        return _base_status(
            state="GRACE", valid=True, edition=payload["edition"],
            license_type=payload["license_type"], read_only=False,
            expires_at=expiration.isoformat(), grace_ends_at=grace_end.isoformat(),
            days_remaining=days,
            notifications=[f"License expired; grace period ends in {days} day(s)."],
        )
    return _base_status(
        state="EXPIRED", valid=False, edition=get_config().licensing.default_edition,
        license_type=payload["license_type"], read_only=True,
        expires_at=expiration.isoformat(), grace_ends_at=grace_end.isoformat(),
        days_remaining=0,
        notifications=["License and grace period expired. The installation is read-only."],
    )


def _validate_payload(payload):
    required = {
        "format_version", "license_id", "license_key", "license_type", "edition",
        "customer_name", "company_name", "issued_at", "perpetual",
        "activation_limit", "activation_number", "activation_id",
        "bound_identifiers", "minimum_application_version", "key_id",
    }
    if required - payload.keys() or payload.get("format_version") != 1:
        raise LicenseValidationError("License payload is incomplete or unsupported.")
    get_edition(payload["edition"])
    if payload["license_type"] not in VALID_LICENSE_TYPES:
        raise LicenseValidationError("License type is invalid.")
    if not LICENSE_KEY_PATTERN.fullmatch(str(payload["license_key"])):
        raise LicenseValidationError("Human-readable license key is invalid.")
    if not str(payload["customer_name"]).strip() or not str(payload["company_name"]).strip():
        raise LicenseValidationError("License customer and company are required.")
    if not isinstance(payload["bound_identifiers"], list) or not payload["bound_identifiers"]:
        raise LicenseValidationError("License machine binding is missing.")
    if not 1 <= int(payload["activation_number"]) <= int(payload["activation_limit"]):
        raise LicenseValidationError("License activation count is invalid.")
    _parse_time(payload["issued_at"], "license issue time")


def _safe_license(payload):
    return {
        "license_id": payload["license_id"],
        "license_key": mask_license_key(payload["license_key"]),
        "license_type": payload["license_type"],
        "edition": payload["edition"],
        "customer_name": payload["customer_name"],
        "company_name": payload["company_name"],
        "issued_at": payload["issued_at"],
        "expires_at": payload.get("expires_at"),
        "perpetual": bool(payload["perpetual"]),
        "activation_number": int(payload["activation_number"]),
        "activation_limit": int(payload["activation_limit"]),
    }


def mask_license_key(value):
    parts = str(value).split("-")
    return "-".join(parts[:2] + ["*****"] * max(len(parts) - 3, 0) + parts[-1:])


def _base_status(*, state, valid, edition, license_type, read_only,
                 notifications=None, expires_at=None, grace_ends_at=None,
                 days_remaining=None, error=None):
    definition = get_edition(edition)
    return {
        "state": state, "valid": valid, "edition": definition.name,
        "license_type": license_type, "read_only": read_only,
        "expires_at": expires_at, "grace_ends_at": grace_ends_at,
        "days_remaining": days_remaining, "notifications": notifications or [],
        "features": sorted(definition.features),
        "limits": {"maximum_stores": definition.maximum_stores,
                   "maximum_users": definition.maximum_users},
        "license": None, "error": error,
    }


def _parse_time(value, label):
    try:
        return _aware(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (TypeError, ValueError) as exc:
        raise LicenseValidationError(f"Invalid {label}.") from exc


def _aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
