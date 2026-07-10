import tempfile
import unittest
from pathlib import Path


class RcBuildAcceptanceTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_authoritative_rc_version_and_semver_ordering(self):
        from app.core.version import APP_VERSION, INSTALLER_VERSION, compare_versions, parse_version
        from scripts.validate_release import authoritative_version, numeric_windows_version

        self.assertEqual(APP_VERSION, "1.0.0-rc.1")
        self.assertEqual(INSTALLER_VERSION, APP_VERSION)
        self.assertEqual(authoritative_version(), APP_VERSION)
        self.assertEqual(parse_version(APP_VERSION), (1, 0, 0, 0, 1))
        self.assertEqual(numeric_windows_version(APP_VERSION), (1, 0, 0, 1))
        self.assertEqual(compare_versions("1.0.0", APP_VERSION), 1)
        self.assertEqual(compare_versions(APP_VERSION, "1.0.0-rc.2"), -1)

    def test_pyinstaller_version_file_is_generated_from_authoritative_version(self):
        from app.core.version import APP_VERSION
        from scripts.validate_release import write_pyinstaller_version_file

        destination = self.root / "version_info.txt"
        write_pyinstaller_version_file(destination)
        content = destination.read_text(encoding="utf-8")
        self.assertIn(f"StringStruct(u'FileVersion', u'{APP_VERSION}')", content)
        self.assertIn("Carthage Business Operating System", content)
        self.assertIn("filevers=(1, 0, 0, 1)", content)

    def test_release_evidence_validates_manifest_checksums_assets_and_inventory(self):
        from app.core.version import APP_VERSION
        from scripts.validate_release import generate_release_evidence, validate_release_artifacts

        release_dir = self.root / "CBOS-1.0.0-rc.1"
        (release_dir / "CarthagePOS").mkdir(parents=True)
        (release_dir / "CarthagePOSDeployment").mkdir(parents=True)
        (release_dir / "_internal" / "app" / "dashboard" / "templates").mkdir(parents=True)
        (release_dir / "_internal" / "app" / "dashboard" / "static").mkdir(parents=True)
        (release_dir / "CarthagePOS" / "CarthagePOS.exe").write_bytes(b"app")
        (release_dir / "CarthagePOSDeployment" / "CarthagePOSDeployment.exe").write_bytes(b"deployment")
        (release_dir / "_internal" / "app" / "dashboard" / "templates" / "index.html").write_text("ok", encoding="utf-8")
        (release_dir / "_internal" / "app" / "dashboard" / "static" / "dashboard.css").write_text("ok", encoding="utf-8")

        evidence = generate_release_evidence(release_dir, require_executables=True)
        validation = validate_release_artifacts(release_dir, require_executables=True)

        self.assertEqual(evidence["version"], APP_VERSION)
        self.assertTrue(validation["valid"], validation)
        self.assertTrue((release_dir / "release-manifest.json").is_file())
        self.assertTrue((release_dir / "checksums.txt").is_file())
        self.assertTrue((release_dir / "artifact-inventory.json").is_file())
        self.assertTrue((release_dir / "build-validation.json").is_file())
        self.assertTrue((release_dir / "release-evidence.json").is_file())

    def test_prohibited_release_files_are_detected(self):
        from scripts.validate_release import prohibited_release_files, validate_release_artifacts

        release_dir = self.root / "release"
        release_dir.mkdir()
        (release_dir / ".env").write_text("SECRET=value", encoding="utf-8")
        (release_dir / "pilot.sqlite3").write_bytes(b"sqlite")

        self.assertEqual(prohibited_release_files(release_dir), [".env", "pilot.sqlite3"])
        result = validate_release_artifacts(release_dir, require_executables=False)
        self.assertFalse(result["valid"])

    def test_runtime_paths_resolve_source_assets(self):
        from app.core.runtime_paths import resource_path

        self.assertTrue(resource_path("app", "dashboard", "templates").is_dir())
        self.assertTrue(resource_path("app", "dashboard", "static").is_dir())

    def test_installer_templates_do_not_duplicate_rc_version(self):
        from app.core.version import APP_VERSION

        installer_script = Path("installer/carthage-pos.iss").read_text(encoding="utf-8")
        static_version_file = Path("installer/version_info.txt").read_text(encoding="utf-8")
        self.assertNotIn(APP_VERSION, installer_script)
        self.assertNotIn(APP_VERSION, static_version_file)
        self.assertIn("MyAppVersion", installer_script)


if __name__ == "__main__":
    unittest.main()

