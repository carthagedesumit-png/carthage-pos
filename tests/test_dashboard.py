import unittest

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


if __name__ == "__main__":
    unittest.main()
