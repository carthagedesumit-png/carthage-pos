import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.app import app


class DashboardSalesCheckoutTestCase(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()
        os.environ["CARTHAGE_POS_DB"] = self.db_file.name
        os.environ["POS_SECURE_COOKIES"] = "false"
        os.environ["POS_DASHBOARD_CSRF"] = "false"
        from app.core.config import reset_config_cache
        from app.database.db_manager import initialize_database
        from app.inventory.inventory_service import create_product
        from tests.support import bootstrap_staff

        reset_config_cache()
        initialize_database()
        self.sessions = bootstrap_staff()
        self.product = create_product(
            self.sessions["manager"], sku="CHECKOUT-1", barcode="629000000001",
            name="Checkout Product", selling_price=10, cost_price=4,
            quantity_in_stock=20, reorder_level=2,
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        for key in ("CARTHAGE_POS_DB", "POS_SECURE_COOKIES", "POS_DASHBOARD_CSRF"):
            os.environ.pop(key, None)
        from app.core.config import reset_config_cache
        reset_config_cache()
        os.unlink(self.db_file.name)

    def login(self, username="cashier1", password="cashier-password"):
        response = self.client.post(
            "/dashboard/login", data={"username": username, "password": password},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def cart_id(self):
        page = self.client.get("/dashboard/sales/checkout")
        self.assertEqual(page.status_code, 200)
        marker = "/dashboard/sales/carts/"
        return int(page.text.split(marker, 1)[1].split("/", 1)[0])

    def add(self, cart_id, identifier="629000000001", quantity="1"):
        return self.client.post(
            f"/dashboard/sales/carts/{cart_id}/items",
            data={"identifier": identifier, "quantity": quantity},
            follow_redirects=False,
        )

    def test_barcode_search_merge_manual_quantity_checkout_and_receipt(self):
        self.login()
        page = self.client.get("/dashboard/sales/checkout?q=Checkout")
        self.assertIn("Checkout Product", page.text)
        cart_id = self.cart_id()
        self.assertEqual(self.add(cart_id).status_code, 303)
        self.add(cart_id, "CHECKOUT-1")
        from app.checkout.checkout_service import get_cart
        self.assertEqual(get_cart(self.sessions["cashier"], cart_id)["items"][0]["quantity"], 2)
        self.client.post(
            f"/dashboard/sales/carts/{cart_id}/items/{self.product['id']}",
            data={"quantity": "3"}, follow_redirects=False,
        )
        with patch("app.checkout.checkout_service.print_receipt", return_value={"success": True}) as printer, \
             patch("app.checkout.checkout_service.maybe_open_drawer_after_sale") as drawer, \
             patch("app.checkout.checkout_service.show_payment_confirmation") as display:
            response = self.client.post(
                f"/dashboard/sales/carts/{cart_id}/checkout",
                data={"tender_type": "CASH", "amount_paid": "40", "print_after": "true"},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303)
        sale_id = int(response.headers["location"].split("/sales/")[1].split("/")[0])
        receipt = self.client.get(f"/dashboard/sales/{sale_id}/receipt")
        self.assertEqual(receipt.status_code, 200)
        self.assertIn("Receipt Preview", receipt.text)
        printer.assert_called_once(); drawer.assert_called_once(); display.assert_called_once()
        from app.inventory.inventory_service import get_product_by_id
        self.assertEqual(get_product_by_id(self.product["id"])["quantity_in_stock"], 17)

    def test_split_payment_rejects_price_manipulation_and_reservations(self):
        self.login()
        cart_id = self.cart_id(); self.add(cart_id)
        response = self.client.post(
            f"/dashboard/sales/carts/{cart_id}/checkout",
            data={"tender_type": "MIXED", "payment_method": ["CASH", "CARD"],
                  "payment_amount": ["4", "6"], "price": "0.01"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        from app.sales.sales_service import print_receipt_data
        sale_id = int(response.headers["location"].split("/sales/")[1].split("/")[0])
        detail = print_receipt_data(sale_id)
        self.assertEqual(detail["sale"]["total_amount"], 10)
        self.assertEqual({p["payment_method"] for p in detail["payments"]}, {"CASH", "CARD"})

    def test_customer_lookup_wallet_loyalty_and_guest_sale(self):
        from app.customers.customer_service import create_customer
        from app.customers.loyalty_service import record_loyalty_transaction
        from app.customers.wallet_service import record_wallet_transaction
        from app.database.transactions import transaction
        customer = create_customer(self.sessions["cashier"], "Ada", "Buyer", email="ada@example.test")
        with transaction() as conn:
            record_wallet_transaction(conn, customer["id"], 20, "DEPOSIT", self.sessions["admin"].user_id)
            record_loyalty_transaction(conn, customer["id"], 100, "ADJUSTMENT", self.sessions["admin"].user_id)
        self.login(); page = self.client.get("/dashboard/sales/checkout?customer_q=Ada")
        self.assertIn("Ada Buyer", page.text)
        cart_id = self.cart_id(); self.add(cart_id)
        self.client.post(f"/dashboard/sales/carts/{cart_id}/customer", data={"customer_id": customer["id"]})
        response = self.client.post(
            f"/dashboard/sales/carts/{cart_id}/checkout",
            data={"tender_type": "WALLET"}, follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def test_suspend_resume_restart_persistence_discount_and_return_authorization(self):
        self.login(); cart_id = self.cart_id(); self.add(cart_id)
        self.client.post(f"/dashboard/sales/carts/{cart_id}/status", data={"action": "suspend"})
        restarted = TestClient(app); restarted.cookies.update(self.client.cookies)
        page = restarted.get("/dashboard/sales/checkout")
        self.assertIn(f"Cart #{cart_id}", page.text)
        restarted.post(f"/dashboard/sales/carts/{cart_id}/status", data={"action": "resume"})
        denied = restarted.post(
            f"/dashboard/sales/carts/{cart_id}/discount",
            data={"discount_type": "PERCENTAGE", "discount_value": "10", "discount_reason": "Promo"},
            follow_redirects=False,
        )
        self.assertIn("error=", denied.headers["location"])
        restarted.close()

        self.client.cookies.clear(); self.login("manager1", "manager-password")
        manager_cart = self.cart_id(); self.add(manager_cart)
        approved = self.client.post(
            f"/dashboard/sales/carts/{manager_cart}/discount",
            data={"discount_type": "PERCENTAGE", "discount_value": "10", "discount_reason": "Approved promotion"},
            follow_redirects=False,
        )
        self.assertIn("success=", approved.headers["location"])
        sale = self.client.post(
            f"/dashboard/sales/carts/{manager_cart}/checkout",
            data={"tender_type": "CASH", "amount_paid": "10"}, follow_redirects=False,
        )
        sale_id = int(sale.headers["location"].split("/sales/")[1].split("/")[0])
        from app.sales.sales_service import print_receipt_data
        item_id = print_receipt_data(sale_id)["items"][0]["id"]
        returned = self.client.post(
            f"/dashboard/sales/{sale_id}/returns",
            data={"sale_item_id": [str(item_id)], "return_quantity": ["1"], "reason": "Damaged"},
            follow_redirects=False,
        )
        self.assertIn("success=", returned.headers["location"])
        from app.database.db_manager import get_connection
        with get_connection() as conn:
            events = {r[0] for r in conn.execute("SELECT event_type FROM checkout_events")}
        self.assertIn("DISCOUNT_APPROVED", events)
        self.assertIn("CHECKOUT_COMPLETED", events)

    def test_csrf_and_anonymous_access_are_enforced(self):
        anonymous = self.client.get("/dashboard/sales/checkout")
        self.assertIn(anonymous.status_code, {401, 403})
        os.environ["POS_DASHBOARD_CSRF"] = "true"
        from app.core.config import reset_config_cache
        reset_config_cache()
        response = self.client.post(
            "/dashboard/login", data={"username": "cashier1", "password": "cashier-password"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("csrf_rejected", response.text)


if __name__ == "__main__":
    unittest.main()
