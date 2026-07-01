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
        from tests.support import bootstrap_staff

        initialize_database()
        self.sessions = bootstrap_staff()

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
        from app.inventory.inventory_service import create_product
        from app.sales.sales_service import create_sale, PAYMENT_CARD
        from app.reports.reporting_service import get_sales_summary

        manager = self.sessions["manager"]
        cashier = self.sessions["cashier"]

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
        from app.inventory.inventory_service import create_product
        from app.sales.sales_service import create_sale, PAYMENT_CARD
        from app.reports.reporting_service import get_daily_sales_report

        manager = self.sessions["manager"]
        cashier = self.sessions["cashier"]

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
        from app.inventory.inventory_service import create_product
        from app.sales.sales_service import create_sale, PAYMENT_CARD
        from app.reports.reporting_service import get_top_selling_products

        manager = self.sessions["manager"]
        cashier = self.sessions["cashier"]

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
    # Sales Report by Date Range
    # ------------------------------------------------------------------

    def test_sales_report_date_range_empty_database(self):
        from app.reports.reporting_service import get_sales_report

        report = get_sales_report("2025-01-01", "2025-12-31")

        self.assertEqual(report["transaction_count"], 0)
        self.assertAlmostEqual(report["total_sales"], 0.0)
        self.assertAlmostEqual(report["total_tax"], 0.0)
        self.assertAlmostEqual(report["average_sale"], 0.0)

    def test_sales_report_date_range_after_sale(self):
        from app.inventory.inventory_service import create_product
        from app.sales.sales_service import create_sale, PAYMENT_CARD
        from app.reports.reporting_service import get_sales_report

        manager = self.sessions["manager"]
        cashier = self.sessions["cashier"]

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

    # ------------------------------------------------------------------
    # Low Stock Report
    # ------------------------------------------------------------------

    def test_low_stock_products_empty_database(self):
        from app.reports.reporting_service import get_low_stock_products

        products = get_low_stock_products()

        self.assertEqual(products, [])

    def test_low_stock_products(self):
        from app.inventory.inventory_service import create_product, deactivate_product
        from app.reports.reporting_service import get_low_stock_products

        manager = self.sessions["manager"]

        create_product(
            manager,
            sku="LOW-001",
            barcode="LOW-001",
            name="Notebook",
            selling_price=20.0,
            cost_price=10.0,
            quantity_in_stock=3,
            reorder_level=5,
        )
        inactive = create_product(
            manager,
            sku="LOW-INACTIVE",
            barcode="LOW-INACTIVE",
            name="Inactive Low Stock",
            selling_price=10.0,
            cost_price=5.0,
            quantity_in_stock=0,
            reorder_level=5,
        )
        deactivate_product(manager, inactive["id"])

        create_product(
            manager,
            sku="HIGH-001",
            barcode="HIGH-001",
            name="Printer",
            selling_price=300.0,
            cost_price=250.0,
            quantity_in_stock=25,
            reorder_level=5,
        )

        products = get_low_stock_products()

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["sku"], "LOW-001")
        self.assertEqual(products[0]["quantity_in_stock"], 3)
        self.assertEqual(products[0]["reorder_level"], 5)
        self.assertNotIn("LOW-INACTIVE", {item["sku"] for item in products})

    # ------------------------------------------------------------------
    # NEW: Sales by Payment Method Report
    # ------------------------------------------------------------------

    def test_payment_method_report_empty_database(self):
        from app.reports.reporting_service import get_payment_method_report

        report = get_payment_method_report()

        self.assertEqual(report, [])

    def test_payment_method_report_after_sales(self):
        from app.inventory.inventory_service import create_product
        from app.sales.sales_service import (
            create_sale,
            PAYMENT_CARD,
            PAYMENT_CASH,
        )
        from app.reports.reporting_service import get_payment_method_report

        manager = self.sessions["manager"]
        cashier = self.sessions["cashier"]

        product = create_product(
            manager,
            sku="PAY-001",
            barcode="PAY-001",
            name="Mouse",
            selling_price=50.0,
            cost_price=25.0,
            quantity_in_stock=100,
            reorder_level=10,
        )

        create_sale(
            cashier,
            [{"product_id": product["id"], "quantity": 2}],
            payment_method=PAYMENT_CARD,
        )

        create_sale(
            cashier,
            [{"product_id": product["id"], "quantity": 1}],
            payment_method=PAYMENT_CASH,
			amount_paid=50.0,
        )

        report = get_payment_method_report()

        self.assertEqual(len(report), 2)

        methods = {item["payment_method"]: item for item in report}

        self.assertEqual(methods[PAYMENT_CARD]["transaction_count"], 1)
        self.assertAlmostEqual(methods[PAYMENT_CARD]["total_sales"], 100.0)

        self.assertEqual(methods[PAYMENT_CASH]["transaction_count"], 1)
        self.assertAlmostEqual(methods[PAYMENT_CASH]["total_sales"], 50.0)

		    # ------------------------------------------------------------------
    # NEW: Inventory Valuation Report
    # ------------------------------------------------------------------

    def test_inventory_valuation_empty_database(self):
        from app.reports.reporting_service import get_inventory_valuation

        report = get_inventory_valuation()

        self.assertEqual(report["total_products"], 0)
        self.assertEqual(report["total_units"], 0)
        self.assertAlmostEqual(report["inventory_cost"], 0.0)
        self.assertAlmostEqual(report["inventory_retail"], 0.0)
        self.assertAlmostEqual(report["potential_profit"], 0.0)

    def test_inventory_valuation_after_products(self):
        from app.inventory.inventory_service import create_product
        from app.reports.reporting_service import get_inventory_valuation

        manager = self.sessions["manager"]

        create_product(
            manager,
            sku="INV-001",
            barcode="INV-001",
            name="Notebook",
            selling_price=20.0,
            cost_price=10.0,
            quantity_in_stock=5,
            reorder_level=2,
        )

        create_product(
            manager,
            sku="INV-002",
            barcode="INV-002",
            name="Printer",
            selling_price=300.0,
            cost_price=250.0,
            quantity_in_stock=2,
            reorder_level=1,
        )

        report = get_inventory_valuation()

        self.assertEqual(report["total_products"], 2)
        self.assertEqual(report["total_units"], 7)
        self.assertAlmostEqual(report["inventory_cost"], 550.0)
        self.assertAlmostEqual(report["inventory_retail"], 700.0)
        self.assertAlmostEqual(report["potential_profit"], 150.0)

    def test_reports_subtract_recorded_returns(self):
        from app.inventory.inventory_service import create_product
        from app.reports.reporting_service import (
            get_payment_method_report,
            get_sales_summary,
            get_top_selling_products,
        )
        from app.sales.sales_service import PAYMENT_CARD, create_sale, process_return

        product = create_product(
            self.sessions["manager"],
            sku="RETURN-REPORT",
            barcode="RETURN-REPORT",
            name="Returnable Item",
            selling_price=20.0,
            cost_price=10.0,
            quantity_in_stock=10,
            reorder_level=2,
        )
        receipt = create_sale(
            self.sessions["cashier"],
            [{"product_id": product["id"], "quantity": 3}],
            payment_method=PAYMENT_CARD,
        )
        process_return(
            self.sessions["manager"],
            receipt["sale"]["sale_id"],
            [{"sale_item_id": receipt["items"][0]["id"], "quantity": 1}],
            "Customer return",
        )

        summary = get_sales_summary()
        payment = get_payment_method_report()[0]
        product_report = get_top_selling_products()[0]
        self.assertAlmostEqual(summary["gross_sales"], 60.0)
        self.assertAlmostEqual(summary["total_refunds"], 20.0)
        self.assertAlmostEqual(summary["total_sales"], 40.0)
        self.assertAlmostEqual(payment["total_sales"], 40.0)
        self.assertEqual(product_report["units_sold"], 2)

    def test_v2_daily_and_date_range_reports_include_discounts_and_profit(self):
        from app.inventory.inventory_service import create_product
        from app.reports.reporting_service import (
            get_daily_sales_report,
            get_date_range_sales_report,
        )
        from app.sales.sales_service import DISCOUNT_FIXED, PAYMENT_CARD, create_sale

        product = create_product(
            self.sessions["manager"],
            sku="V2-DATE",
            barcode="V2-DATE",
            name="Analytics Product",
            selling_price=20.0,
            cost_price=10.0,
            quantity_in_stock=20,
            reorder_level=2,
        )
        create_sale(
            self.sessions["manager"],
            [{"product_id": product["id"], "quantity": 3}],
            payment_method=PAYMENT_CARD,
            discount_type=DISCOUNT_FIXED,
            discount_value=6,
        )
        today = date.today().isoformat()

        daily = get_daily_sales_report(today)
        period = get_date_range_sales_report(today, today)

        for report in (daily, period):
            self.assertAlmostEqual(report["gross_sales"], 60.0)
            self.assertAlmostEqual(report["discount_total"], 6.0)
            self.assertAlmostEqual(report["refund_total"], 0.0)
            self.assertAlmostEqual(report["net_sales"], 54.0)
            self.assertEqual(report["transaction_count"], 1)
            self.assertEqual(report["items_sold"], 3)
            self.assertAlmostEqual(report["estimated_profit"], 24.0)
            self.assertAlmostEqual(report["average_transaction_value"], 54.0)
            self.assertEqual(report["top_selling_products"][0]["sku"], "V2-DATE")

    def test_v2_period_reports_reduce_revenue_profit_and_items_for_refunds(self):
        from app.inventory.inventory_service import create_product
        from app.reports.reporting_service import get_daily_sales_report, get_sales_report
        from app.sales.sales_service import PAYMENT_CARD, create_sale, process_return

        product = create_product(
            self.sessions["manager"],
            sku="V2-RETURN",
            barcode="V2-RETURN",
            name="Refund Analytics Product",
            selling_price=20.0,
            cost_price=10.0,
            quantity_in_stock=20,
            reorder_level=2,
        )
        receipt = create_sale(
            self.sessions["cashier"],
            [{"product_id": product["id"], "quantity": 4}],
            payment_method=PAYMENT_CARD,
        )
        process_return(
            self.sessions["manager"],
            receipt["sale"]["sale_id"],
            [{"sale_item_id": receipt["items"][0]["id"], "quantity": 1}],
            "Analytics refund",
        )
        today = date.today().isoformat()

        for report in (get_daily_sales_report(today), get_sales_report(today, today)):
            self.assertAlmostEqual(report["gross_sales"], 80.0)
            self.assertAlmostEqual(report["refund_total"], 20.0)
            self.assertAlmostEqual(report["net_sales"], 60.0)
            self.assertEqual(report["items_sold"], 3)
            self.assertAlmostEqual(report["estimated_profit"], 30.0)
            self.assertEqual(report["top_selling_products"][0]["items_sold"], 3)

    def test_product_performance_rankings_exclude_inactive_products(self):
        from app.inventory.inventory_service import create_product, deactivate_product
        from app.reports.reporting_service import get_product_performance_report
        from app.sales.sales_service import PAYMENT_CARD, create_sale

        best = create_product(
            self.sessions["manager"], sku="PERF-BEST", barcode="PERF-BEST",
            name="Best Product", selling_price=20.0, cost_price=10.0,
            quantity_in_stock=20, reorder_level=2,
        )
        create_product(
            self.sessions["manager"], sku="PERF-SLOW", barcode="PERF-SLOW",
            name="Slow Product", selling_price=5.0, cost_price=2.0,
            quantity_in_stock=10, reorder_level=2,
        )
        inactive = create_product(
            self.sessions["manager"], sku="PERF-OFF", barcode="PERF-OFF",
            name="Inactive Product", selling_price=1.0, cost_price=0.0,
            quantity_in_stock=1, reorder_level=2,
        )
        missing_cost = create_product(
            self.sessions["manager"], sku="PERF-NOCOST", barcode="PERF-NOCOST",
            name="Missing Cost Product", selling_price=30.0, cost_price=0.0,
            quantity_in_stock=5, reorder_level=1,
        )
        deactivate_product(self.sessions["manager"], inactive["id"])
        create_sale(
            self.sessions["cashier"],
            [{"product_id": best["id"], "quantity": 5},
             {"product_id": missing_cost["id"], "quantity": 1}],
            payment_method=PAYMENT_CARD,
        )

        report = get_product_performance_report(limit=10)

        self.assertEqual(report["best_selling_products"][0]["sku"], "PERF-BEST")
        self.assertEqual(report["highest_revenue_products"][0]["sku"], "PERF-BEST")
        self.assertAlmostEqual(
            next(item for item in report["highest_estimated_profit_products"]
                 if item["sku"] == "PERF-NOCOST")["estimated_profit"],
            30.0,
        )
        worst_skus = {item["sku"] for item in report["worst_selling_active_products"]}
        slow_skus = {item["sku"] for item in report["slow_moving_products"]}
        self.assertIn("PERF-SLOW", worst_skus)
        self.assertIn("PERF-SLOW", slow_skus)
        self.assertNotIn("PERF-OFF", worst_skus)
        self.assertNotIn("PERF-OFF", slow_skus)

    def test_cashier_performance_is_refund_and_discount_aware(self):
        from app.inventory.inventory_service import create_product
        from app.reports.reporting_service import get_cashier_performance_report
        from app.sales.sales_service import (
            DISCOUNT_FIXED,
            PAYMENT_CARD,
            create_sale,
            process_return,
        )

        product = create_product(
            self.sessions["manager"], sku="CASHIER-PERF", barcode="CASHIER-PERF",
            name="Cashier Product", selling_price=20.0, cost_price=10.0,
            quantity_in_stock=20, reorder_level=2,
        )
        first = create_sale(
            self.sessions["cashier"],
            [{"product_id": product["id"], "quantity": 2}],
            payment_method=PAYMENT_CARD,
        )
        create_sale(
            self.sessions["cashier"],
            [{"product_id": product["id"], "quantity": 1}],
            payment_method=PAYMENT_CARD,
        )
        create_sale(
            self.sessions["manager"],
            [{"product_id": product["id"], "quantity": 1}],
            payment_method=PAYMENT_CARD,
            discount_type=DISCOUNT_FIXED,
            discount_value=5,
        )
        process_return(
            self.sessions["manager"],
            first["sale"]["sale_id"],
            [{"sale_item_id": first["items"][0]["id"], "quantity": 1}],
            "Cashier report refund",
        )

        rows = {row["username"]: row for row in get_cashier_performance_report()}
        cashier = rows[self.sessions["cashier"].username]
        manager = rows[self.sessions["manager"].username]

        self.assertEqual(cashier["transaction_count"], 2)
        self.assertAlmostEqual(cashier["gross_sales"], 60.0)
        self.assertAlmostEqual(cashier["refunds"], 20.0)
        self.assertAlmostEqual(cashier["net_sales"], 40.0)
        self.assertEqual(cashier["items_sold"], 2)
        self.assertAlmostEqual(cashier["estimated_profit"], 20.0)
        self.assertAlmostEqual(cashier["average_transaction_value"], 20.0)
        self.assertAlmostEqual(manager["discount_total"], 5.0)

if __name__ == "__main__":
    unittest.main()
