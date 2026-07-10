import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


class ReleaseGovernanceTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "pilot.sqlite3"
        self.backup_dir = self.root / "backups"
        os.environ["CARTHAGE_POS_DB"] = str(self.db_path)
        os.environ["POS_BACKUP_DIRECTORY"] = str(self.backup_dir)
        os.environ["POS_LICENSE_DIRECTORY"] = str(self.root / "licenses")
        os.environ["POS_ACTIVATION_DIRECTORY"] = str(self.root / "licenses" / "activation")

        from app.core.config import reset_config_cache
        from app.database.db_manager import initialize_database

        reset_config_cache()
        initialize_database()

    def tearDown(self):
        from app.core.config import reset_config_cache

        for key in tuple(os.environ):
            if key.startswith("POS_") or key.startswith("CARTHAGE_POS"):
                os.environ.pop(key, None)
        reset_config_cache()
        self.temp_dir.cleanup()

    def test_authoritative_version_manifest_and_installer_metadata_align(self):
        from app.core.version import APP_VERSION, DATABASE_SCHEMA_VERSION, INSTALLER_VERSION, VersionInfo
        from app.deployment.release_manifest import build_release_manifest, validate_release_manifest
        from app.deployment.verification_service import get_installer_information

        manifest = build_release_manifest(channel="pilot", source_commit="abc123")
        self.assertEqual(manifest["application_version"], APP_VERSION)
        self.assertEqual(manifest["database"]["schema_version"], DATABASE_SCHEMA_VERSION)
        self.assertEqual(manifest["installer"]["version"], INSTALLER_VERSION)
        self.assertEqual(manifest["versions"], VersionInfo().to_dict())
        self.assertTrue(validate_release_manifest(manifest)["valid"])
        self.assertEqual(
            get_installer_information()["release_manifest"]["application_version"],
            APP_VERSION,
        )

    def test_release_manifest_package_checksum_metadata_is_machine_readable(self):
        from app.deployment.release_manifest import build_release_manifest, load_release_manifest, write_release_manifest

        package = self.root / "CBOS-Setup.exe"
        package.write_bytes(b"pilot package")
        destination = self.root / "release-manifest.json"
        manifest = write_release_manifest(
            destination,
            channel="pilot",
            source_commit="abc123",
            package_paths=[package],
        )
        self.assertEqual(load_release_manifest(destination), manifest)
        package_metadata = manifest["installer"]["package_checksums"][0]
        self.assertEqual(package_metadata["filename"], "CBOS-Setup.exe")
        self.assertTrue(package_metadata["exists"])
        self.assertEqual(len(package_metadata["sha256"]), 64)

    def test_upgrade_rehearsal_success_and_failed_upgrade_preserve_source_database(self):
        from app.deployment.upgrade_rehearsal import rehearse_database_upgrade, validate_schema_version

        before = self.db_path.read_bytes()
        self.assertTrue(validate_schema_version(self.db_path)["valid"])
        success = rehearse_database_upgrade(self.db_path, backup_directory=self.root / "rehearsal-backups")
        self.assertTrue(success["successful"])
        self.assertEqual(self.db_path.read_bytes(), before)

        failed = rehearse_database_upgrade(
            self.db_path,
            backup_directory=self.root / "failed-rehearsal-backups",
            simulate_failure=True,
        )
        self.assertFalse(failed["successful"])
        self.assertTrue(failed["rolled_back"])
        self.assertTrue(failed["source_unchanged"])
        self.assertEqual(self.db_path.read_bytes(), before)

    def test_release_checklist_validation_is_auditable(self):
        from app.core.version import APP_VERSION
        from app.deployment.release_checklist import REQUIRED_RELEASE_CHECKS, validate_release_checklist

        checklist = {
            "release": APP_VERSION,
            "checks": {name: {"status": "passed", "evidence": "test"} for name in REQUIRED_RELEASE_CHECKS},
        }
        self.assertTrue(validate_release_checklist(checklist)["release_ready"])
        checklist["checks"]["known_issues"]["status"] = "pending"
        result = validate_release_checklist(checklist)
        self.assertTrue(result["valid"])
        self.assertFalse(result["release_ready"])
        self.assertIn("known_issues", result["blocking"])

    def test_development_license_provider_contract(self):
        from app.licensing.providers import DevelopmentLicenseProvider, LICENSE_STATES, validate_license_status_document

        status = DevelopmentLicenseProvider().status()
        self.assertIn("TRIAL", LICENSE_STATES)
        self.assertIn("ACTIVE", LICENSE_STATES)
        self.assertIn("EXPIRED", LICENSE_STATES)
        self.assertIn("SUSPENDED", LICENSE_STATES)
        self.assertIn("INVALID", LICENSE_STATES)
        self.assertTrue(validate_license_status_document(status)["valid"])
        self.assertEqual(status["state"], "DEVELOPER")

    def test_release_manifest_endpoint_uses_current_version_source(self):
        from app.api.app import create_app
        from app.core.version import APP_VERSION
        from tests.support import bootstrap_staff

        bootstrap_staff(include_manager=False, include_cashier=False)
        with TestClient(create_app(initialize=False)) as client:
            login = client.post(
                "/api/v1/auth/login",
                json={"username": "test-admin", "password": "admin-password"},
            )
            token = login.json()["data"]["access_token"]
            response = client.get("/api/v1/release/manifest", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"]["application_version"], APP_VERSION)

    def test_pilot_smoke_journey_preserves_data_after_restart(self):
        from app.backup.backup_service import create_backup, verify_backup
        from app.documents.document_service import generate_sales_receipt
        from app.inventory.inventory_service import create_product, receive_stock
        from app.reports.reporting_service import get_daily_sales_report
        from app.sales.sales_service import create_sale
        from tests.support import bootstrap_staff

        sessions = bootstrap_staff()
        product = create_product(
            sessions["manager"],
            sku="PILOT-SMOKE",
            name="Pilot Smoke Item",
            selling_price=12,
            cost_price=5,
            quantity_in_stock=2,
        )
        receive_stock(sessions["manager"], product["id"], 3, notes="pilot setup")
        sale = create_sale(
            sessions["cashier"],
            [{"product_id": product["id"], "quantity": 1}],
            amount_paid=12,
        )
        receipt = generate_sales_receipt(sale["sale"]["sale_id"])
        self.assertIn("document_number", receipt)
        report = get_daily_sales_report()
        self.assertGreaterEqual(report["total_sales"], 12)
        backup = create_backup(sessions["admin"], name="pilot-smoke", compression=False)
        self.assertTrue(verify_backup(sessions["admin"], backup["backup_id"])["valid"])

        from app.database.db_manager import initialize_database, get_connection

        initialize_database()
        with get_connection() as conn:
            persisted = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        self.assertEqual(persisted, 1)


if __name__ == "__main__":
    unittest.main()
