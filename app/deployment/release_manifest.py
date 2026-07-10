"""Machine-readable release metadata for deployment verification."""

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_config
from app.core.version import (
    APP_VERSION,
    DATABASE_SCHEMA_VERSION,
    INSTALLER_VERSION,
    MIN_SUPPORTED_DATABASE_VERSION,
    VersionInfo,
    compatibility_report,
)


DEFAULT_RELEASE_CHANNEL = "rc"


def build_release_manifest(
    *,
    channel: str | None = None,
    build_timestamp: str | None = None,
    source_commit: str | None = None,
    package_paths: list[str | Path] | None = None,
) -> dict:
    channel = _release_channel(channel)
    timestamp = build_timestamp or datetime.now(timezone.utc).isoformat()
    commit = source_commit or _source_commit()
    packages = [_package_metadata(Path(path)) for path in package_paths or []]
    return {
        "format_version": 1,
        "product": "Carthage Business Operating System",
        "application_version": APP_VERSION,
        "release_channel": channel,
        "build_timestamp": timestamp,
        "source_commit": commit,
        "versions": VersionInfo().to_dict(),
        "database": {
            "schema_version": DATABASE_SCHEMA_VERSION,
            "minimum_supported_schema_version": MIN_SUPPORTED_DATABASE_VERSION,
            "supported_upgrade_path": {
                "minimum_schema_version": MIN_SUPPORTED_DATABASE_VERSION,
                "maximum_schema_version": DATABASE_SCHEMA_VERSION,
                "target_schema_version": DATABASE_SCHEMA_VERSION,
            },
        },
        "installer": {
            "version": INSTALLER_VERSION,
            "package_checksums": packages,
        },
        "compatibility": compatibility_report(),
    }


def write_release_manifest(path: str | Path, **kwargs) -> dict:
    manifest = build_release_manifest(**kwargs)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def load_release_manifest(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_release_manifest(manifest: dict) -> dict:
    checks = [
        _check("application_version", manifest.get("application_version") == APP_VERSION),
        _check("installer_version", (manifest.get("installer") or {}).get("version") == INSTALLER_VERSION),
        _check(
            "schema_version",
            ((manifest.get("database") or {}).get("schema_version") == DATABASE_SCHEMA_VERSION),
        ),
        _check("compatibility", bool((manifest.get("compatibility") or {}).get("compatible"))),
    ]
    return {"valid": all(item["passed"] for item in checks), "checks": checks}


def default_manifest_path() -> Path:
    return Path(get_config().updates.manifest_path).with_name("release-manifest.json")


def _release_channel(value: str | None) -> str:
    channel = (value or os.environ.get("CBOS_RELEASE_CHANNEL") or DEFAULT_RELEASE_CHANNEL).strip().lower()
    if channel not in {"stable", "beta", "pilot", "rc", "development"}:
        raise ValueError("Release channel must be stable, beta, pilot, rc, or development.")
    return channel


def _source_commit() -> str | None:
    env_commit = os.environ.get("CBOS_SOURCE_COMMIT") or os.environ.get("GIT_COMMIT")
    if env_commit:
        return env_commit.strip() or None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[2],
        )
    except Exception:
        return None
    return result.stdout.strip() or None


def _package_metadata(path: Path) -> dict:
    if not path.is_file():
        return {"filename": path.name, "exists": False, "sha256": None, "size": 0}
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "filename": path.name,
        "exists": True,
        "sha256": digest.hexdigest(),
        "size": path.stat().st_size,
    }


def _check(name: str, passed: bool) -> dict:
    return {"name": name, "passed": bool(passed)}
