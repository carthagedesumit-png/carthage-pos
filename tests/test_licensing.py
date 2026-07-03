import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient


class LicensingPlatformTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.database = self.root / "licensing.db"
        self.license_dir = self.root / "licenses"
        fixtures = Path(__file__).resolve().parent / "fixtures"
        self.private_key = fixtures / "license-test-private.json"
        self.public_key = fixtures / "license-test-public.json"
        self.environment = {
            "CARTHAGE_POS_DB": str(self.database),
            "POS_LICENSE_DIRECTORY": str(self.license_dir),
            "POS_LICENSE_FILE": str(self.license_dir / "license.json"),
            "POS_ACTIVATION_DIRECTORY": str(self.license_dir / "activation"),
            "POS_LICENSE_PUBLIC_KEY_FILE": str(self.public_key),
            "POS_LICENSE_ENFORCEMENT": "true",
            "POS_LICENSE_DEFAULT_EDITION": "COMMUNITY",
            "POS_LICENSE_TRIAL_EDITION": "PROFESSIONAL",
            "POS_LICENSE_DEVELOPER_MODE": "false",
            "POS_LICENSE_EVALUATION_DAYS": "14",
            "POS_LICENSE_GRACE_PERIOD_DAYS": "3",
            "POS_LICENSE_FINGERPRINT_MIN_MATCHES": "1",
        }
        self.previous = {key: os.environ.get(key) for key in self.environment}
        os.environ.update(self.environment)

        from app.core.config import reset_config_cache
        reset_config_cache()
        from app.database.db_manager import initialize_database
        from tests.support import bootstrap_staff
        initialize_database()
        self.sessions = bootstrap_staff()

        from app.licensing.fingerprint import StaticFingerprintProvider
        self.provider = StaticFingerprintProvider({
            "host": "licensing-test-host",
            "machine_id": "stable-machine-id",
            "system_volume": "volume-100",
        })

    def tearDown(self):
        from app.core.config import reset_config_cache
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_config_cache()
        self.temp_dir.cleanup()

    def issue(self, *, edition="PROFESSIONAL", license_type="PROFESSIONAL",
              provider=None, expires_at=None):
        from app.licensing.issuer import issue_license
        provider = provider or self.provider
        return issue_license(
            private_key=str(self.private_key),
            license_type=license_type,
            edition=edition,
            customer_name="Ada Owner",
            company_name="Example Retail Ltd",
            bound_identifiers=list(provider.fingerprint().identifiers.values()),
            expires_at=expires_at,
            activation_limit=2,
            activation_number=1,
        )

    def test_rsa_signature_validation_and_tamper_rejection(self):
        from app.core.exceptions import LicenseValidationError
        from app.licensing.license_service import validate_license_document
        document = self.issue()
        status = validate_license_document(document, provider=self.provider)
        self.assertTrue(status["valid"])
        self.assertEqual(status["edition"], "PROFESSIONAL")
        self.assertNotEqual(status["license"]["license_key"], document["payload"]["license_key"])

        tampered = copy.deepcopy(document)
        tampered["payload"]["company_name"] = "Tampered Company"
        with self.assertRaises(LicenseValidationError):
            validate_license_document(tampered, provider=self.provider)

    def test_machine_fingerprint_tolerates_one_stable_identifier(self):
        from app.core.exceptions import LicenseValidationError
        from app.licensing.fingerprint import StaticFingerprintProvider
        from app.licensing.license_service import validate_license_document
        document = self.issue()
        changed = StaticFingerprintProvider({
            "host": "changed-host",
            "machine_id": "stable-machine-id",
            "system_volume": "changed-volume",
        })
        self.assertTrue(validate_license_document(document, provider=changed)["valid"])
        unrelated = StaticFingerprintProvider({"host": "other", "machine_id": "other-id"})
        with self.assertRaises(LicenseValidationError):
            validate_license_document(document, provider=unrelated)

    def test_feature_flags_resource_limits_and_read_only_enforcement(self):
        from app.core.exceptions import LicenseFeatureError
        from app.licensing.editions import CORE_POS, CRM
        from app.licensing.feature_service import (
            enforce_resource_limit, require_feature, require_write_access,
        )
        community = {"edition": "COMMUNITY", "state": "ACTIVE", "read_only": False}
        self.assertTrue(require_feature(CORE_POS, status=community))
        with self.assertRaises(LicenseFeatureError):
            require_feature(CRM, status=community)
        with self.assertRaises(LicenseFeatureError):
            enforce_resource_limit("stores", 1, status=community)
        with self.assertRaises(LicenseFeatureError):
            require_write_access(status={**community, "read_only": True})

    def test_offline_request_response_activation_and_deactivation(self):
        from app.core.exceptions import AuthorizationError
        from app.licensing.activation_service import (
            deactivate_installation, export_activation_request, import_activation_response,
        )
        from app.licensing.issuer import generate_license_key, issue_activation_response
        request = export_activation_request(
            self.sessions["admin"], generate_license_key("ENTERPRISE"),
            "Ada Owner", "Example Retail Ltd", provider=self.provider,
        )
        self.assertTrue(Path(request["path"]).is_file())
        with self.assertRaises(AuthorizationError):
            export_activation_request(
                self.sessions["cashier"], generate_license_key("ENTERPRISE"),
                "Ada Owner", "Example Retail Ltd", provider=self.provider,
            )
        response = issue_activation_response(
            request["document"], private_key=str(self.private_key),
            license_type="ENTERPRISE", edition="ENTERPRISE",
        )
        status = import_activation_response(
            self.sessions["admin"], json.dumps(response), provider=self.provider,
        )
        self.assertEqual(status["state"], "ACTIVE")
        self.assertEqual(status["edition"], "ENTERPRISE")
        deactivated = deactivate_installation(self.sessions["admin"], provider=self.provider)
        self.assertTrue(deactivated["deactivated"])
        self.assertFalse((self.license_dir / "license.json").exists())
        audit = (self.license_dir / "licensing-audit.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(request["document"]["license_key"], audit)

    def test_subscription_expiration_grace_and_read_only_lifecycle(self):
        from app.licensing.license_service import validate_license_document
        base = datetime.now(timezone.utc)
        expiration = base + timedelta(hours=1)
        document = self.issue(
            edition="PROFESSIONAL", license_type="SUBSCRIPTION",
            expires_at=expiration.isoformat(),
        )
        active = validate_license_document(document, provider=self.provider, now=base)
        grace = validate_license_document(
            document, provider=self.provider, now=expiration + timedelta(days=1)
        )
        expired = validate_license_document(
            document, provider=self.provider, now=expiration + timedelta(days=4)
        )
        self.assertEqual(active["state"], "ACTIVE")
        self.assertEqual(grace["state"], "GRACE")
        self.assertFalse(grace["read_only"])
        self.assertEqual(expired["state"], "EXPIRED")
        self.assertTrue(expired["read_only"])

    def test_community_limits_are_enforced_by_user_and_store_services(self):
        from app.core.exceptions import LicenseFeatureError
        from app.licensing.activation_service import import_activation_response
        from auth import create_user
        import_activation_response(
            self.sessions["admin"],
            self.issue(edition="COMMUNITY", license_type="OFFLINE_PERPETUAL"),
            provider=self.provider,
        )
        with self.assertRaises(LicenseFeatureError):
            create_user(
                "fourth-user", "fourth-password", "Fourth User", "cashier",
                acting_session=self.sessions["admin"],
            )
        from app.stores.store_service import create_store
        with self.assertRaises(LicenseFeatureError):
            create_store(self.sessions["admin"], code="BR2", name="Second Branch")

    def test_developer_mode_is_explicit_and_not_for_production(self):
        from app.core.config import reset_config_cache
        from app.licensing.license_service import get_license_status
        os.environ["POS_LICENSE_DEVELOPER_MODE"] = "true"
        reset_config_cache()
        status = get_license_status(provider=self.provider)
        self.assertEqual(status["state"], "DEVELOPER")
        self.assertIn("DEVELOPMENT_TOOLS", status["features"])
        self.assertTrue(status["notifications"])

    def test_licensing_api_and_community_api_restriction(self):
        from app.api.app import create_app
        from app.licensing.fingerprint import SystemFingerprintProvider
        from app.licensing.issuer import generate_license_key
        system_provider = SystemFingerprintProvider()
        document = self.issue(
            edition="COMMUNITY", license_type="OFFLINE_PERPETUAL",
            provider=system_provider,
        )
        with TestClient(create_app(initialize=False)) as client:
            login = client.post(
                "/api/v1/auth/login",
                json={"username": "test-admin", "password": "admin-password"},
            )
            self.assertEqual(login.status_code, 200, login.text)
            headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
            self.assertEqual(client.get("/api/v1/licensing/status", headers=headers).status_code, 200)
            exported = client.post(
                "/api/v1/licensing/export-request", headers=headers,
                json={
                    "license_key": generate_license_key("PROFESSIONAL"),
                    "customer_name": "Ada Owner", "company_name": "Example Retail Ltd",
                },
            )
            self.assertEqual(exported.status_code, 200, exported.text)
            self.assertNotIn("document", exported.json()["data"])
            activated = client.post(
                "/api/v1/licensing/activate", headers=headers,
                json={"document": document},
            )
            self.assertEqual(activated.status_code, 200, activated.text)
            self.assertEqual(activated.json()["data"]["edition"], "COMMUNITY")
            edition = client.get("/api/v1/licensing/edition", headers=headers)
            self.assertEqual(edition.status_code, 200)
            self.assertEqual(edition.json()["data"]["edition"], "COMMUNITY")
            from app.core.config import get_config
            self.assertTrue(get_config().licensing.enforcement_enabled)
            restricted = client.get("/api/v1/products", headers=headers)
            self.assertEqual(restricted.status_code, 403, restricted.text)
            self.assertEqual(restricted.json()["error"]["code"], "license_restriction")
            self.assertEqual(client.post("/api/v1/licensing/deactivate", headers=headers).status_code, 200)


if __name__ == "__main__":
    unittest.main()
