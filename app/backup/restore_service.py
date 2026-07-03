"""Validated, confirmed, and rollback-safe database restore operations."""

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from uuid import uuid4

from app.backup.backup_service import (
    create_backup, get_latest_backup, materialize_database, verify_backup,
)
from app.backup.permissions import require_backup_admin
from app.backup.storage import append_audit, read_manifest
from app.core.config import get_config
from app.core.exceptions import RestoreError
from app.core.logging_utils import get_logger, log_event, log_failure
from app.database.db_manager import get_database_path, initialize_database


logger = get_logger("backup.restore")


def restore_backup(session, backup_id: str | None = None, *, use_latest: bool = False,
                   dry_run: bool = True, confirmation: str | None = None) -> dict:
    """Validate or atomically restore a selected backup with automatic rollback."""
    session = require_backup_admin(session)
    if use_latest:
        metadata = get_latest_backup(session)
    elif backup_id:
        metadata = read_manifest(backup_id)
    else:
        raise RestoreError("A backup ID is required unless use_latest is enabled.")
    verification = verify_backup(session, metadata["backup_id"])
    if not verification["valid"]:
        raise RestoreError("Backup verification failed; restore was not attempted.")
    required_confirmation = restore_confirmation(metadata["backup_id"])
    if dry_run:
        return {
            "dry_run": True,
            "restorable": True,
            "backup": metadata,
            "verification": verification,
            "required_confirmation": required_confirmation,
        }
    if confirmation != required_confirmation:
        raise RestoreError("Restore confirmation is missing or incorrect.")

    target = Path(get_database_path()).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    stage_file = tempfile.NamedTemporaryFile(
        prefix=f".{target.name}.restore-", suffix=".tmp", dir=target.parent, delete=False
    )
    stage = Path(stage_file.name)
    stage_file.close()
    rollback = target.with_name(f".{target.name}.rollback-{uuid4().hex}")
    safety_backup = None
    try:
        with materialize_database(metadata) as candidate:
            shutil.copy2(candidate, stage)
        _validate_stage(stage)
        if get_config().backup.auto_before_restore and target.is_file():
            safety_backup = create_backup(
                session, name=f"pre-restore-{metadata['backup_id'].lower()}",
                preserve_ids={metadata["backup_id"]},
            )
        _checkpoint_database(target)
        had_target = target.is_file()
        if had_target:
            os.replace(target, rollback)
        _remove_sqlite_sidecars(target)
        try:
            os.replace(stage, target)
            initialize_database()
        except Exception:
            target.unlink(missing_ok=True)
            if had_target and rollback.is_file():
                os.replace(rollback, target)
            raise
        rollback.unlink(missing_ok=True)
    except Exception as exc:
        stage.unlink(missing_ok=True)
        if rollback.is_file() and not target.is_file():
            os.replace(rollback, target)
        log_failure(logger, "restore_failed", backup_id=metadata["backup_id"],
                    error_type=type(exc).__name__)
        if isinstance(exc, RestoreError):
            raise
        raise RestoreError("Restore failed; the original database was preserved.") from exc
    append_audit("backup_restored", session, backup_id=metadata["backup_id"],
                 safety_backup_id=safety_backup.get("backup_id") if safety_backup else None)
    log_event(logger, "backup_restored", backup_id=metadata["backup_id"],
              safety_backup_id=safety_backup.get("backup_id") if safety_backup else None,
              user_id=session.user_id)
    return {
        "restored": True,
        "backup_id": metadata["backup_id"],
        "automatic_backup": safety_backup,
        "verification": verification,
    }


def restore_latest(session, *, dry_run: bool = True, confirmation: str | None = None) -> dict:
    return restore_backup(session, use_latest=True, dry_run=dry_run, confirmation=confirmation)


def restore_confirmation(backup_id: str) -> str:
    return f"RESTORE:{backup_id}"


def _validate_stage(path: Path) -> None:
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RestoreError("Restore staging database failed integrity validation.")
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise RestoreError("Restore staging database is unreadable.") from exc


def _checkpoint_database(path: Path) -> None:
    if not path.is_file():
        return
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()


def _remove_sqlite_sidecars(path: Path) -> None:
    Path(f"{path}-wal").unlink(missing_ok=True)
    Path(f"{path}-shm").unlink(missing_ok=True)
