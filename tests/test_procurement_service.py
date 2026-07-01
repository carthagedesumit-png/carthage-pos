import os
import sqlite3
import tempfile
import unittest


class ProcurementServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()
        os.environ["CARTHAGE_POS_DB"] = self.db_file.name

        from app.database.db_manager import initialize_database
        from app.inventory.inventory_service import create_product
        from app.procurement.supplier_service import create_supplier
        from tests.support import bootstrap_staff

        initialize_database()
        self.sessions = bootstrap_staff()
        self.supplier = create_supplier(
            self.sessions["manager"],
            "Acme Wholesale",
            phone="555-0100",
            email="orders@acme.test",
            address="10 Supply Street",
        )
        self.product = create_product(
            self.sessions["manager"],
            sku="PROC-1",
            barcode="PROC-1",
            name="Procurement Product",
            category_id=1,
            supplier_id=self.supplier["id"],
            selling_price=20.0,
            cost_price=10.0,
            quantity_in_stock=10,
            reorder_level=2,
        )

    def tearDown(self):
        os.environ.pop("CARTHAGE_POS_DB", None)
        os.unlink(self.db_file.name)

    def create_submitted_order(self, reference="PO-100", quantity=10, unit_cost=20.0):
        from app.procurement.purchase_service import create_purchase_order, submit_purchase_order

        order = create_purchase_order(
            self.sessions["manager"],
            self.supplier["id"],
            reference,
            [{"product_id": self.product["id"], "quantity": quantity, "unit_cost": unit_cost}],
            expected_delivery_date="2026-07-15",
            notes="Restock",
        )
        return submit_purchase_order(
            self.sessions["manager"], order["purchase_order"]["id"]
        )

    def test_partial_and_multiple_receipts_complete_order_and_update_stock(self):
        from app.database.db_manager import get_connection
        from app.procurement.purchase_service import (
            STATUS_FULLY_RECEIVED,
            STATUS_PARTIALLY_RECEIVED,
            get_purchase_order,
            receive_purchase_order,
        )

        order = self.create_submitted_order()
        order_id = order["purchase_order"]["id"]
        line_id = order["items"][0]["id"]

        first = receive_purchase_order(
            self.sessions["manager"],
            order_id,
            [{"purchase_order_item_id": line_id, "quantity": 4}],
            notes="First delivery",
        )
        partial = get_purchase_order(order_id)

        self.assertEqual(partial["purchase_order"]["status"], STATUS_PARTIALLY_RECEIVED)
        self.assertEqual(partial["items"][0]["received_quantity"], 4)
        self.assertEqual(partial["items"][0]["remaining_quantity"], 6)
        self.assertEqual(first["items"][0]["previous_quantity"], 10)
        self.assertEqual(first["items"][0]["new_quantity"], 14)
        self.assertAlmostEqual(first["items"][0]["new_cost"], 12.8571, places=4)

        second = receive_purchase_order(
            self.sessions["admin"],
            order_id,
            [{"purchase_order_item_id": line_id, "quantity": 6}],
            notes="Final delivery",
        )
        completed = get_purchase_order(order_id)

        self.assertEqual(completed["purchase_order"]["status"], STATUS_FULLY_RECEIVED)
        self.assertEqual(completed["items"][0]["received_quantity"], 10)
        self.assertEqual(len(completed["receipts"]), 2)
        self.assertNotEqual(first["receipt"]["receipt_number"], second["receipt"]["receipt_number"])

        with get_connection() as conn:
            product = conn.execute(
                "SELECT quantity_in_stock, cost_price FROM products WHERE id = ?",
                (self.product["id"],),
            ).fetchone()
            movements = conn.execute(
                """SELECT quantity, previous_quantity, new_quantity, user_id, notes
                   FROM stock_movements
                   WHERE product_id = ? AND notes LIKE 'Receipt %'
                   ORDER BY id""",
                (self.product["id"],),
            ).fetchall()
        self.assertEqual(product["quantity_in_stock"], 20)
        self.assertAlmostEqual(product["cost_price"], 15.0, places=3)
        self.assertEqual([row["quantity"] for row in movements], [4, 6])
        self.assertEqual([row["new_quantity"] for row in movements], [14, 20])

    def test_receiving_validation_is_transactional(self):
        from app.database.db_manager import get_connection
        from app.procurement.purchase_service import receive_purchase_order

        order = self.create_submitted_order(quantity=3)
        order_id = order["purchase_order"]["id"]
        line_id = order["items"][0]["id"]

        for quantity in (0, -1, 4):
            with self.assertRaises(ValueError):
                receive_purchase_order(
                    self.sessions["manager"],
                    order_id,
                    [{"purchase_order_item_id": line_id, "quantity": quantity}],
                )

        with get_connection() as conn:
            stock = conn.execute(
                "SELECT quantity_in_stock FROM products WHERE id = ?",
                (self.product["id"],),
            ).fetchone()[0]
            receipt_count = conn.execute("SELECT COUNT(*) FROM purchase_receipts").fetchone()[0]
        self.assertEqual(stock, 10)
        self.assertEqual(receipt_count, 0)

    def test_purchase_order_validation_and_duplicate_reference(self):
        from app.procurement.purchase_service import create_purchase_order, receive_purchase_order

        order = self.create_submitted_order(reference="PO-DUP", quantity=2)
        with self.assertRaises(ValueError):
            create_purchase_order(
                self.sessions["manager"],
                self.supplier["id"],
                "po-dup",
                [{"product_id": self.product["id"], "quantity": 1, "unit_cost": 5}],
            )
        for quantity in (0, -2):
            with self.assertRaises(ValueError):
                create_purchase_order(
                    self.sessions["manager"],
                    self.supplier["id"],
                    f"PO-QTY-{quantity}",
                    [{"product_id": self.product["id"], "quantity": quantity, "unit_cost": 5}],
                )
        with self.assertRaises(ValueError):
            create_purchase_order(
                self.sessions["manager"],
                self.supplier["id"],
                "PO-BAD-PRODUCT",
                [{"product_id": 999999, "quantity": 1, "unit_cost": 5}],
            )
        with self.assertRaises(ValueError):
            receive_purchase_order(
                self.sessions["manager"],
                order["purchase_order"]["id"],
                [{"purchase_order_item_id": 999999, "quantity": 1}],
            )

    def test_draft_submission_and_cancellation_transitions(self):
        from app.procurement.purchase_service import (
            STATUS_CANCELLED,
            create_purchase_order,
            receive_purchase_order,
            submit_purchase_order,
            cancel_purchase_order,
        )

        order = create_purchase_order(
            self.sessions["manager"],
            self.supplier["id"],
            "PO-CANCEL",
            [{"product_id": self.product["id"], "quantity": 2, "unit_cost": 10}],
        )
        order_id = order["purchase_order"]["id"]
        with self.assertRaises(ValueError):
            receive_purchase_order(
                self.sessions["manager"],
                order_id,
                [{"purchase_order_item_id": order["items"][0]["id"], "quantity": 1}],
            )

        cancelled = cancel_purchase_order(self.sessions["admin"], order_id)
        self.assertEqual(cancelled["purchase_order"]["status"], STATUS_CANCELLED)
        with self.assertRaises(ValueError):
            submit_purchase_order(self.sessions["manager"], order_id)

    def test_supplier_management_duplicate_prevention_and_soft_deactivation(self):
        from app.procurement.purchase_service import create_purchase_order
        from app.procurement.supplier_service import (
            create_supplier,
            deactivate_supplier,
            search_suppliers,
            update_supplier,
        )

        updated = update_supplier(
            self.sessions["manager"],
            self.supplier["id"],
            phone="555-0199",
            address="11 Supply Street",
        )
        self.assertEqual(updated["phone"], "555-0199")
        self.assertEqual(search_suppliers("0199")[0]["id"], self.supplier["id"])

        with self.assertRaises(ValueError):
            create_supplier(self.sessions["admin"], "acme wholesale")
        with self.assertRaises(ValueError):
            create_supplier(
                self.sessions["admin"], "Different Name", email="ORDERS@ACME.TEST"
            )

        create_purchase_order(
            self.sessions["manager"],
            self.supplier["id"],
            "PO-HISTORY",
            [{"product_id": self.product["id"], "quantity": 1, "unit_cost": 10}],
        )
        inactive = deactivate_supplier(self.sessions["manager"], self.supplier["id"])
        self.assertFalse(inactive["is_active"])
        self.assertNotIn(self.supplier["id"], {row["id"] for row in search_suppliers()})
        self.assertIn(
            self.supplier["id"],
            {row["id"] for row in search_suppliers(include_inactive=True)},
        )
        with self.assertRaises(ValueError):
            create_purchase_order(
                self.sessions["manager"],
                self.supplier["id"],
                "PO-INACTIVE",
                [{"product_id": self.product["id"], "quantity": 1, "unit_cost": 10}],
            )

    def test_cashier_is_denied_procurement_and_supplier_operations(self):
        from auth import AuthorizationError
        from app.procurement.purchase_service import (
            create_purchase_order,
            receive_purchase_order,
            submit_purchase_order,
        )
        from app.procurement.supplier_service import create_supplier, update_supplier

        with self.assertRaises(AuthorizationError):
            create_supplier(self.sessions["cashier"], "Denied Supplier")
        with self.assertRaises(AuthorizationError):
            update_supplier(
                self.sessions["cashier"], self.supplier["id"], phone="denied"
            )
        with self.assertRaises(AuthorizationError):
            create_purchase_order(
                self.sessions["cashier"],
                self.supplier["id"],
                "PO-DENIED",
                [{"product_id": self.product["id"], "quantity": 1, "unit_cost": 5}],
            )
        order = create_purchase_order(
            self.sessions["manager"],
            self.supplier["id"],
            "PO-RECEIVE-DENIED",
            [{"product_id": self.product["id"], "quantity": 1, "unit_cost": 5}],
        )
        order = submit_purchase_order(
            self.sessions["manager"], order["purchase_order"]["id"]
        )
        with self.assertRaises(AuthorizationError):
            receive_purchase_order(
                self.sessions["cashier"],
                order["purchase_order"]["id"],
                [{"purchase_order_item_id": order["items"][0]["id"], "quantity": 1}],
            )

    def test_inventory_valuation_uses_moving_average_cost(self):
        from app.procurement.purchase_service import receive_purchase_order
        from app.reports.reporting_service import (
            get_average_cost_report,
            get_current_inventory_value,
            get_stock_value_by_category,
        )

        order = self.create_submitted_order(reference="PO-VALUE", quantity=10, unit_cost=20)
        receive_purchase_order(
            self.sessions["manager"],
            order["purchase_order"]["id"],
            [{"purchase_order_item_id": order["items"][0]["id"], "quantity": 10}],
        )

        product_value = next(
            row for row in get_average_cost_report() if row["id"] == self.product["id"]
        )
        current = get_current_inventory_value()
        category = next(
            row for row in get_stock_value_by_category() if row["category_id"] == 1
        )

        self.assertAlmostEqual(product_value["average_cost"], 15.0)
        self.assertAlmostEqual(product_value["inventory_value"], 300.0)
        self.assertAlmostEqual(current["current_inventory_value"], 300.0)
        self.assertAlmostEqual(category["inventory_value"], 300.0)

    def test_cost_updates_do_not_rewrite_historical_profit(self):
        from app.database.db_manager import get_connection
        from app.procurement.purchase_service import receive_purchase_order
        from app.reports.reporting_service import get_product_performance_report
        from app.sales.sales_service import PAYMENT_CARD, create_sale

        receipt = create_sale(
            self.sessions["cashier"],
            [{"product_id": self.product["id"], "quantity": 1}],
            payment_method=PAYMENT_CARD,
        )
        order = self.create_submitted_order(reference="PO-COST", quantity=1, unit_cost=100)
        receive_purchase_order(
            self.sessions["manager"],
            order["purchase_order"]["id"],
            [{"purchase_order_item_id": order["items"][0]["id"], "quantity": 1}],
        )

        performance = get_product_performance_report(limit=10)
        product_result = next(
            row for row in performance["highest_estimated_profit_products"]
            if row["id"] == self.product["id"]
        )
        with get_connection() as conn:
            sale_cost = conn.execute(
                "SELECT unit_cost_at_sale FROM sale_items WHERE sale_id = ?",
                (receipt["sale"]["sale_id"],),
            ).fetchone()[0]
            current_cost = conn.execute(
                "SELECT cost_price FROM products WHERE id = ?", (self.product["id"],)
            ).fetchone()[0]
        self.assertAlmostEqual(sale_cost, 10.0)
        self.assertAlmostEqual(current_cost, 19.0)
        self.assertAlmostEqual(product_result["estimated_profit"], 10.0)


class ProcurementMigrationTestCase(unittest.TestCase):
    def test_legacy_sale_items_gain_cost_snapshot_without_data_loss(self):
        db_file = tempfile.NamedTemporaryFile(delete=False)
        db_file.close()
        previous_path = os.environ.get("CARTHAGE_POS_DB")
        try:
            with sqlite3.connect(db_file.name) as conn:
                conn.execute(
                    """CREATE TABLE products (
                           id INTEGER PRIMARY KEY AUTOINCREMENT,
                           category_id INTEGER, supplier_id INTEGER,
                           sku TEXT NOT NULL UNIQUE, barcode TEXT UNIQUE,
                           name TEXT NOT NULL, description TEXT,
                           cost_price REAL NOT NULL DEFAULT 0,
                           selling_price REAL NOT NULL,
                           quantity_in_stock INTEGER NOT NULL DEFAULT 0,
                           reorder_level INTEGER NOT NULL DEFAULT 0,
                           is_active INTEGER NOT NULL DEFAULT 1,
                           created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                           updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                       )"""
                )
                conn.execute(
                    """INSERT INTO products (
                           id, sku, barcode, name, cost_price, selling_price,
                           quantity_in_stock, reorder_level, is_active
                       ) VALUES (1, 'LEGACY', 'LEGACY', 'Legacy Product', 7, 12, 3, 1, 1)"""
                )
                conn.execute(
                    """CREATE TABLE sale_items (
                           id INTEGER PRIMARY KEY AUTOINCREMENT,
                           sale_id INTEGER NOT NULL,
                           product_id TEXT NOT NULL,
                           quantity INTEGER NOT NULL,
                           price_at_sale REAL NOT NULL
                       )"""
                )
                conn.execute(
                    """INSERT INTO sale_items (
                           sale_id, product_id, quantity, price_at_sale
                       ) VALUES (1, '1', 2, 12)"""
                )
            conn.close()

            os.environ["CARTHAGE_POS_DB"] = db_file.name
            from app.database.db_manager import get_connection, initialize_database

            initialize_database()
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT quantity, price_at_sale, unit_cost_at_sale FROM sale_items WHERE id = 1"
                ).fetchone()
                procurement_tables = {
                    result["name"]
                    for result in conn.execute(
                        """SELECT name FROM sqlite_master
                           WHERE type = 'table' AND name LIKE 'purchase_%'"""
                    ).fetchall()
                }
            self.assertEqual(row["quantity"], 2)
            self.assertAlmostEqual(row["price_at_sale"], 12.0)
            self.assertAlmostEqual(row["unit_cost_at_sale"], 7.0)
            self.assertEqual(
                procurement_tables,
                {
                    "purchase_orders",
                    "purchase_order_items",
                    "purchase_receipts",
                    "purchase_receipt_items",
                },
            )
        finally:
            if previous_path is None:
                os.environ.pop("CARTHAGE_POS_DB", None)
            else:
                os.environ["CARTHAGE_POS_DB"] = previous_path
            os.unlink(db_file.name)


if __name__ == "__main__":
    unittest.main()
