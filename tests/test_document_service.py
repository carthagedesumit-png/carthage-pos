import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import bcrypt


class DocumentServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()
        os.environ["CARTHAGE_POS_DB"] = self.db_file.name

        from app.database.db_manager import initialize_database
        from app.inventory.inventory_service import create_product
        from app.procurement.purchase_service import (
            create_purchase_order,
            receive_purchase_order,
            submit_purchase_order,
        )
        from app.procurement.supplier_service import create_supplier
        from app.sales.sales_service import PAYMENT_CARD, create_sale, process_return
        from app.stores.store_service import create_store
        from app.stores.transfer_service import (
            approve_transfer,
            create_transfer,
            dispatch_transfer,
            receive_transfer,
        )
        from auth import authenticate_user, create_user, switch_store
        from tests.support import bootstrap_staff

        initialize_database()
        self.sessions = bootstrap_staff()
        self.branch = create_store(
            self.sessions["admin"],
            "DOC-02",
            "Document Branch",
            address="22 Document Avenue",
            phone="555-0222",
            email="branch@example.test",
            manager_user_id=self.sessions["manager"].user_id,
        )
        self.product = create_product(
            self.sessions["manager"],
            sku="DOC-PRODUCT",
            barcode="DOC-PRODUCT",
            name="Document Product",
            selling_price=25.0,
            cost_price=10.0,
            quantity_in_stock=10,
            reorder_level=2,
        )
        with patch("auth.bcrypt.gensalt", return_value=bcrypt.gensalt(rounds=4)):
            create_user(
                "document-cashier",
                "cashier-password",
                "Document Cashier",
                "cashier",
                acting_session=self.sessions["admin"],
                home_store_id=self.branch["id"],
            )
        self.cashier = authenticate_user("document-cashier", "cashier-password")
        self.manager = switch_store(self.sessions["manager"], self.branch["id"])

        from app.inventory.inventory_service import adjust_stock

        adjust_stock(
            self.manager,
            self.product["id"],
            8,
            store_id=self.branch["id"],
        )
        self.sale = create_sale(
            self.cashier,
            [{"product_id": self.product["id"], "quantity": 2}],
            payment_method=PAYMENT_CARD,
            tax_rate=0.10,
            register_name="DOC-REGISTER",
        )
        self.tax_exempt_sale = create_sale(
            self.cashier,
            [{"product_id": self.product["id"], "quantity": 1}],
            payment_method=PAYMENT_CARD,
            tax_rate=0,
            register_name="DOC-REGISTER",
        )
        self.sales_return = process_return(
            self.manager,
            self.sale["sale"]["sale_id"],
            [{"sale_item_id": self.sale["items"][0]["id"], "quantity": 1}],
            "Document test refund",
        )

        self.supplier = create_supplier(self.manager, "Contactless Supplier")
        self.purchase_order = create_purchase_order(
            self.manager,
            self.supplier["id"],
            "DOC-PO-1",
            [{"product_id": self.product["id"], "quantity": 3, "unit_cost": 12}],
            store_id=self.branch["id"],
        )
        self.purchase_order = submit_purchase_order(
            self.manager, self.purchase_order["purchase_order"]["id"]
        )
        self.goods_receipt = receive_purchase_order(
            self.manager,
            self.purchase_order["purchase_order"]["id"],
            [
                {
                    "purchase_order_item_id": self.purchase_order["items"][0]["id"],
                    "quantity": 2,
                }
            ],
        )

        self.transfer = create_transfer(
            self.sessions["manager"],
            "DOC-TRANSFER-1",
            self.sessions["manager"].store_id,
            self.branch["id"],
            [{"product_id": self.product["id"], "quantity": 2}],
        )
        self.transfer = approve_transfer(
            self.sessions["manager"], self.transfer["transfer"]["id"]
        )
        transfer_line_id = self.transfer["items"][0]["id"]
        self.transfer = dispatch_transfer(
            self.sessions["manager"],
            self.transfer["transfer"]["id"],
            [{"transfer_item_id": transfer_line_id, "quantity": 2}],
        )
        self.transfer = receive_transfer(
            self.manager,
            self.transfer["transfer"]["id"],
            [{"transfer_item_id": transfer_line_id, "quantity": 1}],
        )

    def tearDown(self):
        os.environ.pop("CARTHAGE_POS_DB", None)
        os.unlink(self.db_file.name)

    def test_receipt_generation_supports_58mm_and_80mm_layouts(self):
        from app.documents.document_service import generate_sales_receipt

        branding = {
            "business_name": "Example Retail Group",
            "tax_id": "TAX-123",
            "receipt_footer": "Returns accepted with receipt.",
        }
        receipt_58 = generate_sales_receipt(
            self.sale["sale"]["sale_id"], width_mm=58, branding=branding
        )
        receipt_80 = generate_sales_receipt(
            self.sale["sale"]["sale_id"], width_mm=80, branding=branding
        )

        self.assertEqual(receipt_58["document_number"], self.sale["sale"]["receipt_number"])
        self.assertEqual(receipt_58["store"]["name"], "Document Branch")
        self.assertEqual(receipt_58["metadata"]["cashier"], "Document Cashier")
        self.assertEqual(receipt_58["metadata"]["register"], "DOC-REGISTER")
        self.assertAlmostEqual(receipt_58["totals"]["tax"], 5.0)
        self.assertIn("Example Retail Group", receipt_58["text"])
        self.assertIn("Returns accepted", receipt_58["text"])
        self.assertTrue(all(len(line) <= 32 for line in receipt_58["text"].splitlines()))
        self.assertTrue(all(len(line) <= 48 for line in receipt_80["text"].splitlines()))
        self.assertIn("<!doctype html>", receipt_80["html"])

    def test_a4_invoice_has_customer_placeholders_and_tax_exempt_totals(self):
        from app.documents.document_service import generate_sales_invoice

        placeholder_invoice = generate_sales_invoice(
            self.tax_exempt_sale["sale"]["sale_id"]
        )
        customer_invoice = generate_sales_invoice(
            self.sale["sale"]["sale_id"],
            customer={
                "name": "Ada Customer",
                "address": "1 Customer Way",
                "tax_id": "CUS-TAX-9",
            },
        )

        self.assertEqual(placeholder_invoice["customer"]["name"], "Walk-in Customer")
        self.assertAlmostEqual(placeholder_invoice["totals"]["tax"], 0.0)
        self.assertEqual(placeholder_invoice["page_layout"], "A4")
        self.assertEqual(customer_invoice["customer"]["name"], "Ada Customer")
        self.assertIn("Ada Customer", customer_invoice["html"])
        self.assertIn(self.sale["sale"]["receipt_number"], customer_invoice["text"])

    def test_credit_note_references_original_sale_and_refund(self):
        from app.documents.document_service import generate_credit_note

        credit = generate_credit_note(self.sales_return["return"]["id"], width_mm=58)

        self.assertEqual(credit["document_type"], "credit_note")
        self.assertEqual(
            credit["metadata"]["original_receipt"], self.sale["sale"]["receipt_number"]
        )
        self.assertAlmostEqual(
            credit["totals"]["total_refunded"],
            self.sales_return["return"]["total_refunded"],
        )
        self.assertIn("Document test refund", credit["text"])

    def test_purchase_order_and_goods_received_documents(self):
        from app.documents.document_service import (
            generate_goods_received_note,
            generate_purchase_order_document,
        )

        purchase = generate_purchase_order_document(
            self.purchase_order["purchase_order"]["id"]
        )
        goods = generate_goods_received_note(self.goods_receipt["receipt"]["id"])

        self.assertEqual(purchase["metadata"]["po_reference"], "DOC-PO-1")
        self.assertEqual(purchase["supplier"]["name"], "Contactless Supplier")
        self.assertEqual(purchase["supplier"]["phone"], "")
        self.assertEqual(purchase["store"]["name"], "Document Branch")
        self.assertEqual(purchase["totals"]["pending_units"], 1)
        self.assertEqual(goods["document_number"], self.goods_receipt["receipt"]["receipt_number"])
        self.assertEqual(goods["line_items"][0]["received_quantity"], 2)
        self.assertEqual(goods["line_items"][0]["pending_quantity"], 1)
        self.assertIn("Contactless Supplier", purchase["html"])

    def test_stock_transfer_document_contains_quantities_users_and_events(self):
        from app.documents.document_service import generate_stock_transfer_document

        document = generate_stock_transfer_document(self.transfer["transfer"]["id"])

        self.assertEqual(document["metadata"]["transfer_reference"], "DOC-TRANSFER-1")
        self.assertEqual(document["metadata"]["destination_store"], "Document Branch")
        self.assertEqual(document["line_items"][0]["dispatched_quantity"], 2)
        self.assertEqual(document["line_items"][0]["received_quantity"], 1)
        self.assertEqual(document["line_items"][0]["pending_quantity"], 1)
        self.assertGreaterEqual(len(document["event_history"]), 3)
        self.assertIn("EVENT HISTORY", document["text"])
        self.assertIn("Event History", document["html"])

    def test_document_numbering_is_unique_deterministic_and_legacy_receipt_still_works(self):
        from app.documents.document_service import (
            document_number,
            generate_sales_invoice,
            generate_sales_receipt,
        )
        from app.sales.sales_service import print_receipt_data
        from app.ui.terminal_ui import print_receipt

        first = generate_sales_invoice(self.sale["sale"]["sale_id"])
        repeated = generate_sales_invoice(self.sale["sale"]["sale_id"])
        second = generate_sales_invoice(self.tax_exempt_sale["sale"]["sale_id"])

        self.assertEqual(first["document_number"], repeated["document_number"])
        self.assertNotEqual(first["document_number"], second["document_number"])
        self.assertNotEqual(
            document_number("invoice", 1, "DOC-02"),
            document_number("credit_note", 1, "DOC-02"),
        )
        legacy = print_receipt_data(self.sale["sale"]["sale_id"])
        generated = generate_sales_receipt(self.sale["sale"]["sale_id"])
        output = io.StringIO()
        with patch("app.ui.terminal_ui.clear_screen"), redirect_stdout(output):
            print_receipt(legacy)
        self.assertIn(generated["document_number"], output.getvalue())


if __name__ == "__main__":
    unittest.main()
