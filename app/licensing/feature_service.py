"""Central feature and resource-limit enforcement."""

from app.core.config import get_config
from app.core.exceptions import LicenseFeatureError
from app.licensing.editions import ALL_FEATURES, get_edition
from app.licensing.license_service import get_license_status
from app.licensing.storage import append_audit


def enabled_features(status: dict | None = None) -> list[str]:
    status = status or get_license_status()
    return sorted(get_edition(status["edition"]).features)


def require_feature(feature: str, *, status: dict | None = None) -> bool:
    feature = str(feature or "").strip().upper()
    if feature not in ALL_FEATURES:
        raise LicenseFeatureError("Unknown licensed feature.")
    if status is None and not get_config().licensing.enforcement_enabled:
        return True
    status = status or get_license_status()
    if feature not in get_edition(status["edition"]).features:
        append_audit("feature_restricted", feature=feature, edition=status["edition"])
        raise LicenseFeatureError(
            f"Feature {feature} is not available in the {status['edition']} edition."
        )
    return True


def require_write_access(*, status: dict | None = None) -> bool:
    if status is None and not get_config().licensing.enforcement_enabled:
        return True
    status = status or get_license_status()
    if status["read_only"]:
        append_audit("write_restricted", state=status["state"], edition=status["edition"])
        raise LicenseFeatureError("The license is in read-only mode.")
    return True


def enforce_resource_limit(resource: str, current_count: int,
                           *, status: dict | None = None) -> bool:
    if status is None and not get_config().licensing.enforcement_enabled:
        return True
    status = status or get_license_status()
    definition = get_edition(status["edition"])
    if resource not in {"stores", "users"}:
        raise LicenseFeatureError("Unknown licensed resource limit.")
    limit = {
        "stores": definition.maximum_stores,
        "users": definition.maximum_users,
    }[resource]
    if limit is not None and int(current_count) >= limit:
        append_audit("resource_limit_reached", resource=resource,
                     edition=definition.name, limit=limit)
        raise LicenseFeatureError(
            f"The {definition.name} edition permits at most {limit} {resource}."
        )
    return True
