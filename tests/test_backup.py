import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class BackupPlatformTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "pos.sqlite3"
        self.backup_path = Path(self.temp_dir.name) / "backups"
        os.environ["CARTHAGE_POS_DB"] = str(self.db_path)
        os.environ["POS_BACKUP_DIRECTORY"] = str(self.backup_path)
        os.environ["POS_BACKUP_COMPRESSION"] = "true"
        os.environ["POS_BACKUP_VERIFY_AFTER_CREATE"] = "true"
        os.environ["POS_BACKUP_AUTO_BEFORE_RESTORE"] = "true"

        from app.core.config import reset_config_cache
        from app.database.db_manager import initialize_database
        from app.inventory.inventory_service import create_product
        from tests.support import bootstrap_staff

        reset_config_cache()
        initialize_database()
        sessions = bootstrap_staff()
        self.admin = sessions["admin"]
        self.manager = sessions["manager"]
        self.cashier = sessions["cashier"]
        self.product = create_product(
            self.manager, sku="BACKUP-ONE", name="Backup Product",
            selling_price=20, cost_price=8, quantity_in_stock=9,
        )

    def tearDown(self):
        from app.core.config import reset_config_cache
        for key in tuple(os.environ):
            if key.startswith("POS_BACKUP_") or key == "CARTHAGE_POS_DB":
                os.environ.pop(key, None)
        reset_config_cache()
        self.temp_dir.cleanup()

    def test_manual_compressed_and_uncompressed_backup_metadata_and_verification(self):
        from app.backup.backup_service import create_backup, get_backup_metadata, list_backups, verify_backup

        compressed = create_backup(self.manager, name="closing-shift")
        self.assertTrue(compressed["compressed"])
        self.assertTrue((self.backup_path / compressed["artifact_filename"]).is_file())
        self.assertEqual(len(compressed["checksum"]), 64)
        self.assertEqual(compressed["initiating_user"]["username"], "manager1")
        self.assertTrue(verify_backup(self.manager, compressed["backup_id"])["valid"])
        self.assertEqual(get_backup_metadata(self.manager, compressed["backup_id"])["backup_id"], compressed["backup_id"])

        plain = create_backup(self.manager, backup_type="INCREMENTAL", compression=False)
        self.assertFalse(plain["compressed"])
        self.assertTrue(plain["artifact_filename"].endswith(".sqlite3"))
        self.assertEqual(plain["base_backup_id"], compressed["backup_id"])
        self.assertEqual(len(list_backups(self.manager)), 2)

    def test_corrupted_backup_is_detected_and_cannot_restore(self):
        from app.backup.backup_service import create_backup, verify_backup
        from app.backup.restore_service import restore_backup
        from app.core.exceptions import RestoreError

        backup = create_backup(self.manager)
        artifact = self.backup_path / backup["artifact_filename"]
        with artifact.open("ab") as stream:
            stream.write(b"corruption")
        result = verify_backup(self.manager, backup["backup_id"])
        self.assertFalse(result["valid"])
        self.assertFalse(result["checks"]["checksum"])
        with self.assertRaises(RestoreError):
            restore_backup(self.admin, backup["backup_id"], dry_run=False,
                           confirmation=f"RESTORE:{backup['backup_id']}")

    def test_restore_dry_run_confirmation_and_automatic_safety_backup(self):
        from app.backup.backup_service import create_backup, list_backups
        from app.backup.restore_service import restore_backup
        from app.core.exceptions import RestoreError
        from app.inventory.inventory_service import create_product, get_product_by_id

        backup = create_backup(self.manager, name="known-good")
        later = create_product(self.manager, sku="AFTER-BACKUP", name="Later Product", selling_price=5)
        dry_run = restore_backup(self.admin, backup["backup_id"])
        self.assertTrue(dry_run["restorable"])
        with self.assertRaises(RestoreError):
            restore_backup(self.admin, backup["backup_id"], dry_run=False, confirmation="wrong")
        restored = restore_backup(
            self.admin, backup["backup_id"], dry_run=False,
            confirmation=f"RESTORE:{backup['backup_id']}",
        )
        self.assertTrue(restored["restored"])
        self.assertIsNotNone(restored["automatic_backup"])
        self.assertIsNone(get_product_by_id(later["id"]))
        self.assertGreaterEqual(len(list_backups(self.admin)), 2)

    def test_restore_failure_rolls_back_original_database(self):
        from app.backup.backup_service import create_backup
        from app.backup.restore_service import restore_backup
        from app.core.exceptions import RestoreError
        from app.inventory.inventory_service import create_product, get_product_by_id

        backup = create_backup(self.manager)
        later = create_product(self.manager, sku="ROLLBACK-SAFE", name="Must Survive", selling_price=7)
        with patch("app.backup.restore_service.initialize_database", side_effect=RuntimeError("migration failed")):
            with self.assertRaises(RestoreError):
                restore_backup(
                    self.admin, backup["backup_id"], dry_run=False,
                    confirmation=f"RESTORE:{backup['backup_id']}",
                )
        self.assertEqual(get_product_by_id(later["id"])["sku"], "ROLLBACK-SAFE")

    def test_permission_enforcement_delete_and_scheduler(self):
        from auth import AuthorizationError
        from app.backup.backup_service import create_backup, delete_backup, list_backups, verify_backup
        from app.backup.restore_service import restore_backup
        from app.backup.scheduler_service import run_scheduled_backup, update_scheduler_configuration

        with self.assertRaises(AuthorizationError):
            list_backups(self.cashier)
        backup = create_backup(self.manager)
        self.assertTrue(verify_backup(self.manager, backup["backup_id"])["valid"])
        with self.assertRaises(AuthorizationError):
            delete_backup(self.manager, backup["backup_id"])
        with self.assertRaises(AuthorizationError):
            restore_backup(self.manager, backup["backup_id"])
        with self.assertRaises(AuthorizationError):
            update_scheduler_configuration(self.manager, "DAILY")
        configuration = update_scheduler_configuration(self.admin, "DAILY")
        due = datetime.fromisoformat(configuration["next_run_at"]) + timedelta(seconds=1)
        scheduled = run_scheduled_backup(self.manager, now=due)
        self.assertTrue(scheduled["ran"])
        self.assertTrue(delete_backup(self.admin, backup["backup_id"])["deleted"])

    def test_retention_maximum_count(self):
        from app.backup.backup_service import create_backup, list_backups
        from app.core.config import reset_config_cache

        os.environ["POS_BACKUP_MAX_COUNT"] = "2"
        reset_config_cache()
        for _ in range(3):
            create_backup(self.manager)
        self.assertEqual(len(list_backups(self.manager)), 2)

    def test_json_csv_export_and_transactional_import(self):
        from app.backup.transfer_service import export_resource, import_resource
        from app.database.db_manager import get_connection

        products = export_resource(self.manager, "products", "JSON")
        records = json.loads(products["content"])
        records[0]["name"] = "Imported Product Name"
        result = import_resource(self.admin, "products", json.dumps(records), "JSON")
        self.assertEqual(result["imported"], len(records))
        with get_connection() as conn:
            name = conn.execute("SELECT name FROM products WHERE sku = ?", (records[0]["sku"],)).fetchone()[0]
        self.assertEqual(name, "Imported Product Name")
        suppliers = export_resource(self.manager, "suppliers", "CSV")
        self.assertIn("name,phone,email", suppliers["content"])
        configuration = export_resource(self.admin, "configuration", "JSON")
        staged = import_resource(self.admin, "configuration", configuration["content"], "JSON")
        self.assertTrue(staged["staged"])

    def test_configuration_validation(self):
        from app.core.config import get_config, reset_config_cache
        from app.core.exceptions import ConfigurationError

        os.environ["POS_BACKUP_RETENTION_DAYS"] = "14"
        os.environ["POS_BACKUP_MAX_COUNT"] = "5"
        os.environ["POS_BACKUP_COMPRESSION"] = "false"
        os.environ["POS_BACKUP_SCHEDULE"] = "WEEKLY"
        reset_config_cache()
        settings = get_config().backup
        self.assertEqual(settings.retention_days, 14)
        self.assertEqual(settings.max_count, 5)
        self.assertFalse(settings.compression_enabled)
        self.assertEqual(settings.schedule, "WEEKLY")
        os.environ["POS_BACKUP_SCHEDULE"] = "HOURLY"
        reset_config_cache()
        with self.assertRaises(ConfigurationError):
            get_config()

    def test_backup_api_endpoints_and_role_boundaries(self):
        from app.api.app import create_app

        with TestClient(create_app(initialize=False)) as client:
            def login(username, password):
                response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
                token = response.json()["data"]["access_token"]
                return {"Authorization": f"Bearer {token}"}

            admin_headers = login("test-admin", "admin-password")
            manager_headers = login("manager1", "manager-password")
            cashier_headers = login("cashier1", "cashier-password")
            self.assertEqual(client.get("/api/v1/backups", headers=cashier_headers).status_code, 403)
            created = client.post(
                "/api/v1/backups", headers=manager_headers,
                json={"name": "api-backup", "backup_type": "FULL"},
            )
            self.assertEqual(created.status_code, 201, created.text)
            backup_id = created.json()["data"]["backup_id"]
            self.assertEqual(client.get("/api/v1/backups/status", headers=manager_headers).status_code, 200)
            self.assertEqual(client.get(f"/api/v1/backups/{backup_id}", headers=manager_headers).status_code, 200)
            self.assertEqual(client.post(
                "/api/v1/backups/verify", headers=manager_headers,
                json={"backup_id": backup_id},
            ).status_code, 200)
            dry_run = client.post(
                "/api/v1/backups/restore", headers=admin_headers,
                json={"backup_id": backup_id, "dry_run": True},
            )
            self.assertTrue(dry_run.json()["data"]["restorable"])
            self.assertEqual(client.post(
                "/api/v1/backups/scheduler", headers=manager_headers,
                json={"schedule": "DAILY", "enabled": True},
            ).status_code, 403)
            self.assertEqual(client.post(
                "/api/v1/backups/scheduler", headers=admin_headers,
                json={"schedule": "WEEKLY", "enabled": True},
            ).status_code, 200)
            self.assertEqual(client.get(
                "/api/v1/backups/scheduler", headers=manager_headers
            ).status_code, 200)
            self.assertEqual(client.get(
                "/api/v1/backups/exports/products?format=JSON", headers=manager_headers
            ).status_code, 200)
            self.assertEqual(client.delete(f"/api/v1/backups/{backup_id}", headers=admin_headers).status_code, 200)


if __name__ == "__main__":
    unittest.main()
