"""Consistent SQLite backups, verification, retention, and metadata queries."""

import json
import os
import sqlite3
import tempfile
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from app.backup.permissions import require_backup_access, require_backup_admin
from app.backup.storage import (
    append_audit, artifact_path, backup_directory, checksum, manifest_path,
    new_backup_id, read_manifest, safe_name, validate_backup_id, write_json_atomic,
)
from app.core.config import get_config
from app.core.exceptions import BackupError
from app.core.logging_utils import get_logger, log_event, log_failure
from app.core.version import APP_VERSION, DATABASE_SCHEMA_VERSION
from app.database.db_manager import get_connection, get_database_path


REQUIRED_TABLES = {"users", "stores", "products", "store_inventory", "sales", "sale_items"}
VALID_BACKUP_TYPES = {"FULL", "INCREMENTAL"}
DATABASE_ARCHIVE_NAME = "database.sqlite3"
logger = get_logger("backup")


def create_backup(session, name: str | None = None, backup_type: str = "FULL",
                  compression: bool | None = None, *, preserve_ids: set[str] | None = None) -> dict:
    """Create an online-consistent database snapshot and sidecar manifest."""
    session = require_backup_access(session)
    backup_type = str(backup_type or "FULL").strip().upper()
    if backup_type not in VALID_BACKUP_TYPES:
        raise BackupError("Backup type must be FULL or INCREMENTAL.")
    name = safe_name(name)
    settings = get_config().backup
    compression = settings.compression_enabled if compression is None else bool(compression)
    directory = backup_directory()
    source_path = Path(get_database_path()).resolve()
    if not source_path.is_file():
        raise BackupError("Active database file does not exist.")
    existing = []
    if name:
        existing = [item for item in _list_manifests() if (item.get("name") or "").casefold() == name.casefold()]
        if existing and not settings.overwrite_enabled:
            raise BackupError("A named backup already exists and overwrite is disabled.")

    backup_id = new_backup_id()
    suffix = f"-{name}" if name else ""
    raw_path = directory / f".{backup_id}{suffix}.snapshot.tmp"
    artifact = directory / f"{backup_id}{suffix}{'.zip' if compression else '.sqlite3'}"
    try:
        _sqlite_snapshot(raw_path)
        database_version = _database_version(raw_path)
        if compression:
            with zipfile.ZipFile(artifact, "w", compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=6) as archive:
                archive.write(raw_path, DATABASE_ARCHIVE_NAME)
            raw_path.unlink(missing_ok=True)
        else:
            os.replace(raw_path, artifact)
        previous = get_latest_backup(session, required=False) if backup_type == "INCREMENTAL" else None
        metadata = {
            "backup_id": backup_id,
            "name": name or None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "application_version": APP_VERSION,
            "database_version": database_version,
            "backup_size": artifact.stat().st_size,
            "checksum": checksum(artifact),
            "checksum_algorithm": "SHA256",
            "initiating_user": {"id": session.user_id, "username": session.username},
            "backup_type": backup_type,
            "strategy": "FULL_SNAPSHOT" if backup_type == "FULL" else "INCREMENTAL_FOUNDATION_FULL_SNAPSHOT",
            "base_backup_id": previous.get("backup_id") if previous else None,
            "compressed": compression,
            "artifact_filename": artifact.name,
            "database_archive_name": DATABASE_ARCHIVE_NAME,
            "metadata_version": 1,
        }
        write_json_atomic(manifest_path(backup_id), metadata)
        if settings.verify_after_create:
            verification = _verify_metadata(metadata)
            if not verification["valid"]:
                _delete_files(metadata)
                raise BackupError("Created backup failed integrity verification.")
            metadata["verified_at"] = verification["verified_at"]
            write_json_atomic(manifest_path(backup_id), metadata)
        for item in existing:
            _delete_files(item)
        _apply_retention(exclude={backup_id, *(preserve_ids or set())})
    except Exception as exc:
        raw_path.unlink(missing_ok=True)
        artifact.unlink(missing_ok=True)
        manifest_path(backup_id).unlink(missing_ok=True)
        if not isinstance(exc, BackupError):
            log_failure(logger, "backup_creation_failed", error_type=type(exc).__name__)
            raise BackupError("Database backup could not be created.") from exc
        raise
    append_audit("backup_created", session, backup_id=backup_id, backup_type=backup_type)
    log_event(logger, "backup_created", backup_id=backup_id, backup_type=backup_type,
              size=metadata["backup_size"], user_id=session.user_id)
    return metadata


def list_backups(session) -> list[dict]:
    require_backup_access(session)
    return sorted(_list_manifests(), key=lambda item: item.get("timestamp", ""), reverse=True)


def get_backup_metadata(session, backup_id: str) -> dict:
    require_backup_access(session)
    return read_manifest(backup_id)


def get_latest_backup(session, *, required: bool = True) -> dict | None:
    items = list_backups(session)
    if items:
        return items[0]
    if required:
        raise BackupError("No backups are available.")
    return None


def verify_backup(session, backup_id: str) -> dict:
    session = require_backup_access(session)
    metadata = read_manifest(backup_id)
    result = _verify_metadata(metadata)
    append_audit("backup_verified" if result["valid"] else "backup_verification_failed",
                 session, backup_id=metadata["backup_id"], valid=result["valid"])
    log_event(logger, "backup_verified", backup_id=metadata["backup_id"],
              valid=result["valid"], user_id=session.user_id)
    return result


def delete_backup(session, backup_id: str) -> dict:
    session = require_backup_admin(session)
    metadata = read_manifest(backup_id)
    _delete_files(metadata)
    append_audit("backup_deleted", session, backup_id=metadata["backup_id"])
    log_event(logger, "backup_deleted", backup_id=metadata["backup_id"], user_id=session.user_id)
    return {"deleted": True, "backup_id": metadata["backup_id"]}


def get_backup_status(session) -> dict:
    session = require_backup_access(session)
    items = list_backups(session)
    total_size = sum(int(item.get("backup_size", 0)) for item in items)
    return {
        "backup_directory": str(backup_directory()),
        "backup_count": len(items),
        "total_size": total_size,
        "latest_backup": items[0] if items else None,
        "compression_enabled": get_config().backup.compression_enabled,
        "retention_days": get_config().backup.retention_days,
        "maximum_backup_count": get_config().backup.max_count,
    }


def _sqlite_snapshot(destination_path: Path) -> None:
    source = get_connection()
    destination = sqlite3.connect(destination_path)
    try:
        source.backup(destination)
        destination.commit()
    finally:
        destination.close()
        source.close()


def _database_version(path: Path) -> int:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])
    finally:
        connection.close()


def _verify_metadata(metadata: dict) -> dict:
    checks = {}
    artifact = artifact_path(metadata)
    checks["artifact_exists"] = artifact.is_file()
    if not checks["artifact_exists"]:
        return _verification_result(metadata, checks, "Backup artifact is missing.")
    try:
        checks["checksum"] = checksum(artifact) == metadata.get("checksum")
        if not checks["checksum"]:
            return _verification_result(metadata, checks, "Backup checksum does not match metadata.")
        with materialize_database(metadata) as database_path:
            connection = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
            try:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                checks["database_integrity"] = integrity == "ok"
                tables = {row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()}
                checks["required_tables"] = REQUIRED_TABLES.issubset(tables)
                actual_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                checks["schema_version"] = actual_version == int(metadata.get("database_version", -1))
                checks["schema_compatible"] = 0 <= actual_version <= DATABASE_SCHEMA_VERSION
            finally:
                connection.close()
        backup_major = int(str(metadata.get("application_version", "0")).split(".")[0])
        current_major = int(APP_VERSION.split(".")[0])
        checks["application_compatible"] = backup_major <= current_major
    except (OSError, sqlite3.DatabaseError, zipfile.BadZipFile, ValueError, KeyError,
            BackupError) as exc:
        return _verification_result(metadata, checks, "Backup is unreadable or corrupted.", type(exc).__name__)
    valid = all(checks.values())
    message = "Backup is valid." if valid else "Backup failed one or more compatibility checks."
    return _verification_result(metadata, checks, message)


def _verification_result(metadata, checks, message, error_type=None):
    return {
        "backup_id": metadata.get("backup_id"),
        "valid": bool(checks) and all(checks.values()),
        "checks": checks,
        "message": message,
        "error_type": error_type,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


@contextmanager
def materialize_database(metadata: dict) -> Iterator[Path]:
    """Yield a readable SQLite file from compressed or plain backup storage."""
    artifact = artifact_path(metadata)
    if not metadata.get("compressed"):
        yield artifact
        return
    temporary = tempfile.NamedTemporaryFile(prefix="carthage-restore-", suffix=".sqlite3", delete=False)
    temporary_path = Path(temporary.name)
    temporary.close()
    try:
        with zipfile.ZipFile(artifact, "r") as archive:
            names = archive.namelist()
            if names != [DATABASE_ARCHIVE_NAME]:
                raise BackupError("Compressed backup has an unexpected archive layout.")
            info = archive.getinfo(DATABASE_ARCHIVE_NAME)
            if info.flag_bits & 0x1:
                raise BackupError("Encrypted backup archives are unsupported.")
            with archive.open(info, "r") as source, temporary_path.open("wb") as destination:
                while block := source.read(1024 * 1024):
                    destination.write(block)
        yield temporary_path
    finally:
        temporary_path.unlink(missing_ok=True)


def _list_manifests() -> list[dict]:
    items = []
    for path in backup_directory().glob("BKP-*.metadata.json"):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            if item.get("backup_id") and validate_backup_id(item["backup_id"]):
                items.append(item)
        except (OSError, json.JSONDecodeError, BackupError):
            continue
    return items


def _delete_files(metadata: dict) -> None:
    artifact_path(metadata).unlink(missing_ok=True)
    manifest_path(metadata["backup_id"]).unlink(missing_ok=True)


def _apply_retention(exclude: set[str] | None = None) -> None:
    settings = get_config().backup
    exclude = exclude or set()
    items = sorted(_list_manifests(), key=lambda item: item.get("timestamp", ""), reverse=True)
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.retention_days)
    for index, item in enumerate(items):
        if item.get("backup_id") in exclude:
            continue
        try:
            created = datetime.fromisoformat(item["timestamp"])
        except (KeyError, ValueError):
            created = datetime.min.replace(tzinfo=timezone.utc)
        expired = settings.retention_days > 0 and created < cutoff
        over_count = index >= settings.max_count
        if expired or over_count:
            _delete_files(item)
