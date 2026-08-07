"""Startup configuration diagnostics for production operation."""

import os
import tempfile
from pathlib import Path

from app.core.config import get_config
from app.core.exceptions import ConfigurationError
from app.database.db_manager import get_database_path


def validate_startup_configuration(*, strict: bool | None = None) -> dict:
    config = get_config()
    strict = _strict_validation_enabled(config) if strict is None else strict
    checks = [
        _directory_check("database_directory", Path(get_database_path()).expanduser().resolve().parent),
        _directory_check("backup_directory", Path(config.backup.directory).expanduser().resolve(), create=True, strict=strict),
        _directory_check("log_directory", Path(config.deployment.log_directory).expanduser().resolve(), create=True, strict=strict),
        _directory_check("installation_directory", Path(config.deployment.installation_directory).expanduser().resolve(), strict=strict),
        _parent_check("deployment_state_file", Path(config.deployment.state_file).expanduser().resolve(), strict=strict),
        _parent_check("update_manifest", Path(config.updates.manifest_path).expanduser().resolve(), strict=strict),
        _directory_check("license_directory", Path(config.licensing.directory).expanduser().resolve(), create=True, strict=strict),
        _directory_check(
            "activation_directory",
            Path(config.licensing.activation_directory).expanduser().resolve(),
            create=True,
            strict=strict,
        ),
    ]
    failed = [item for item in checks if not item["passed"]]
    result = {"valid": not failed, "checks": checks}
    if failed:
        names = ", ".join(item["name"] for item in failed)
        raise ConfigurationError(f"Startup configuration is invalid: {names}.")
    return result


def configuration_diagnostics() -> dict:
    try:
        return validate_startup_configuration()
    except ConfigurationError as exc:
        return {"valid": False, "error": str(exc), "checks": getattr(exc, "checks", [])}


def _strict_validation_enabled(config) -> bool:
    return os.environ.get("POS_STRICT_STARTUP_VALIDATION", "").strip().lower() in {"1", "true", "yes", "on"}


def _parent_check(name: str, path: Path, *, strict: bool = True) -> dict:
    return _directory_check(name, path.parent, strict=strict)


def _directory_check(name: str, path: Path, *, create: bool = False, strict: bool = True) -> dict:
    try:
        if create:
            path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            return _check(name, not strict, f"Directory is missing: {path}", warning=not strict)
        handle, probe = tempfile.mkstemp(prefix=".cbos-write-", dir=path)
        os.close(handle)
        Path(probe).unlink(missing_ok=True)
    except OSError as exc:
        return _check(name, not strict, f"Directory is not writable: {path}", type(exc).__name__, warning=not strict)
    return _check(name, True, "Directory exists and is writable.")


def _check(
    name: str,
    passed: bool,
    message: str,
    error_type: str | None = None,
    *,
    warning: bool = False,
) -> dict:
    return {
        "name": name,
        "passed": bool(passed),
        "message": message,
        "error_type": error_type,
        "warning": bool(warning),
    }
