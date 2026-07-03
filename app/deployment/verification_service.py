"""Deployment health and installation verification."""

import os
import sqlite3
import tempfile
from pathlib import Path

from app.core.config import get_config, parse_environment_file
from app.core.version import VersionInfo, compatibility_report
from app.deployment.installer_service import get_deployment_state
from app.hardware.profiles import get_printer_profile


def verify_installation(installation_directory: str) -> dict:
    """Verify configuration, storage, database, backup, logging, and hardware defaults."""
    install_dir = Path(installation_directory).expanduser().resolve()
    state = get_deployment_state(str(install_dir))
    checks = []
    if not state.get("installed"):
        return {"healthy": False, "installed": False, "checks": [
            _check("deployment_state", False, "Deployment state was not found.")
        ], "versions": VersionInfo().to_dict()}
    config_path = Path(state.get("configuration_file", ""))
    try:
        environment = parse_environment_file(str(config_path))
        required_keys = {
            "CARTHAGE_POS_DB", "POS_BACKUP_DIRECTORY", "POS_LOG_DIRECTORY",
            "POS_PRINTER_ENABLED", "POS_PRINTER_PROFILE",
        }
        missing = required_keys - environment.keys()
        if missing:
            raise ValueError(f"Missing required settings: {', '.join(sorted(missing))}")
        checks.append(_check("configuration", True, "Configuration is readable."))
    except Exception as exc:
        return {"healthy": False, "installed": True, "checks": [
            _check("configuration", False, "Configuration is unreadable.", type(exc).__name__)
        ], "versions": VersionInfo().to_dict()}

    required = {
        "installation_directory": install_dir,
        "database_directory": Path(environment["CARTHAGE_POS_DB"]).parent,
        "backup_directory": Path(environment["POS_BACKUP_DIRECTORY"]),
        "log_directory": Path(environment["POS_LOG_DIRECTORY"]),
        "update_directory": install_dir / "updates",
    }
    for name, path in required.items():
        checks.append(_directory_check(name, path))

    database_path = Path(environment["CARTHAGE_POS_DB"])
    checks.extend(_database_checks(database_path))
    printer_enabled = environment.get("POS_PRINTER_ENABLED", "false").lower() == "true"
    try:
        profile = get_printer_profile(environment.get("POS_PRINTER_PROFILE", "80mm"))
        message = f"Printer profile {profile.name} is valid."
        if printer_enabled:
            message += " Device availability is checked at runtime."
        checks.append(_check("hardware_configuration", True, message, warning=printer_enabled))
    except Exception as exc:
        checks.append(_check("hardware_configuration", False, "Printer profile is invalid.",
                             type(exc).__name__))
    database_version = next(
        (item.get("value") for item in checks if item["name"] == "database_version" and item["passed"]),
        -1,
    )
    compatibility = compatibility_report(
        application_version=state.get("application_version", "0.0.0"),
        database_version=database_version,
        installer_version=state.get("installer_version", "0.0.0"),
    )
    checks.append(_check("compatibility", compatibility["compatible"],
                         "Installed versions are compatible." if compatibility["compatible"]
                         else "Installed versions are not compatible."))
    healthy = all(item["passed"] for item in checks)
    return {
        "healthy": healthy,
        "installed": True,
        "checks": checks,
        "compatibility": compatibility,
        "versions": VersionInfo().to_dict(),
        "deployment_type": (state.get("setup") or {}).get("deployment_type", "desktop"),
    }


def get_current_deployment_status() -> dict:
    return verify_installation(get_config().deployment.installation_directory)


def get_installer_information() -> dict:
    return {
        "name": "Carthage POS Windows Installer",
        "versions": VersionInfo().to_dict(),
        "supported_operations": ["FRESH", "UPGRADE", "REPAIR", "UNINSTALL"],
        "deployment_targets": ["desktop", "standalone", "network-foundation"],
        "windows_integration": [
            "desktop shortcut", "Start Menu shortcut", "application icon",
            "uninstall registry entry", "version metadata",
        ],
        "packaging": {"application": "PyInstaller", "installer": "Inno Setup"},
        "live_internet_updates": False,
    }


def _database_checks(path):
    if not path.is_file():
        return [_check("database_connectivity", False, "Database file is missing.")]
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            admin_count = int(connection.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
            ).fetchone()[0])
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        return [_check("database_connectivity", False, "Database is unreadable.", type(exc).__name__)]
    return [
        _check("database_connectivity", True, "Database is readable."),
        _check("database_integrity", integrity == "ok",
               "Database integrity is valid." if integrity == "ok" else "Database integrity failed."),
        {**_check("database_version", version >= 0, "Database version is readable."), "value": version},
        _check("administrator_account", admin_count > 0,
               "An active administrator account exists." if admin_count else "No active administrator exists."),
    ]


def _directory_check(name, path):
    if not path.is_dir():
        return _check(name, False, f"Required directory is missing: {path}")
    try:
        handle, probe = tempfile.mkstemp(prefix=".carthage-write-test-", dir=path)
        os.close(handle)
        Path(probe).unlink(missing_ok=True)
    except OSError as exc:
        return _check(name, False, f"Directory is not writable: {path}", type(exc).__name__)
    return _check(name, True, f"Directory exists and is writable: {path}")


def _check(name, passed, message, error_type=None, warning=False):
    return {"name": name, "passed": bool(passed), "message": message,
            "error_type": error_type, "warning": bool(warning)}
