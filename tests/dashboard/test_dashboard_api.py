import unittest

from fastapi.testclient import TestClient

from app.api.app import app


class DashboardApiTestCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_sales_chart_endpoint(self):
        response = self.client.get("/dashboard/api/sales-chart")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("labels", data)
        self.assertIn("values", data)

    def test_recent_sales_endpoint(self):
        response = self.client.get("/dashboard/api/recent-sales")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_top_products_endpoint(self):
        response = self.client.get("/dashboard/api/top-products")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_low_stock_endpoint(self):
        response = self.client.get("/dashboard/api/low-stock")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)


if __name__ == "__main__":
    unittest.main()
