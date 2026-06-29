import os
import tempfile
import unittest


class InventoryServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()
        os.environ["CARTHAGE_POS_DB"] = self.db_file.name

        from app.database.db_manager import initialize_database
        from auth import authenticate_user, create_user

        initialize_database()
        create_user("admin1", "admin-password", "Admin One", "admin")
        create_user("manager1", "manager-password", "Manager One", "manager")
        create_user("cashier1", "cashier-password", "Cashier One", "cashier")
        self.admin_session = authenticate_user("admin1", "admin-password")
        self.manager_session = authenticate_user("manager1", "manager-password")
        self.cashier_session = authenticate_user("cashier1", "cashier-password")

    def tearDown(self):
        os.environ.pop("CARTHAGE_POS_DB", None)
        os.unlink(self.db_file.name)

    def create_sample_product(self, **overrides):
        from app.inventory.inventory_service import create_product

        data = {
            "sku": "SKU-100",
            "barcode": "BAR-100",
            "name": "Test Product",
            "selling_price": 10.0,
            "cost_price": 6.0,
            "quantity_in_stock": 5,
            "reorder_level": 3,
        }
        data.update(overrides)
        return create_product(self.manager_session, **data)

    def test_product_creation_logs_initial_stock(self):
        from app.database.db_manager import get_connection

        product = self.create_sample_product()

        self.assertEqual(product["sku"], "SKU-100")
        self.assertEqual(product["quantity_in_stock"], 5)
        with get_connection() as conn:
            movement = conn.execute(
                "SELECT movement_type, quantity, previous_quantity, new_quantity, user_id FROM stock_movements WHERE product_id = ?",
                (product["id"],)
            ).fetchone()
        self.assertEqual(movement["movement_type"], "PURCHASE")
        self.assertEqual(movement["quantity"], 5)
        self.assertEqual(movement["previous_quantity"], 0)
        self.assertEqual(movement["new_quantity"], 5)
        self.assertEqual(movement["user_id"], self.manager_session.user_id)

    def test_duplicate_sku_is_rejected(self):
        self.create_sample_product()

        with self.assertRaises(ValueError):
            self.create_sample_product(barcode="BAR-101")

    def test_stock_adjustment_logs_movement(self):
        from app.database.db_manager import get_connection
        from app.inventory.inventory_service import adjust_stock

        product = self.create_sample_product(quantity_in_stock=5)
        updated = adjust_stock(self.admin_session, product["id"], 12, notes="Cycle count")

        self.assertEqual(updated["quantity_in_stock"], 12)
        with get_connection() as conn:
            movement = conn.execute(
                """SELECT movement_type, quantity, previous_quantity, new_quantity, notes
                   FROM stock_movements WHERE product_id = ? ORDER BY id DESC LIMIT 1""",
                (product["id"],)
            ).fetchone()
        self.assertEqual(movement["movement_type"], "ADJUSTMENT")
        self.assertEqual(movement["quantity"], 7)
        self.assertEqual(movement["previous_quantity"], 5)
        self.assertEqual(movement["new_quantity"], 12)
        self.assertEqual(movement["notes"], "Cycle count")

    def test_low_stock_detection(self):
        from app.inventory.inventory_service import get_low_stock_products

        low = self.create_sample_product(sku="LOW-1", barcode="LOW-1", quantity_in_stock=2, reorder_level=3)
        self.create_sample_product(sku="OK-1", barcode="OK-1", quantity_in_stock=10, reorder_level=3)

        results = get_low_stock_products()

        self.assertIn(low["id"], {item["id"] for item in results})
        self.assertNotIn("OK-1", {item["sku"] for item in results})

    def test_receive_stock_logs_purchase_movement(self):
        from app.database.db_manager import get_connection
        from app.inventory.inventory_service import receive_stock

        product = self.create_sample_product(quantity_in_stock=1)
        updated = receive_stock(self.manager_session, product["id"], 4, notes="PO-123")

        self.assertEqual(updated["quantity_in_stock"], 5)
        with get_connection() as conn:
            movement = conn.execute(
                """SELECT movement_type, quantity, previous_quantity, new_quantity, notes
                   FROM stock_movements WHERE product_id = ? ORDER BY id DESC LIMIT 1""",
                (product["id"],)
            ).fetchone()
        self.assertEqual(movement["movement_type"], "PURCHASE")
        self.assertEqual(movement["quantity"], 4)
        self.assertEqual(movement["previous_quantity"], 1)
        self.assertEqual(movement["new_quantity"], 5)
        self.assertEqual(movement["notes"], "PO-123")

    def test_role_restrictions(self):
        from auth import AuthorizationError
        from app.inventory.inventory_service import create_product

        with self.assertRaises(AuthorizationError):
            create_product(
                self.cashier_session,
                sku="DENIED",
                barcode="DENIED",
                name="Denied Product",
                selling_price=1.0,
            )

        product = create_product(
            self.admin_session,
            sku="ADMIN-1",
            barcode="ADMIN-1",
            name="Admin Product",
            selling_price=1.0,
        )
        self.assertEqual(product["sku"], "ADMIN-1")


if __name__ == "__main__":
    unittest.main()