import os
import shutil
import tempfile
import unittest
from pathlib import Path


class PilotDataSetupTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        os.environ["CARTHAGE_POS_DB"] = str(self.root / "pilot.db")
        os.environ["POS_BACKUP_DIRECTORY"] = str(self.root / "backups")
        from app.core.config import reset_config_cache
        from app.database.db_manager import initialize_database
        from tests.support import bootstrap_staff
        reset_config_cache(); initialize_database(); self.sessions = bootstrap_staff()

    def tearDown(self):
        os.environ.pop("CARTHAGE_POS_DB", None); os.environ.pop("POS_BACKUP_DIRECTORY", None)
        from app.core.config import reset_config_cache
        reset_config_cache(); shutil.rmtree(self.root, ignore_errors=True)

    def test_templates_are_utf8_and_formula_safe(self):
        from app.operations.pilot_data_service import csv_safe, template
        self.assertEqual(csv_safe("=2+2"), "'=2+2")
        self.assertEqual(template("products").decode("utf-8").splitlines()[0],
                         "sku,barcode,name,selling_price,cost_price,category,supplier,unit,reorder_level")

    def test_product_dry_run_reports_safe_structured_errors_and_writes_nothing(self):
        from app.operations.pilot_data_service import validate_csv
        bad = b"sku,barcode,name,selling_price,cost_price,category\nX,ABC,,no,-1,Missing\nX,ABC,Again,1,0,General\n"
        result = validate_csv(self.sessions["manager"], "PRODUCTS", bad)
        self.assertFalse(result["valid"]); self.assertIsNone(result["confirmation_token"])
        codes = {e["code"] for e in result["errors"]}
        self.assertTrue({"REQUIRED","INVALID_NUMBER","UNKNOWN_CATEGORY","DUPLICATE_SKU","DUPLICATE_BARCODE"}.issubset(codes))
        from app.database.db_manager import get_connection
        with get_connection() as conn: self.assertEqual(conn.execute("SELECT COUNT(*) FROM products").fetchone()[0], 0)

    def test_encoding_size_malformed_and_field_limits(self):
        from app.core.exceptions import ValidationError
        from app.operations.pilot_data_service import MAX_BYTES, validate_csv
        for content in (b"\xff", b'a,b\n"unterminated', b"x" * (MAX_BYTES + 1)):
            with self.assertRaises(ValidationError): validate_csv(self.sessions["admin"], "PRODUCTS", content)
        long_name = ("x" * 256).encode()
        result=validate_csv(self.sessions["admin"],"PRODUCTS",b"sku,name,selling_price\nA,"+long_name+b",1\n")
        self.assertIn("FIELD_TOO_LONG", {e["code"] for e in result["errors"]})

    def test_atomic_product_apply_and_duplicate_confirmation_prevention(self):
        from app.operations.pilot_data_service import apply_import, validate_csv
        content=b"sku,barcode,name,selling_price,cost_price,category,supplier,unit,reorder_level\nP-1,ABC123,Fictional Tea,2.50,1.25,General,Default Supplier,each,2\n"
        checked=validate_csv(self.sessions["manager"],"PRODUCTS",content)
        self.assertTrue(checked["valid"]); self.assertEqual(apply_import(self.sessions["manager"],checked["confirmation_token"])["created"],1)
        from app.core.exceptions import ValidationError
        with self.assertRaises(ValidationError): apply_import(self.sessions["manager"],checked["confirmation_token"])
        from app.database.db_manager import get_connection
        with get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM products WHERE sku='P-1'").fetchone()[0],1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM pilot_audit_events").fetchone()[0],2)

    def test_opening_stock_scope_movement_reconciliation_zero_and_authorization(self):
        from app.inventory.inventory_service import create_product
        product=create_product(self.sessions["manager"],"OPEN-1","Fictional Rice",3,cost_price=1)
        from app.operations.pilot_data_service import apply_import, validate_csv
        checked=validate_csv(self.sessions["manager"],"OPENING_STOCK",b"store_code,sku,quantity,unit_cost\nMAIN,OPEN-1,12,1.50\n")
        self.assertTrue(checked["valid"]); apply_import(self.sessions["manager"],checked["confirmation_token"])
        from app.database.db_manager import get_connection
        with get_connection() as conn:
            line=conn.execute("SELECT * FROM pilot_opening_stock_lines").fetchone(); self.assertEqual(line["quantity"],12); self.assertIsNotNone(line["movement_id"])
            movement=conn.execute("SELECT * FROM stock_movements WHERE id=?",(line["movement_id"],)).fetchone(); self.assertEqual(movement["new_quantity"],12); self.assertIn("OPENING_STOCK",movement["notes"])
        from app.core.exceptions import AuthorizationError
        with self.assertRaises(AuthorizationError): validate_csv(self.sessions["cashier"],"OPENING_STOCK",b"store_code,sku,quantity,unit_cost\nMAIN,OPEN-1,0,0\n")

    def test_onboarding_resumes_and_physical_completion_needs_evidence(self):
        from app.core.exceptions import AuthorizationError, ValidationError
        from app.operations.pilot_data_service import onboarding_summary, set_onboarding_step
        with self.assertRaises(ValidationError): set_onboarding_step(self.sessions["admin"],"peripherals","COMPLETED")
        set_onboarding_step(self.sessions["admin"],"company_profile","COMPLETED",notes="Confirmed fictional pilot profile")
        resumed=onboarding_summary(self.sessions["admin"]); self.assertEqual(resumed["completed"],1); self.assertTrue(resumed["resumable"])
        with self.assertRaises(AuthorizationError): onboarding_summary(self.sessions["manager"])

    def test_readiness_is_blocked_audited_and_physical_gate_cannot_be_fabricated(self):
        from app.operations.pilot_service import assess_pilot_readiness
        result=assess_pilot_readiness(self.sessions["admin"],"ASSESSMENT-001")
        self.assertEqual(result["overall"],"BLOCKING"); self.assertFalse(result["activation_performed"])
        checks={x["code"]:x["status"] for x in result["checks"]}
        self.assertEqual(checks["physical_acceptance"],"UNVERIFIED"); self.assertEqual(checks["product_catalogue"],"BLOCKING")
        from app.database.db_manager import get_connection
        with get_connection() as conn: self.assertEqual(conn.execute("SELECT COUNT(*) FROM pilot_audit_events WHERE event_type='READINESS_ASSESSED'").fetchone()[0],1)

    def test_failed_opening_stock_apply_is_atomic(self):
        from app.inventory.inventory_service import create_product, receive_stock
        create_product(self.sessions["manager"],"A","A",1); product=create_product(self.sessions["manager"],"B","B",1)
        checked=__import__('app.operations.pilot_data_service',fromlist=['validate_csv']).validate_csv(self.sessions["manager"],"OPENING_STOCK",b"store_code,sku,quantity,unit_cost\nMAIN,A,3,1\nMAIN,B,4,1\n")
        receive_stock(self.sessions["manager"],product["id"],1)
        from app.core.exceptions import ValidationError
        from app.operations.pilot_data_service import apply_import
        with self.assertRaises(ValidationError): apply_import(self.sessions["manager"],checked["confirmation_token"])
        from app.database.db_manager import get_connection
        with get_connection() as conn:
            self.assertEqual(conn.execute("SELECT quantity_on_hand FROM store_inventory si JOIN products p ON p.id=si.product_id WHERE p.sku='A'").fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM pilot_opening_stock_batches").fetchone()[0],0)

    def test_migration_is_idempotent(self):
        from app.database.db_manager import initialize_database, get_connection
        initialize_database(); initialize_database()
        with get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'pilot_%'").fetchone()[0],5)


if __name__ == "__main__": unittest.main()
