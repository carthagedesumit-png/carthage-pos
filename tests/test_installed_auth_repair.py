import os
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class InstalledAuthenticationRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old_programdata = os.environ.get("PROGRAMDATA")
        os.environ["PROGRAMDATA"] = str(self.root / "ProgramData")
        self.db = self.root / "ProgramData" / "Carthage POS" / "data" / "carthage-pos.db"
        self.config = self.root / "ProgramData" / "Carthage POS" / "config"
        self.backups = self.root / "ProgramData" / "Carthage POS" / "backups"
        self.install = self.root / "CBOS"
        self.password = "Installed-Admin9!"
        from app.deployment.models import SetupRequest
        self.request = SetupRequest(
            business_name="Installed CBOS", store_name="Main Store",
            administrator_username="Admin", administrator_password=self.password,
            administrator_full_name="Local Administrator", installation_directory=str(self.install),
            configuration_directory=str(self.config), database_path=str(self.db),
            backup_directory=str(self.backups), currency="USD", tax_rate=0,
            timezone="UTC", deployment_type="desktop", printer_preference="none",
            api_host="127.0.0.1", api_port=8000,
        )
        from app.deployment.installer_service import fresh_install
        self.state = fresh_install(self.request)
        self.old = {key: os.environ.get(key) for key in ("CARTHAGE_POS_DB", "POS_SECURE_COOKIES", "POS_DASHBOARD_CSRF")}
        os.environ.update({"CARTHAGE_POS_DB": str(self.db), "POS_SECURE_COOKIES": "false", "POS_DASHBOARD_CSRF": "false"})
        from app.core.config import reset_config_cache
        reset_config_cache()
        from app.api.app import create_app
        self.client = TestClient(create_app(initialize=False), base_url="http://127.0.0.1:8000")

    def tearDown(self):
        self.client.close()
        for key, value in self.old.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value
        from app.core.config import reset_config_cache
        reset_config_cache()
        if self.old_programdata is None: os.environ.pop("PROGRAMDATA", None)
        else: os.environ["PROGRAMDATA"] = self.old_programdata
        self.temp.cleanup()

    def test_installed_database_and_valid_bcrypt_login(self):
        from app.database.db_manager import get_database_path
        from auth import authenticate_user
        self.assertEqual(Path(get_database_path()), self.db)
        self.assertEqual(authenticate_user(" ADMIN ", self.password).role, "admin")
        self.assertTrue(self.state["database"]["administrator_verified"])
        self.assertEqual(self.state["environment"]["POS_SECURE_COOKIES"], "false")

    def test_form_mapping_blank_store_cookie_and_original_destination(self):
        response = self.client.post("/dashboard/login?next=%2Fdashboard%2Ffinance", data={
            "username": "Admin", "password": self.password, "store_id": ""
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/dashboard/finance"))
        cookie = response.headers["set-cookie"]
        self.assertIn("cbos_dashboard_session=", cookie); self.assertIn("HttpOnly", cookie)
        self.assertIn("Path=/dashboard", cookie); self.assertIn("SameSite=strict", cookie)

    def test_open_redirect_is_rejected(self):
        response = self.client.post("/dashboard/login?next=https%3A%2F%2Fevil.example", data={
            "username": "admin", "password": self.password
        }, follow_redirects=False)
        self.assertTrue(response.headers["location"].startswith("/dashboard/inventory"))

    def test_dashboard_redirects_but_api_remains_json(self):
        page = self.client.get("/dashboard/finance", follow_redirects=False)
        self.assertEqual(page.status_code, 303); self.assertIn("next=", page.headers["location"])
        api = self.client.get("/api/v1/auth/session")
        self.assertIn(api.status_code, (401, 404)); self.assertIn("application/json", api.headers["content-type"])

    def test_localhost_redirects_to_canonical_host_before_finance_auth(self):
        response = self.client.get(
            "http://localhost:8000/dashboard/finance?view=summary",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "http://127.0.0.1:8000/dashboard/finance?view=summary")

    def test_logout_revokes_and_stale_cookie_redirects(self):
        self.client.post("/dashboard/login", data={"username":"admin", "password":self.password})
        self.assertEqual(self.client.get("/dashboard/finance").status_code, 200)
        self.client.post("/dashboard/logout")
        self.assertEqual(self.client.get("/dashboard/finance", follow_redirects=False).status_code, 303)

    def test_secure_recovery_revokes_sessions_and_changes_password(self):
        self.client.post("/dashboard/login", data={"username":"admin", "password":self.password})
        from app.deployment.password_recovery_service import reset_local_admin_password
        new_password = "Recovered-Admin8!"
        result = reset_local_admin_password(str(self.install), "ADMIN", new_password, elevated=True)
        self.assertTrue(result["sessions_revoked"])
        from auth import authenticate_user
        self.assertIsNone(authenticate_user("admin", self.password))
        self.assertIsNotNone(authenticate_user("admin", new_password))
        self.assertEqual(self.client.get("/dashboard/finance", follow_redirects=False).status_code, 303)

    def test_password_file_only_removes_line_ending(self):
        from deployment_cli import _consume_password_file
        path = self.root / "one-use-password.txt"; path.write_bytes(b"\xef\xbb\xbf  Secret Value!9\r\n")
        self.assertEqual(_consume_password_file(path), "  Secret Value!9")
        self.assertFalse(path.exists())

    def test_existing_install_requires_current_preserved_administrator_credentials(self):
        from app.core.exceptions import InstallationError
        from app.deployment.installer_service import verify_installed_administrator
        from app.database.db_manager import get_connection
        with get_connection() as conn:
            conn.execute("UPDATE users SET force_password_change = 1 WHERE username = 'admin'")
            before = dict(conn.execute(
                "SELECT failed_login_count, last_login FROM users WHERE username = 'admin'"
            ).fetchone())
        with self.assertRaisesRegex(InstallationError, "existing administrator password is preserved"):
            verify_installed_administrator(str(self.install), "admin", "Different-Install9!")
        self.assertTrue(verify_installed_administrator(str(self.install), "ADMIN", self.password)["verified"])
        with get_connection() as conn:
            after = dict(conn.execute(
                "SELECT failed_login_count, last_login, force_password_change FROM users WHERE username = 'admin'"
            ).fetchone())
        self.assertEqual(after["failed_login_count"], before["failed_login_count"])
        self.assertEqual(after["last_login"], before["last_login"])
        self.assertEqual(after["force_password_change"], 1)

    def test_dedicated_upgrade_verifier_uses_programdata_database_read_only(self):
        password_file = self.root / "upgrade-password.once"
        password_file.write_text(self.password, encoding="utf-8")
        from upgrade_verifier_cli import main as verify_main
        import io
        from contextlib import redirect_stdout
        output = io.StringIO()
        with redirect_stdout(output):
            code = verify_main([
                "verify-upgrade-credentials", "--install-dir", str(self.install),
                "--username", "ADMIN", "--password-file", str(password_file),
            ])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(Path(result["database_path"]), self.db.resolve())
        stat = self.db.stat()
        self.assertEqual(result["database_identity"], f"{stat.st_dev}:{stat.st_ino}")
        self.assertFalse(password_file.exists())


class CanonicalHostTests(unittest.TestCase):
    def test_localhost_normalizes_to_single_cookie_host(self):
        from app.deployment.startup_service import instance_url
        self.assertEqual(instance_url("localhost", 8000), "http://127.0.0.1:8000")


class InnoArgumentAuthenticationTests(unittest.TestCase):
    def test_inno_windows_argument_path_creates_admin_that_can_open_finance(self):
        import ctypes
        import io
        from contextlib import redirect_stdout

        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name); program_data = root / "ProgramData"; install = root / "Program Files" / "CBOS"
            runtime = program_data / "Carthage POS"; password = "Inno-Exact-Pass9!"
            password_file = root / "Inno Password Input.once"; password_file.write_text(password + "\r\n", encoding="utf-8")
            values = {
                "CBOSBusiness":"Inno Acceptance", "CBOSStore":"Main Store", "CBOSAdminUser":"Admin",
                "CBOSAdminPasswordFile":str(password_file), "CBOSAdminFullName":"Inno Administrator",
                "CBOSCurrency":"USD", "CBOSTaxRate":"0", "CBOSTimezone":"UTC",
                "CBOSDeploymentType":"desktop", "CBOSPrinter":"none",
            }
            from app.deployment.installer_arguments import build_deployment_cli_arguments, quote_deployment_cli_arguments
            arguments = build_deployment_cli_arguments(values, install_dir=install, runtime_root=runtime, password_file=password_file)
            command_line = quote_deployment_cli_arguments(arguments)
            parser = ctypes.windll.shell32.CommandLineToArgvW
            parser.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
            parser.restype = ctypes.POINTER(ctypes.c_wchar_p)
            argc = ctypes.c_int(); argv_pointer = parser(command_line, ctypes.byref(argc))
            try: windows_arguments = [argv_pointer[index] for index in range(argc.value)]
            finally: ctypes.windll.kernel32.LocalFree(argv_pointer)
            self.assertEqual(windows_arguments, arguments)
            old_program_data = os.environ.get("PROGRAMDATA")
            try:
                os.environ["PROGRAMDATA"] = str(program_data)
                from deployment_cli import main as deployment_main
                with redirect_stdout(io.StringIO()): self.assertEqual(deployment_main(windows_arguments), 0)
                self.assertFalse(password_file.exists())
                old_db = os.environ.get("CARTHAGE_POS_DB"); old_secure = os.environ.get("POS_SECURE_COOKIES")
                os.environ["CARTHAGE_POS_DB"] = str(runtime / "data" / "carthage-pos.db"); os.environ["POS_SECURE_COOKIES"] = "false"
                from app.core.config import reset_config_cache
                reset_config_cache()
                from app.api.app import create_app
                with TestClient(create_app(initialize=False), base_url="http://127.0.0.1:8000") as client:
                    login = client.post("/dashboard/login?next=%2Fdashboard%2Ffinance", data={"username":"admin","password":password,"store_id":""})
                    self.assertEqual(login.status_code, 200); self.assertEqual(login.url.path, "/dashboard/finance")
            finally:
                if old_program_data is None: os.environ.pop("PROGRAMDATA",None)
                else: os.environ["PROGRAMDATA"] = old_program_data
                if 'old_db' in locals() and old_db is not None: os.environ["CARTHAGE_POS_DB"] = old_db
                else: os.environ.pop("CARTHAGE_POS_DB",None)
                if 'old_secure' in locals() and old_secure is not None: os.environ["POS_SECURE_COOKIES"] = old_secure
                else: os.environ.pop("POS_SECURE_COOKIES",None)
                from app.core.config import reset_config_cache
                reset_config_cache()
