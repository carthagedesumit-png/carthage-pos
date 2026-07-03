"""Central version and compatibility contracts."""

from dataclasses import asdict, dataclass
import re


APP_VERSION = "1.0.0"
DATABASE_SCHEMA_VERSION = 1
MIGRATION_VERSION = 1
API_VERSION = "1.0"
INSTALLER_VERSION = "1.0.0"
MIN_SUPPORTED_DATABASE_VERSION = 0


@dataclass(frozen=True)
class VersionInfo:
    application_version: str = APP_VERSION
    database_version: int = DATABASE_SCHEMA_VERSION
    migration_version: int = MIGRATION_VERSION
    api_version: str = API_VERSION
    installer_version: str = INSTALLER_VERSION

    def to_dict(self) -> dict:
        return asdict(self)


def parse_version(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", str(value or ""))
    if not match:
        raise ValueError("Version must use semantic MAJOR.MINOR.PATCH format.")
    return tuple(int(part) for part in match.groups())


def compare_versions(left: str, right: str) -> int:
    left_parts, right_parts = parse_version(left), parse_version(right)
    return (left_parts > right_parts) - (left_parts < right_parts)


def compatibility_report(application_version: str = APP_VERSION,
                         database_version: int = DATABASE_SCHEMA_VERSION,
                         installer_version: str = INSTALLER_VERSION) -> dict:
    app = parse_version(application_version)
    installer = parse_version(installer_version)
    database_ok = MIN_SUPPORTED_DATABASE_VERSION <= int(database_version) <= DATABASE_SCHEMA_VERSION
    installer_ok = installer[0] == parse_version(APP_VERSION)[0]
    application_ok = app[0] == parse_version(APP_VERSION)[0]
    return {
        "compatible": database_ok and installer_ok and application_ok,
        "application_compatible": application_ok,
        "database_compatible": database_ok,
        "installer_compatible": installer_ok,
        "supported_database_range": [MIN_SUPPORTED_DATABASE_VERSION, DATABASE_SCHEMA_VERSION],
        "current": VersionInfo().to_dict(),
        "candidate": {
            "application_version": application_version,
            "database_version": int(database_version),
            "installer_version": installer_version,
        },
    }
