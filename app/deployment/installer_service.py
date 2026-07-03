"""Rollback-safe installation, upgrade, repair, and uninstall workflows."""

import json
import os
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from auth import bootstrap_admin
from app.core.config import parse_environment_file, reset_config_cache
from app.core.exceptions import InstallationError
from app.core.logging_utils import get_logger, log_event, log_failure
from app.core.version import APP_VERSION, INSTALLER_VERSION, VersionInfo, compatibility_report
from app.database.db_manager import get_connection, initialize_database
from app.deployment.audit import record_deployment_event
from app.deployment.configuration_service import (
    build_environment, generate_environment_file, write_environment_values,
)
from app.deployment.models import SetupRequest
from app.deployment.windows_integration import (
    build_windows_integration_manifest, build_windows_integration_manifest_from_setup,
)


logger = get_logger("deployment.installer")


def fresh_install(request: SetupRequest) -> dict:
    """Perform first-run configuration and atomic database initialization."""
    request = request.validated()
    install_dir = Path(request.installation_directory)
    state_path = _state_path(install_dir)
    database_path = Path(request.database_path)
    if state_path.exists():
        raise InstallationError("Carthage POS is already installed at this location.")
    if database_path.exists():
        raise InstallationError("Fresh installation will not overwrite an existing database.")
    _prepare_directories(request)
    config_path = install_dir / "config" / "carthage-pos.env"
    windows_path = install_dir / "config" / "windows-integration.json"
    created_files = [config_path, windows_path, state_path]
    try:
        generated = generate_environment_file(request, str(config_path))
        database = _initialize_fresh_database(request, generated["settings"])
        windows_manifest = build_windows_integration_manifest(request)
        _write_json_atomic(windows_path, windows_manifest)
        state = _build_state(request, generated["settings"], config_path, windows_path, "FRESH")
        state["database"] = database
        _write_json_atomic(state_path, state)
    except Exception as exc:
        for path in created_files:
            path.unlink(missing_ok=True)
        if database_path.exists():
            database_path.unlink(missing_ok=True)
        record_deployment_event(str(install_dir), "installation_failed",
                                error_type=type(exc).__name__)
        log_failure(logger, "installation_failed", error_type=type(exc).__name__)
        if isinstance(exc, InstallationError):
            raise
        raise InstallationError("Installation failed and partial data was removed.") from exc
    record_deployment_event(str(install_dir), "installation_completed",
                            application_version=APP_VERSION, mode="FRESH")
    log_event(logger, "installation_completed", application_version=APP_VERSION, mode="FRESH")
    return state


def upgrade_installation(installation_directory: str) -> dict:
    """Run compatibility checks and migrations with a rollback snapshot."""
    install_dir = Path(installation_directory).expanduser().resolve()
    state, environment = _load_installation(install_dir)
    database_path = Path(environment["CARTHAGE_POS_DB"])
    current_database_version = _database_version(database_path)
    compatibility = compatibility_report(
        application_version=state.get("application_version", APP_VERSION),
        database_version=current_database_version,
        installer_version=INSTALLER_VERSION,
    )
    if not compatibility["compatible"]:
        raise InstallationError("Installed application or database is not upgrade-compatible.")
    rollback = _snapshot_database(database_path, install_dir / "rollback", "upgrade")
    previous_version = state.get("application_version")
    try:
        with _temporary_environment(environment):
            initialize_database()
            _assert_database_integrity(database_path)
    except Exception as exc:
        _restore_snapshot(rollback, database_path)
        record_deployment_event(str(install_dir), "upgrade_failed",
                                error_type=type(exc).__name__)
        raise InstallationError("Upgrade failed; the previous database was restored.") from exc
    state.update({
        "application_version": APP_VERSION,
        "versions": VersionInfo().to_dict(),
        "last_operation": "UPGRADE",
        "previous_application_version": previous_version,
        "rollback_database": str(rollback),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    _write_json_atomic(_state_path(install_dir), state)
    record_deployment_event(str(install_dir), "upgrade_completed",
                            from_version=previous_version, to_version=APP_VERSION)
    return state


def repair_installation(installation_directory: str) -> dict:
    """Regenerate missing configuration and repair database migrations safely."""
    install_dir = Path(installation_directory).expanduser().resolve()
    state_path = _state_path(install_dir)
    if not state_path.is_file():
        raise InstallationError("Installed deployment state was not found.")
    state = _read_json(state_path)
    config_path = Path(state.get("configuration_file") or install_dir / "config" / "carthage-pos.env")
    environment = state.get("environment") or {}
    if not config_path.is_file():
        if not environment:
            raise InstallationError("Configuration is missing and cannot be reconstructed.")
        write_environment_values(environment, config_path)
    else:
        environment = parse_environment_file(str(config_path))
    database_path = Path(environment.get("CARTHAGE_POS_DB", ""))
    if not database_path.is_file():
        raise InstallationError("Repair cannot continue because the database is missing.")
    _prepare_runtime_directories(install_dir, database_path, Path(environment["POS_BACKUP_DIRECTORY"]))
    rollback = _snapshot_database(database_path, install_dir / "rollback", "repair")
    try:
        with _temporary_environment(environment):
            initialize_database()
            _assert_database_integrity(database_path)
        setup_data = state.get("setup") or {}
        windows_path = install_dir / "config" / "windows-integration.json"
        _write_json_atomic(windows_path, build_windows_integration_manifest_from_setup(setup_data))
    except Exception as exc:
        _restore_snapshot(rollback, database_path)
        record_deployment_event(str(install_dir), "repair_failed",
                                error_type=type(exc).__name__)
        raise InstallationError("Repair failed; the previous database was restored.") from exc
    state.update({
        "environment": environment,
        "last_operation": "REPAIR",
        "rollback_database": str(rollback),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    _write_json_atomic(state_path, state)
    record_deployment_event(str(install_dir), "repair_completed")
    return state


def uninstall_installation(installation_directory: str, *, remove_data: bool = False,
                           confirmation: str | None = None) -> dict:
    """Remove installer-generated state while preserving business data by default."""
    install_dir = Path(installation_directory).expanduser().resolve()
    state, environment = _load_installation(install_dir)
    if remove_data and confirmation != "REMOVE-ALL-DATA":
        raise InstallationError("Removing business data requires REMOVE-ALL-DATA confirmation.")
    database_path = Path(environment["CARTHAGE_POS_DB"])
    backup_path = Path(environment["POS_BACKUP_DIRECTORY"])
    if remove_data and not (backup_path / ".carthage-pos-backup-root").is_file():
        raise InstallationError("Backup data ownership cannot be verified; uninstall was cancelled.")
    record_deployment_event(str(install_dir), "uninstall_started", remove_data=remove_data)
    removed, preserved = [], []
    if remove_data:
        database_path.unlink(missing_ok=True)
        _remove_managed_backup_data(backup_path)
        removed.extend([str(database_path), str(backup_path)])
    else:
        preserved.extend([str(database_path), str(backup_path)])
    for path in (
        Path(state["configuration_file"]),
        Path(state["windows_integration_file"]),
        _state_path(install_dir),
    ):
        path.unlink(missing_ok=True)
        removed.append(str(path))
    log_event(logger, "uninstall_completed", remove_data=remove_data)
    return {"uninstalled": True, "removed": removed, "preserved": preserved,
            "remove_data": remove_data}


def get_deployment_state(installation_directory: str) -> dict:
    path = _state_path(Path(installation_directory).expanduser().resolve())
    if not path.is_file():
        return {"installed": False, "state_file": str(path)}
    return {"installed": True, **_read_json(path)}


def _initialize_fresh_database(request: SetupRequest, environment: dict[str, str]) -> dict:
    destination = Path(request.database_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.installing")
    setup_environment = {**environment, "CARTHAGE_POS_DB": str(temporary)}
    try:
        with _temporary_environment(setup_environment):
            initialize_database()
            with get_connection() as conn:
                conn.execute("UPDATE stores SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE code = 'MAIN'", (request.store_name,))
            bootstrap_admin(
                request.administrator_username, request.administrator_password,
                request.administrator_full_name,
            )
            _assert_database_integrity(temporary)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        Path(f"{temporary}-journal").unlink(missing_ok=True)
        raise
    return {"path": str(destination), "schema_version": _database_version(destination),
            "integrity": "ok"}


def _build_state(request, environment, config_path, windows_path, operation):
    now = datetime.now(timezone.utc).isoformat()
    return {
        "installed": True,
        "status": "READY",
        "application_version": APP_VERSION,
        "installer_version": INSTALLER_VERSION,
        "versions": VersionInfo().to_dict(),
        "installation_directory": request.installation_directory,
        "configuration_file": str(config_path),
        "windows_integration_file": str(windows_path),
        "environment": environment,
        "setup": request.safe_dict(),
        "last_operation": operation,
        "installed_at": now,
        "updated_at": now,
    }


def _prepare_directories(request):
    _prepare_runtime_directories(
        Path(request.installation_directory), Path(request.database_path),
        Path(request.backup_directory),
    )
    marker = Path(request.backup_directory) / ".carthage-pos-backup-root"
    if not marker.exists():
        marker.write_text("Managed by Carthage POS.\n", encoding="utf-8")


def _prepare_runtime_directories(install_dir, database_path, backup_path):
    for path in (install_dir, install_dir / "config", install_dir / "logs",
                 install_dir / "updates", install_dir / "rollback",
                 install_dir / "licenses", install_dir / "licenses" / "activation",
                 database_path.parent, backup_path):
        path.mkdir(parents=True, exist_ok=True)


def _load_installation(install_dir):
    state_path = _state_path(install_dir)
    if not state_path.is_file():
        raise InstallationError("Installed deployment state was not found.")
    state = _read_json(state_path)
    config_path = Path(state.get("configuration_file") or "")
    if not config_path.is_file():
        environment = state.get("environment") or {}
        if not environment:
            raise InstallationError("Installed configuration was not found.")
    else:
        environment = parse_environment_file(str(config_path))
    return state, environment


def _snapshot_database(database_path, rollback_dir, purpose):
    if not database_path.is_file():
        raise InstallationError("Installed database was not found.")
    rollback_dir.mkdir(parents=True, exist_ok=True)
    destination = rollback_dir / f"{purpose}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}.sqlite3"
    source = sqlite3.connect(database_path)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()
    return destination


def _restore_snapshot(snapshot, database_path):
    failed = database_path.with_name(f".{database_path.name}.failed-{uuid4().hex}")
    if database_path.exists():
        os.replace(database_path, failed)
    try:
        shutil.copy2(snapshot, database_path)
    except Exception:
        database_path.unlink(missing_ok=True)
        if failed.is_file():
            os.replace(failed, database_path)
        raise
    else:
        failed.unlink(missing_ok=True)


def _remove_managed_backup_data(backup_path):
    marker = backup_path / ".carthage-pos-backup-root"
    if not marker.is_file():
        raise InstallationError("Backup data was not removed because its ownership marker is missing.")
    patterns = (
        "BKP-*.metadata.json", "BKP-*.zip", "BKP-*.sqlite3",
        "backup-audit.jsonl", "scheduler.json", "imported-*.json",
    )
    for pattern in patterns:
        for path in backup_path.glob(pattern):
            if path.is_file():
                path.unlink()
    marker.unlink(missing_ok=True)
    try:
        backup_path.rmdir()
    except OSError:
        pass


def _assert_database_integrity(path):
    connection = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise InstallationError("Database integrity verification failed.")
    finally:
        connection.close()


def _database_version(path):
    connection = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])
    finally:
        connection.close()


def _state_path(install_dir):
    return install_dir / "config" / "deployment.json"


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallationError("Deployment state is unreadable or corrupted.") from exc


def _write_json_atomic(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise InstallationError("Deployment state could not be written safely.") from exc


@contextmanager
def _temporary_environment(values):
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update({key: str(value) for key, value in values.items()})
        reset_config_cache()
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_config_cache()
