"""Interactive first-run setup workflow for non-technical operators."""

import getpass
import os
from pathlib import Path

from app.deployment.models import SetupRequest


class SetupWizard:
    def __init__(self, input_func=input, password_func=getpass.getpass):
        self.input = input_func
        self.password = password_func

    def collect(self) -> SetupRequest:
        program_data = Path(os.environ.get("PROGRAMDATA", Path.home() / "AppData" / "Local"))
        program_files = Path(os.environ.get("PROGRAMFILES", program_data))
        install_dir = self._ask("Installation directory", str(program_files / "Carthage POS"))
        data_dir = program_data / "Carthage POS"
        request = SetupRequest(
            business_name=self._ask("Business name"),
            store_name=self._ask("Store name", "Main Store"),
            administrator_username=self._ask("Administrator username", "admin"),
            administrator_password=self.password("Administrator password: "),
            administrator_full_name=self._ask("Administrator full name"),
            installation_directory=install_dir,
            database_path=self._ask("Database location", str(data_dir / "data" / "carthage-pos.db")),
            backup_directory=self._ask("Backup location", str(data_dir / "backups")),
            printer_preference=self._ask("Receipt printer (none/58mm/80mm/generic)", "none"),
            currency=self._ask("Currency code", "USD"),
            tax_rate=float(self._ask("Tax rate as decimal", "0")),
            timezone=self._ask("Timezone", "UTC"),
            deployment_type=self._ask("Deployment type (desktop/standalone/network)", "desktop"),
        )
        return request.validated()

    def _ask(self, label, default=None):
        suffix = f" [{default}]" if default is not None else ""
        value = self.input(f"{label}{suffix}: ").strip()
        return value or default or ""
