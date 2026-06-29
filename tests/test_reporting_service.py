import os
import tempfile
import unittest
from datetime import date


class ReportingServiceTestCase(unittest.TestCase):

    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()

        os.environ["CARTHAGE_POS_DB"] = self.db_file.name

        from app.database.db_manager import initialize_database

        initialize_database()

    def tearDown(self):
        os.environ.pop("CARTHAGE_POS_DB", None)
        os.unlink(self.db_file.name)

    def test_empty_database_returns_zero_summary(self):
        from app.reports.reporting_service import get_sales_summary

        summary = get_sales_summary()

        self.assertEqual(summary["transaction_count"], 0)
        self.assertEqual(summary["total_sales"], 0.0)
        self.assertEqual(summary["total_tax"], 0.0)
        self.assertEqual(summary["average_sale"], 0.0)

    def test_sales_summary_after_single_sale(self):
        from auth import create_user, authenticate_user
        from app.inventory.inventory_service import create_product
        from app.sales.sales_service import create_sale, PAYMENT_CARD
        from app.reports.reporting_service import get_sales_summary

        create_user("manager", "password", "Manager", "manager")
        create_user("cashier", "password", "Cashier", "cashier")

        manager = authenticate_user("manager", "password")
        cashier = authenticate_user("cashier", "password")

        product = create_product(
            manager,
            sku="REPORT-1",
            barcode="REPORT-1",
            name="Notebook",
            selling_price=25.0,
            cost_price=10.0,
            quantity_in_stock=20,
            reorder_level=5,
        )

        create_sale(
            cashier,
            [{"product_id": product["id"], "quantity": 2}],
            payment_method=PAYMENT_CARD,
        )

        summary = get_sales_summary()

        self.assertEqual(summary["transaction_count"], 1)
        self.assertAlmostEqual(summary["total_sales"], 50.0)
        self.assertAlmostEqual(summary["average_sale"], 50.0)
        self.assertAlmostEqual(summary["total_tax"], 0.0)

    def test_daily_sales_report_empty_database(self):
        from app.reports.reporting_service import get_daily_sales_report

        report = get_daily_sales_report()

        self.assertEqual(report["transaction_count"], 0)
        self.assertAlmostEqual(report["total_sales"], 0.0)
        self.assertAlmostEqual(report["total_tax"], 0.0)
        self.assertAlmostEqual(report["average_sale"], 0.0)

    def test_daily_sales_report_after_sale(self):
        from auth import create_user, authenticate_user
        from app.inventory.inventory_service import create_product
        from app.sales.sales_service import create_sale, PAYMENT_CARD
        from app.reports.reporting_service import get_daily_sales_report

        create_user("manager", "password", "Manager", "manager")
        create_user("cashier", "password", "Cashier", "cashier")

        manager = authenticate_user("manager", "password")
        cashier = authenticate_user("cashier", "password")

        product = create_product(
            manager,
            sku="DAILY-001",
            barcode="DAILY-001",
            name="Notebook",
            selling_price=30.0,
            cost_price=15.0,
            quantity_in_stock=20,
            reorder_level=5,
        )

        create_sale(
            cashier,
            [{"product_id": product["id"], "quantity": 2}],
            payment_method=PAYMENT_CARD,
        )

        report = get_daily_sales_report()

        self.assertEqual(report["transaction_count"], 1)
        self.assertAlmostEqual(report["total_sales"], 60.0)
        self.assertAlmostEqual(report["total_tax"], 0.0)
        self.assertAlmostEqual(report["average_sale"], 60.0)

    def test_top_selling_products_empty_database(self):
        from app.reports.reporting_service import get_top_selling_products

        products = get_top_selling_products()

        self.assertEqual(products, [])

    def test_top_selling_products_after_sales(self):
        from auth import create_user, authenticate_user
        from app.inventory.inventory_service import create_product
        from app.sales.sales_service import create_sale, PAYMENT_CARD
        from app.reports.reporting_service import get_top_selling_products

        create_user("manager", "password", "Manager", "manager")
        create_user("cashier", "password", "Cashier", "cashier")

        manager = authenticate_user("manager", "password")
        cashier = authenticate_user("cashier", "password")

        notebook = create_product(
            manager,
            sku="BOOK-1",
            barcode="BOOK-1",
            name="Notebook",
            selling_price=20.0,
            cost_price=10.0,
            quantity_in_stock=100,
            reorder_level=5,
        )

        pen = create_product(
            manager,
            sku="PEN-1",
            barcode="PEN-1",
            name="Pen",
            selling_price=5.0,
            cost_price=2.0,
            quantity_in_stock=100,
            reorder_level=5,
        )

        create_sale(
            cashier,
            [{"product_id": notebook["id"], "quantity": 5}],
            payment_method=PAYMENT_CARD,
        )

        create_sale(
            cashier,
            [{"product_id": pen["id"], "quantity": 2}],
            payment_method=PAYMENT_CARD,
        )

        products = get_top_selling_products()

        self.assertEqual(len(products), 2)

        self.assertEqual(products[0]["name"], "Notebook")
        self.assertEqual(products[0]["units_sold"], 5)

        self.assertEqual(products[1]["name"], "Pen")
        self.assertEqual(products[1]["units_sold"], 2)

    # ------------------------------------------------------------------
    # NEW: Sales Report by Date Range
    # ------------------------------------------------------------------

    def test_sales_report_date_range_empty_database(self):
        from app.reports.reporting_service import get_sales_report

        report = get_sales_report("2025-01-01", "2025-12-31")

        self.assertEqual(report["transaction_count"], 0)
        self.assertAlmostEqual(report["total_sales"], 0.0)
        self.assertAlmostEqual(report["total_tax"], 0.0)
        self.assertAlmostEqual(report["average_sale"], 0.0)

    def test_sales_report_date_range_after_sale(self):
        from auth import create_user, authenticate_user
        from app.inventory.inventory_service import create_product
        from app.sales.sales_service import create_sale, PAYMENT_CARD
        from app.reports.reporting_service import get_sales_report

        create_user("manager", "password", "Manager", "manager")
        create_user("cashier", "password", "Cashier", "cashier")

        manager = authenticate_user("manager", "password")
        cashier = authenticate_user("cashier", "password")

        product = create_product(
            manager,
            sku="DATE-001",
            barcode="DATE-001",
            name="Printer Paper",
            selling_price=15.0,
            cost_price=8.0,
            quantity_in_stock=100,
            reorder_level=10,
        )

        create_sale(
            cashier,
            [{"product_id": product["id"], "quantity": 4}],
            payment_method=PAYMENT_CARD,
        )

        today = date.today().isoformat()

        report = get_sales_report(today, today)

        self.assertEqual(report["transaction_count"], 1)
        self.assertAlmostEqual(report["total_sales"], 60.0)
        self.assertAlmostEqual(report["total_tax"], 0.0)
        self.assertAlmostEqual(report["average_sale"], 60.0)


if __name__ == "__main__":
    unittest.main()