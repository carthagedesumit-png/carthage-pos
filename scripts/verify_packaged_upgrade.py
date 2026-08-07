"""Isolated acceptance for the exact self-contained installer preflight verifier."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.deployment.installer_service import fresh_install
from app.deployment.models import SetupRequest


def main():
    verifier = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory() as root_name:
        root = Path(root_name)
        runtime = root / "ProgramData" / "Carthage POS"
        install = root / "Program Files" / "CBOS"
        database = runtime / "data" / "carthage-pos.db"
        password = "Packaged-Upgrade-Only9!"
        old_programdata = os.environ.get("PROGRAMDATA")
        try:
            os.environ["PROGRAMDATA"] = str(root / "ProgramData")
            fresh_install(SetupRequest(
                business_name="Packaged Upgrade Acceptance", store_name="Main Store",
                administrator_username="admin", administrator_password=password,
                administrator_full_name="Acceptance Administrator",
                installation_directory=str(install), configuration_directory=str(runtime / "config"),
                database_path=str(database), backup_directory=str(runtime / "backups"),
                currency="USD", tax_rate=0, timezone="UTC", deployment_type="desktop",
                printer_preference="none",
            ))
            password_file = root / "credential.once"
            password_file.write_text(password, encoding="utf-8")
            environment = dict(os.environ)
            completed = subprocess.run([
                str(verifier), "verify-upgrade-credentials", "--install-dir", str(install),
                "--username", "admin", "--password-file", str(password_file),
            ], env=environment, capture_output=True, text=True, timeout=60)
            result = json.loads(completed.stdout)
            stat = database.stat()
            assert completed.returncode == 0
            assert result["status"] == "ok"
            assert result["database_identity"] == f"{stat.st_dev}:{stat.st_ino}"
            assert not password_file.exists()
        finally:
            if old_programdata is None:
                os.environ.pop("PROGRAMDATA", None)
            else:
                os.environ["PROGRAMDATA"] = old_programdata
    print("Packaged upgrade verifier acceptance passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
