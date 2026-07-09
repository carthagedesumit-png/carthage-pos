import unittest
import os
import tempfile

from fastapi.testclient import TestClient

from app.api.app import app


class DashboardTestCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_dashboard_health(self):
        response = self.client.get("/dashboard/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_dashboard_summary_returns_metrics(self):
        response = self.client.get("/dashboard/api/summary")
        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertIn("today_sales", data)
        self.assertIn("today_profit", data)
        self.assertIn("transactions", data)
        self.assertIn("low_stock", data)
        self.assertIn("inventory_value", data)
        self.assertIn("customers", data)
        self.assertIn("stores", data)
        self.assertIn("users", data)
        self.assertIn("license_status", data)
        self.assertIn("backup_status", data)
        self.assertIn("api_status", data)

    def test_dashboard_page_loads(self):
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Executive Dashboard", response.text)
        self.assertIn("Today's Sales", response.text)
        self.assertIn("Inventory Value", response.text)


class DashboardSalesWorkspaceTestCase(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()
        os.environ["CARTHAGE_POS_DB"] = self.db_file.name

        from app.database.db_manager import initialize_database
        from app.inventory.inventory_service import create_product
        from app.sales.sales_service import PAYMENT_CARD, PAYMENT_CASH, create_sale
        from tests.support import bootstrap_staff

        initialize_database()
        sessions = bootstrap_staff()
        self.admin_session = sessions["admin"]
        self.manager_session = sessions["manager"]
        self.cashier_session = sessions["cashier"]
        self.product = create_product(
            self.manager_session,
            sku="DASH-SALE-1",
            barcode="DASH-SALE-1",
            name="Dashboard Sale Product",
            selling_price=15.0,
            cost_price=8.0,
            quantity_in_stock=50,
            reorder_level=5,
        )
        self.first_sale = create_sale(
            self.cashier_session,
            [{"product_id": self.product["id"], "quantity": 1}],
            payment_method=PAYMENT_CARD,
        )
        self.second_sale = create_sale(
            self.cashier_session,
            [{"product_id": self.product["id"], "quantity": 2}],
            payment_method=PAYMENT_CASH,
            amount_paid=40.0,
        )
        self.client = TestClient(app)

    def tearDown(self):
        os.environ.pop("CARTHAGE_POS_DB", None)
        os.unlink(self.db_file.name)

    def test_sales_workspace_renders_and_preserves_filters(self):
        receipt = self.first_sale["sale"]["receipt_number"]
        response = self.client.get(
            f"/dashboard/sales?payment_method=CARD&search={receipt}&page_size=10"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Sales Workspace", response.text)
        self.assertIn(receipt, response.text)
        self.assertIn('value="CARD" selected', response.text)
        self.assertIn('value="10"', response.text)

    def test_sales_workspace_pagination(self):
        response = self.client.get("/dashboard/sales?page_size=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Page 1 of 2", response.text)
        self.assertIn("Next", response.text)

    def test_sales_api_returns_json_with_filters_and_pagination(self):
        response = self.client.get("/dashboard/api/sales?payment_method=CARD&page_size=1")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("items", data)
        self.assertIn("summary", data)
        self.assertIn("pagination", data)
        self.assertEqual(data["pagination"]["page_size"], 1)
        self.assertEqual(data["items"][0]["payment_method"], "CARD")

    def test_sales_summary_api_returns_json(self):
        response = self.client.get("/dashboard/api/sales-summary")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["transaction_count"], 2)
        self.assertAlmostEqual(data["gross_sales"], 45.0)

    def test_sales_detail_route_handles_existing_sale(self):
        sale_id = self.first_sale["sale"]["sale_id"]
        response = self.client.get(f"/dashboard/sales/{sale_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.first_sale["sale"]["receipt_number"], response.text)
        self.assertIn("Line Items", response.text)
        self.assertIn("Receipt Preview", response.text)

    def test_sales_detail_api_and_route_handle_missing_sale_safely(self):
        page_response = self.client.get("/dashboard/sales/999999")
        self.assertEqual(page_response.status_code, 404)
        self.assertIn("Sale Not Found", page_response.text)

        api_response = self.client.get("/dashboard/api/sales/999999")
        self.assertEqual(api_response.status_code, 200)
        self.assertIsNone(api_response.json()["sale"])


class DashboardSalesEmptyDatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()
        os.environ["CARTHAGE_POS_DB"] = self.db_file.name

        from app.database.db_manager import initialize_database

        initialize_database()
        self.client = TestClient(app)

    def tearDown(self):
        os.environ.pop("CARTHAGE_POS_DB", None)
        os.unlink(self.db_file.name)

    def test_sales_workspace_empty_database_behavior(self):
        response = self.client.get("/dashboard/sales")
        self.assertEqual(response.status_code, 200)
        self.assertIn("No sales match the selected filters.", response.text)

        api_response = self.client.get("/dashboard/api/sales")
        self.assertEqual(api_response.status_code, 200)
        self.assertEqual(api_response.json()["pagination"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
