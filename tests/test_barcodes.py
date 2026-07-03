import os
import tempfile
import unittest
from dataclasses import replace

from fastapi.testclient import TestClient


class BarcodePlatformTestCase(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()
        os.environ["CARTHAGE_POS_DB"] = self.db_file.name

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
            self.manager, sku="LBL-ONE", barcode="PRIMARY-ONE", name="Label Product",
            selling_price=25, cost_price=10, quantity_in_stock=12,
            reorder_level=3, unit="box", promotion_price=22,
        )
        self.second = create_product(
            self.manager, sku="LBL-TWO", name="Second Product", selling_price=12,
            cost_price=5, quantity_in_stock=2, reorder_level=4,
        )

    def tearDown(self):
        from app.core.config import reset_config_cache
        from app.hardware.manager import reset_hardware_manager
        reset_hardware_manager()
        for key in tuple(os.environ):
            if key.startswith("POS_") or key == "CARTHAGE_POS_DB":
                os.environ.pop(key, None)
        reset_config_cache()
        os.unlink(self.db_file.name)

    def configure_printer(self, available=True):
        from app.core.config import get_config
        from app.hardware.adapters import MockBarcodeScanner, MockCashDrawer, MockCustomerDisplay, MockPrinter
        from app.hardware.manager import HardwareManager, configure_hardware_manager
        settings = replace(get_config().hardware, printer_enabled=True)
        self.printer = MockPrinter(available=available)
        configure_hardware_manager(HardwareManager(
            settings, self.printer, MockCashDrawer(), MockBarcodeScanner(), MockCustomerDisplay()
        ))

    def test_validation_generation_regeneration_and_permissions(self):
        from auth import AuthorizationError
        from app.barcodes.barcode_service import generate_identifier, validate_identifier
        from app.core.exceptions import BarcodeError

        self.assertEqual(validate_identifier("4006381333931", "EAN-13"), "4006381333931")
        with self.assertRaises(BarcodeError):
            validate_identifier("4006381333932", "EAN13")
        generated = generate_identifier(self.manager, self.product["id"], "CODE39", "SECONDARY")
        self.assertEqual(generated["format"], "CODE39")
        with self.assertRaises(AuthorizationError):
            generate_identifier(self.cashier, self.product["id"], "CODE128", "SECONDARY")
        first = generate_identifier(self.admin, self.product["id"], "CODE128", "PRIMARY", True)
        second = generate_identifier(self.admin, self.product["id"], "CODE128", "PRIMARY", True)
        self.assertNotEqual(first["value"], second["value"])

    def test_product_creation_can_auto_generate_configured_barcode(self):
        from app.barcodes.barcode_service import validate_identifier
        from app.core.config import reset_config_cache
        from app.inventory.inventory_service import create_product

        os.environ["POS_AUTO_GENERATE_BARCODES"] = "true"
        os.environ["POS_DEFAULT_BARCODE_FORMAT"] = "EAN13"
        reset_config_cache()
        product = create_product(
            self.manager, sku="AUTO-EAN", name="Auto EAN", selling_price=5
        )
        self.assertEqual(validate_identifier(product["barcode"], "EAN13"), product["barcode"])

    def test_manual_assignment_duplicate_prevention_and_lookup(self):
        from app.barcodes.barcode_service import assign_identifier, lookup_product
        from app.core.exceptions import BarcodeError

        supplier = assign_identifier(
            self.admin, self.product["id"], "SUPPLIER-42", "CODE128", "SUPPLIER", False
        )
        self.assertEqual(lookup_product(supplier["value"], session=self.cashier)["id"], self.product["id"])
        self.assertEqual(lookup_product("LBL-ONE", session=self.cashier)["id"], self.product["id"])
        with self.assertRaises(BarcodeError):
            assign_identifier(
                self.admin, self.second["id"], "supplier-42", "CODE128", "SECONDARY", False
            )

    def test_preview_batch_print_reprint_and_reporting(self):
        self.configure_printer()
        from app.barcodes.label_service import preview_label, print_labels, reprint_label_job, supported_templates
        from app.barcodes.reporting import barcode_audit, labels_printed, last_print_dates

        preview = preview_label(self.manager, self.product["id"], "LARGE_PRODUCT", include_cost=True)
        self.assertEqual(preview["structured"]["unit"], "box")
        self.assertEqual(preview["structured"]["cost_price"], 10.0)
        self.assertIn("<svg", preview["svg"])
        self.assertEqual(preview["png"]["status"], "placeholder")
        self.assertEqual(len(supported_templates()), 6)

        printed = print_labels(self.manager, [
            {"product_id": self.product["id"], "quantity": 2},
            {"product_id": self.second["id"], "quantity": 1},
        ], "SMALL_PRODUCT")
        self.assertTrue(printed["success"])
        self.assertEqual(printed["label_count"], 3)
        reprinted = reprint_label_job(self.manager, printed["job_id"])
        self.assertTrue(reprinted["success"])
        self.assertEqual(len(self.printer.jobs), 2)
        self.assertTrue(labels_printed(self.manager))
        self.assertTrue(any(row["last_printed_at"] for row in last_print_dates(self.manager)))
        self.assertEqual(barcode_audit(self.manager), [])

    def test_printer_unavailable_is_safe_and_low_stock_batch_works(self):
        self.configure_printer(available=False)
        from app.barcodes.label_service import print_label, print_low_stock_labels
        from app.database.db_manager import get_connection

        failed = print_label(self.manager, self.product["id"])
        self.assertFalse(failed["success"])
        with get_connection() as conn:
            status = conn.execute("SELECT status FROM label_print_jobs WHERE id = ?", (failed["job_id"],)).fetchone()[0]
        self.assertEqual(status, "FAILED")
        low_stock = print_low_stock_labels(self.manager)
        self.assertFalse(low_stock["success"])

    def test_missing_barcode_and_duplicate_reports(self):
        from app.barcodes.reporting import duplicate_identifiers, products_without_barcode
        from app.database.transactions import transaction

        with transaction() as conn:
            conn.execute("UPDATE product_identifiers SET is_active = 0, is_primary = 0 WHERE product_id = ?", (self.second["id"],))
            conn.execute("UPDATE products SET barcode = NULL WHERE id = ?", (self.second["id"],))
        missing = products_without_barcode(self.manager)
        self.assertEqual([row["id"] for row in missing], [self.second["id"]])
        self.assertEqual(duplicate_identifiers(self.manager), [])

    def test_api_endpoints_authorization_lookup_preview_and_print(self):
        self.configure_printer()
        from app.api.app import create_app
        with TestClient(create_app(initialize=False)) as client:
            def login(username, password):
                token = client.post("/api/v1/auth/login", json={"username": username, "password": password}).json()["data"]["access_token"]
                return {"Authorization": f"Bearer {token}"}
            admin_headers = login("test-admin", "admin-password")
            manager_headers = login("manager1", "manager-password")
            cashier_headers = login("cashier1", "cashier-password")

            self.assertEqual(client.get("/api/v1/barcodes/templates", headers=cashier_headers).status_code, 200)
            lookup = client.get("/api/v1/barcodes/lookup?value=LBL-ONE", headers=cashier_headers)
            self.assertEqual(lookup.json()["data"]["id"], self.product["id"])
            denied = client.post(
                f"/api/v1/barcodes/products/{self.product['id']}/generate",
                headers=cashier_headers, json={"format": "CODE128", "identifier_type": "SECONDARY"},
            )
            self.assertEqual(denied.status_code, 403)
            generated = client.post(
                f"/api/v1/barcodes/products/{self.product['id']}/generate",
                headers=manager_headers, json={"format": "QR", "identifier_type": "QR"},
            )
            self.assertEqual(generated.status_code, 201, generated.text)
            assign_denied = client.post(
                f"/api/v1/barcodes/products/{self.product['id']}/assign",
                headers=manager_headers,
                json={"value": "MANUAL-1", "format": "CODE128", "identifier_type": "SECONDARY", "primary": False},
            )
            self.assertEqual(assign_denied.status_code, 403)
            self.assertEqual(client.post(
                "/api/v1/barcodes/labels/preview", headers=cashier_headers,
                json={"product_id": self.product["id"], "template_code": "SMALL_PRODUCT"},
            ).status_code, 403)
            self.assertEqual(client.post(
                "/api/v1/barcodes/labels/preview", headers=manager_headers,
                json={"product_id": self.product["id"], "template_code": "QR"},
            ).status_code, 200)
            printed = client.post(
                "/api/v1/barcodes/labels/print", headers=manager_headers,
                json={"items": [{"product_id": self.product["id"], "quantity": 1}]},
            )
            self.assertEqual(printed.status_code, 200, printed.text)
            self.assertEqual(client.get(
                "/api/v1/barcodes/reports/labels-printed", headers=admin_headers
            ).status_code, 200)


if __name__ == "__main__":
    unittest.main()
