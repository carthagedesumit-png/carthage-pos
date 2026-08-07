import os
import tempfile
import unittest
from unittest.mock import patch


class PlatformHardeningTestCase(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()
        os.environ["CARTHAGE_POS_DB"] = self.db_file.name

        from app.core.config import reset_config_cache
        from app.database.db_manager import initialize_database

        reset_config_cache()
        initialize_database()

    def tearDown(self):
        from app.core.config import reset_config_cache

        for name in (
            "CARTHAGE_POS_DB",
            "POS_BUSINESS_NAME",
            "POS_DEFAULT_TAX_RATE",
            "POS_RECEIPT_WIDTH_MM",
            "POS_INVOICE_PREFIX",
            "POS_REPORT_DEFAULT_LIMIT",
        ):
            os.environ.pop(name, None)
        reset_config_cache()
        os.unlink(self.db_file.name)

    def test_exception_hierarchy_preserves_value_error_compatibility(self):
        from app.core.exceptions import (
            ApplicationError,
            DocumentError,
            InventoryError,
            ProcurementError,
            TransferError,
            ValidationError,
        )

        for error_type in (
            ValidationError,
            DocumentError,
            InventoryError,
            ProcurementError,
            TransferError,
        ):
            self.assertTrue(issubclass(error_type, ApplicationError))
            self.assertTrue(issubclass(error_type, ValueError))

    def test_shared_validation_normalizes_and_rejects_invalid_values(self):
        from app.core.exceptions import ValidationError
        from app.core.validation import (
            non_negative_number,
            normalized_email,
            positive_int,
            required_text,
        )

        self.assertEqual(required_text("  Main Store  ", "Name"), "Main Store")
        self.assertEqual(normalized_email("  OWNER@EXAMPLE.COM "), "owner@example.com")
        self.assertEqual(positive_int("4"), 4)
        self.assertEqual(non_negative_number("2.5", "Cost"), 2.5)
        for value in (0, -1, 1.5, True, "invalid"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    positive_int(value)

    def test_central_configuration_loads_validated_environment_values(self):
        from app.core.config import get_config, reset_config_cache
        from app.documents.branding import load_branding

        os.environ.update(
            {
                "POS_BUSINESS_NAME": "Global Retail Ltd",
                "POS_DEFAULT_TAX_RATE": "0.075",
                "POS_RECEIPT_WIDTH_MM": "58",
                "POS_INVOICE_PREFIX": "TAX-INV",
                "POS_REPORT_DEFAULT_LIMIT": "25",
            }
        )
        reset_config_cache()
        config = get_config()

        self.assertEqual(config.company.name, "Global Retail Ltd")
        self.assertEqual(config.tax_rate, 0.075)
        self.assertEqual(config.receipt.width_mm, 58)
        self.assertEqual(config.numbering.invoice_prefix, "TAX-INV")
        self.assertEqual(config.reports.default_limit, 25)
        self.assertEqual(load_branding().business_name, "Global Retail Ltd")

    def test_transaction_rolls_back_every_write_after_failure(self):
        from app.database.db_manager import get_connection
        from app.database.transactions import transaction

        with self.assertRaisesRegex(RuntimeError, "injected failure"):
            with transaction() as conn:
                conn.execute(
                    "INSERT INTO categories (name, description) VALUES (?, ?)",
                    ("Rollback Category", "must not persist"),
                )
                conn.execute(
                    "INSERT INTO suppliers (name, is_active) VALUES (?, 1)",
                    ("Rollback Supplier",),
                )
                raise RuntimeError("injected failure")

        with get_connection() as conn:
            category_count = conn.execute(
                "SELECT COUNT(*) FROM categories WHERE name = 'Rollback Category'"
            ).fetchone()[0]
            supplier_count = conn.execute(
                "SELECT COUNT(*) FROM suppliers WHERE name = 'Rollback Supplier'"
            ).fetchone()[0]
        self.assertEqual(category_count, 0)
        self.assertEqual(supplier_count, 0)

    def test_sale_failure_rolls_back_sale_stock_and_audit_rows(self):
        from app.database.db_manager import get_connection
        from app.inventory.inventory_service import create_product
        from app.sales.sales_service import create_sale
        from tests.support import bootstrap_staff

        sessions = bootstrap_staff()
        product = create_product(
            sessions["manager"],
            sku="ATOMIC-SALE",
            name="Atomic Sale Product",
            selling_price=10,
            cost_price=4,
            quantity_in_stock=5,
        )

        from app.sales import sales_service

        real_stock_write = sales_service.record_sale_stock_movement

        def fail_after_stock_write(*args, **kwargs):
            real_stock_write(*args, **kwargs)
            raise RuntimeError("injected failure")

        with patch.object(
            sales_service,
            "record_sale_stock_movement",
            side_effect=fail_after_stock_write,
        ):
            with self.assertRaisesRegex(RuntimeError, "injected failure"):
                create_sale(
                    sessions["cashier"],
                    [{"product_id": product["id"], "quantity": 2}],
                    amount_paid=20,
                )

        with get_connection() as conn:
            sale_count = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
            stock = conn.execute(
                "SELECT quantity_in_stock FROM products WHERE id = ?", (product["id"],)
            ).fetchone()[0]
            sale_movements = conn.execute(
                "SELECT COUNT(*) FROM stock_movements WHERE movement_type = 'SALE'"
            ).fetchone()[0]
        self.assertEqual(sale_count, 0)
        self.assertEqual(stock, 5)
        self.assertEqual(sale_movements, 0)

    def test_authentication_logging_excludes_passwords(self):
        from auth import authenticate_user
        from tests.support import bootstrap_staff

        bootstrap_staff(include_manager=False, include_cashier=False)
        with self.assertLogs("carthage_pos.authentication", level="INFO") as captured:
            self.assertIsNone(authenticate_user("test-admin", "not-the-password"))

        output = "\n".join(captured.output)
        self.assertIn("authentication_failed", output)
        self.assertNotIn("not-the-password", output)
        self.assertNotIn("password_hash", output)


if __name__ == "__main__":
    unittest.main()
