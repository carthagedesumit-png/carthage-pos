"""Database upgrade rehearsal built on existing migrations and backup service."""

import os
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path

from app.core.exceptions import InstallationError
from app.core.version import DATABASE_SCHEMA_VERSION, MIN_SUPPORTED_DATABASE_VERSION
from app.database.db_manager import initialize_database


def validate_schema_version(database_path: str | Path) -> dict:
    version = _database_version(Path(database_path))
    compatible = MIN_SUPPORTED_DATABASE_VERSION <= version <= DATABASE_SCHEMA_VERSION
    return {
        "valid": compatible,
        "database_version": version,
        "target_schema_version": DATABASE_SCHEMA_VERSION,
        "supported_range": [MIN_SUPPORTED_DATABASE_VERSION, DATABASE_SCHEMA_VERSION],
    }


def rehearse_database_upgrade(
    database_path: str | Path,
    *,
    backup_directory: str | Path | None = None,
    simulate_failure: bool = False,
) -> dict:
    source = Path(database_path).resolve()
    if not source.is_file():
        raise InstallationError("Source database for upgrade rehearsal was not found.")
    initial = validate_schema_version(source)
    if not initial["valid"]:
        raise InstallationError("Database schema version is not supported for upgrade.")
    with tempfile.TemporaryDirectory(prefix="cbos-upgrade-rehearsal-") as workspace:
        workspace_path = Path(workspace)
        rehearsal_db = workspace_path / source.name
        shutil.copy2(source, rehearsal_db)
        pre_upgrade_backup = _copy_backup(source, Path(backup_directory or workspace_path))
        try:
            with _database_environment(rehearsal_db):
                if simulate_failure:
                    raise RuntimeError("simulated upgrade failure")
                initialize_database()
            upgraded = validate_schema_version(rehearsal_db)
            _assert_integrity(rehearsal_db)
        except Exception as exc:
            _assert_integrity(source)
            return {
                "successful": False,
                "rolled_back": True,
                "error_type": type(exc).__name__,
                "source_unchanged": source.read_bytes() == pre_upgrade_backup.read_bytes(),
                "pre_upgrade_backup": str(pre_upgrade_backup),
                "initial": initial,
            }
    return {
        "successful": True,
        "rolled_back": False,
        "pre_upgrade_backup": str(pre_upgrade_backup),
        "initial": initial,
        "upgraded": upgraded,
    }


def _copy_backup(source: Path, backup_directory: Path) -> Path:
    backup_directory.mkdir(parents=True, exist_ok=True)
    destination = backup_directory / f"pre-upgrade-{source.stem}.sqlite3"
    shutil.copy2(source, destination)
    return destination


def _database_version(path: Path) -> int:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])
    finally:
        connection.close()


def _assert_integrity(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise InstallationError("Database integrity check failed.")
    finally:
        connection.close()


@contextmanager
def _database_environment(path: Path):
    previous = os.environ.get("CARTHAGE_POS_DB")
    try:
        os.environ["CARTHAGE_POS_DB"] = str(path)
        yield
    finally:
        if previous is None:
            os.environ.pop("CARTHAGE_POS_DB", None)
        else:
            os.environ["CARTHAGE_POS_DB"] = previous
