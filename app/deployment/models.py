"""Validated setup workflow inputs."""

from dataclasses import asdict, dataclass, replace
from pathlib import Path
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.exceptions import InstallationError


@dataclass(frozen=True)
class SetupRequest:
    business_name: str
    store_name: str
    administrator_username: str
    administrator_password: str
    administrator_full_name: str
    installation_directory: str
    database_path: str
    backup_directory: str
    printer_preference: str = "none"
    currency: str = "USD"
    tax_rate: float = 0.0
    timezone: str = "UTC"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    log_level: str = "INFO"
    deployment_type: str = "desktop"
    create_desktop_shortcut: bool = True
    create_start_menu_shortcut: bool = True

    def validated(self) -> "SetupRequest":
        business_name = _required(self.business_name, "Business name")
        store_name = _required(self.store_name, "Store name")
        full_name = _required(self.administrator_full_name, "Administrator full name")
        username = str(self.administrator_username or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,49}", username):
            raise InstallationError("Administrator username must contain 3-50 safe characters.")
        password = str(self.administrator_password or "")
        if (len(password) < 12 or not re.search(r"[A-Z]", password)
                or not re.search(r"[a-z]", password) or not re.search(r"[0-9]", password)):
            raise InstallationError(
                "Administrator password must be at least 12 characters with upper, lower, and numeric characters."
            )
        install_dir = str(Path(_required(self.installation_directory, "Installation directory")).expanduser().resolve())
        database_path = str(Path(_required(self.database_path, "Database location")).expanduser().resolve())
        backup_dir = str(Path(_required(self.backup_directory, "Backup location")).expanduser().resolve())
        if Path(database_path).suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
            raise InstallationError("Database location must use .db, .sqlite, or .sqlite3.")
        printer = str(self.printer_preference or "none").strip().lower()
        if printer not in {"none", "58mm", "80mm", "generic"}:
            raise InstallationError("Printer preference must be none, 58mm, 80mm, or generic.")
        currency = str(self.currency or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise InstallationError("Currency must use a three-letter code.")
        try:
            tax_rate = float(self.tax_rate)
        except (TypeError, ValueError) as exc:
            raise InstallationError("Tax rate must be numeric.") from exc
        if not 0 <= tax_rate <= 1:
            raise InstallationError("Tax rate must be between 0 and 1.")
        timezone = str(self.timezone or "").strip()
        if timezone.upper() not in {"UTC", "GMT"}:
            if not re.fullmatch(r"[A-Za-z_+-]+(?:/[A-Za-z0-9_+.-]+)+", timezone):
                raise InstallationError("Timezone must be UTC or a safe IANA timezone name.")
            try:
                ZoneInfo(timezone)
            except ZoneInfoNotFoundError:
                # Packaged Windows runtimes may not include the optional IANA database.
                pass
            except ValueError as exc:
                raise InstallationError("Timezone is invalid.") from exc
        if not isinstance(self.api_port, int) or not 1 <= self.api_port <= 65535:
            raise InstallationError("API port must be between 1 and 65535.")
        log_level = str(self.log_level or "INFO").strip().upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise InstallationError("Logging level is invalid.")
        deployment_type = str(self.deployment_type or "desktop").strip().lower()
        if deployment_type not in {"desktop", "standalone", "network"}:
            raise InstallationError("Deployment type must be desktop, standalone, or network.")
        return replace(
            self, business_name=business_name, store_name=store_name,
            administrator_username=username, administrator_full_name=full_name,
            installation_directory=install_dir, database_path=database_path,
            backup_directory=backup_dir, printer_preference=printer,
            currency=currency, tax_rate=tax_rate, timezone=timezone,
            api_host=_required(self.api_host, "API host"), log_level=log_level,
            deployment_type=deployment_type,
        )

    def safe_dict(self) -> dict:
        values = asdict(self)
        values.pop("administrator_password", None)
        return values


def _required(value, label):
    text = str(value or "").strip()
    if not text:
        raise InstallationError(f"{label} is required.")
    if "\n" in text or "\r" in text:
        raise InstallationError(f"{label} cannot contain line breaks.")
    return text
