"""Deterministic SQLite fixtures reconstructed from supported repository milestones.

``core_multistore_68db2de`` uses the table/column contracts committed at
68db2de (multi-store and transfer support). ``payments_fd5c947`` adds the
sale-payment, tender, return and hardware contracts present at fd5c947
(payment/refund hardening). The SQL below is explicit so tests do not depend on
Git or manufacture history by migrating today's schema and deleting objects.
``pre_deployment_settings`` is a non-operational bootstrap input, not an
advertised business-database upgrade path.
"""

import sqlite3
from pathlib import Path


HISTORICAL_FIXTURE_STATES = (
    "core_multistore_68db2de",
    "payments_fd5c947",
)
BOOTSTRAP_FIXTURE_STATES = ("pre_deployment_settings",)
FIXTURE_STATES = BOOTSTRAP_FIXTURE_STATES + HISTORICAL_FIXTURE_STATES
FIXTURE_PASSWORD = "Fixture-Only-Admin9!"
FIXTURE_PASSWORD_HASH = "$2b$04$abcdefghijklmnopqrstuuITY0DVHLGeBGt7F8ruivgxoXRWiRgnq"


CORE_SCHEMA = """
CREATE TABLE users (
 id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
 password_hash TEXT NOT NULL, full_name TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('admin','manager','cashier')),
 is_active INTEGER NOT NULL DEFAULT 1, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 last_login DATETIME, home_store_id INTEGER);
CREATE TABLE stores (
 id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL COLLATE NOCASE UNIQUE,
 name TEXT NOT NULL, address TEXT, phone TEXT, email TEXT, manager_user_id INTEGER,
 is_active INTEGER NOT NULL DEFAULT 1, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 updated_at DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE user_store_access (
 user_id INTEGER NOT NULL, store_id INTEGER NOT NULL,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(user_id,store_id));
CREATE TABLE categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
 description TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE suppliers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
 phone TEXT, email TEXT, address TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE products (
 id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER, supplier_id INTEGER,
 sku TEXT NOT NULL UNIQUE, barcode TEXT UNIQUE, name TEXT NOT NULL, description TEXT,
 cost_price REAL NOT NULL DEFAULT 0, selling_price REAL NOT NULL,
 quantity_in_stock INTEGER NOT NULL DEFAULT 0, reorder_level INTEGER NOT NULL DEFAULT 0,
 is_active INTEGER NOT NULL DEFAULT 1, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 updated_at DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE store_inventory (
 store_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
 quantity_on_hand INTEGER NOT NULL DEFAULT 0, reorder_level INTEGER NOT NULL DEFAULT 0,
 average_cost REAL NOT NULL DEFAULT 0, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(store_id,product_id));
CREATE TABLE stock_movements (
 id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL,
 movement_type TEXT NOT NULL, quantity INTEGER NOT NULL, previous_quantity INTEGER NOT NULL,
 new_quantity INTEGER NOT NULL, user_id INTEGER, store_id INTEGER, transfer_id INTEGER,
 notes TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE sales (
 sale_id INTEGER PRIMARY KEY AUTOINCREMENT, receipt_number TEXT UNIQUE,
 timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 user_id INTEGER, store_id INTEGER, register_name TEXT NOT NULL DEFAULT 'REGISTER-1',
 username TEXT NOT NULL DEFAULT 'system', cashier_name TEXT NOT NULL DEFAULT 'system',
 subtotal REAL NOT NULL DEFAULT 0, discount_amount REAL NOT NULL DEFAULT 0,
 tax REAL NOT NULL DEFAULT 0, tax_amount REAL NOT NULL DEFAULT 0,
 total REAL NOT NULL DEFAULT 0, total_amount REAL NOT NULL DEFAULT 0,
 payment_method TEXT NOT NULL DEFAULT 'CASH', payment_status TEXT NOT NULL DEFAULT 'PAID',
 amount_paid REAL NOT NULL DEFAULT 0, change_given REAL NOT NULL DEFAULT 0);
CREATE TABLE sale_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT, sale_id INTEGER NOT NULL, product_id TEXT NOT NULL,
 quantity INTEGER NOT NULL, price_at_sale REAL NOT NULL);
CREATE TABLE sales_returns (
 id INTEGER PRIMARY KEY AUTOINCREMENT, sale_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
 reason TEXT NOT NULL, total_refunded REAL NOT NULL DEFAULT 0,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE sales_return_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT, return_id INTEGER NOT NULL,
 sale_item_id INTEGER NOT NULL, quantity INTEGER NOT NULL, refund_amount REAL NOT NULL);
"""

PAYMENT_SCHEMA = """
CREATE TABLE sale_payments (
 id INTEGER PRIMARY KEY AUTOINCREMENT, sale_id INTEGER NOT NULL,
 payment_method TEXT NOT NULL, amount REAL NOT NULL, reference TEXT,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE hardware_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, device_type TEXT NOT NULL,
 operation TEXT NOT NULL, success INTEGER NOT NULL, user_id INTEGER, store_id INTEGER,
 details TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, sale_id INTEGER,
 reason TEXT, attempt_type TEXT);
"""


def build_upgrade_fixture(path: str | Path, state: str) -> Path:
    if state not in FIXTURE_STATES:
        raise ValueError(f"Unknown upgrade fixture: {state}")
    destination = Path(path)
    connection = sqlite3.connect(destination)
    try:
        if state == "pre_deployment_settings":
            connection.executescript("""
                CREATE TABLE legacy_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO legacy_settings VALUES ('currency','FIC');
                INSERT INTO legacy_settings VALUES ('receipt_prefix','SALE-FIX');
                PRAGMA user_version=0;
            """)
        else:
            connection.executescript(CORE_SCHEMA)
            if state == "payments_fd5c947":
                connection.executescript(PAYMENT_SCHEMA)
            _seed_business_rows(connection, with_payments=state == "payments_fd5c947")
            connection.execute("PRAGMA user_version=0")
        connection.commit()
    finally:
        connection.close()
    return destination


def _seed_business_rows(connection: sqlite3.Connection, *, with_payments: bool) -> None:
    connection.execute("INSERT INTO stores(id,code,name) VALUES(1,'MAIN','Historical Main Store')")
    connection.execute(
        "INSERT INTO users(id,username,password_hash,full_name,role,home_store_id) "
        "VALUES(101,'fixture.admin',?,'Fixture Administrator','admin',1)",
        (FIXTURE_PASSWORD_HASH,),
    )
    connection.execute("INSERT INTO user_store_access(user_id,store_id) VALUES(101,1)")
    connection.execute("INSERT INTO categories(id,name) VALUES(1,'Historical General')")
    connection.execute("INSERT INTO suppliers(id,name) VALUES(1,'Historical Supplier')")
    connection.execute(
        "INSERT INTO products(id,category_id,supplier_id,sku,name,cost_price,selling_price,"
        "quantity_in_stock,reorder_level) VALUES(201,1,1,'FIXTURE-001','Fictional Product',3.25,5.50,7,2)"
    )
    connection.execute(
        "INSERT INTO store_inventory(store_id,product_id,quantity_on_hand,reorder_level,average_cost) "
        "VALUES(1,201,7,2,3.25)"
    )
    connection.execute(
        "INSERT INTO stock_movements(id,product_id,movement_type,quantity,previous_quantity,new_quantity,"
        "user_id,store_id,notes) VALUES(701,201,'PURCHASE',7,0,7,101,1,'Historical opening stock')"
    )
    connection.execute(
        "INSERT INTO sales(sale_id,receipt_number,user_id,store_id,username,cashier_name,subtotal,total,"
        "total_amount,payment_method,amount_paid) VALUES(301,'SALE-FIX-0001',101,1,'fixture.admin',"
        "'Fixture Administrator',5.50,5.50,5.50,?,5.50)",
        ("CARD" if with_payments else "CASH",),
    )
    connection.execute(
        "INSERT INTO sale_items(id,sale_id,product_id,quantity,price_at_sale) VALUES(401,301,'201',1,5.50)"
    )
    connection.execute(
        "INSERT INTO sales_returns(id,sale_id,user_id,reason,total_refunded) "
        "VALUES(601,301,101,'Fictional return',1.25)"
    )
    connection.execute(
        "INSERT INTO sales_return_items(id,return_id,sale_item_id,quantity,refund_amount) "
        "VALUES(602,601,401,1,1.25)"
    )
    if with_payments:
        connection.execute(
            "INSERT INTO sale_payments(id,sale_id,payment_method,amount,reference) "
            "VALUES(501,301,'CARD',5.50,'HIST-CARD-001')"
        )
        connection.execute(
            "INSERT INTO hardware_events(id,event_type,device_type,operation,success,user_id,store_id,"
            "details,sale_id) VALUES(801,'PRINT','RECEIPT_PRINTER','receipt',1,101,1,'fictional',301)"
        )


def capture_invariants(path: str | Path, state: str) -> dict:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        if state == "pre_deployment_settings":
            return {"legacy_settings": [tuple(row) for row in connection.execute(
                "SELECT key,value FROM legacy_settings ORDER BY key"
            )]}
        result = {
            "user": tuple(connection.execute(
                "SELECT id,username,role,home_store_id FROM users WHERE id=101"
            ).fetchone()),
            "assignment": tuple(connection.execute(
                "SELECT user_id,store_id FROM user_store_access WHERE user_id=101"
            ).fetchone()),
            "product": tuple(connection.execute(
                "SELECT id,sku,quantity_in_stock,cost_price FROM products WHERE id=201"
            ).fetchone()),
            "inventory": tuple(connection.execute(
                "SELECT store_id,product_id,quantity_on_hand,average_cost FROM store_inventory WHERE product_id=201"
            ).fetchone()),
            "sale": tuple(connection.execute(
                "SELECT sale_id,receipt_number,subtotal,total,total_amount,payment_method FROM sales WHERE sale_id=301"
            ).fetchone()),
            "sale_item": tuple(connection.execute(
                "SELECT id,sale_id,product_id,quantity,price_at_sale FROM sale_items WHERE id=401"
            ).fetchone()),
            "return": tuple(connection.execute(
                "SELECT id,sale_id,user_id,total_refunded FROM sales_returns WHERE id=601"
            ).fetchone()),
            "return_item": tuple(connection.execute(
                "SELECT id,return_id,sale_item_id,quantity,refund_amount FROM sales_return_items WHERE id=602"
            ).fetchone()),
            "movement": tuple(connection.execute(
                "SELECT id,product_id,quantity,previous_quantity,new_quantity,user_id,store_id FROM stock_movements WHERE id=701"
            ).fetchone()),
        }
        if state == "payments_fd5c947":
            result["payment"] = tuple(connection.execute(
                "SELECT id,sale_id,payment_method,amount,reference FROM sale_payments WHERE id=501"
            ).fetchone())
            result["hardware_audit"] = tuple(connection.execute(
                "SELECT id,user_id,store_id,sale_id,success FROM hardware_events WHERE id=801"
            ).fetchone())
        return result
    finally:
        connection.close()
