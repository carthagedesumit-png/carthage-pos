"""Central product edition and feature registry."""

from dataclasses import asdict, dataclass

from app.core.exceptions import LicenseError


COMMUNITY = "COMMUNITY"
PROFESSIONAL = "PROFESSIONAL"
ENTERPRISE = "ENTERPRISE"
DEVELOPER = "DEVELOPER"
VALID_EDITIONS = {COMMUNITY, PROFESSIONAL, ENTERPRISE, DEVELOPER}

CORE_POS = "CORE_POS"
MULTI_STORE = "MULTI_STORE"
API_ACCESS = "API"
CRM = "CRM"
PROCUREMENT = "PROCUREMENT"
HARDWARE = "HARDWARE"
BACKUP = "BACKUP"
BARCODE = "BARCODE"
DOCUMENTS = "DOCUMENTS"
REPORTING = "REPORTING"
TRANSFERS = "TRANSFERS"
CLOUD_SYNC = "CLOUD_SYNC"
DEVELOPMENT_TOOLS = "DEVELOPMENT_TOOLS"

ALL_FEATURES = {
    CORE_POS, MULTI_STORE, API_ACCESS, CRM, PROCUREMENT, HARDWARE, BACKUP,
    BARCODE, DOCUMENTS, REPORTING, TRANSFERS, CLOUD_SYNC, DEVELOPMENT_TOOLS,
}


@dataclass(frozen=True)
class EditionDefinition:
    name: str
    features: frozenset[str]
    maximum_stores: int | None
    maximum_users: int | None
    development_only: bool = False

    def to_dict(self) -> dict:
        result = asdict(self)
        result["features"] = sorted(self.features)
        return result


EDITIONS = {
    COMMUNITY: EditionDefinition(
        COMMUNITY, frozenset({CORE_POS, REPORTING}), 1, 3,
    ),
    PROFESSIONAL: EditionDefinition(
        PROFESSIONAL,
        frozenset({CORE_POS, MULTI_STORE, API_ACCESS, CRM, HARDWARE, BACKUP,
                   BARCODE, DOCUMENTS, REPORTING, TRANSFERS}),
        10, 50,
    ),
    ENTERPRISE: EditionDefinition(
        ENTERPRISE, frozenset(ALL_FEATURES - {DEVELOPMENT_TOOLS}), None, None,
    ),
    DEVELOPER: EditionDefinition(
        DEVELOPER, frozenset(ALL_FEATURES), None, None, development_only=True,
    ),
}


def get_edition(edition: str) -> EditionDefinition:
    normalized = str(edition or "").strip().upper()
    if normalized not in EDITIONS:
        raise LicenseError("Unknown product edition.")
    return EDITIONS[normalized]


def list_editions() -> list[dict]:
    return [definition.to_dict() for definition in EDITIONS.values()]
