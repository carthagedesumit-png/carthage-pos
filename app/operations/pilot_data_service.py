"""Controlled pilot CSV validation, atomic apply, and resumable readiness evidence."""
import csv
import hashlib
import io
import json
import secrets
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from auth import require_inventory_management, validate_session
from app.core.exceptions import AuthorizationError, ValidationError
from app.database.db_manager import get_connection
from app.database.transactions import transaction
from app.inventory.inventory_service import ensure_store_inventory, log_stock_movement, sync_product_aggregate

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
MAX_FIELD = 255
STEPS = (
    "company_profile", "currency_country", "pilot_store", "administrator", "pilot_users",
    "role_store_assignments", "product_catalogue", "opening_stock", "document_branding",
    "backup_configuration", "licensing", "peripherals", "training", "go_live",
)
STATUSES = {"COMPLETED", "PENDING", "WARNING", "BLOCKED", "PHYSICALLY_UNVERIFIED"}
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value):
    text = str(value or "")
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


def template(kind):
    headers = {
        "products": ["sku", "barcode", "name", "selling_price", "cost_price", "category", "supplier", "unit", "reorder_level"],
        "opening_stock": ["store_code", "sku", "quantity", "unit_cost"],
        "suppliers": ["name", "email", "phone", "address"],
    }
    if kind not in headers:
        raise ValidationError("Unknown pilot CSV template.")
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\r\n").writerow([csv_safe(x) for x in headers[kind]])
    return output.getvalue().encode("utf-8")


def _decimal(value, row, field, errors, *, integral=False):
    try:
        number = Decimal(str(value).strip())
        if not number.is_finite() or number < 0 or (integral and number != number.to_integral_value()):
            raise InvalidOperation
        return int(number) if integral else format(number.quantize(Decimal("0.01")), "f")
    except (InvalidOperation, ValueError):
        errors.append({"row": row, "field": field, "code": "INVALID_NUMBER", "message": f"{field.replace('_',' ').title()} must be a non-negative {'whole number' if integral else 'decimal amount'}."})
        return None


def _decode(content):
    if not isinstance(content, bytes) or len(content) > MAX_BYTES:
        raise ValidationError("CSV upload must be no larger than 2 MiB.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError("CSV must use valid UTF-8 encoding.") from exc
    if "\x00" in text:
        raise ValidationError("CSV contains unsupported binary content.")
    return text


def validate_csv(session, import_type, content, store_id=None):
    session = require_inventory_management(session, store_id=store_id)
    import_type = str(import_type).upper()
    required = {"PRODUCTS": {"sku", "name", "selling_price"}, "OPENING_STOCK": {"store_code", "sku", "quantity", "unit_cost"}}
    if import_type not in required:
        raise ValidationError("Unsupported pilot import type.")
    try:
        reader = csv.DictReader(io.StringIO(_decode(content), newline=""), strict=True)
        fields = [str(x or "").strip().lower() for x in (reader.fieldnames or [])]
        if len(fields) != len(set(fields)) or not required[import_type].issubset(fields):
            raise ValidationError("CSV headers are missing, duplicated, or unsupported for this import.")
        rows = []
        for number, source in enumerate(reader, 2):
            if number - 1 > MAX_ROWS:
                raise ValidationError("CSV exceeds the 5,000-row limit.")
            row = {str(k or "").strip().lower(): str(v or "").strip() for k, v in source.items()}
            rows.append((number, row))
    except csv.Error as exc:
        raise ValidationError("CSV is malformed and could not be parsed safely.") from exc
    errors, normalized, seen_sku, seen_barcode = [], [], set(), set()
    with get_connection() as conn:
        stores = {r["code"].casefold(): dict(r) for r in conn.execute("SELECT id,code,is_active FROM stores")}
        categories = {r["name"].casefold(): r["id"] for r in conn.execute("SELECT id,name FROM categories WHERE is_active=1")}
        suppliers = {r["name"].casefold(): r["id"] for r in conn.execute("SELECT id,name FROM suppliers WHERE is_active=1")}
        existing_skus = {r[0].casefold() for r in conn.execute("SELECT sku FROM products")}
        existing_barcodes = {r[0].casefold() for r in conn.execute("SELECT value FROM product_identifiers WHERE is_active=1")}
        for number, row in rows:
            for field, value in row.items():
                if len(value) > MAX_FIELD:
                    errors.append({"row": number, "field": field, "code": "FIELD_TOO_LONG", "message": "Field exceeds the 255-character limit."})
            sku = row.get("sku", "")
            if not sku:
                errors.append({"row": number, "field": "sku", "code": "REQUIRED", "message": "SKU is required."})
            key = sku.casefold()
            if key in seen_sku or (import_type == "PRODUCTS" and key in existing_skus):
                errors.append({"row": number, "field": "sku", "code": "DUPLICATE_SKU", "message": "SKU already exists in this file or catalogue."})
            seen_sku.add(key)
            if import_type == "PRODUCTS":
                barcode = row.get("barcode", "")
                bkey = barcode.casefold()
                if barcode and (bkey in seen_barcode or bkey in existing_barcodes):
                    errors.append({"row": number, "field": "barcode", "code": "DUPLICATE_BARCODE", "message": "Barcode already exists in this file or catalogue."})
                if barcode: seen_barcode.add(bkey)
                if not row.get("name"):
                    errors.append({"row": number, "field": "name", "code": "REQUIRED", "message": "Product name is required."})
                price = _decimal(row.get("selling_price"), number, "selling_price", errors)
                cost = _decimal(row.get("cost_price", "0") or "0", number, "cost_price", errors)
                reorder = _decimal(row.get("reorder_level", "0") or "0", number, "reorder_level", errors, integral=True)
                category = row.get("category", "")
                supplier = row.get("supplier", "")
                if category and category.casefold() not in categories: errors.append({"row":number,"field":"category","code":"UNKNOWN_CATEGORY","message":"Category does not exist or is inactive."})
                if supplier and supplier.casefold() not in suppliers: errors.append({"row":number,"field":"supplier","code":"UNKNOWN_SUPPLIER","message":"Supplier does not exist or is inactive."})
                normalized.append({**row,"selling_price":price,"cost_price":cost,"reorder_level":reorder,"category_id":categories.get(category.casefold()),"supplier_id":suppliers.get(supplier.casefold())})
            else:
                store = stores.get(row.get("store_code", "").casefold())
                if not store or not store["is_active"]:
                    errors.append({"row":number,"field":"store_code","code":"INVALID_STORE","message":"Store code does not identify an active store."})
                elif int(store["id"]) != int(store_id or session.store_id):
                    errors.append({"row":number,"field":"store_code","code":"STORE_SCOPE","message":"Row is outside the confirmed target store."})
                product = conn.execute("SELECT id FROM products WHERE sku=? COLLATE NOCASE AND is_active=1", (sku,)).fetchone()
                if not product: errors.append({"row":number,"field":"sku","code":"UNKNOWN_PRODUCT","message":"SKU does not identify an active product."})
                quantity = _decimal(row.get("quantity"), number, "quantity", errors, integral=True)
                cost = _decimal(row.get("unit_cost"), number, "unit_cost", errors)
                normalized.append({**row,"product_id":product["id"] if product else None,"store_id":store["id"] if store else None,"quantity":quantity,"unit_cost":cost})
    result = {"valid": not errors, "import_type": import_type, "row_count": len(rows), "errors": errors, "confirmation_token": None, "summary": {"rows":len(rows)}}
    if not errors:
        payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256((import_type + "\n" + payload).encode()).hexdigest()
        token = secrets.token_urlsafe(24)
        with transaction() as conn:
            conn.execute("INSERT INTO pilot_import_batches(confirmation_token,import_type,target_store_id,payload_json,payload_digest,row_count,status,validated_by) VALUES(?,?,?,?,?,?,'VALIDATED',?)",(token,import_type,int(store_id or session.store_id),payload,digest,len(rows),session.user_id))
            _audit(conn, session, "IMPORT_VALIDATED", token, {"type":import_type,"rows":len(rows)})
        result["confirmation_token"] = token
    return result


def apply_import(session, confirmation_token):
    session = require_inventory_management(session)
    with transaction() as conn:
        batch = conn.execute("SELECT * FROM pilot_import_batches WHERE confirmation_token=?", (confirmation_token,)).fetchone()
        if not batch or batch["status"] != "VALIDATED": raise ValidationError("Import confirmation is invalid or has already been used.")
        if int(batch["target_store_id"]) != int(session.store_id) and session.role != "admin": raise AuthorizationError("Import target is outside this user's store scope.")
        rows = json.loads(batch["payload_json"]); created = 0
        if batch["import_type"] == "PRODUCTS":
            for row in rows:
                cur=conn.execute("INSERT INTO products(category_id,supplier_id,sku,barcode,name,cost_price,selling_price,quantity_in_stock,reorder_level,is_active,unit) VALUES(?,?,?,?,?,?,?,0,0,1,?)",(row.get("category_id"),row.get("supplier_id"),row["sku"],row.get("barcode") or None,row["name"],float(Decimal(row["cost_price"])),float(Decimal(row["selling_price"])),row.get("unit") or "each"))
                product_id=cur.lastrowid
                if row.get("barcode"): conn.execute("INSERT INTO product_identifiers(product_id,identifier_type,format,value,is_primary,is_active,created_by) VALUES(?,'PRIMARY','CODE128',?,1,1,?)",(product_id,row["barcode"],session.user_id))
                conn.execute("INSERT INTO store_inventory(store_id,product_id,quantity_on_hand,reorder_level,average_cost) SELECT id,?,0,?,? FROM stores WHERE is_active=1",(product_id,int(row["reorder_level"]),float(Decimal(row["cost_price"]))))
                created += 1
        else:
            total_qty=sum(int(r["quantity"]) for r in rows);total_value=sum(Decimal(r["unit_cost"])*int(r["quantity"]) for r in rows)
            cur=conn.execute("INSERT INTO pilot_opening_stock_batches(import_batch_id,store_id,status,total_quantity,total_value,applied_by) VALUES(?,?,'APPLIED',?,?,?)",(batch["id"],batch["target_store_id"],total_qty,format(total_value,"f"),session.user_id)); opening_id=cur.lastrowid
            for row in rows:
                ensure_store_inventory(conn,row["store_id"],row["product_id"]);inv=conn.execute("SELECT quantity_on_hand,average_cost FROM store_inventory WHERE store_id=? AND product_id=?",(row["store_id"],row["product_id"])).fetchone()
                qty=int(row["quantity"]);cost=Decimal(row["unit_cost"]);old=int(inv["quantity_on_hand"])
                if old != 0: raise ValidationError("Opening stock may only be applied to a zero-balance product at the target store.")
                conn.execute("UPDATE store_inventory SET quantity_on_hand=?,average_cost=?,updated_at=CURRENT_TIMESTAMP WHERE store_id=? AND product_id=?",(qty,float(cost),row["store_id"],row["product_id"]));sync_product_aggregate(conn,row["product_id"])
                movement=None
                if qty:
                    log_stock_movement(conn,row["product_id"],"ADJUSTMENT",qty,0,qty,session.user_id,f"OPENING_STOCK batch {opening_id}",store_id=row["store_id"]);movement=conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                conn.execute("INSERT INTO pilot_opening_stock_lines(batch_id,product_id,quantity,unit_cost,movement_id) VALUES(?,?,?,?,?)",(opening_id,row["product_id"],qty,row["unit_cost"],movement));created += 1
        outcome={"created":created,"rows":len(rows)}
        conn.execute("UPDATE pilot_import_batches SET status='APPLIED',applied_by=?,applied_at=CURRENT_TIMESTAMP,outcome_json=? WHERE id=?",(session.user_id,json.dumps(outcome,sort_keys=True),batch["id"]))
        _audit(conn,session,"IMPORT_APPLIED",confirmation_token,{"type":batch["import_type"],**outcome})
    return {"status":"APPLIED",**outcome}


def set_onboarding_step(session, step, status, evidence_reference=None, notes=None):
    session=validate_session(session)
    if session.role != "admin": raise AuthorizationError("Administrator access is required.")
    if step not in STEPS or status not in STATUSES: raise ValidationError("Invalid onboarding step or status.")
    evidence=str(evidence_reference or "").strip();note=str(notes or "").strip()
    if len(evidence)>120 or len(note)>500 or evidence.startswith(("/","\\")) or ":\\" in evidence: raise ValidationError("Evidence reference or note is invalid.")
    if step in {"peripherals","go_live"} and status=="COMPLETED" and not evidence: raise ValidationError("Physical and go-live completion require a controlled evidence reference.")
    with transaction() as conn:
        conn.execute("INSERT INTO pilot_onboarding_steps(step_code,status,evidence_reference,notes,updated_by) VALUES(?,?,?,?,?) ON CONFLICT(step_code) DO UPDATE SET status=excluded.status,evidence_reference=excluded.evidence_reference,notes=excluded.notes,updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP",(step,status,evidence or None,note or None,session.user_id));_audit(conn,session,"ONBOARDING_STEP_UPDATED",step,{"status":status,"evidence":bool(evidence)})
    return onboarding_summary(session)


def onboarding_summary(session):
    session=validate_session(session)
    if session.role != "admin": raise AuthorizationError("Administrator access is required.")
    with get_connection() as conn: saved={r["step_code"]:dict(r) for r in conn.execute("SELECT * FROM pilot_onboarding_steps")}
    steps=[saved.get(code,{"step_code":code,"status":"PHYSICALLY_UNVERIFIED" if code=="peripherals" else "PENDING","evidence_reference":None,"notes":None}) for code in STEPS]
    return {"steps":steps,"completed":sum(x["status"]=="COMPLETED" for x in steps),"total":len(steps),"resumable":True}


def _audit(conn, session, event, subject, details):
    conn.execute("INSERT INTO pilot_audit_events(event_type,user_id,store_id,subject_reference,details) VALUES(?,?,?,?,?)",(event,session.user_id,session.store_id,str(subject)[:120],json.dumps(details,sort_keys=True)))
