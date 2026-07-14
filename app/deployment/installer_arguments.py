"""Pure helpers for the Inno Setup silent-install parameter contract."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path

from app.core.exceptions import InstallationError


SILENT_INSTALLER_PARAMETERS = {
    "CBOSBusiness": ("business_name", "--business-name", "Business name"),
    "CBOSStore": ("store_name", "--store-name", "Store name"),
    "CBOSAdminUser": ("administrator_username", "--admin-username", "Administrator username"),
    "CBOSAdminPasswordFile": ("administrator_password", None, "Administrator password file"),
    "CBOSAdminFullName": ("administrator_full_name", "--admin-full-name", "Administrator full name"),
    "CBOSCurrency": ("currency", "--currency", "Currency"),
    "CBOSTaxRate": ("tax_rate", "--tax-rate", "Tax rate"),
    "CBOSTimezone": ("timezone", "--timezone", "Timezone"),
    "CBOSDeploymentType": ("deployment_type", "--deployment-type", "Deployment type"),
    "CBOSPrinter": ("printer_preference", "--receipt-printer", "Receipt printer"),
}


def validate_silent_installer_values(values: Mapping[str, object]) -> dict[str, str]:
    """Return trimmed values or fail with labels safe to show in installer output."""
    normalized = {name: str(values.get(name, "")).strip() for name in SILENT_INSTALLER_PARAMETERS}
    missing = [
        label
        for name, (_, _, label) in SILENT_INSTALLER_PARAMETERS.items()
        if not normalized[name]
    ]
    if missing:
        raise InstallationError(
            "Silent installation is missing required values: " + ", ".join(missing)
        )
    return normalized


def build_deployment_cli_arguments(
    values: Mapping[str, object],
    *,
    install_dir: str | Path,
    runtime_root: str | Path,
    password_file: str | Path,
) -> list[str]:
    """Map validated installer values to the noninteractive deployment CLI."""
    normalized = validate_silent_installer_values(values)
    runtime = Path(runtime_root)
    arguments = [
        "configure",
        "--install-dir", str(install_dir),
    ]
    for parameter, (_, option, _) in SILENT_INSTALLER_PARAMETERS.items():
        if option:
            arguments.extend((option, normalized[parameter]))
        elif parameter == "CBOSAdminPasswordFile":
            arguments.extend(("--admin-password-file", str(password_file)))
    arguments.extend((
        "--config-dir", str(runtime / "config"),
        "--database-path", str(runtime / "data" / "carthage-pos.db"),
        "--backup-path", str(runtime / "backups"),
    ))
    return arguments


def quote_deployment_cli_arguments(arguments: list[str]) -> str:
    """Render arguments with Windows command-line quoting."""
    return subprocess.list2cmdline(arguments)


def redacted_deployment_cli_arguments(arguments: list[str]) -> list[str]:
    """Return a log-safe representation of a deployment invocation."""
    redacted = list(arguments)
    for secret_option in ("--admin-password", "--admin-password-file"):
        if secret_option in redacted:
            index = redacted.index(secret_option)
            if index + 1 < len(redacted):
                redacted[index + 1] = "<redacted>"
    return redacted
