import hashlib
import os
import tempfile
import unittest

from fastapi.testclient import TestClient


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()
        os.environ["CARTHAGE_POS_DB"] = self.db_file.name

        from app.database.db_manager import initialize_database
        from app.inventory.inventory_service import create_product
        from tests.support import bootstrap_staff

        initialize_database()
        sessions = bootstrap_staff()
        self.admin_session = sessions["admin"]
        self.manager_session = sessions["manager"]
        self.cashier_session = sessions["cashier"]
        self.product = create_product(
            self.manager_session,
            sku="API-ITEM",
            name="API Test Item",
            selling_price=20,
            cost_price=8,
            quantity_in_stock=100,
            reorder_level=5,
        )

        from app.api.app import create_app

        self.client_context = TestClient(create_app(initialize=False))
        self.client = self.client_context.__enter__()
        self.admin_headers = self.login("test-admin", "admin-password")
        self.manager_headers = self.login("manager1", "manager-password")
        self.cashier_headers = self.login("cashier1", "cashier-password")

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        os.environ.pop("CARTHAGE_POS_DB", None)
        os.unlink(self.db_file.name)

    def login(self, username, password):
        response = self.client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
        self.assertEqual(response.status_code, 200, response.text)
        token = response.json()["data"]["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def test_authentication_current_user_logout_and_hashed_storage(self):
        bad = self.client.post(
            "/api/v1/auth/login", json={"username": "test-admin", "password": "wrong"}
        )
        self.assertEqual(bad.status_code, 401)
        self.assertNotIn("password_hash", bad.text)

        current = self.client.get("/api/v1/auth/me", headers=self.admin_headers)
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["data"]["role"], "admin")

        raw_token = self.admin_headers["Authorization"].split()[1]
        from app.database.db_manager import get_connection

        with get_connection() as conn:
            row = conn.execute("SELECT token_hash FROM api_sessions WHERE user_id = ?", (self.admin_session.user_id,)).fetchone()
        self.assertEqual(row["token_hash"], hashlib.sha256(raw_token.encode()).hexdigest())
        self.assertNotEqual(row["token_hash"], raw_token)

        logout = self.client.post("/api/v1/auth/logout", headers=self.admin_headers)
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=self.admin_headers).status_code, 401)

    def test_validation_error_conflict_not_found_and_pagination(self):
        invalid = self.client.post(
            "/api/v1/sales",
            headers=self.cashier_headers,
            json={"items": [{"product_id": self.product["id"], "quantity": 0}]},
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.json()["error"]["code"], "validation_error")
        self.assertEqual(
            self.client.get("/api/v1/products/99999", headers=self.cashier_headers).status_code,
            404,
        )

        customer = {
            "first_name": "API",
            "last_name": "Customer",
            "phone_number": "+1000001",
            "email": "api.customer@example.com",
        }
        self.assertEqual(self.client.post("/api/v1/customers", headers=self.cashier_headers, json=customer).status_code, 201)
        duplicate = self.client.post("/api/v1/customers", headers=self.cashier_headers, json=customer)
        self.assertEqual(duplicate.status_code, 409)
        listing = self.client.get("/api/v1/customers?page=1&per_page=1", headers=self.cashier_headers)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["meta"]["total"], 1)

    def test_authorization_and_store_scope_are_server_derived(self):
        denied = self.client.post(
            "/api/v1/products",
            headers=self.cashier_headers,
            json={"sku": "DENIED", "name": "Denied", "selling_price": 5},
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.client.get("/api/v1/users", headers=self.cashier_headers).status_code, 403)

        branch = self.client.post(
            "/api/v1/stores",
            headers=self.admin_headers,
            json={"code": "API-BR", "name": "API Branch"},
        ).json()["data"]
        out_of_scope = self.client.get(
            f"/api/v1/products?store_id={branch['id']}", headers=self.cashier_headers
        )
        self.assertEqual(out_of_scope.status_code, 403)
        report = self.client.get(
            f"/api/v1/reports/sales-summary?store_id={branch['id']}",
            headers=self.cashier_headers,
        )
        self.assertEqual(report.status_code, 403)
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/switch-store",
                headers=self.cashier_headers,
                json={"store_id": branch["id"]},
            ).status_code,
            403,
        )
        switched = self.client.post(
            "/api/v1/auth/switch-store",
            headers=self.admin_headers,
            json={"store_id": branch["id"]},
        )
        self.assertEqual(switched.status_code, 200)
        self.assertEqual(switched.json()["data"]["store_id"], branch["id"])

    def test_customer_wallet_credit_sale_reports_and_documents(self):
        customer_response = self.client.post(
            "/api/v1/customers",
            headers=self.cashier_headers,
            json={
                "first_name": "Grace",
                "last_name": "Hopper",
                "phone_number": "+1000002",
                "email": "grace.api@example.com",
            },
        )
        self.assertEqual(customer_response.status_code, 201, customer_response.text)
        customer = customer_response.json()["data"]
        self.assertEqual(
            self.client.post(
                f"/api/v1/customers/{customer['id']}/wallet/deposit",
                headers=self.manager_headers,
                json={"amount": 30},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.put(
                f"/api/v1/customers/{customer['id']}/credit/terms",
                headers=self.manager_headers,
                json={"credit_limit": 50},
            ).status_code,
            200,
        )
        sale_response = self.client.post(
            "/api/v1/sales",
            headers=self.cashier_headers,
            json={
                "items": [{"product_id": self.product["id"], "quantity": 1}],
                "payment_method": "MIXED",
                "customer_id": customer["id"],
                "payments": [
                    {"payment_method": "WALLET", "amount": 10},
                    {"payment_method": "CREDIT", "amount": 10},
                ],
            },
        )
        self.assertEqual(sale_response.status_code, 201, sale_response.text)
        sale_id = sale_response.json()["data"]["sale"]["sale_id"]

        self.assertEqual(self.client.get("/api/v1/reports/customers/top", headers=self.manager_headers).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/reports/outstanding-credit", headers=self.manager_headers).status_code, 200)
        receipt = self.client.get(f"/api/v1/documents/receipts/{sale_id}", headers=self.cashier_headers)
        self.assertEqual(receipt.status_code, 200)
        self.assertEqual(receipt.json()["data"]["customer"]["customer_code"], customer["customer_code"])
        text_receipt = self.client.get(
            f"/api/v1/documents/receipts/{sale_id}?format=text&width_mm=58",
            headers=self.cashier_headers,
        )
        self.assertEqual(text_receipt.status_code, 200, text_receipt.text)
        self.assertTrue(text_receipt.headers["content-type"].startswith("text/plain"))
        html_invoice = self.client.get(
            f"/api/v1/documents/invoices/{sale_id}?format=html",
            headers=self.cashier_headers,
        )
        self.assertEqual(html_invoice.status_code, 200)
        self.assertTrue(html_invoice.headers["content-type"].startswith("text/html"))
        refund = self.client.post(
            f"/api/v1/sales/{sale_id}/refund",
            headers=self.manager_headers,
            json={"reason": "API return"},
        )
        self.assertEqual(refund.status_code, 201, refund.text)
        return_id = refund.json()["data"]["return"]["id"]
        credit_note = self.client.get(
            f"/api/v1/documents/credit-notes/{return_id}?format=text",
            headers=self.cashier_headers,
        )
        self.assertEqual(credit_note.status_code, 200, credit_note.text)

    def test_procurement_and_transfer_endpoint_groups(self):
        supplier = self.client.post(
            "/api/v1/suppliers",
            headers=self.manager_headers,
            json={"name": "API Supplier", "email": "supplier.api@example.com"},
        )
        self.assertEqual(supplier.status_code, 201, supplier.text)
        po = self.client.post(
            "/api/v1/purchase-orders",
            headers=self.manager_headers,
            json={
                "supplier_id": supplier.json()["data"]["id"],
                "reference_number": "API-PO-001",
                "line_items": [{"product_id": self.product["id"], "quantity": 2, "unit_cost": 7}],
            },
        )
        self.assertEqual(po.status_code, 201, po.text)
        po_data = po.json()["data"]
        po_id = po_data["purchase_order"]["id"]
        line_id = po_data["items"][0]["id"]
        self.assertEqual(self.client.post(f"/api/v1/purchase-orders/{po_id}/submit", headers=self.manager_headers).status_code, 200)
        received = self.client.post(
            f"/api/v1/purchase-orders/{po_id}/receive",
            headers=self.manager_headers,
            json={"line_items": [{"purchase_order_item_id": line_id, "quantity": 2}]},
        )
        self.assertEqual(received.status_code, 200, received.text)
        receipt_id = received.json()["data"]["receipt"]["id"]
        self.assertEqual(
            self.client.get(f"/api/v1/documents/goods-received/{receipt_id}", headers=self.manager_headers).status_code,
            200,
        )

        branch_response = self.client.post(
            "/api/v1/stores", headers=self.admin_headers,
            json={"code": "API-DST", "name": "Transfer Destination"},
        )
        branch = branch_response.json()["data"]
        from app.stores.store_service import assign_user_to_store

        assign_user_to_store(self.admin_session, self.manager_session.user_id, branch["id"])
        transfer = self.client.post(
            "/api/v1/transfers",
            headers=self.manager_headers,
            json={
                "reference_number": "API-TR-001",
                "source_store_id": self.manager_session.store_id,
                "destination_store_id": branch["id"],
                "line_items": [{"product_id": self.product["id"], "quantity": 1}],
            },
        )
        self.assertEqual(transfer.status_code, 201, transfer.text)
        transfer_data = transfer.json()["data"]
        transfer_id = transfer_data["transfer"]["id"]
        transfer_item_id = transfer_data["items"][0]["id"]
        self.assertEqual(self.client.post(f"/api/v1/transfers/{transfer_id}/approve", headers=self.manager_headers).status_code, 200)
        self.assertEqual(
            self.client.post(
                f"/api/v1/transfers/{transfer_id}/dispatch",
                headers=self.manager_headers,
                json={"line_items": [{"transfer_item_id": transfer_item_id, "quantity": 1}]},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                f"/api/v1/transfers/{transfer_id}/receive",
                headers=self.manager_headers,
                json={"line_items": [{"transfer_item_id": transfer_item_id, "quantity": 1}]},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(f"/api/v1/documents/transfers/{transfer_id}?format=html", headers=self.manager_headers).status_code,
            200,
        )

    def test_openapi_documentation_is_available(self):
        schema = self.client.get("/openapi.json")
        self.assertEqual(schema.status_code, 200)
        self.assertIn("/api/v1/auth/login", schema.json()["paths"])
        self.assertIn("/api/v1/documents/receipts/{sale_id}", schema.json()["paths"])
        self.assertEqual(self.client.get("/docs").status_code, 200)


if __name__ == "__main__":
    unittest.main()
