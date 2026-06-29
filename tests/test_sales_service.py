import os
import tempfile
import unittest


class SalesServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()
        os.environ["CARTHAGE_POS_DB"] = self.db_file.name

        from app.database.db_manager import initialize_database
        from auth import authenticate_user, create_user
        from app.inventory.inventory_service import create_product

        initialize_database()
        create_user("manager1", "manager-password", "Manager One", "manager")
        create_user("cashier1", "cashier-password", "Cashier One", "cashier")
        self.manager_session = authenticate_user("manager1", "manager-password")
        self.cashier_session = authenticate_user("cashier1", "cashier-password")
        self.product = create_product(
            self.manager_session,
            sku="SALE-1",
            barcode="SALE-1",
            name="Sale Product",
            selling_price=20.0,
            cost_price=10.0,
            quantity_in_stock=10,
            reorder_level=2,
        )

    def tearDown(self):
        os.environ.pop("CARTHAGE_POS_DB", None)
        os.unlink(self.db_file.name)

    def test_cash_payment_records_change_and_stock_movement(self):
        from app.database.db_manager import get_connection
        from app.sales.sales_service import PAYMENT_CASH, create_sale

        receipt = create_sale(
            self.cashier_session,
            [{"product_id": self.product["id"], "quantity": 2}],
            payment_method=PAYMENT_CASH,
            amount_paid=50.0,
        )

        sale = receipt["sale"]
        self.assertEqual(sale["payment_method"], "CASH")
        self.assertEqual(sale["payment_status"], "PAID")
        self.assertAlmostEqual(sale["total_amount"], 40.0)
        self.assertAlmostEqual(sale["change_given"], 10.0)
        with get_connection() as conn:
            product_stock = conn.execute("SELECT quantity_in_stock FROM products WHERE id = ?", (self.product["id"],)).fetchone()[0]
            movement = conn.execute("SELECT movement_type, quantity, previous_quantity, new_quantity FROM stock_movements ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(product_stock, 8)
        self.assertEqual(movement["movement_type"], "SALE")
        self.assertEqual(movement["quantity"], -2)
        self.assertEqual(movement["previous_quantity"], 10)
        self.assertEqual(movement["new_quantity"], 8)

    def test_card_payment_defaults_to_exact_paid(self):
        from app.sales.sales_service import PAYMENT_CARD, create_sale

        receipt = create_sale(
            self.cashier_session,
            [{"product_id": self.product["id"], "quantity": 1}],
            payment_method=PAYMENT_CARD,
        )

        self.assertEqual(receipt["sale"]["payment_method"], "CARD")
        self.assertAlmostEqual(receipt["sale"]["amount_paid"], 20.0)
        self.assertAlmostEqual(receipt["sale"]["change_given"], 0.0)

    def test_discounts_and_taxes(self):
        from app.sales.sales_service import DISCOUNT_FIXED, DISCOUNT_PERCENTAGE, calculate_totals

        percent = calculate_totals(
            [{"product_id": self.product["id"], "quantity": 2}],
            discount_type=DISCOUNT_PERCENTAGE,
            discount_value=10,
            tax_rate=0.10,
        )
        fixed = calculate_totals(
            [{"product_id": self.product["id"], "quantity": 2}],
            discount_type=DISCOUNT_FIXED,
            discount_value=5,
            tax_rate=0.10,
        )

        self.assertAlmostEqual(percent["subtotal"], 40.0)
        self.assertAlmostEqual(percent["discount_amount"], 4.0)
        self.assertAlmostEqual(percent["tax_amount"], 3.6)
        self.assertAlmostEqual(percent["total_amount"], 39.6)
        self.assertAlmostEqual(fixed["discount_amount"], 5.0)
        self.assertAlmostEqual(fixed["total_amount"], 38.5)

    def test_receipt_generation_is_sequential(self):
        from app.sales.sales_service import PAYMENT_CARD, create_sale

        first = create_sale(self.cashier_session, [{"product_id": self.product["id"], "quantity": 1}], payment_method=PAYMENT_CARD)
        second = create_sale(self.cashier_session, [{"product_id": self.product["id"], "quantity": 1}], payment_method=PAYMENT_CARD)

        self.assertRegex(first["sale"]["receipt_number"], r"^POS-\d{8}-0001$")
        self.assertRegex(second["sale"]["receipt_number"], r"^POS-\d{8}-0002$")

    def test_return_restores_stock_and_prevents_duplicate_over_return(self):
        from app.database.db_manager import get_connection
        from app.sales.sales_service import PAYMENT_CARD, create_sale, process_return

        receipt = create_sale(self.cashier_session, [{"product_id": self.product["id"], "quantity": 3}], payment_method=PAYMENT_CARD)
        sale_id = receipt["sale"]["sale_id"]
        sale_item_id = receipt["items"][0]["id"]

        sales_return = process_return(
            self.manager_session,
            sale_id,
            [{"sale_item_id": sale_item_id, "quantity": 2}],
            "Customer return",
        )

        self.assertAlmostEqual(sales_return["return"]["total_refunded"], 40.0)
        with get_connection() as conn:
            stock = conn.execute("SELECT quantity_in_stock FROM products WHERE id = ?", (self.product["id"],)).fetchone()[0]
            movement = conn.execute("SELECT movement_type, quantity, new_quantity FROM stock_movements ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(stock, 9)
        self.assertEqual(movement["movement_type"], "RETURN")
        self.assertEqual(movement["quantity"], 2)
        self.assertEqual(movement["new_quantity"], 9)

        with self.assertRaises(ValueError):
            process_return(
                self.manager_session,
                sale_id,
                [{"sale_item_id": sale_item_id, "quantity": 2}],
                "Duplicate return",
            )

    def test_refund_sale_restores_all_stock(self):
        from app.database.db_manager import get_connection
        from app.sales.sales_service import PAYMENT_CARD, create_sale, refund_sale

        receipt = create_sale(self.cashier_session, [{"product_id": self.product["id"], "quantity": 2}], payment_method=PAYMENT_CARD)
        refund = refund_sale(self.manager_session, receipt["sale"]["sale_id"], reason="Full refund")

        self.assertAlmostEqual(refund["return"]["total_refunded"], 40.0)
        with get_connection() as conn:
            stock = conn.execute("SELECT quantity_in_stock FROM products WHERE id = ?", (self.product["id"],)).fetchone()[0]
        self.assertEqual(stock, 10)

    def test_insufficient_payment_is_rejected(self):
        from app.sales.sales_service import PAYMENT_CASH, create_sale, process_payment

        with self.assertRaises(ValueError):
            process_payment(20.0, PAYMENT_CASH, amount_paid=19.99)
        with self.assertRaises(ValueError):
            create_sale(
                self.cashier_session,
                [{"product_id": self.product["id"], "quantity": 1}],
                payment_method=PAYMENT_CASH,
                amount_paid=5.0,
            )

    def test_invalid_quantities_are_rejected(self):
        from app.sales.sales_service import PAYMENT_CARD, create_sale

        with self.assertRaises(ValueError):
            create_sale(
                self.cashier_session,
                [{"product_id": self.product["id"], "quantity": 0}],
                payment_method=PAYMENT_CARD,
            )


if __name__ == "__main__":
    unittest.main()