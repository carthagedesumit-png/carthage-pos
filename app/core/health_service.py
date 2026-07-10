"""Operational health and readiness diagnostics."""

import sqlite3
from pathlib import Path

from app.core.configuration_validation import configuration_diagnostics
from app.core.version import DATABASE_SCHEMA_VERSION, VersionInfo
from app.database.db_manager import get_connection
from app.deployment.verification_service import get_current_deployment_status


REQUIRED_TABLES = {"users", "stores", "products", "sales", "sale_items", "api_sessions"}


def live_status() -> dict:
    return {"status": "ok", "service": "cbos", "versions": VersionInfo().to_dict()}


def readiness_status() -> dict:
    checks = []
    checks.extend(_database_checks())
    config = configuration_diagnostics()
    checks.append({
        "name": "configuration",
        "passed": config["valid"],
        "message": "Startup configuration is valid." if config["valid"] else config.get("error", ""),
        "details": config.get("checks", []),
    })
    checks.append(_deployment_check())
    ready = all(item["passed"] for item in checks)
    return {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "checks": checks,
        "versions": VersionInfo().to_dict(),
    }


def _database_checks() -> list[dict]:
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
            user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            tables = {
                row["name"]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }
            database_path = Path(conn.execute("PRAGMA database_list").fetchone()["file"])
    except (sqlite3.DatabaseError, OSError) as exc:
        return [_check("database_connectivity", False, "Database is unavailable.", type(exc).__name__)]
    return [
        _check("database_connectivity", True, "Database connection succeeded."),
        _check(
            "schema_compatibility",
            0 <= user_version <= DATABASE_SCHEMA_VERSION and REQUIRED_TABLES.issubset(tables),
            "Database schema is compatible.",
            details={
                "database_version": user_version,
                "required_tables_present": REQUIRED_TABLES.issubset(tables),
                "database_file": database_path.name,
            },
        ),
    ]


def _deployment_check() -> dict:
    try:
        status = get_current_deployment_status()
    except Exception as exc:
        return _check("deployment_status", False, "Deployment status is unavailable.", type(exc).__name__)
    installed = bool(status.get("installed"))
    healthy = bool(status.get("healthy"))
    return _check(
        "deployment_status",
        healthy or not installed,
        "Deployment verification completed." if installed else "Source/development deployment is active.",
        details={"installed": installed, "healthy": healthy},
    )


def _check(
    name: str,
    passed: bool,
    message: str,
    error_type: str | None = None,
    details: dict | list | None = None,
) -> dict:
    item = {"name": name, "passed": bool(passed), "message": message, "error_type": error_type}
    if details is not None:
        item["details"] = details
    return item
