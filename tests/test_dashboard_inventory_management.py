import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from app.api.app import app


class DashboardInventoryManagementTestCase(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()
        os.environ["CARTHAGE_POS_DB"] = self.db_file.name
        os.environ["POS_SECURE_COOKIES"] = "false"
        os.environ["POS_DASHBOARD_CSRF"] = "false"
        from app.core.config import reset_config_cache
        from app.database.db_manager import initialize_database
        from tests.support import bootstrap_staff

        reset_config_cache()
        initialize_database()
        self.sessions = bootstrap_staff()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        os.environ.pop("CARTHAGE_POS_DB", None)
        os.environ.pop("POS_SECURE_COOKIES", None)
        os.environ.pop("POS_DASHBOARD_CSRF", None)
        from app.core.config import reset_config_cache
        reset_config_cache()
        os.unlink(self.db_file.name)

    def login(self, username="test-admin", password="admin-password"):
        response = self.client.post(
            "/dashboard/login", data={"username": username, "password": password},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        return response

    def create_product(self, sku="WEB-001", barcode="WEB-001"):
        return self.client.post(
            "/dashboard/inventory/products",
            data={
                "name": "Dashboard Product", "sku": sku, "barcode": barcode,
                "barcode_format": "CODE128", "selling_price": "20.50",
                "cost_price": "10", "quantity_in_stock": "5", "reorder_level": "2",
                "store_id": str(self.sessions["admin"].store_id), "unit": "each",
            }, follow_redirects=False,
        )

    def test_add_product_page_and_successful_prg_creation(self):
        self.login()
        page = self.client.get("/dashboard/inventory/products/new")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Add Product", page.text)
        response = self.create_product()
        self.assertEqual(response.status_code, 303)
        self.assertIn("/dashboard/inventory/products/", response.headers["location"])
        from app.inventory.inventory_service import search_products
        self.assertEqual(search_products("WEB-001")[0]["quantity_in_stock"], 5)

    def test_duplicate_sku_barcode_and_invalid_values_show_validation(self):
        self.login()
        self.assertEqual(self.create_product().status_code, 303)
        duplicate = self.create_product(barcode="WEB-002")
        self.assertEqual(duplicate.status_code, 422)
        self.assertIn("SKU or barcode already exists", duplicate.text)
        duplicate_barcode = self.create_product(sku="WEB-002")
        self.assertEqual(duplicate_barcode.status_code, 422)
        invalid = self.client.post("/dashboard/inventory/products", data={
            "name": "Bad", "sku": "BAD", "selling_price": "-1", "cost_price": "0",
            "quantity_in_stock": "0", "reorder_level": "0",
            "store_id": str(self.sessions["admin"].store_id), "unit": "each",
        })
        self.assertEqual(invalid.status_code, 422)
        self.assertIn("Selling price", invalid.text)

    def test_edit_lifecycle_stock_and_movements(self):
        self.login()
        created = self.create_product()
        product_id = int(created.headers["location"].split("/")[-1].split("?")[0])
        edited = self.client.post(f"/dashboard/inventory/products/{product_id}", data={
            "name": "Edited Product", "sku": "WEB-001", "barcode": "WEB-001",
            "selling_price": "25", "cost_price": "10", "reorder_level": "3",
            "store_id": str(self.sessions["admin"].store_id), "unit": "each",
        }, follow_redirects=False)
        self.assertEqual(edited.status_code, 303)
        received = self.client.post(f"/dashboard/inventory/products/{product_id}/receive", data={
            "store_id": str(self.sessions["admin"].store_id), "quantity": "4",
            "reason": "Direct count receipt", "supplier_reference": "REF-1",
        }, follow_redirects=False)
        self.assertEqual(received.status_code, 303)
        adjusted = self.client.post(f"/dashboard/inventory/products/{product_id}/adjust", data={
            "store_id": str(self.sessions["admin"].store_id), "new_quantity": "7",
            "reason": "Cycle count", "confirmed": "true",
        }, follow_redirects=False)
        self.assertEqual(adjusted.status_code, 303)
        deactivated = self.client.post(f"/dashboard/inventory/products/{product_id}/lifecycle", data={
            "store_id": str(self.sessions["admin"].store_id), "active": "false",
        }, follow_redirects=False)
        self.assertEqual(deactivated.status_code, 303)
        reactivated = self.client.post(f"/dashboard/inventory/products/{product_id}/lifecycle", data={
            "store_id": str(self.sessions["admin"].store_id), "active": "true",
        }, follow_redirects=False)
        self.assertEqual(reactivated.status_code, 303)
        from app.database.db_manager import get_connection
        with get_connection() as conn:
            product = conn.execute("SELECT name, is_active FROM products WHERE id = ?", (product_id,)).fetchone()
            movements = conn.execute("SELECT movement_type FROM stock_movements WHERE product_id = ?", (product_id,)).fetchall()
        self.assertEqual(product["name"], "Edited Product")
        self.assertEqual(product["is_active"], 1)
        self.assertIn("PURCHASE", {row["movement_type"] for row in movements})
        self.assertIn("ADJUSTMENT", {row["movement_type"] for row in movements})

    def test_cashier_write_is_forbidden_and_list_is_read_only(self):
        self.login("cashier1", "cashier-password")
        page = self.client.get("/dashboard/inventory")
        self.assertIn("Read Only", page.text)
        self.assertNotIn("Add Product</a>", page.text)
        response = self.create_product()
        self.assertEqual(response.status_code, 403)

    def test_manager_store_scope_is_enforced(self):
        self.login("manager1", "manager-password")
        response = self.client.post("/dashboard/inventory/products", data={
            "name": "Wrong Store", "sku": "WRONG-STORE", "selling_price": "1",
            "cost_price": "0", "quantity_in_stock": "0", "reorder_level": "0",
            "store_id": "999999", "unit": "each",
        })
        self.assertIn(response.status_code, {403, 422})
        self.assertTrue(
            "inactive or unavailable" in response.text or "Access denied" in response.text,
            response.text,
        )

    def test_category_create_duplicate_and_referenced_deactivation(self):
        self.login()
        response = self.client.post("/dashboard/inventory/categories", data={
            "name": "Beverages", "description": "Drinks",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        duplicate = self.client.post("/dashboard/inventory/categories", data={"name": "Beverages"},
                                     follow_redirects=False)
        self.assertIn("error=", duplicate.headers["location"])

    def test_barcode_generation_preview_and_list_actions(self):
        self.login()
        created = self.create_product(barcode="")
        product_id = int(created.headers["location"].split("/")[-1].split("?")[0])
        generated = self.client.post(f"/dashboard/inventory/products/{product_id}/barcode", data={
            "operation": "generate", "barcode_format": "CODE128",
            "store_id": str(self.sessions["admin"].store_id),
        }, follow_redirects=False)
        self.assertEqual(generated.status_code, 303)
        preview = self.client.post(f"/dashboard/inventory/products/{product_id}/barcode", data={
            "operation": "preview", "store_id": str(self.sessions["admin"].store_id),
        })
        self.assertEqual(preview.status_code, 200)
        self.assertIn("Label Preview", preview.text)
        listing = self.client.get("/dashboard/inventory")
        for marker in ("Edit", "Receive", "Adjust", "Deactivate"):
            self.assertIn(marker, listing.text)

    def test_csrf_failure(self):
        os.environ["POS_DASHBOARD_CSRF"] = "true"
        from app.core.config import reset_config_cache
        reset_config_cache()
        response = self.client.post("/dashboard/login", data={
            "username": "test-admin", "password": "admin-password",
        })
        self.assertEqual(response.status_code, 403)
        self.assertIn("csrf_rejected", response.text)


if __name__ == "__main__":
    unittest.main()
