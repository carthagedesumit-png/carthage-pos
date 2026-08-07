import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from tests.upgrade_fixture_builder import (
    BOOTSTRAP_FIXTURE_STATES,
    HISTORICAL_FIXTURE_STATES,
    build_upgrade_fixture,
    capture_invariants,
)


class MigrationConsolidationTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.environment = {
            key: os.environ.get(key) for key in (
                "CARTHAGE_POS_DB", "POS_BACKUP_DIRECTORY", "POS_BACKUP_COMPRESSION",
                "POS_BACKUP_VERIFY_AFTER_CREATE", "POS_BACKUP_AUTO_BEFORE_RESTORE",
            )
        }

    def tearDown(self):
        from app.core.config import reset_config_cache
        for key, value in self.environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_config_cache()
        self.temporary.cleanup()

    def _activate(self, database: Path, backup_directory: Path) -> None:
        from app.core.config import reset_config_cache
        os.environ.update({
            "CARTHAGE_POS_DB": str(database),
            "POS_BACKUP_DIRECTORY": str(backup_directory),
            "POS_BACKUP_COMPRESSION": "true",
            "POS_BACKUP_VERIFY_AFTER_CREATE": "true",
            "POS_BACKUP_AUTO_BEFORE_RESTORE": "false",
        })
        reset_config_cache()

    @staticmethod
    def _admin_session():
        from auth import UserSession
        return UserSession(101, "fixture.admin", "Fixture Administrator", "admin", 1)

    def test_authoritative_migration_order_is_unique(self):
        from app.database.db_manager import authoritative_migrations
        names = [name for name, _migration in authoritative_migrations()]
        self.assertEqual(len(names), len(set(names)))
        self.assertLess(names.index("users"), names.index("stores_and_assignments"))
        self.assertLess(names.index("sales"), names.index("customer_financial"))
        self.assertLess(names.index("hardware_events"), names.index("pilot_readiness_and_data"))

    def test_historical_fixtures_backup_upgrade_restore_and_preserve_invariants(self):
        from app.backup.backup_service import create_backup, verify_backup
        from app.backup.restore_service import restore_backup_copy
        from app.core.version import DATABASE_SCHEMA_VERSION
        from app.database.db_manager import initialize_database

        for state in HISTORICAL_FIXTURE_STATES:
            with self.subTest(state=state):
                source = build_upgrade_fixture(self.root / f"{state}-source.sqlite3", state)
                before = capture_invariants(source, state)
                source_bytes = source.read_bytes()
                backups = self.root / f"{state}-backups"
                self._activate(source, backups)
                backup = create_backup(self._admin_session(), name=state)
                self.assertTrue(verify_backup(self._admin_session(), backup["backup_id"])["valid"])
                self.assertEqual(source.read_bytes(), source_bytes)

                working = self.root / f"{state}-working.sqlite3"
                shutil.copy2(source, working)
                self._activate(working, backups)
                initialize_database()
                initialize_database()
                self.assertEqual(capture_invariants(working, state), before)
                with closing(sqlite3.connect(working)) as connection:
                    self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                    self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], DATABASE_SCHEMA_VERSION)

                self._activate(source, backups)
                restored = self.root / f"{state}-restored.sqlite3"
                result = restore_backup_copy(self._admin_session(), backup["backup_id"], restored)
                self.assertFalse(result["migrated"])
                self.assertEqual(capture_invariants(restored, state), before)
                self.assertEqual(source.read_bytes(), source_bytes)
                with self.assertRaisesRegex(Exception, "active database"):
                    restore_backup_copy(self._admin_session(), backup["backup_id"], source)
                with self.assertRaisesRegex(Exception, "overwrite"):
                    restore_backup_copy(self._admin_session(), backup["backup_id"], restored)

    def test_bootstrap_settings_upgrade_preserves_configuration(self):
        from app.database.db_manager import initialize_database
        state = BOOTSTRAP_FIXTURE_STATES[0]
        database = build_upgrade_fixture(self.root / "settings.sqlite3", state)
        before = capture_invariants(database, state)
        self._activate(database, self.root / "settings-backups")
        initialize_database()
        self.assertEqual(capture_invariants(database, state), before)

    def test_corrupt_historical_backup_cannot_restore_or_create_destination(self):
        from app.backup.backup_service import create_backup, verify_backup
        from app.backup.restore_service import restore_backup_copy
        from app.core.exceptions import RestoreError
        state = HISTORICAL_FIXTURE_STATES[-1]
        source = build_upgrade_fixture(self.root / "corrupt-source.sqlite3", state)
        backups = self.root / "corrupt-backups"
        self._activate(source, backups)
        backup = create_backup(self._admin_session(), name="corrupt-rehearsal")
        (backups / backup["artifact_filename"]).write_bytes(b"corrupt")
        self.assertFalse(verify_backup(self._admin_session(), backup["backup_id"])["valid"])
        destination = self.root / "must-not-exist.sqlite3"
        with self.assertRaises(RestoreError):
            restore_backup_copy(self._admin_session(), backup["backup_id"], destination)
        self.assertFalse(destination.exists())

    def test_failed_migration_rolls_back_schema_and_version(self):
        from app.database import db_manager
        database = self.root / "rollback.sqlite3"
        sqlite3.connect(database).close()
        os.environ["CARTHAGE_POS_DB"] = str(database)

        def fail(_cursor):
            raise RuntimeError("deliberate fixture failure")

        with patch.object(db_manager, "authoritative_migrations", return_value=(
            ("users", db_manager.migrate_users_table), ("failure", fail),
        )):
            with self.assertRaises(RuntimeError):
                db_manager.initialize_database()
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertIsNone(connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
            ).fetchone())

    def test_newer_schema_fails_closed_without_downgrade(self):
        from app.core.version import DATABASE_SCHEMA_VERSION
        from app.database.db_manager import initialize_database
        database = self.root / "newer.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            connection.execute(f"PRAGMA user_version={DATABASE_SCHEMA_VERSION + 1}")
        os.environ["CARTHAGE_POS_DB"] = str(database)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "newer than supported"):
            initialize_database()
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], DATABASE_SCHEMA_VERSION + 1)


class ReleasePreparationTestCase(unittest.TestCase):
    def test_runtime_manifest_drives_deterministic_pyinstaller_arguments(self):
        from app.deployment.runtime_assets import pyinstaller_arguments, validate_runtime_assets
        arguments = pyinstaller_arguments(Path.cwd())
        self.assertTrue(validate_runtime_assets(Path.cwd())["valid"])
        self.assertIn("--hidden-import", arguments)
        self.assertIn("app.operations.pilot_data_service", arguments)
        build_scripts = [Path("scripts/build_rc.ps1"), Path("installer/build.ps1")]
        for script in build_scripts:
            content = script.read_text(encoding="utf-8")
            self.assertIn("app.deployment.runtime_assets", content)
            self.assertNotIn("--add-data", content)
            self.assertIn("git status --porcelain", content)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                pyinstaller_arguments(directory)

    def test_source_evidence_binds_commit_and_cannot_satisfy_physical_gates(self):
        from scripts.validate_release import generate_release_evidence, source_commit
        with tempfile.TemporaryDirectory() as directory:
            release_dir = Path(directory) / "CBOS-1.0.0-rc.2"
            evidence = generate_release_evidence(release_dir)
            self.assertEqual(evidence["build_type"], "source-only")
            self.assertIsNone(evidence["source_commit"])
            self.assertIsNone(evidence["release_manifest"]["source_commit"])
            self.assertEqual(evidence["gate_status"]["source_validation"], "passed")
            self.assertEqual(evidence["gate_status"]["installer_validation"], "not-run")
            self.assertEqual(evidence["gate_status"]["clean_pc_acceptance"], "physically-unverified")
            self.assertNotIn(str(Path(directory)), json.dumps(evidence))
            with self.assertRaises(ValueError):
                generate_release_evidence(release_dir, source_commit="000000000000")

    def test_rc2_identity_rejects_stale_or_mismatched_evidence(self):
        from scripts.validate_release import validate_evidence_identity
        expected_commit = "abcdef123456"
        stale = {"version": "1.0.0-rc.1", "source_commit": expected_commit}
        wrong_commit = {"version": "1.0.0-rc.2", "source_commit": "000000000000"}
        self.assertFalse(validate_evidence_identity(stale, expected_commit=expected_commit)["valid"])
        self.assertFalse(validate_evidence_identity(wrong_commit, expected_commit=expected_commit)["valid"])

    def test_historical_rc1_reference_is_preserved(self):
        from app.core.version import APP_VERSION, compare_versions
        self.assertEqual(APP_VERSION, "1.0.0-rc.2")
        self.assertLess(compare_versions("1.0.0-rc.1", APP_VERSION), 0)

    def test_installer_upgrade_identity_and_rc2_paths_are_stable(self):
        from scripts.validate_release import expected_installer_filename, expected_release_directory
        script = Path("installer/carthage-pos.iss").read_text(encoding="utf-8")
        self.assertIn("AppId={{9A81751F-18D8-4B90-9237-9B79845CB945}", script)
        self.assertIn("OutputBaseFilename=CBOS-Setup-{#MyAppVersion}", script)
        self.assertEqual(expected_installer_filename(), "CBOS-Setup-1.0.0-rc.2.exe")
        self.assertEqual(expected_release_directory(), "CBOS-1.0.0-rc.2")

    def test_preflight_reports_dirty_tree_test_evidence_and_physical_gates(self):
        from scripts.build_preflight import run_preflight
        result = run_preflight(Path.cwd())
        checks = {item["name"]: item for item in result["checks"]}
        self.assertFalse(result["build_performed"])
        self.assertFalse(checks["clean_working_tree"]["passed"])
        self.assertFalse(checks["canonical_tests_same_commit"]["passed"])
        self.assertIn("physically-unverified", {item["status"] for item in result["warnings"]})

    def test_inno_discovery_uses_explicit_and_standard_paths_without_path_dependency(self):
        from scripts.build_preflight import discover_iscc
        with tempfile.TemporaryDirectory() as directory:
            compiler = Path(directory) / "Inno Setup 6" / "ISCC.exe"
            compiler.parent.mkdir()
            compiler.touch()
            with patch("scripts.build_preflight.shutil.which", return_value=None), patch.dict(
                    "scripts.build_preflight.os.environ", {"ProgramFiles(x86)": directory}, clear=True):
                self.assertEqual(discover_iscc(), compiler.resolve())
                self.assertEqual(discover_iscc(compiler), compiler.resolve())

    def test_preflight_accepts_full_expected_commit(self):
        from scripts.build_preflight import run_preflight
        full_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
        ).stdout.strip()
        result = run_preflight(Path.cwd(), expected_commit=full_commit)
        check = next(item for item in result["checks"] if item["name"] == "expected_commit")
        self.assertTrue(check["passed"], check)


if __name__ == "__main__":
    unittest.main()
