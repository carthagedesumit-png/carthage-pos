"""Offline-first update manifest, staging, verification, and rollback foundation."""

import hashlib
import json
import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.core.config import get_config
from app.core.exceptions import UpdateError
from app.core.version import (
    APP_VERSION, DATABASE_SCHEMA_VERSION, INSTALLER_VERSION,
    compare_versions, compatibility_report, parse_version,
)
from app.deployment.audit import record_deployment_event


VALID_CHANNELS = {"stable", "beta", "pilot", "rc", "development"}


@dataclass(frozen=True)
class UpdateManifest:
    version: str
    channel: str
    package_filename: str
    sha256: str
    package_size: int
    minimum_database_version: int = 0
    maximum_database_version: int = DATABASE_SCHEMA_VERSION
    minimum_installer_version: str = INSTALLER_VERSION
    published_at: str | None = None
    release_notes: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "UpdateManifest":
        try:
            manifest = cls(
                version=str(data["version"]), channel=str(data["channel"]).lower(),
                package_filename=str(data["package_filename"]),
                sha256=str(data["sha256"]).lower(), package_size=int(data["package_size"]),
                minimum_database_version=int(data.get("minimum_database_version", 0)),
                maximum_database_version=int(data.get("maximum_database_version", DATABASE_SCHEMA_VERSION)),
                minimum_installer_version=str(data.get("minimum_installer_version", INSTALLER_VERSION)),
                published_at=data.get("published_at"),
                release_notes=str(data.get("release_notes", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise UpdateError("Update manifest is missing required fields.") from exc
        manifest.validate()
        return manifest

    def validate(self) -> None:
        try:
            parse_version(self.version)
            parse_version(self.minimum_installer_version)
        except ValueError as exc:
            raise UpdateError("Update manifest contains an invalid semantic version.") from exc
        if self.channel not in VALID_CHANNELS:
            raise UpdateError("Update channel is invalid.")
        if Path(self.package_filename).name != self.package_filename or not self.package_filename:
            raise UpdateError("Update package filename is invalid.")
        if len(self.sha256) != 64 or any(char not in "0123456789abcdef" for char in self.sha256):
            raise UpdateError("Update package checksum must be SHA-256.")
        if self.package_size <= 0:
            raise UpdateError("Update package size must be positive.")
        if self.minimum_database_version > self.maximum_database_version:
            raise UpdateError("Update database version range is invalid.")

    def to_dict(self) -> dict:
        return asdict(self)


class DownloadAdapter(ABC):
    @abstractmethod
    def fetch(self, manifest: UpdateManifest, destination: Path) -> None:
        """Copy or download a package to destination."""


class LocalFileDownloadAdapter(DownloadAdapter):
    def __init__(self, source_directory: str):
        self.source_directory = Path(source_directory).resolve()

    def fetch(self, manifest: UpdateManifest, destination: Path) -> None:
        source = self.source_directory / manifest.package_filename
        if not source.is_file():
            raise UpdateError("Update package is unavailable from the local source.")
        shutil.copy2(source, destination)


class UnavailableDownloadAdapter(DownloadAdapter):
    def fetch(self, manifest: UpdateManifest, destination: Path) -> None:
        raise UpdateError("Live update downloads are not enabled in this release.")


def parse_update_manifest(source: str | dict) -> UpdateManifest:
    if isinstance(source, dict):
        return UpdateManifest.from_dict(source)
    try:
        text = Path(source).read_text(encoding="utf-8") if Path(source).is_file() else source
        data = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateError("Update manifest is unreadable or malformed.") from exc
    if not isinstance(data, dict):
        raise UpdateError("Update manifest must be a JSON object.")
    return UpdateManifest.from_dict(data)


def check_for_update(manifest: UpdateManifest, *, current_version: str = APP_VERSION,
                     channel: str | None = None,
                     database_version: int = DATABASE_SCHEMA_VERSION,
                     installation_directory: str | None = None) -> dict:
    manifest.validate()
    channel = (channel or get_config().updates.channel).lower()
    if channel not in VALID_CHANNELS:
        raise UpdateError("Configured update channel is invalid.")
    allowed = {
        "stable": {"stable"},
        "beta": {"stable", "beta"},
        "development": VALID_CHANNELS,
    }[channel]
    channel_ok = manifest.channel in allowed
    version_newer = compare_versions(manifest.version, current_version) > 0
    database_ok = manifest.minimum_database_version <= database_version <= manifest.maximum_database_version
    installer_ok = compare_versions(INSTALLER_VERSION, manifest.minimum_installer_version) >= 0
    compatibility = compatibility_report(
        application_version=current_version, database_version=database_version,
        installer_version=INSTALLER_VERSION,
    )
    result = {
        "update_available": version_newer and channel_ok and database_ok and installer_ok
                            and compatibility["compatible"],
        "current_version": current_version,
        "candidate_version": manifest.version,
        "channel": channel,
        "manifest_channel": manifest.channel,
        "checks": {
            "version_newer": version_newer,
            "channel_allowed": channel_ok,
            "database_compatible": database_ok,
            "installer_compatible": installer_ok,
            "platform_compatible": compatibility["compatible"],
        },
    }
    if installation_directory:
        record_deployment_event(
            installation_directory, "update_checked",
            current_version=current_version, candidate_version=manifest.version,
            update_available=result["update_available"], channel=channel,
        )
    return result


def stage_update(manifest: UpdateManifest, adapter: DownloadAdapter,
                 installation_directory: str) -> dict:
    """Stage and verify an update package without executing it."""
    install_dir = Path(installation_directory).resolve()
    status = check_for_update(manifest, installation_directory=str(install_dir))
    if not status["update_available"]:
        raise UpdateError("Update is not applicable to this installation.")
    staging_dir = install_dir / "updates" / "staging" / manifest.version
    staging_dir.mkdir(parents=True, exist_ok=True)
    destination = staging_dir / manifest.package_filename
    temporary = staging_dir / f".{manifest.package_filename}.{uuid4().hex}.tmp"
    try:
        adapter.fetch(manifest, temporary)
        if temporary.stat().st_size != manifest.package_size:
            raise UpdateError("Staged update size does not match the manifest.")
        if _checksum(temporary) != manifest.sha256:
            raise UpdateError("Staged update checksum does not match the manifest.")
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    update_state = {
        "status": "STAGED",
        "staged_at": datetime.now(timezone.utc).isoformat(),
        "current_version": APP_VERSION,
        "target_version": manifest.version,
        "package": str(destination),
        "manifest": manifest.to_dict(),
        "rollback": {
            "strategy": "RETAIN_CURRENT_INSTALLATION_AND_DATABASE_BACKUP",
            "application_version": APP_VERSION,
            "prepared": True,
        },
    }
    _write_update_state(install_dir, update_state)
    record_deployment_event(str(install_dir), "update_staged",
                            target_version=manifest.version, channel=manifest.channel)
    return update_state


def get_update_status(installation_directory: str | None = None) -> dict:
    install_dir = Path(installation_directory or get_config().deployment.installation_directory).resolve()
    state_path = install_dir / "updates" / "update-state.json"
    if not state_path.is_file():
        return {"status": "IDLE", "current_version": APP_VERSION,
                "channel": get_config().updates.channel, "live_download_enabled": False}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateError("Update state is unreadable or corrupted.") from exc


def _write_update_state(install_dir, payload):
    destination = install_dir / "updates" / "update-state.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, destination)


def _checksum(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
