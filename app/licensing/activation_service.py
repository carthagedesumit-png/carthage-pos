"""Offline activation requests, license import/replacement, renewal, and deactivation."""

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from auth import require_user_management
from app.core.exceptions import ActivationError, LicenseError, LicenseValidationError
from app.core.logging_utils import get_logger, log_event
from app.core.version import APP_VERSION
from app.licensing.fingerprint import FingerprintProvider, SystemFingerprintProvider
from app.licensing.license_service import (
    LICENSE_KEY_PATTERN, get_license_status, validate_license_document,
)
from app.licensing.storage import (
    activation_directory, active_license_path, append_audit, license_directory,
    read_json, write_json_atomic,
)


logger = get_logger("licensing.activation")


class ActivationProvider(ABC):
    @abstractmethod
    def activate(self, request_document: dict) -> dict:
        """Return a signed activation response document."""


class OnlineActivationProvider(ActivationProvider):
    def activate(self, request_document: dict) -> dict:
        raise ActivationError("Online activation is not enabled in this release.")


def export_activation_request(session, license_key: str, customer_name: str,
                              company_name: str, *, provider: FingerprintProvider | None = None) -> dict:
    """Create a portable request containing hashed machine identifiers only."""
    session = require_user_management(session)
    license_key = str(license_key or "").strip().upper()
    if not LICENSE_KEY_PATTERN.fullmatch(license_key):
        raise ActivationError("License key format is invalid.")
    customer_name, company_name = str(customer_name).strip(), str(company_name).strip()
    if not customer_name or not company_name:
        raise ActivationError("Customer and company names are required.")
    machine = (provider or SystemFingerprintProvider()).fingerprint()
    request_id = str(uuid4())
    document = {
        "format_version": 1,
        "request_id": request_id,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "application_version": APP_VERSION,
        "license_key": license_key,
        "customer_name": customer_name,
        "company_name": company_name,
        "machine": machine.to_dict(),
        "nonce": uuid4().hex,
    }
    path = activation_directory() / f"activation-request-{request_id}.json"
    write_json_atomic(path, document)
    append_audit("activation_request_exported", user_id=session.user_id,
                 username=session.username, request_id=request_id)
    log_event(logger, "activation_request_exported", request_id=request_id,
              user_id=session.user_id)
    return {"request_id": request_id, "path": str(path), "document": document}


def import_activation_response(session, response: str | dict,
                               *, provider: FingerprintProvider | None = None) -> dict:
    """Validate and atomically install a signed offline activation response."""
    session = require_user_management(session)
    document = _document(response)
    status = validate_license_document(document, provider=provider)
    if status["state"] == "EXPIRED":
        raise LicenseValidationError("Expired licenses cannot be activated.")
    target = active_license_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    archive = None
    if target.is_file():
        old = read_json(target)
        old_id = str((old.get("payload") or {}).get("license_id") or uuid4())
        archive = license_directory() / "archive" / f"license-{old_id}.json"
        archive.parent.mkdir(parents=True, exist_ok=True)
        os.replace(target, archive)
    try:
        write_json_atomic(target, document)
    except Exception:
        if archive and archive.is_file() and not target.exists():
            os.replace(archive, target)
        raise
    event = "license_replaced" if archive else "license_activated"
    append_audit(event, user_id=session.user_id, username=session.username,
                 license_id=status["license"]["license_id"], edition=status["edition"])
    log_event(logger, event, license_id=status["license"]["license_id"],
              edition=status["edition"], user_id=session.user_id)
    return status


def activate_license(session, response: str | dict, *, provider=None) -> dict:
    return import_activation_response(session, response, provider=provider)


def deactivate_installation(session, *, provider: FingerprintProvider | None = None) -> dict:
    session = require_user_management(session)
    target = active_license_path()
    if not target.is_file():
        raise ActivationError("No installed license is available to deactivate.")
    document = read_json(target)
    payload = document.get("payload") or {}
    license_id = str(payload.get("license_id") or "")
    if not license_id:
        raise ActivationError("Installed license is malformed.")
    machine = (provider or SystemFingerprintProvider()).fingerprint()
    request = {
        "format_version": 1,
        "deactivation_id": str(uuid4()),
        "license_id": license_id,
        "deactivated_at": datetime.now(timezone.utc).isoformat(),
        "machine_fingerprint": machine.fingerprint,
    }
    request_path = activation_directory() / f"deactivation-{request['deactivation_id']}.json"
    archive = license_directory() / "deactivated" / f"license-{license_id}.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(request_path, request)
    os.replace(target, archive)
    append_audit("license_deactivated", user_id=session.user_id, username=session.username,
                 license_id=license_id, deactivation_id=request["deactivation_id"])
    log_event(logger, "license_deactivated", license_id=license_id,
              user_id=session.user_id)
    return {"deactivated": True, "license_id": license_id,
            "request_path": str(request_path), "deactivation_id": request["deactivation_id"]}


def export_license_copy(session) -> dict:
    session = require_user_management(session)
    source = active_license_path()
    if not source.is_file():
        raise ActivationError("No installed license is available to export.")
    document = read_json(source)
    license_id = str((document.get("payload") or {}).get("license_id") or uuid4())
    path = activation_directory() / f"license-export-{license_id}.json"
    write_json_atomic(path, document)
    append_audit("license_exported", user_id=session.user_id,
                 username=session.username, license_id=license_id)
    return {"exported": True, "license_id": license_id, "path": str(path)}


def create_renewal_request(session, *, provider: FingerprintProvider | None = None) -> dict:
    session = require_user_management(session)
    status = get_license_status(provider=provider)
    if not status.get("license"):
        raise ActivationError("A signed license is required for renewal.")
    machine = (provider or SystemFingerprintProvider()).fingerprint()
    request = {
        "format_version": 1,
        "renewal_id": str(uuid4()),
        "license_id": status["license"]["license_id"],
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "machine_fingerprint": machine.fingerprint,
    }
    path = activation_directory() / f"renewal-{request['renewal_id']}.json"
    write_json_atomic(path, request)
    append_audit("renewal_request_exported", user_id=session.user_id,
                 username=session.username, license_id=request["license_id"])
    return {"renewal_id": request["renewal_id"], "path": str(path), "document": request}


def _document(value):
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        raise ActivationError("Activation response is required.")
    path = Path(text)
    try:
        if path.is_file():
            return read_json(path)
    except OSError:
        # Long inline JSON is not a filesystem path on all platforms.
        pass
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ActivationError("Activation response is malformed.") from exc
    if not isinstance(document, dict):
        raise ActivationError("Activation response must be a JSON object.")
    return document
