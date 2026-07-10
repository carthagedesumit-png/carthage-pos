"""Auditable release checklist validation."""


REQUIRED_RELEASE_CHECKS = (
    "code_and_tests",
    "security_configuration",
    "database_migrations",
    "backup_and_restore",
    "installer_build",
    "clean_install",
    "upgrade_install",
    "rollback",
    "documentation",
    "licensing_readiness",
    "known_issues",
    "release_notes",
    "pilot_approval",
    "final_signoff",
)


VALID_STATUSES = {"pending", "passed", "failed", "waived"}


def validate_release_checklist(checklist: dict) -> dict:
    items = checklist.get("checks") if isinstance(checklist, dict) else None
    if not isinstance(items, dict):
        return {"valid": False, "missing": list(REQUIRED_RELEASE_CHECKS), "invalid": []}
    missing = [name for name in REQUIRED_RELEASE_CHECKS if name not in items]
    invalid = [
        {"name": name, "status": value.get("status") if isinstance(value, dict) else None}
        for name, value in items.items()
        if name in REQUIRED_RELEASE_CHECKS
        and (not isinstance(value, dict) or value.get("status") not in VALID_STATUSES)
    ]
    blocking = [
        name
        for name in REQUIRED_RELEASE_CHECKS
        if isinstance(items.get(name), dict) and items[name].get("status") in {"pending", "failed"}
    ]
    return {
        "valid": not missing and not invalid,
        "release_ready": not missing and not invalid and not blocking,
        "missing": missing,
        "invalid": invalid,
        "blocking": blocking,
    }
