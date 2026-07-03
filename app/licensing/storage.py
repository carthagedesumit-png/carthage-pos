"""Atomic licensing state, activation files, and secret-safe audit records."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.core.config import get_config
from app.core.exceptions import LicenseError


def license_directory() -> Path:
    path = Path(get_config().licensing.directory).resolve()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise LicenseError("License directory is unavailable or not writable.") from exc
    return path


def activation_directory() -> Path:
    path = Path(get_config().licensing.activation_directory).resolve()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise LicenseError("Activation directory is unavailable or not writable.") from exc
    return path


def active_license_path() -> Path:
    return Path(get_config().licensing.license_file).resolve()


def read_json(path: str | Path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LicenseError("License or activation file is unreadable.") from exc
    if not isinstance(value, dict):
        raise LicenseError("License or activation document must be a JSON object.")
    return value


def write_json_atomic(path: str | Path, payload: dict) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise LicenseError("License state could not be written safely.") from exc
    return destination


def append_audit(event: str, *, user_id=None, username=None, **details) -> None:
    safe = {
        key: value for key, value in details.items()
        if not any(marker in key.lower() for marker in ("license_key", "signature", "secret", "private"))
    }
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "user_id": user_id,
        "username": username,
        "details": safe,
    }
    try:
        with (license_directory() / "licensing-audit.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        pass
