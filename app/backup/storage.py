"""Filesystem primitives for backup artifacts and sidecar metadata."""

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.core.config import get_config
from app.core.exceptions import BackupError


BACKUP_ID_PATTERN = re.compile(r"^BKP-[0-9]{14}-[A-F0-9]{8}$")


def backup_directory() -> Path:
    path = Path(get_config().backup.directory).resolve()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupError("Backup directory is unavailable or not writable.") from exc
    return path


def new_backup_id(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"BKP-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8].upper()}"


def validate_backup_id(backup_id: str) -> str:
    value = str(backup_id or "").strip().upper()
    if not BACKUP_ID_PATTERN.fullmatch(value):
        raise BackupError("Invalid backup identifier.")
    return value


def safe_name(name: str | None) -> str:
    if not name:
        return ""
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name).strip()).strip("-._")
    if not value:
        raise BackupError("Backup name must contain letters or numbers.")
    return value[:80]


def manifest_path(backup_id: str) -> Path:
    return backup_directory() / f"{validate_backup_id(backup_id)}.metadata.json"


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_atomic(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise BackupError("Backup metadata could not be written safely.") from exc


def read_manifest(backup_id: str) -> dict:
    path = manifest_path(backup_id)
    if not path.is_file():
        raise BackupError("Backup not found.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError("Backup metadata is unreadable or corrupted.") from exc
    if data.get("backup_id") != validate_backup_id(backup_id):
        raise BackupError("Backup metadata identifier mismatch.")
    return data


def artifact_path(metadata: dict) -> Path:
    filename = str(metadata.get("artifact_filename") or "")
    if not filename or Path(filename).name != filename:
        raise BackupError("Backup metadata contains an invalid artifact path.")
    return backup_directory() / filename


def append_audit(event: str, session, **details) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "user_id": getattr(session, "user_id", None),
        "username": getattr(session, "username", None),
        "details": details,
    }
    path = backup_directory() / "backup-audit.jsonl"
    try:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        # Structured application logging remains available if external storage is read-only.
        pass
