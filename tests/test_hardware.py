import os
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from fastapi.testclient import TestClient


class HardwareIntegrationTestCase(unittest.TestCase):
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
            self.manager,
            sku="HW-SKU-1",
            barcode="0123456789012",
            name="Hardware Test Product",
            selling_price=10,
            cost_price=4,
            quantity_in_stock=50,
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

    def configure_mocks(self, **settings_changes):
        from app.core.config import get_config
        from app.hardware.adapters import (
            MockBarcodeScanner,
            MockCashDrawer,
            MockCustomerDisplay,
            MockPrinter,
        )
        from app.hardware.manager import HardwareManager, configure_hardware_manager

        settings = replace(
            get_config().hardware,
            printer_enabled=True,
            cash_drawer_enabled=True,
            scanner_enabled=True,
            customer_display_enabled=True,
            **settings_changes,
        )
        self.printer = MockPrinter()
        self.drawer = MockCashDrawer()
        self.scanner = MockBarcodeScanner()
        self.display = MockCustomerDisplay()
        manager = HardwareManager(settings, self.printer, self.drawer, self.scanner, self.display)
        configure_hardware_manager(manager)
        return manager

    def create_sale(self):
        from app.sales.sales_service import create_sale

        return create_sale(
            self.cashier,
            [{"product_id": self.product["id"], "quantity": 1}],
            payment_method="CASH",
            amount_paid=20,
        )

    def test_mock_printer_prints_receipt_invoice_credit_note_and_test_page(self):
        self.configure_mocks(printer_profile="58mm")
        from app.hardware.hardware_service import (
            print_credit_note,
            print_invoice,
            print_receipt,
            print_test_page,
        )
        from app.sales.sales_service import refund_sale

        sale = self.create_sale()
        self.assertTrue(print_receipt(self.cashier, sale["sale"]["sale_id"])["success"])
        self.assertTrue(print_invoice(self.cashier, sale["sale"]["sale_id"])["success"])
        sales_return = refund_sale(self.manager, sale["sale"]["sale_id"])
        self.assertTrue(print_credit_note(self.manager, sales_return["return"]["id"])["success"])
        self.assertTrue(print_test_page(self.manager)["success"])
        self.assertEqual(len(self.printer.jobs), 4)
        self.assertTrue(all(job["profile"] == "58mm" for job in self.printer.jobs))
        self.assertIn("Sales Receipt", self.printer.jobs[0]["text"])

    def test_unavailable_printer_returns_safe_fallback_and_audits_failure(self):
        manager = self.configure_mocks()
        manager.printer.available = False
        from app.database.db_manager import get_connection
        from app.hardware.hardware_service import print_receipt

        sale = self.create_sale()
        result = print_receipt(self.cashier, sale["sale"]["sale_id"])
        self.assertFalse(result["success"])
        with get_connection() as conn:
            event = conn.execute(
                "SELECT success, device_type, operation FROM hardware_events ORDER BY id DESC LIMIT 1"
            ).fetchone()
        self.assertEqual((event["success"], event["device_type"], event["operation"]), (0, "printer", "print"))

    def test_cash_drawer_authorization_manual_open_and_cash_sale_auto_open(self):
        self.configure_mocks(open_drawer_after_cash_sale=True)
        from auth import AuthorizationError
        from app.database.db_manager import get_connection
        from app.hardware.hardware_service import open_cash_drawer
        from app.ui.terminal_ui import commit_transaction

        with self.assertRaises(AuthorizationError):
            open_cash_drawer(self.cashier)
        self.assertTrue(open_cash_drawer(self.manager, reason="Cash count verification")["success"])
        self.assertEqual(self.drawer.open_count, 1)

        cart_data = {
            "items": [{"product_id": self.product["id"], "quantity": 1}],
            "grand_total": 10.75,
        }
        receipt = commit_transaction(cart_data, self.cashier, payment_method="CASH")
        self.assertEqual(receipt["sale"]["payment_method"], "CASH")
        self.assertEqual(self.drawer.open_count, 2)
        with get_connection() as conn:
            opens = conn.execute(
                "SELECT COUNT(*) FROM hardware_events WHERE device_type = 'cash_drawer' AND success = 1"
            ).fetchone()[0]
        self.assertEqual(opens, 2)

    def test_scanner_lookup_manual_fallback_invalid_and_duplicate_scans(self):
        manager = self.configure_mocks()
        from app.core.exceptions import ScannerError
        from app.core.pos_engine import ShoppingCart
        from app.hardware.hardware_service import lookup_scanned_product

        product = lookup_scanned_product(self.cashier, "  0123456789012\r\n")
        self.assertEqual(product["id"], self.product["id"])
        cart = ShoppingCart(store_id=self.cashier.store_id)
        self.assertTrue(cart.add_item(product["id"], 1)["success"])
        self.assertTrue(cart.add_item(product["id"], 1)["success"])
        self.assertEqual(cart.items[product["id"]], 2)
        with self.assertRaises(ScannerError):
            lookup_scanned_product(self.cashier, "UNKNOWN-BARCODE")

        manager.scanner.enabled = False
        fallback = lookup_scanned_product(
            self.cashier, "HW-SKU-1", allow_manual_fallback=True
        )
        self.assertEqual(fallback["id"], self.product["id"])

    def test_customer_display_mock_tracks_all_supported_states(self):
        self.configure_mocks()
        from app.hardware.hardware_service import (
            clear_display,
            show_cart_item,
            show_payment_confirmation,
            show_totals,
            show_welcome,
        )

        self.assertTrue(show_welcome(self.cashier)["success"])
        show_cart_item(self.cashier, "Hardware Test Product", 2, 10)
        show_totals(self.cashier, 20, 21.5)
        show_payment_confirmation(self.cashier, 21.5)
        clear_display(self.cashier)
        self.assertEqual(
            [entry["mode"] for entry in self.display.history],
            ["welcome", "item", "total", "payment", "clear"],
        )
        self.assertEqual(self.display.state, {"mode": "clear"})

    def test_hardware_api_endpoints_and_terminal_receipt_compatibility(self):
        self.configure_mocks()
        from app.api.app import create_app
        from app.ui.terminal_ui import print_receipt as terminal_print_receipt

        sale = self.create_sale()
        with TestClient(create_app(initialize=False)) as client:
            manager_token = client.post(
                "/api/v1/auth/login",
                json={"username": "manager1", "password": "manager-password"},
            ).json()["data"]["access_token"]
            cashier_token = client.post(
                "/api/v1/auth/login",
                json={"username": "cashier1", "password": "cashier-password"},
            ).json()["data"]["access_token"]
            manager_headers = {"Authorization": f"Bearer {manager_token}"}
            cashier_headers = {"Authorization": f"Bearer {cashier_token}"}

            status_response = client.get("/api/v1/hardware/status", headers=cashier_headers)
            self.assertEqual(status_response.status_code, 200)
            self.assertTrue(status_response.json()["data"]["printer"]["available"])
            self.assertEqual(client.post("/api/v1/hardware/printer/test", headers=manager_headers).status_code, 200)
            self.assertEqual(
                client.post(
                    f"/api/v1/hardware/printer/receipts/{sale['sale']['sale_id']}",
                    headers=cashier_headers,
                ).status_code,
                403,
            )
            self.assertEqual(
                client.post(
                    f"/api/v1/hardware/printer/receipts/{sale['sale']['sale_id']}",
                    headers=manager_headers,
                ).status_code,
                200,
            )
            self.assertEqual(client.post("/api/v1/hardware/cash-drawer/open", headers=cashier_headers,
                                         json={"reason":"Till inspection"}).status_code, 403)
            lookup = client.post(
                "/api/v1/hardware/scanner/lookup",
                headers=cashier_headers,
                json={"value": "0123456789012"},
            )
            self.assertEqual(lookup.status_code, 200)
            self.assertEqual(lookup.json()["data"]["id"], self.product["id"])
            self.assertEqual(
                client.post(
                    "/api/v1/hardware/display/test",
                    headers=manager_headers,
                    json={"message": "Display ready"},
                ).status_code,
                200,
            )

        with patch("app.ui.terminal_ui.clear_screen"), patch("builtins.print") as output:
            terminal_print_receipt(sale)
        self.assertTrue(output.called)

    def test_invalid_printer_profile_and_hardware_configuration(self):
        from app.core.config import get_config, reset_config_cache
        from app.core.exceptions import ConfigurationError, PrinterError
        from app.hardware.manager import build_hardware_manager

        with self.assertRaises(PrinterError):
            build_hardware_manager(replace(get_config().hardware, printer_profile="invalid"))
        os.environ["POS_CASH_DRAWER_ENABLED"] = "sometimes"
        reset_config_cache()
        with self.assertRaises(ConfigurationError):
            get_config()

    def test_reprint_is_marked_audited_and_does_not_mutate_sale_or_stock(self):
        self.configure_mocks(receipt_copies=2)
        from app.database.db_manager import get_connection
        from app.hardware.hardware_service import print_receipt

        sale = self.create_sale()
        sale_id = sale["sale"]["sale_id"]
        with get_connection() as conn:
            before = (
                conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM sale_payments").fetchone()[0],
                conn.execute("SELECT quantity_on_hand FROM store_inventory WHERE product_id=?",
                             (self.product["id"],)).fetchone()[0],
            )
        result = print_receipt(self.manager, sale_id, reprint=True)
        self.assertTrue(result["success"]);self.assertEqual(result["copies_completed"], 2)
        self.assertTrue(all("REPRINT" in job["text"] for job in self.printer.jobs))
        with get_connection() as conn:
            after = (
                conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM sale_payments").fetchone()[0],
                conn.execute("SELECT quantity_on_hand FROM store_inventory WHERE product_id=?",
                             (self.product["id"],)).fetchone()[0],
            )
            event = conn.execute("SELECT sale_id,attempt_type FROM hardware_events ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(before, after);self.assertEqual((event["sale_id"],event["attempt_type"]),(sale_id,"REPRINT"))

    def test_failed_original_print_is_retryable_after_sale_commit(self):
        self.configure_mocks()
        from app.database.db_manager import get_connection
        from app.hardware.hardware_service import print_receipt

        sale = self.create_sale();self.printer.fail_next=True
        failed = print_receipt(self.cashier, sale["sale"]["sale_id"])
        self.assertFalse(failed["success"]);self.assertTrue(failed["retryable"])
        retried = print_receipt(self.manager, sale["sale"]["sale_id"], reprint=True)
        self.assertTrue(retried["success"])
        with get_connection() as conn:self.assertEqual(conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0],1)

    def test_manual_drawer_reason_is_required_sanitized_and_audited(self):
        self.configure_mocks()
        from app.core.exceptions import HardwareError
        from app.database.db_manager import get_connection
        from app.hardware.hardware_service import open_cash_drawer

        with self.assertRaises(HardwareError):open_cash_drawer(self.manager,reason="")
        self.assertTrue(open_cash_drawer(self.manager,reason="Till check\r\nsecond line")["success"])
        with get_connection() as conn:event=conn.execute("SELECT reason,user_id,store_id FROM hardware_events ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(event["reason"],"Till check  second line");self.assertEqual(event["user_id"],self.manager.user_id);self.assertEqual(event["store_id"],self.manager.store_id)

    def test_receipt_copy_configuration_is_bounded(self):
        from app.core.config import get_config
        from app.core.exceptions import ConfigurationError
        from app.hardware.manager import build_hardware_manager
        with self.assertRaises(ConfigurationError):build_hardware_manager(replace(get_config().hardware,receipt_copies=4))


if __name__ == "__main__":
    unittest.main()
