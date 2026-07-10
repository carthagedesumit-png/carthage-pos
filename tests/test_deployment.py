import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bcrypt
from fastapi.testclient import TestClient


class DeploymentPlatformTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.install_dir = self.root / "Carthage POS"
        self.database_path = self.root / "data" / "carthage-pos.db"
        self.backup_dir = self.root / "backups"

        from app.deployment.models import SetupRequest
        self.request = SetupRequest(
            business_name="Deployment Test Store",
            store_name="Main Test Branch",
            administrator_username="owner.admin",
            administrator_password="StrongAdmin123",
            administrator_full_name="Business Owner",
            installation_directory=str(self.install_dir),
            database_path=str(self.database_path),
            backup_directory=str(self.backup_dir),
            printer_preference="80mm",
            currency="USD",
            tax_rate=0.075,
            timezone="UTC",
        )

    def tearDown(self):
        from app.core.config import reset_config_cache
        for key in tuple(os.environ):
            if key.startswith("POS_") or key.startswith("CARTHAGE_POS_"):
                os.environ.pop(key, None)
        reset_config_cache()
        self.temp_dir.cleanup()

    def install(self):
        from app.deployment.installer_service import fresh_install
        with patch("auth.bcrypt.gensalt", return_value=bcrypt.gensalt(rounds=4)):
            return fresh_install(self.request)

    def test_fresh_install_generates_configuration_database_admin_and_integration(self):
        state = self.install()
        self.assertEqual(state["status"], "READY")
        self.assertTrue(self.database_path.is_file())
        config = Path(state["configuration_file"]).read_text(encoding="utf-8")
        self.assertIn('POS_BUSINESS_NAME="Deployment Test Store"', config)
        self.assertIn('POS_CURRENCY="USD"', config)
        self.assertIn('POS_LICENSE_ENFORCEMENT="true"', config)
        self.assertTrue((self.install_dir / "licenses" / "activation").is_dir())
        self.assertNotIn("StrongAdmin123", config)
        self.assertNotIn("StrongAdmin123", json.dumps(state))
        self.assertTrue(Path(state["windows_integration_file"]).is_file())
        self.assertTrue((self.backup_dir / ".carthage-pos-backup-root").is_file())
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM products").fetchone()[0], 0)

        from auth import authenticate_user
        old_database = os.environ.get("CARTHAGE_POS_DB")
        os.environ["CARTHAGE_POS_DB"] = str(self.database_path)
        try:
            session = authenticate_user("owner.admin", "StrongAdmin123")
        finally:
            if old_database is None:
                os.environ.pop("CARTHAGE_POS_DB", None)
            else:
                os.environ["CARTHAGE_POS_DB"] = old_database
        self.assertEqual(session.role, "admin")

        from app.deployment.verification_service import verify_installation
        verification = verify_installation(str(self.install_dir))
        self.assertTrue(verification["healthy"], verification)

    def test_fresh_install_failure_removes_partial_database_and_configuration(self):
        from app.core.exceptions import InstallationError
        from app.deployment.installer_service import fresh_install

        with patch("app.deployment.installer_service.bootstrap_admin", side_effect=RuntimeError("bootstrap failure")):
            with self.assertRaises(InstallationError):
                fresh_install(self.request)
        self.assertFalse(self.database_path.exists())
        self.assertFalse((self.install_dir / "config" / "carthage-pos.env").exists())
        self.assertFalse((self.install_dir / "config" / "deployment.json").exists())

    def test_configuration_generation_and_environment_parsing(self):
        from app.core.config import parse_environment_file
        from app.deployment.configuration_service import generate_environment_file

        generated = generate_environment_file(self.request)
        parsed = parse_environment_file(generated["path"])
        self.assertEqual(parsed["CARTHAGE_POS_DB"], str(self.database_path.resolve()))
        self.assertEqual(parsed["POS_PRINTER_PROFILE"], "80mm")
        self.assertEqual(parsed["POS_DEFAULT_TAX_RATE"], "0.075")
        self.assertEqual(parsed["POS_LICENSE_DEFAULT_EDITION"], "COMMUNITY")
        self.assertEqual(parsed["POS_LICENSE_TRIAL_EDITION"], "PROFESSIONAL")
        self.assertNotIn("CARTHAGE_POS_ADMIN_PASSWORD", parsed)

    def test_upgrade_and_repair_regenerate_missing_configuration(self):
        state = self.install()
        config_path = Path(state["configuration_file"])
        windows_path = Path(state["windows_integration_file"])
        config_path.unlink()
        windows_path.unlink()

        from app.deployment.installer_service import repair_installation, upgrade_installation
        repaired = repair_installation(str(self.install_dir))
        self.assertEqual(repaired["last_operation"], "REPAIR")
        self.assertTrue(config_path.is_file())
        self.assertTrue(windows_path.is_file())
        upgraded = upgrade_installation(str(self.install_dir))
        self.assertEqual(upgraded["last_operation"], "UPGRADE")
        self.assertTrue(Path(upgraded["rollback_database"]).is_file())

    def test_uninstall_preserves_data_and_requires_confirmation_for_removal(self):
        self.install()
        from app.core.exceptions import InstallationError
        from app.deployment.installer_service import uninstall_installation

        with self.assertRaises(InstallationError):
            uninstall_installation(str(self.install_dir), remove_data=True, confirmation="wrong")
        result = uninstall_installation(str(self.install_dir))
        self.assertTrue(result["uninstalled"])
        self.assertTrue(self.database_path.is_file())
        self.assertTrue(self.backup_dir.is_dir())

    def test_clean_uninstall_removes_only_managed_business_data(self):
        self.install()
        unrelated = self.backup_dir / "keep-me.txt"
        unrelated.write_text("not managed", encoding="utf-8")
        from app.deployment.installer_service import uninstall_installation

        result = uninstall_installation(
            str(self.install_dir), remove_data=True, confirmation="REMOVE-ALL-DATA"
        )
        self.assertTrue(result["remove_data"])
        self.assertFalse(self.database_path.exists())
        self.assertTrue(unrelated.is_file())

    def test_version_and_update_manifest_compatibility_and_staging(self):
        from app.core.version import compare_versions, compatibility_report
        from app.deployment.update_service import (
            LocalFileDownloadAdapter, check_for_update, get_update_status,
            parse_update_manifest, stage_update,
        )
        from app.core.exceptions import UpdateError

        self.assertEqual(compare_versions("1.1.0", "1.0.9"), 1)
        self.assertTrue(compatibility_report()["compatible"])
        source = self.root / "packages"
        source.mkdir()
        package = source / "CarthagePOS-Update-1.1.0.exe"
        package.write_bytes(b"verified offline update package")
        manifest = parse_update_manifest({
            "version": "1.1.0",
            "channel": "stable",
            "package_filename": package.name,
            "sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
            "package_size": package.stat().st_size,
            "minimum_database_version": 1,
            "maximum_database_version": 1,
            "minimum_installer_version": "0.9.0",
        })
        self.assertTrue(check_for_update(manifest)["update_available"])
        staged = stage_update(manifest, LocalFileDownloadAdapter(str(source)), str(self.install_dir))
        self.assertEqual(staged["status"], "STAGED")
        self.assertTrue(Path(staged["package"]).is_file())
        self.assertEqual(get_update_status(str(self.install_dir))["target_version"], "1.1.0")
        invalid = parse_update_manifest({
            **manifest.to_dict(), "version": "1.2.0", "sha256": "0" * 64,
        })
        with self.assertRaises(UpdateError):
            stage_update(invalid, LocalFileDownloadAdapter(str(source)), str(self.install_dir))

    def test_deployment_api_endpoints(self):
        state = self.install()
        from app.core.config import load_environment_file
        load_environment_file(state["configuration_file"], override=True)
        from app.api.app import create_app

        with TestClient(create_app(initialize=False)) as client:
            login = client.post(
                "/api/v1/auth/login",
                json={"username": "owner.admin", "password": "StrongAdmin123"},
            )
            self.assertEqual(login.status_code, 200, login.text)
            token = login.json()["data"]["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            self.assertEqual(client.get("/api/v1/version", headers=headers).status_code, 200)
            status = client.get("/api/v1/deployment/status", headers=headers)
            self.assertEqual(status.status_code, 200, status.text)
            self.assertTrue(status.json()["data"]["healthy"])
            self.assertEqual(client.get("/api/v1/deployment/installer", headers=headers).status_code, 200)
            self.assertEqual(client.get("/api/v1/updates/status", headers=headers).status_code, 200)
            self.assertEqual(client.post("/api/v1/deployment/verify", headers=headers).status_code, 200)
            compatible = client.get("/api/v1/deployment/compatibility", headers=headers)
            self.assertTrue(compatible.json()["data"]["compatible"])


if __name__ == "__main__":
    unittest.main()
