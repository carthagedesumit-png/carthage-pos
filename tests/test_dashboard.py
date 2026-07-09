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


class DashboardInventoryWorkspaceTestCase(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()
        os.environ["CARTHAGE_POS_DB"] = self.db_file.name

        from app.database.db_manager import initialize_database
        from app.inventory.inventory_service import create_product, update_product
        from tests.support import bootstrap_staff

        initialize_database()
        sessions = bootstrap_staff()
        self.admin_session = sessions["admin"]
        self.manager_session = sessions["manager"]
        self.client = TestClient(app)
        self.in_stock = create_product(
            self.manager_session,
            sku="DASH-INV-1",
            barcode="DASH-INV-1",
            name="Dashboard Inventory Product",
            selling_price=25.0,
            cost_price=12.0,
            quantity_in_stock=10,
            reorder_level=3,
        )
        self.low_stock = create_product(
            self.manager_session,
            sku="DASH-LOW-1",
            barcode="DASH-LOW-1",
            name="Dashboard Low Stock Product",
            selling_price=15.0,
            cost_price=5.0,
            quantity_in_stock=2,
            reorder_level=5,
        )
        self.missing_barcode = create_product(
            self.manager_session,
            sku="DASH-NOBC-1",
            barcode=None,
            name="Dashboard Missing Barcode Product",
            selling_price=9.0,
            cost_price=3.0,
            quantity_in_stock=0,
            reorder_level=2,
        )
        self.inactive = update_product(
            self.manager_session,
            self.missing_barcode["id"],
            is_active=0,
        )

    def tearDown(self):
        os.environ.pop("CARTHAGE_POS_DB", None)
        os.unlink(self.db_file.name)

    def test_inventory_workspace_renders_and_preserves_filters(self):
        response = self.client.get(
            "/dashboard/inventory?search=LOW&low_stock=true&active=all&has_barcode=has&page_size=10"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Inventory Workspace", response.text)
        self.assertIn("Dashboard Low Stock Product", response.text)
        self.assertIn('value="LOW"', response.text)
        self.assertIn('value="all" selected', response.text)
        self.assertIn('value="has" selected', response.text)
        self.assertIn("checked", response.text)

    def test_inventory_workspace_pagination(self):
        response = self.client.get("/dashboard/inventory?active=all&page_size=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Page 1 of 3", response.text)
        self.assertIn("Next", response.text)

    def test_inventory_api_returns_json(self):
        response = self.client.get("/dashboard/api/inventory?search=DASH-INV&page_size=1")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("items", data)
        self.assertIn("summary", data)
        self.assertIn("pagination", data)
        self.assertEqual(data["items"][0]["sku"], "DASH-INV-1")

    def test_inventory_low_stock_and_valuation_endpoints_return_json(self):
        low_response = self.client.get("/dashboard/api/inventory/low-stock")
        self.assertEqual(low_response.status_code, 200)
        self.assertIsInstance(low_response.json(), list)
        self.assertIn("DASH-LOW-1", {item["sku"] for item in low_response.json()})

        valuation_response = self.client.get("/dashboard/api/inventory/valuation")
        self.assertEqual(valuation_response.status_code, 200)
        valuation = valuation_response.json()
        self.assertIn("summary", valuation)
        self.assertIn("by_store", valuation)
        self.assertGreaterEqual(valuation["summary"]["inventory_value"], 130.0)

    def test_inventory_summary_endpoint_returns_json(self):
        response = self.client.get("/dashboard/api/inventory/summary?active=all")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["product_rows"], 3)
        self.assertEqual(data["missing_barcode"], 1)

    def test_product_detail_handles_existing_product(self):
        response = self.client.get(f"/dashboard/inventory/products/{self.in_stock['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Dashboard Inventory Product", response.text)
        self.assertIn("Barcode Identifiers", response.text)
        self.assertIn("Stock Movement History", response.text)

        api_response = self.client.get(f"/dashboard/api/inventory/products/{self.in_stock['id']}")
        self.assertEqual(api_response.status_code, 200)
        self.assertEqual(api_response.json()["product"]["sku"], "DASH-INV-1")

    def test_product_detail_handles_missing_product_safely(self):
        page_response = self.client.get("/dashboard/inventory/products/999999")
        self.assertEqual(page_response.status_code, 404)
        self.assertIn("Product Not Found", page_response.text)

        api_response = self.client.get("/dashboard/api/inventory/products/999999")
        self.assertEqual(api_response.status_code, 200)
        self.assertIsNone(api_response.json()["product"])


class DashboardInventoryEmptyDatabaseTestCase(unittest.TestCase):
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

    def test_inventory_workspace_empty_database_behavior(self):
        response = self.client.get("/dashboard/inventory")
        self.assertEqual(response.status_code, 200)
        self.assertIn("No products match the selected filters.", response.text)

        api_response = self.client.get("/dashboard/api/inventory")
        self.assertEqual(api_response.status_code, 200)
        self.assertEqual(api_response.json()["pagination"]["total"], 0)


class DashboardCrmWorkspaceTestCase(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()
        os.environ["CARTHAGE_POS_DB"] = self.db_file.name

        from app.customers.credit_service import set_credit_terms
        from app.customers.customer_service import create_customer, create_customer_group, deactivate_customer
        from app.customers.wallet_service import deposit_wallet
        from app.database.db_manager import initialize_database
        from app.inventory.inventory_service import create_product
        from app.sales.sales_service import PAYMENT_CASH, PAYMENT_CREDIT, create_sale
        from tests.support import bootstrap_staff

        initialize_database()
        sessions = bootstrap_staff()
        self.manager_session = sessions["manager"]
        self.cashier_session = sessions["cashier"]
        self.client = TestClient(app)
        self.product = create_product(
            self.manager_session,
            sku="DASH-CRM-ITEM",
            barcode="DASH-CRM-ITEM",
            name="Dashboard CRM Item",
            selling_price=20.0,
            cost_price=8.0,
            quantity_in_stock=100,
            reorder_level=5,
        )
        self.vip_group = create_customer_group(
            self.manager_session,
            "Dashboard VIP",
            default_discount=0,
            pricing_priority=50,
        )
        self.customer = create_customer(
            self.cashier_session,
            first_name="Nia",
            last_name="Okafor",
            phone_number="+234811000001",
            email="nia@example.com",
            group_id=self.vip_group["id"],
            city="Lagos",
        )
        deposit_wallet(self.manager_session, self.customer["id"], 50)
        create_sale(
            self.cashier_session,
            [{"product_id": self.product["id"], "quantity": 1}],
            payment_method=PAYMENT_CASH,
            amount_paid=20,
            customer_id=self.customer["id"],
        )
        set_credit_terms(self.manager_session, self.customer["id"], 100, "2026-12-31")
        create_sale(
            self.cashier_session,
            [{"product_id": self.product["id"], "quantity": 1}],
            payment_method=PAYMENT_CREDIT,
            customer_id=self.customer["id"],
        )
        self.other_customer = create_customer(
            self.cashier_session,
            first_name="Tunde",
            last_name="Bello",
            phone_number="+234811000002",
            email="tunde@example.com",
        )
        self.inactive_customer = create_customer(
            self.cashier_session,
            first_name="Mina",
            last_name="Stone",
            phone_number="+234811000003",
            email="mina@example.com",
        )
        deactivate_customer(self.manager_session, self.inactive_customer["id"])

    def tearDown(self):
        os.environ.pop("CARTHAGE_POS_DB", None)
        os.unlink(self.db_file.name)

    def test_crm_workspace_renders_and_preserves_filters(self):
        response = self.client.get(
            "/dashboard/customers?search=Nia&customer_group=Dashboard&active=all"
            "&has_credit=true&has_wallet_balance=true&loyalty_customer=true&page_size=10"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("CRM Workspace", response.text)
        self.assertIn("Nia Okafor", response.text)
        self.assertIn('value="Nia"', response.text)
        self.assertIn('value="Dashboard"', response.text)
        self.assertIn('value="all" selected', response.text)
        self.assertIn("checked", response.text)

    def test_crm_workspace_pagination(self):
        response = self.client.get("/dashboard/customers?active=all&page_size=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Page 1 of 3", response.text)
        self.assertIn("Next", response.text)

    def test_crm_api_returns_json(self):
        response = self.client.get("/dashboard/api/customers?search=Nia&page_size=1")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("items", data)
        self.assertIn("summary", data)
        self.assertIn("pagination", data)
        self.assertEqual(data["items"][0]["customer_id"], self.customer["id"])

    def test_crm_summary_and_top_endpoints_return_json(self):
        summary_response = self.client.get("/dashboard/api/customers/summary?active=all")
        self.assertEqual(summary_response.status_code, 200)
        summary = summary_response.json()
        self.assertEqual(summary["customer_count"], 3)
        self.assertGreaterEqual(summary["lifetime_value"], 40.0)

        top_response = self.client.get("/dashboard/api/customers/top?limit=2")
        self.assertEqual(top_response.status_code, 200)
        top = top_response.json()
        self.assertIsInstance(top, list)
        self.assertEqual(top[0]["customer_id"], self.customer["id"])

    def test_customer_detail_and_activity_handle_existing_customer(self):
        response = self.client.get(f"/dashboard/customers/{self.customer['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Nia Okafor", response.text)
        self.assertIn("Wallet History", response.text)
        self.assertIn("Recent Sales", response.text)

        detail_response = self.client.get(f"/dashboard/api/customers/{self.customer['id']}")
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["customer"]["customer_id"], self.customer["id"])

        activity_response = self.client.get(f"/dashboard/api/customers/{self.customer['id']}/activity")
        self.assertEqual(activity_response.status_code, 200)
        activity = activity_response.json()
        self.assertGreaterEqual(len(activity["recent_sales"]), 2)
        self.assertGreaterEqual(len(activity["wallet"]), 1)
        self.assertGreaterEqual(len(activity["loyalty"]), 1)
        self.assertGreaterEqual(len(activity["credit"]), 1)

    def test_customer_detail_handles_missing_customer_safely(self):
        page_response = self.client.get("/dashboard/customers/999999")
        self.assertEqual(page_response.status_code, 404)
        self.assertIn("Customer Not Found", page_response.text)

        api_response = self.client.get("/dashboard/api/customers/999999")
        self.assertEqual(api_response.status_code, 200)
        self.assertIsNone(api_response.json()["customer"])


class DashboardCrmEmptyDatabaseTestCase(unittest.TestCase):
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

    def test_crm_workspace_empty_database_behavior(self):
        response = self.client.get("/dashboard/customers")
        self.assertEqual(response.status_code, 200)
        self.assertIn("No customers match the selected filters.", response.text)

        api_response = self.client.get("/dashboard/api/customers")
        self.assertEqual(api_response.status_code, 200)
        self.assertEqual(api_response.json()["pagination"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
