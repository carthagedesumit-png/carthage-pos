import json
import logging
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


class ProductionReadinessTestCase(unittest.TestCase):
    def setUp(self):
        self.previous_program_data = os.environ.get("PROGRAMDATA")
        self.program_data_dir = tempfile.TemporaryDirectory()
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()
        self.backup_dir = tempfile.TemporaryDirectory()
        self.log_dir = tempfile.TemporaryDirectory()
        self.license_dir = tempfile.TemporaryDirectory()
        self.activation_dir = tempfile.TemporaryDirectory()
        os.environ.update(
            {
                "CARTHAGE_POS_DB": self.db_file.name,
                "POS_BACKUP_DIRECTORY": self.backup_dir.name,
                "POS_LOG_DIRECTORY": self.log_dir.name,
                "POS_LICENSE_DIRECTORY": self.license_dir.name,
                "POS_ACTIVATION_DIRECTORY": self.activation_dir.name,
                "POS_AUTH_RATE_LIMIT_ATTEMPTS": "2",
                "POS_AUTH_RATE_LIMIT_WINDOW_SECONDS": "60",
                "POS_SESSION_IDLE_MINUTES": "1",
                "PROGRAMDATA": self.program_data_dir.name,
            }
        )

        from app.api.security_middleware import reset_rate_limit_state
        from app.core.config import reset_config_cache
        from app.database.db_manager import initialize_database
        from tests.support import bootstrap_staff

        reset_rate_limit_state()
        reset_config_cache()
        initialize_database()
        self.sessions = bootstrap_staff()

        from app.api.app import create_app

        self.client_context = TestClient(create_app(initialize=False))
        self.client = self.client_context.__enter__()

    def tearDown(self):
        from app.api.security_middleware import reset_rate_limit_state
        from app.core.config import reset_config_cache

        self.client_context.__exit__(None, None, None)
        for name in (
            "CARTHAGE_POS_DB",
            "POS_BACKUP_DIRECTORY",
            "POS_LOG_DIRECTORY",
            "POS_LICENSE_DIRECTORY",
            "POS_ACTIVATION_DIRECTORY",
            "POS_AUTH_RATE_LIMIT_ATTEMPTS",
            "POS_AUTH_RATE_LIMIT_WINDOW_SECONDS",
            "POS_SESSION_IDLE_MINUTES",
            "POS_STRICT_STARTUP_VALIDATION",
        ):
            os.environ.pop(name, None)
        if self.previous_program_data is None:
            os.environ.pop("PROGRAMDATA", None)
        else:
            os.environ["PROGRAMDATA"] = self.previous_program_data
        reset_rate_limit_state()
        reset_config_cache()
        os.unlink(self.db_file.name)
        self.backup_dir.cleanup()
        self.log_dir.cleanup()
        self.license_dir.cleanup()
        self.activation_dir.cleanup()
        self.program_data_dir.cleanup()

    def login_headers(self):
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": "test-admin", "password": "admin-password"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}

    def test_health_endpoints_report_liveness_and_readiness(self):
        live = self.client.get("/health/live")
        self.assertEqual(live.status_code, 200)
        self.assertEqual(live.json()["service"], "cbos")

        ready = self.client.get("/health/ready")
        self.assertEqual(ready.status_code, 200, ready.text)
        payload = ready.json()
        self.assertTrue(payload["ready"])
        self.assertIn("database_connectivity", {item["name"] for item in payload["checks"]})
        self.assertIn("schema_compatibility", {item["name"] for item in payload["checks"]})

    def test_security_headers_and_request_id_are_applied(self):
        response = self.client.get("/health/live", headers={"X-Request-ID": "ops-test-request"})
        self.assertEqual(response.headers["X-Request-ID"], "ops-test-request")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["Referrer-Policy"], "same-origin")

    def test_failed_authentication_rate_limiting(self):
        for _ in range(2):
            response = self.client.post(
                "/api/v1/auth/login",
                json={"username": "test-admin", "password": "wrong"},
            )
            self.assertEqual(response.status_code, 401)

        limited = self.client.post(
            "/api/v1/auth/login",
            json={"username": "test-admin", "password": "wrong"},
        )
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.json()["error"]["code"], "rate_limited")

    def test_api_session_idle_timeout(self):
        headers = self.login_headers()
        token = headers["Authorization"].split()[1]

        from app.api.session_service import _token_hash
        from app.database.db_manager import get_connection

        with get_connection() as conn:
            conn.execute(
                "UPDATE api_sessions SET last_used_at = '2000-01-01T00:00:00' WHERE token_hash = ?",
                (_token_hash(token),),
            )

        response = self.client.get("/api/v1/auth/me", headers=headers)
        self.assertEqual(response.status_code, 401)
        self.assertIn("inactivity", response.text)

    def test_strict_configuration_validation_fails_fast_on_invalid_paths(self):
        invalid_backup_file = Path(self.backup_dir.name) / "not-a-directory"
        invalid_backup_file.write_text("not a directory", encoding="utf-8")
        os.environ["POS_BACKUP_DIRECTORY"] = str(invalid_backup_file)
        os.environ["POS_STRICT_STARTUP_VALIDATION"] = "true"

        from app.core.config import reset_config_cache
        from app.core.configuration_validation import validate_startup_configuration
        from app.core.exceptions import ConfigurationError

        reset_config_cache()
        with self.assertRaises(ConfigurationError):
            validate_startup_configuration()

    def test_structured_logging_redacts_sensitive_context(self):
        from app.core.logging_utils import StructuredLogFormatter, get_logger, log_event

        logger = get_logger("ops_test")
        record = logging.LogRecord(
            "carthage_pos.ops_test",
            logging.INFO,
            __file__,
            1,
            "operator_event",
            (),
            None,
        )
        record.event = "operator_event"
        record.context = {"username": "admin", "password": "secret-password"}
        payload = json.loads(StructuredLogFormatter().format(record))
        self.assertEqual(payload["event"], "operator_event")
        self.assertEqual(payload["context"], {"username": "admin"})

        with self.assertLogs("carthage_pos.ops_test", level="INFO") as captured:
            log_event(logger, "operator_event", username="admin", token="hidden")
        self.assertIn("operator_event", "\n".join(captured.output))
        self.assertNotIn("hidden", "\n".join(captured.output))

    def test_manual_backup_and_verification_use_existing_backup_service(self):
        from app.backup.backup_service import create_backup, verify_backup

        backup = create_backup(self.sessions["admin"], name="ops-check", compression=False)
        self.assertTrue(backup["backup_id"].startswith("BKP-"))
        verification = verify_backup(self.sessions["admin"], backup["backup_id"])
        self.assertTrue(verification["valid"])


if __name__ == "__main__":
    unittest.main()
