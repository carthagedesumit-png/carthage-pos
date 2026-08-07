import os
import tempfile
import unittest


class MultiStoreTestCase(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()
        os.environ["CARTHAGE_POS_DB"] = self.db_file.name

        from app.database.db_manager import initialize_database
        from app.stores.store_service import create_store, get_default_store_id
        from tests.support import bootstrap_staff

        initialize_database()
        self.sessions = bootstrap_staff()
        self.main_store_id = get_default_store_id()
        self.branch = create_store(
            self.sessions["admin"],
            "BR-02",
            "Second Branch",
            address="2 Branch Road",
            manager_user_id=self.sessions["manager"].user_id,
        )

    def tearDown(self):
        os.environ.pop("CARTHAGE_POS_DB", None)
        os.unlink(self.db_file.name)

    def create_product(self, quantity=10, cost=5.0, price=10.0):
        from app.inventory.inventory_service import create_product

        return create_product(
            self.sessions["manager"],
            sku="MULTI-1",
            barcode="MULTI-1",
            name="Multi Store Product",
            selling_price=price,
            cost_price=cost,
            quantity_in_stock=quantity,
            reorder_level=2,
        )

    def test_store_management_and_assignment_permissions(self):
        from auth import AuthorizationError, switch_store
        from app.stores.store_service import (
            create_store,
            deactivate_store,
            reactivate_store,
            search_stores,
            update_store,
        )

        manager_at_branch = switch_store(
            self.sessions["manager"], self.branch["id"]
        )
        updated = update_store(
            manager_at_branch, self.branch["id"], phone="555-0202"
        )
        self.assertEqual(updated["phone"], "555-0202")
        with self.assertRaises(ValueError):
            create_store(self.sessions["admin"], "br-02", "Duplicate")
        with self.assertRaises(AuthorizationError):
            create_store(self.sessions["cashier"], "DENIED", "Denied")
        with self.assertRaises(AuthorizationError):
            switch_store(self.sessions["cashier"], self.branch["id"])

        inactive = deactivate_store(self.sessions["admin"], self.branch["id"])
        self.assertFalse(inactive["is_active"])
        self.assertNotIn(
            self.branch["id"], {store["id"] for store in search_stores()}
        )
        self.assertTrue(
            reactivate_store(self.sessions["admin"], self.branch["id"])["is_active"]
        )

    def test_inventory_is_separated_and_aggregate_is_backward_compatible(self):
        from auth import switch_store
        from app.database.db_manager import get_connection
        from app.inventory.inventory_service import adjust_stock, get_store_inventory

        product = self.create_product(quantity=10)
        manager_at_branch = switch_store(
            self.sessions["manager"], self.branch["id"]
        )
        adjust_stock(
            manager_at_branch,
            product["id"],
            5,
            notes="Branch opening stock",
            store_id=self.branch["id"],
        )

        main = get_store_inventory(product["id"], self.main_store_id)
        branch = get_store_inventory(product["id"], self.branch["id"])
        with get_connection() as conn:
            aggregate = conn.execute(
                "SELECT quantity_in_stock FROM products WHERE id = ?", (product["id"],)
            ).fetchone()[0]
        self.assertEqual(main["quantity_on_hand"], 10)
        self.assertEqual(branch["quantity_on_hand"], 5)
        self.assertEqual(aggregate, 15)

    def test_store_aware_sale_only_decrements_originating_branch(self):
        from auth import authenticate_user, create_user
        from app.database.db_manager import get_connection
        from app.inventory.inventory_service import adjust_stock, get_store_inventory
        from app.sales.sales_service import PAYMENT_CARD, create_sale

        product = self.create_product(quantity=10)
        adjust_stock(
            self.sessions["manager"], product["id"], 4, store_id=self.branch["id"]
        )
        create_user(
            "branch-cashier",
            "cashier-password",
            "Branch Cashier",
            "cashier",
            acting_session=self.sessions["admin"],
            home_store_id=self.branch["id"],
        )
        cashier = authenticate_user("branch-cashier", "cashier-password")
        sale = create_sale(
            cashier,
            [{"product_id": product["id"], "quantity": 2}],
            payment_method=PAYMENT_CARD,
            register_name="REGISTER-2",
        )

        self.assertEqual(sale["sale"]["store_id"], self.branch["id"])
        self.assertEqual(sale["sale"]["register_name"], "REGISTER-2")
        self.assertEqual(
            get_store_inventory(product["id"], self.main_store_id)["quantity_on_hand"],
            10,
        )
        self.assertEqual(
            get_store_inventory(product["id"], self.branch["id"])["quantity_on_hand"],
            2,
        )
        with get_connection() as conn:
            movement_store = conn.execute(
                """SELECT store_id FROM stock_movements
                   WHERE movement_type = 'SALE' ORDER BY id DESC LIMIT 1"""
            ).fetchone()[0]
        self.assertEqual(movement_store, self.branch["id"])

    def test_procurement_receipt_targets_only_selected_store(self):
        from auth import switch_store
        from app.inventory.inventory_service import get_store_inventory
        from app.procurement.purchase_service import (
            create_purchase_order,
            receive_purchase_order,
            submit_purchase_order,
        )
        from app.procurement.supplier_service import create_supplier

        product = self.create_product(quantity=10)
        manager = switch_store(self.sessions["manager"], self.branch["id"])
        supplier = create_supplier(manager, "Branch Supplier")
        order = create_purchase_order(
            manager,
            supplier["id"],
            "PO-BRANCH-1",
            [{"product_id": product["id"], "quantity": 3, "unit_cost": 7}],
            store_id=self.branch["id"],
        )
        order = submit_purchase_order(manager, order["purchase_order"]["id"])
        receive_purchase_order(
            manager,
            order["purchase_order"]["id"],
            [{"purchase_order_item_id": order["items"][0]["id"], "quantity": 3}],
        )

        self.assertEqual(
            get_store_inventory(product["id"], self.main_store_id)["quantity_on_hand"],
            10,
        )
        self.assertEqual(
            get_store_inventory(product["id"], self.branch["id"])["quantity_on_hand"],
            3,
        )

    def test_partial_transfer_preserves_total_and_in_transit_inventory(self):
        from app.inventory.inventory_service import get_store_inventory
        from app.stores.transfer_service import (
            STATUS_IN_TRANSIT,
            STATUS_RECEIVED,
            approve_transfer,
            create_transfer,
            dispatch_transfer,
            receive_transfer,
        )

        product = self.create_product(quantity=10)
        transfer = create_transfer(
            self.sessions["manager"],
            "TR-001",
            self.main_store_id,
            self.branch["id"],
            [{"product_id": product["id"], "quantity": 6}],
        )
        transfer = approve_transfer(
            self.sessions["manager"], transfer["transfer"]["id"]
        )
        line_id = transfer["items"][0]["id"]
        transfer = dispatch_transfer(
            self.sessions["manager"],
            transfer["transfer"]["id"],
            [{"transfer_item_id": line_id, "quantity": 3}],
        )
        self.assertEqual(transfer["transfer"]["status"], STATUS_IN_TRANSIT)
        self.assertEqual(transfer["items"][0]["quantity_in_transit"], 3)
        transfer = receive_transfer(
            self.sessions["manager"],
            transfer["transfer"]["id"],
            [{"transfer_item_id": line_id, "quantity": 2}],
        )
        self.assertEqual(transfer["items"][0]["quantity_in_transit"], 1)
        transfer = dispatch_transfer(
            self.sessions["manager"],
            transfer["transfer"]["id"],
            [{"transfer_item_id": line_id, "quantity": 3}],
        )
        transfer = receive_transfer(
            self.sessions["manager"],
            transfer["transfer"]["id"],
            [{"transfer_item_id": line_id, "quantity": 4}],
        )

        main_quantity = get_store_inventory(
            product["id"], self.main_store_id
        )["quantity_on_hand"]
        branch_quantity = get_store_inventory(
            product["id"], self.branch["id"]
        )["quantity_on_hand"]
        self.assertEqual(transfer["transfer"]["status"], STATUS_RECEIVED)
        self.assertEqual(main_quantity, 4)
        self.assertEqual(branch_quantity, 6)
        self.assertEqual(main_quantity + branch_quantity, 10)
        self.assertEqual(len(transfer["dispatches"]), 2)
        self.assertEqual(len(transfer["receipts"]), 2)

    def test_reporting_filters_and_branch_comparison(self):
        from auth import AuthorizationError, authenticate_user, create_user
        from app.inventory.inventory_service import adjust_stock
        from app.reports.reporting_service import (
            get_branch_comparison_report,
            get_inventory_valuation,
            get_sales_summary,
        )
        from app.sales.sales_service import PAYMENT_CARD, create_sale

        product = self.create_product(quantity=10)
        adjust_stock(
            self.sessions["manager"], product["id"], 5, store_id=self.branch["id"]
        )
        create_user(
            "branch-report-cashier",
            "cashier-password",
            "Branch Report Cashier",
            "cashier",
            acting_session=self.sessions["admin"],
            home_store_id=self.branch["id"],
        )
        branch_cashier = authenticate_user(
            "branch-report-cashier", "cashier-password"
        )
        create_sale(
            self.sessions["cashier"],
            [{"product_id": product["id"], "quantity": 1}],
            payment_method=PAYMENT_CARD,
        )
        create_sale(
            branch_cashier,
            [{"product_id": product["id"], "quantity": 2}],
            payment_method=PAYMENT_CARD,
        )

        main_sales = get_sales_summary(store_ids=[self.main_store_id])
        branch_sales = get_sales_summary(store_ids=[self.branch["id"]])
        company_sales = get_sales_summary()
        branch_value = get_inventory_valuation(store_ids=[self.branch["id"]])
        comparison = {
            row["store_id"]: row for row in get_branch_comparison_report()
        }

        self.assertAlmostEqual(main_sales["total_sales"], 10.0)
        self.assertAlmostEqual(branch_sales["total_sales"], 20.0)
        self.assertAlmostEqual(company_sales["total_sales"], 30.0)
        self.assertEqual(branch_value["total_units"], 3)
        self.assertAlmostEqual(comparison[self.branch["id"]]["net_sales"], 20.0)
        with self.assertRaises(AuthorizationError):
            get_sales_summary(
                store_ids=[self.branch["id"]], session=self.sessions["cashier"]
            )

    def test_transfer_validation_and_manager_store_scope(self):
        from auth import AuthorizationError, switch_store
        from app.stores.store_service import create_store, deactivate_store
        from app.stores.transfer_service import approve_transfer, create_transfer

        product = self.create_product(quantity=2)
        third = create_store(self.sessions["admin"], "BR-03", "Third Branch")
        with self.assertRaises(AuthorizationError):
            switch_store(self.sessions["manager"], third["id"])
        with self.assertRaises(ValueError):
            create_transfer(
                self.sessions["manager"],
                "TR-SAME",
                self.main_store_id,
                self.main_store_id,
                [{"product_id": product["id"], "quantity": 1}],
            )
        with self.assertRaises(AuthorizationError):
            create_transfer(
                self.sessions["cashier"],
                "TR-CASHIER",
                self.main_store_id,
                self.branch["id"],
                [{"product_id": product["id"], "quantity": 1}],
            )

        insufficient = create_transfer(
            self.sessions["manager"],
            "TR-TOO-MUCH",
            self.main_store_id,
            self.branch["id"],
            [{"product_id": product["id"], "quantity": 3}],
        )
        with self.assertRaises(ValueError):
            approve_transfer(
                self.sessions["manager"], insufficient["transfer"]["id"]
            )

        deactivate_store(self.sessions["admin"], third["id"])
        with self.assertRaises(ValueError):
            create_transfer(
                self.sessions["manager"],
                "TR-INACTIVE",
                self.main_store_id,
                third["id"],
                [{"product_id": product["id"], "quantity": 1}],
            )


if __name__ == "__main__":
    unittest.main()
