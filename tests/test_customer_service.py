import os
import sqlite3
import tempfile
import unittest


class CustomerPlatformTestCase(unittest.TestCase):
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
            sku="CRM-ITEM",
            name="CRM Test Item",
            selling_price=20,
            cost_price=8,
            quantity_in_stock=100,
            reorder_level=5,
        )

    def tearDown(self):
        from app.core.config import reset_config_cache

        for key in tuple(os.environ):
            if key.startswith("POS_LOYALTY_") or key == "CARTHAGE_POS_DB":
                os.environ.pop(key, None)
        reset_config_cache()
        os.unlink(self.db_file.name)

    def create_customer(self, **overrides):
        from app.customers.customer_service import create_customer

        values = {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "phone_number": "+234800000001",
            "email": "ada@example.com",
            "city": "Lagos",
        }
        values.update(overrides)
        return create_customer(self.cashier, **values)

    def test_customer_crud_search_duplicates_and_soft_lifecycle(self):
        from app.core.exceptions import CustomerError
        from app.customers.customer_service import (
            deactivate_customer,
            reactivate_customer,
            search_customers,
            update_customer,
        )

        customer = self.create_customer()
        self.assertTrue(customer["customer_code"].startswith("CUS-"))
        self.assertEqual(search_customers(self.cashier, "lovelace")[0]["id"], customer["id"])
        self.assertEqual(search_customers(self.cashier, "+234800")[0]["id"], customer["id"])
        updated = update_customer(self.manager, customer["id"], business_name="Analytical Engines")
        self.assertEqual(updated["business_name"], "Analytical Engines")

        with self.assertRaisesRegex(CustomerError, "Phone number"):
            self.create_customer(first_name="Grace", last_name="Hopper", email="grace@example.com")
        with self.assertRaisesRegex(CustomerError, "Email address"):
            self.create_customer(first_name="Grace", last_name="Hopper", phone_number="+234800000002")

        self.assertFalse(deactivate_customer(self.manager, customer["id"])["is_active"])
        self.assertEqual(search_customers(self.cashier, customer["customer_code"]), [])
        self.assertTrue(reactivate_customer(self.manager, customer["id"])["is_active"])

    def test_groups_default_discount_and_invalid_group_validation(self):
        from app.core.exceptions import CustomerError
        from app.customers.customer_service import create_customer_group
        from app.sales.sales_service import create_sale

        group = create_customer_group(
            self.manager, "Gold Test", default_discount=10, pricing_priority=50
        )
        customer = self.create_customer(group_id=group["id"])
        receipt = create_sale(
            self.cashier,
            [{"product_id": self.product["id"], "quantity": 1}],
            amount_paid=20,
            customer_id=customer["id"],
        )
        self.assertEqual(receipt["sale"]["discount_amount"], 2.0)
        self.assertEqual(receipt["sale"]["customer_group_id"], group["id"])
        with self.assertRaises(CustomerError):
            self.create_customer(first_name="Bad", last_name="Group", phone_number="3", email="b@g.test", group_id=99999)

    def test_loyalty_earning_partial_redemption_and_non_negative_balance(self):
        from app.core.exceptions import SalesError
        from app.customers.loyalty_service import get_loyalty_balance
        from app.sales.sales_service import create_sale

        customer = self.create_customer()
        first = create_sale(
            self.cashier, [{"product_id": self.product["id"], "quantity": 1}],
            amount_paid=20, customer_id=customer["id"],
        )
        self.assertEqual(first["sale"]["loyalty_points_earned"], 20)
        self.assertEqual(get_loyalty_balance(customer["id"]), 20)

        second = create_sale(
            self.cashier, [{"product_id": self.product["id"], "quantity": 1}],
            amount_paid=20, customer_id=customer["id"], redeem_points=10,
        )
        self.assertEqual(second["sale"]["loyalty_points_redeemed"], 10)
        self.assertEqual(second["sale"]["loyalty_redemption_amount"], 0.1)
        self.assertEqual(get_loyalty_balance(customer["id"]), 29)
        with self.assertRaises(SalesError):
            create_sale(
                self.cashier, [{"product_id": self.product["id"], "quantity": 1}],
                amount_paid=20, customer_id=customer["id"], redeem_points=1000,
            )

    def test_loyalty_configuration_controls_earning_and_redemption(self):
        from app.core.config import reset_config_cache
        from app.customers.loyalty_service import get_loyalty_balance
        from app.sales.sales_service import create_sale

        os.environ["POS_LOYALTY_POINTS_PER_CURRENCY"] = "2"
        os.environ["POS_LOYALTY_MINIMUM_PURCHASE"] = "10"
        os.environ["POS_LOYALTY_REDEMPTION_RATIO"] = "10"
        reset_config_cache()
        customer = self.create_customer()
        first = create_sale(
            self.cashier, [{"product_id": self.product["id"], "quantity": 1}],
            amount_paid=20, customer_id=customer["id"],
        )
        self.assertEqual(first["sale"]["loyalty_points_earned"], 40)
        second = create_sale(
            self.cashier, [{"product_id": self.product["id"], "quantity": 1}],
            amount_paid=19, customer_id=customer["id"], redeem_points=10,
        )
        self.assertEqual(second["sale"]["loyalty_redemption_amount"], 1.0)
        self.assertEqual(get_loyalty_balance(customer["id"]), 68)

    def test_wallet_sale_refund_and_immutable_ledger(self):
        from app.customers.wallet_service import deposit_wallet, get_wallet_balance
        from app.database.db_manager import get_connection
        from app.sales.sales_service import PAYMENT_WALLET, create_sale, refund_sale

        customer = self.create_customer()
        deposit_wallet(self.manager, customer["id"], 50)
        receipt = create_sale(
            self.cashier, [{"product_id": self.product["id"], "quantity": 1}],
            payment_method=PAYMENT_WALLET, customer_id=customer["id"],
        )
        self.assertEqual(receipt["sale"]["payment_method"], "WALLET")
        self.assertEqual(get_wallet_balance(customer["id"]), 30.0)
        refund_sale(self.manager, receipt["sale"]["sale_id"])
        self.assertEqual(get_wallet_balance(customer["id"]), 50.0)
        with self.assertRaises(sqlite3.IntegrityError):
            with get_connection() as conn:
                conn.execute("UPDATE wallet_transactions SET amount_delta = 999 WHERE customer_id = ?", (customer["id"],))

    def test_credit_limit_payment_refund_and_mixed_tenders(self):
        from app.core.exceptions import SalesError
        from app.customers.credit_service import (
            get_credit_outstanding,
            make_credit_payment,
            set_credit_terms,
        )
        from app.customers.wallet_service import deposit_wallet, get_wallet_balance
        from app.sales.sales_service import PAYMENT_CREDIT, PAYMENT_MIXED, create_sale, refund_sale

        customer = self.create_customer()
        set_credit_terms(self.manager, customer["id"], 30, "2026-12-31")
        deposit_wallet(self.manager, customer["id"], 10)
        mixed = create_sale(
            self.cashier, [{"product_id": self.product["id"], "quantity": 1}],
            payment_method=PAYMENT_MIXED, customer_id=customer["id"],
            payments=[
                {"payment_method": "WALLET", "amount": 5},
                {"payment_method": "CREDIT", "amount": 10},
                {"payment_method": "CASH", "amount": 5},
            ],
        )
        self.assertEqual(mixed["sale"]["wallet_amount"], 5.0)
        self.assertEqual(mixed["sale"]["credit_amount"], 10.0)
        self.assertEqual(get_wallet_balance(customer["id"]), 5.0)
        self.assertEqual(get_credit_outstanding(customer["id"]), 10.0)

        make_credit_payment(self.manager, customer["id"], 5)
        self.assertEqual(get_credit_outstanding(customer["id"]), 5.0)
        with self.assertRaises(SalesError):
            create_sale(
                self.cashier, [{"product_id": self.product["id"], "quantity": 2}],
                payment_method=PAYMENT_CREDIT, customer_id=customer["id"],
            )
        refund_sale(self.manager, mixed["sale"]["sale_id"])
        self.assertEqual(get_credit_outstanding(customer["id"]), 0.0)
        self.assertEqual(get_wallet_balance(customer["id"]), 10.0)

    def test_authorization_and_inactive_customer_usage(self):
        from auth import AuthorizationError
        from app.core.exceptions import CustomerError
        from app.customers.customer_service import deactivate_customer, update_customer
        from app.customers.wallet_service import deposit_wallet
        from app.sales.sales_service import create_sale

        customer = self.create_customer()
        with self.assertRaises(AuthorizationError):
            update_customer(self.cashier, customer["id"], city="Abuja")
        with self.assertRaises(AuthorizationError):
            deposit_wallet(self.cashier, customer["id"], 5)
        deactivate_customer(self.manager, customer["id"])
        with self.assertRaises(CustomerError):
            create_sale(
                self.cashier, [{"product_id": self.product["id"], "quantity": 1}],
                amount_paid=20, customer_id=customer["id"],
            )

    def test_customer_reports_and_document_metadata(self):
        from app.customers.credit_service import set_credit_terms
        from app.customers.wallet_service import deposit_wallet
        from app.documents.document_service import generate_sales_invoice, generate_sales_receipt
        from app.reports.reporting_service import (
            get_customer_lifetime_value,
            get_customer_purchase_history,
            get_loyalty_liability_report,
            get_most_loyal_customers,
            get_outstanding_credit_report,
            get_top_customers,
            get_wallet_balances_report,
        )
        from app.sales.sales_service import create_sale

        customer = self.create_customer()
        set_credit_terms(self.manager, customer["id"], 100)
        deposit_wallet(self.manager, customer["id"], 25)
        sale = create_sale(
            self.cashier, [{"product_id": self.product["id"], "quantity": 1}],
            amount_paid=20, customer_id=customer["id"],
        )
        self.assertEqual(get_top_customers()[0]["customer_id"], customer["id"])
        self.assertEqual(get_most_loyal_customers()[0]["loyalty_balance"], 20)
        self.assertEqual(get_wallet_balances_report()[0]["wallet_balance"], 25.0)
        self.assertEqual(get_outstanding_credit_report(), [])
        self.assertEqual(get_loyalty_liability_report()["outstanding_points"], 20)
        self.assertEqual(len(get_customer_purchase_history(customer["id"])), 1)
        self.assertEqual(get_customer_lifetime_value(customer["id"])["lifetime_value"], 20.0)

        receipt = generate_sales_receipt(sale["sale"]["sale_id"])
        invoice = generate_sales_invoice(sale["sale"]["sale_id"])
        self.assertEqual(receipt["customer"]["customer_code"], customer["customer_code"])
        self.assertEqual(receipt["customer"]["points_earned"], 20)
        self.assertIn(customer["customer_code"], receipt["text"])
        self.assertEqual(invoice["customer"]["name"], "Ada Lovelace")

    def test_migration_rerun_preserves_guest_sales_and_backfills_tenders(self):
        from app.database.db_manager import get_connection, initialize_database
        from app.sales.sales_service import create_sale

        guest = create_sale(
            self.cashier, [{"product_id": self.product["id"], "quantity": 1}], amount_paid=20
        )
        initialize_database()
        with get_connection() as conn:
            sale = conn.execute("SELECT customer_id, tender_type FROM sales WHERE sale_id = ?", (guest["sale"]["sale_id"],)).fetchone()
            payment_count = conn.execute("SELECT COUNT(*) FROM sale_payments WHERE sale_id = ?", (guest["sale"]["sale_id"],)).fetchone()[0]
        self.assertIsNone(sale["customer_id"])
        self.assertEqual(sale["tender_type"], "CASH")
        self.assertEqual(payment_count, 1)


class LegacyCustomerMigrationTestCase(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()
        os.environ["CARTHAGE_POS_DB"] = self.db_file.name

    def tearDown(self):
        os.environ.pop("CARTHAGE_POS_DB", None)
        os.unlink(self.db_file.name)

    def test_legacy_sales_schema_upgrades_without_data_loss(self):
        connection = sqlite3.connect(self.db_file.name)
        connection.execute(
            """CREATE TABLE sales (
                   sale_id INTEGER PRIMARY KEY AUTOINCREMENT,
                   receipt_number TEXT,
                   timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                   username TEXT DEFAULT 'system',
                   cashier_name TEXT DEFAULT 'system',
                   subtotal REAL DEFAULT 0,
                   tax REAL DEFAULT 0,
                   total REAL DEFAULT 0,
                   payment_method TEXT DEFAULT 'CASH'
                       CHECK (payment_method IN ('CASH', 'CARD', 'TRANSFER', 'MIXED'))
               )"""
        )
        connection.execute(
            """INSERT INTO sales (
                   receipt_number, username, cashier_name, subtotal, total, payment_method
               ) VALUES ('LEGACY-001', 'system', 'system', 12, 12, 'CASH')"""
        )
        connection.commit()
        connection.close()

        from app.database.db_manager import get_connection, initialize_database

        initialize_database()
        with get_connection() as conn:
            sale = conn.execute(
                """SELECT receipt_number, customer_id, tender_type, total_amount
                   FROM sales WHERE receipt_number = 'LEGACY-001'"""
            ).fetchone()
            payments = conn.execute(
                "SELECT payment_method, amount FROM sale_payments WHERE sale_id = 1"
            ).fetchall()
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        self.assertEqual(sale["receipt_number"], "LEGACY-001")
        self.assertIsNone(sale["customer_id"])
        self.assertEqual(sale["tender_type"], "CASH")
        self.assertEqual(sale["total_amount"], 12)
        self.assertEqual([(row["payment_method"], row["amount"]) for row in payments], [("CASH", 12)])
        self.assertTrue(
            {"customers", "customer_groups", "loyalty_transactions",
             "wallet_transactions", "credit_transactions"}.issubset(tables)
        )


if __name__ == "__main__":
    unittest.main()
