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

    def create_cashier_session(self):
        from tests.support import bootstrap_staff

        return bootstrap_staff(include_manager=False)["cashier"]

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

    def test_checkout_records_user_identity_and_decrements_stock(self):
        from app.core.pos_engine import ShoppingCart
        from app.database.db_manager import get_connection
        from app.ui.terminal_ui import commit_transaction

        session = self.create_cashier_session()
        cart = ShoppingCart()
        self.assertTrue(cart.add_item("1002", 2)["success"])

        commit_transaction(cart.calculate_totals(), session=session)

        with get_connection() as conn:
            sale = conn.execute(
                """SELECT user_id, username, cashier_name, total
                   FROM sales ORDER BY sale_id DESC LIMIT 1"""
            ).fetchone()
            stock = conn.execute(
                "SELECT stock FROM inventory WHERE product_id = '1002'"
            ).fetchone()["stock"]

        self.assertEqual(sale["user_id"], session.user_id)
        self.assertEqual(sale["username"], "cashier1")
        self.assertEqual(sale["cashier_name"], "cashier1")
        self.assertAlmostEqual(sale["total"], 183.83)
        self.assertEqual(stock, 22)


if __name__ == "__main__":
    unittest.main()
