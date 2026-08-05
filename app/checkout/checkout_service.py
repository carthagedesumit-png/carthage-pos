"""Persisted cart orchestration over the authoritative sales engine."""
import json
import sqlite3
from auth import INVENTORY_ROLES, require_store_access, validate_session
from app.barcodes.barcode_service import lookup_product
from app.core.exceptions import AuthorizationError, SalesError
from app.customers.customer_service import get_customer_by_id, search_customers
from app.database.db_manager import get_connection
from app.database.transactions import transaction
from app.documents.document_service import generate_sales_receipt
from app.hardware.hardware_service import (clear_display, maybe_open_drawer_after_sale, open_cash_drawer,
    print_receipt, show_cart_item, show_payment_confirmation, show_totals)
from app.inventory.inventory_service import get_product_by_id, search_products
from app.sales.sales_service import calculate_totals, create_sale, print_receipt_data, process_return

def active_cart(session):
    session=validate_session(session)
    with get_connection() as conn:
        row=conn.execute("SELECT id FROM checkout_carts WHERE user_id=? AND store_id=? AND status='ACTIVE' ORDER BY id DESC LIMIT 1",(session.user_id,session.store_id)).fetchone()
    return get_cart(session,row["id"]) if row else create_cart(session)

def create_cart(session):
    session=validate_session(session); require_store_access(session,session.store_id)
    with transaction() as conn:
        cid=conn.execute("INSERT INTO checkout_carts(user_id,store_id) VALUES(?,?)",(session.user_id,session.store_id)).lastrowid
        _event(conn,cid,session.user_id,"CART_CREATED")
    return get_cart(session,cid)

def get_cart(session,cart_id):
    session=validate_session(session)
    with get_connection() as conn:
        cart=conn.execute("SELECT * FROM checkout_carts WHERE id=?",(cart_id,)).fetchone()
        if not cart:raise SalesError("Cart not found.")
        require_store_access(session,cart["store_id"])
        if cart["user_id"]!=session.user_id and session.role not in INVENTORY_ROLES:raise AuthorizationError("Cart belongs to another cashier.")
        rows=conn.execute("SELECT ci.product_id,ci.quantity,p.name,p.sku,p.selling_price,si.quantity_on_hand FROM checkout_cart_items ci JOIN products p ON p.id=ci.product_id JOIN store_inventory si ON si.product_id=p.id AND si.store_id=? WHERE ci.cart_id=? ORDER BY ci.id",(cart["store_id"],cart_id)).fetchall()
    items=[dict(r) for r in rows]
    totals=calculate_totals(items,cart["discount_type"],cart["discount_value"],store_id=cart["store_id"]) if items else {"subtotal":0,"discount_amount":0,"tax_amount":0,"total_amount":0,"items":[]}
    customer=get_customer_by_id(cart["customer_id"]) if cart["customer_id"] else None
    return {"cart":dict(cart),"items":items,"totals":totals,"customer":customer}

def add_identifier(session,cart_id,identifier,quantity=1):
    session=validate_session(session); cart=get_cart(session,cart_id); product=lookup_product(identifier,store_id=cart["cart"]["store_id"],session=session)
    if not product:raise SalesError("Product not found for barcode, SKU, or search selection.")
    return set_item(session,cart_id,product["id"],quantity,increment=True)

def set_item(session,cart_id,product_id,quantity,increment=False):
    session=validate_session(session); cart=get_cart(session,cart_id); quantity=int(quantity)
    with transaction() as conn:
        current=conn.execute("SELECT quantity FROM checkout_cart_items WHERE cart_id=? AND product_id=?",(cart_id,product_id)).fetchone()
        desired=(current["quantity"] if current else 0)+quantity if increment else quantity
        if desired<=0:
            conn.execute("DELETE FROM checkout_cart_items WHERE cart_id=? AND product_id=?",(cart_id,product_id)); _event(conn,cart_id,session.user_id,"ITEM_REMOVED",{"product_id":product_id})
        else:
            product=get_product_by_id(product_id,conn=conn,store_id=cart["cart"]["store_id"])
            if not product or not product["is_active"]:raise SalesError("Product not found or inactive.")
            reserved=conn.execute("""SELECT COALESCE(SUM(ci.quantity),0) FROM checkout_cart_items ci JOIN checkout_carts c ON c.id=ci.cart_id WHERE ci.product_id=? AND c.store_id=? AND c.status IN ('ACTIVE','SUSPENDED') AND c.id!=?""",(product_id,cart["cart"]["store_id"],cart_id)).fetchone()[0]
            if desired+reserved>product["quantity_in_stock"]:raise SalesError("Insufficient available stock after cart reservations.")
            conn.execute("INSERT INTO checkout_cart_items(cart_id,product_id,quantity) VALUES(?,?,?) ON CONFLICT(cart_id,product_id) DO UPDATE SET quantity=excluded.quantity,updated_at=CURRENT_TIMESTAMP",(cart_id,product_id,desired))
            _event(conn,cart_id,session.user_id,"ITEM_UPDATED",{"product_id":product_id,"quantity":desired})
    updated=get_cart(session,cart_id)
    if desired>0:
        item=next(x for x in updated["items"] if x["product_id"]==product_id); show_cart_item(session,item["name"],item["quantity"],item["selling_price"])
    show_totals(session,updated["totals"]["subtotal"],updated["totals"]["total_amount"]); return updated

def set_customer(session,cart_id,customer_id=None):
    session=validate_session(session); get_cart(session,cart_id)
    if customer_id and not get_customer_by_id(int(customer_id)):raise SalesError("Customer not found.")
    with transaction() as conn:conn.execute("UPDATE checkout_carts SET customer_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(int(customer_id) if customer_id else None,cart_id));_event(conn,cart_id,session.user_id,"CUSTOMER_SET")
    return get_cart(session,cart_id)

def apply_discount(session,cart_id,discount_type,value,reason):
    session=validate_session(session)
    if session.role not in INVENTORY_ROLES:raise AuthorizationError("Manager authorization is required for discounts.")
    if not str(reason or "").strip():raise SalesError("Discount reason is required.")
    cart=get_cart(session,cart_id); calculate_totals(cart["items"],discount_type,float(value),store_id=cart["cart"]["store_id"])
    with transaction() as conn:conn.execute("UPDATE checkout_carts SET discount_type=?,discount_value=?,discount_reason=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(discount_type,float(value),reason.strip(),cart_id));_event(conn,cart_id,session.user_id,"DISCOUNT_APPROVED",{"type":discount_type,"value":float(value),"reason":reason.strip()})
    return get_cart(session,cart_id)

def suspend_cart(session,cart_id):return _status(session,cart_id,"SUSPENDED","CART_SUSPENDED")
def resume_cart(session,cart_id):return _status(session,cart_id,"ACTIVE","CART_RESUMED",suspend_current=True)
def void_cart(session,cart_id):return _status(session,cart_id,"VOIDED","CART_VOIDED")
def list_holds(session):
    session=validate_session(session)
    with get_connection() as conn:rows=conn.execute("SELECT id,customer_id,created_at,updated_at FROM checkout_carts WHERE store_id=? AND status='SUSPENDED' ORDER BY updated_at DESC",(session.store_id,)).fetchall()
    return [dict(r) for r in rows]

def checkout(session,cart_id,*,payment_method="CASH",amount_paid=None,payments=None,redeem_points=0,print_after=False,payment_reference=None):
    session=validate_session(session); cart=get_cart(session,cart_id)
    if cart["cart"]["status"] == "COMPLETED" and cart["cart"]["completed_sale_id"]:
        result=print_receipt_data(cart["cart"]["completed_sale_id"])
    elif cart["cart"]["status"] != "ACTIVE":
        raise SalesError("Only an active cart can be checked out.")
    else:
        try:
            result=create_sale(session,[{"product_id":x["product_id"],"quantity":x["quantity"]} for x in cart["items"]],payment_method=payment_method,amount_paid=amount_paid,discount_type=cart["cart"]["discount_type"],discount_value=cart["cart"]["discount_value"],store_id=cart["cart"]["store_id"],customer_id=cart["cart"]["customer_id"],redeem_points=int(redeem_points or 0),payments=payments,source_cart_id=cart_id,payment_reference=payment_reference)
        except sqlite3.IntegrityError:
            with get_connection() as conn:existing=conn.execute("SELECT sale_id FROM sales WHERE source_cart_id=?",(cart_id,)).fetchone()
            if not existing:raise
            result=print_receipt_data(existing["sale_id"])
    show_payment_confirmation(session,result["sale"]["total_amount"]);maybe_open_drawer_after_sale(session,result);clear_display(session)
    hardware=print_receipt(session,result["sale"]["sale_id"]) if print_after else {"skipped":True}
    return {"receipt":result,"document":generate_sales_receipt(result["sale"]["sale_id"]),"hardware":hardware}

def receipt_actions(session,sale_id,action):
    if action=="print":return print_receipt(session,sale_id)
    if action=="drawer":return open_cash_drawer(session)
    return generate_sales_receipt(sale_id)

def return_sale(session,sale_id,items,reason):return process_return(session,sale_id,items,reason)
def product_search(session,term):return search_products(term,store_id=session.store_id)[:25]
def customer_search(session,term):return search_customers(session,term)[:25]

def _status(session,cart_id,status,event,suspend_current=False):
    session=validate_session(session);get_cart(session,cart_id)
    with transaction() as conn:
        if suspend_current:conn.execute("UPDATE checkout_carts SET status='SUSPENDED',updated_at=CURRENT_TIMESTAMP WHERE user_id=? AND store_id=? AND status='ACTIVE'",(session.user_id,session.store_id))
        conn.execute("UPDATE checkout_carts SET status=?,user_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(status,session.user_id,cart_id));_event(conn,cart_id,session.user_id,event)
    return get_cart(session,cart_id)
def _event(conn,cart,user,event,details=None):conn.execute("INSERT INTO checkout_events(cart_id,user_id,event_type,details) VALUES(?,?,?,?)",(cart,user,event,json.dumps(details or {},sort_keys=True)))
