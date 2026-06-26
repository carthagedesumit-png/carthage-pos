import os
import tempfile
import unittest


class PosEngineTestCase(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()
        os.environ["CARTHAGE_POS_DB"] = self.db_file.name

        from app.database.db_manager import initialize_database, seed_initial_data

        initialize_database()
        seed_initial_data()

    def tearDown(self):
        os.environ.pop("CARTHAGE_POS_DB", None)
        os.unlink(self.db_file.name)

    def create_cashier(self, username="cashier1"):
        from app.database.db_manager import get_connection
        from auth import AuthenticationSystem

        with get_connection() as conn:
            conn.execute(
                """INSERT INTO users (username, password_hash, role)
                   VALUES (?, ?, ?)""",
                (username, AuthenticationSystem.hash_password("test-password"), "cashier")
            )

    def test_cart_rejects_non_positive_quantities(self):
        from app.core.pos_engine import ShoppingCart

        cart = ShoppingCart()

        self.assertFalse(cart.add_item("1001", 0)["success"])
        self.assertFalse(cart.add_item("1001", -1)["success"])
        self.assertEqual(cart.items, {})

    def test_cart_rejects_stock_overrun(self):
        from app.core.pos_engine import ShoppingCart

        cart = ShoppingCart()
        result = cart.add_item("1004", 9)

        self.assertFalse(result["success"])
        self.assertEqual(cart.items, {})

    def test_checkout_records_cashier_and_decrements_stock(self):
        from app.core.pos_engine import ShoppingCart
        from app.database.db_manager import get_connection
        from app.ui.terminal_ui import commit_transaction

        self.create_cashier()
        cart = ShoppingCart()
        self.assertTrue(cart.add_item("1002", 2)["success"])

        commit_transaction(cart.calculate_totals(), cashier_name="cashier1")

        with get_connection() as conn:
            sale = conn.execute(
                "SELECT cashier_name, total FROM sales ORDER BY sale_id DESC LIMIT 1"
            ).fetchone()
            stock = conn.execute(
                "SELECT stock FROM inventory WHERE product_id = '1002'"
            ).fetchone()["stock"]

        self.assertEqual(sale["cashier_name"], "cashier1")
        self.assertAlmostEqual(sale["total"], 183.825)
        self.assertEqual(stock, 22)


if __name__ == "__main__":
    unittest.main()