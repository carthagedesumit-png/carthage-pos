import os
import sqlite3


DEFAULT_SYSTEM_USERNAME = "system"
MOVEMENT_TYPES = {"PURCHASE", "SALE", "ADJUSTMENT", "RETURN"}
PAYMENT_METHODS = {"CASH", "CARD", "TRANSFER", "MIXED"}


def get_database_path():
    """Returns the active database path, allowing tests/deployments to override it."""
    return os.environ.get(
        "CARTHAGE_POS_DB",
        os.path.join(os.path.dirname(__file__), "supermarket.db")
    )


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()
        return False


def get_connection():
    """Establishes and returns a foreign-key-safe SQLite connection."""
    conn = sqlite3.connect(get_database_path(), factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_exists(cursor, table_name):
    row = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,)
    ).fetchone()
    return row is not None


def view_exists(cursor, view_name):
    row = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'view' AND name = ?",
        (view_name,)
    ).fetchone()
    return row is not None


def get_table_columns(cursor, table_name):
    return {row["name"] for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()}


def initialize_database():
    """Creates application tables and applies safe SQLite migrations."""
    with get_connection() as conn:
        cursor = conn.cursor()
        migrate_users_table(cursor)
        ensure_system_user(cursor)
        migrate_categories_table(cursor)
        migrate_suppliers_table(cursor)
        migrate_products_table(cursor)
        migrate_stock_movements_table(cursor)
        migrate_sales_table(cursor)
        migrate_sale_items_table(cursor)
        migrate_sales_returns_table(cursor)
        migrate_inventory_compatibility(cursor)
    print("Carthage POS Database Initialized Successfully.")


def migrate_users_table(cursor):
    if not table_exists(cursor, "users"):
        create_users_table(cursor)
        return

    columns = get_table_columns(cursor, "users")
    required_columns = {"id", "username", "password_hash", "full_name", "role", "is_active", "created_at", "last_login"}
    if required_columns.issubset(columns):
        return

    cursor.execute("ALTER TABLE users RENAME TO users_legacy")
    create_users_table(cursor)

    legacy_columns = get_table_columns(cursor, "users_legacy")
    select_full_name = "full_name" if "full_name" in legacy_columns else "username"
    select_role = "role" if "role" in legacy_columns else "'cashier'"
    select_is_active = "is_active" if "is_active" in legacy_columns else "1"
    select_created_at = "created_at" if "created_at" in legacy_columns else "CURRENT_TIMESTAMP"
    select_last_login = "last_login" if "last_login" in legacy_columns else "NULL"

    cursor.execute(f"""
        INSERT OR IGNORE INTO users (username, password_hash, full_name, role, is_active, created_at, last_login)
        SELECT username, password_hash, {select_full_name}, {select_role}, {select_is_active},
               {select_created_at}, {select_last_login}
        FROM users_legacy
        WHERE username IS NOT NULL AND password_hash IS NOT NULL
    """)
    cursor.execute("DROP TABLE users_legacy")


def create_users_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('admin', 'manager', 'cashier')),
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_login DATETIME
        );
    """)


def ensure_system_user(cursor):
    cursor.execute("""
        INSERT OR IGNORE INTO users (username, password_hash, full_name, role, is_active)
        VALUES ('system', 'SYSTEM_ACCOUNT_NO_LOGIN', 'System Account', 'admin', 0)
    """)


def migrate_categories_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cursor.execute("""
        INSERT OR IGNORE INTO categories (id, name, description)
        VALUES (1, 'General', 'Default migrated category')
    """)


def migrate_suppliers_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            phone TEXT,
            email TEXT,
            address TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cursor.execute("""
        INSERT OR IGNORE INTO suppliers (id, name, phone, email, address)
        VALUES (1, 'Default Supplier', NULL, NULL, NULL)
    """)


def migrate_products_table(cursor):
    legacy_rows = []
    if table_exists(cursor, "inventory"):
        inventory_type = cursor.execute(
            "SELECT type FROM sqlite_master WHERE name = 'inventory'"
        ).fetchone()["type"]
        if inventory_type == "table":
            legacy_rows = [dict(row) for row in cursor.execute(
                "SELECT product_id, name, price, stock FROM inventory"
            ).fetchall()]
            cursor.execute("ALTER TABLE inventory RENAME TO inventory_legacy")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER,
            supplier_id INTEGER,
            sku TEXT NOT NULL UNIQUE,
            barcode TEXT UNIQUE,
            name TEXT NOT NULL,
            description TEXT,
            cost_price REAL NOT NULL DEFAULT 0,
            selling_price REAL NOT NULL,
            quantity_in_stock INTEGER NOT NULL DEFAULT 0,
            reorder_level INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES categories (id),
            FOREIGN KEY (supplier_id) REFERENCES suppliers (id)
        );
    """)

    columns = get_table_columns(cursor, "products")
    if "description" not in columns:
        cursor.execute("ALTER TABLE products ADD COLUMN description TEXT")

    for row in legacy_rows:
        cursor.execute("""
            INSERT OR IGNORE INTO products (
                category_id, supplier_id, sku, barcode, name, cost_price,
                selling_price, quantity_in_stock, reorder_level, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (1, 1, row["product_id"], row["product_id"], row["name"], 0, row["price"], row["stock"], 0))


def migrate_stock_movements_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            movement_type TEXT NOT NULL CHECK (movement_type IN ('PURCHASE', 'SALE', 'ADJUSTMENT', 'RETURN')),
            quantity INTEGER NOT NULL,
            previous_quantity INTEGER NOT NULL,
            new_quantity INTEGER NOT NULL,
            user_id INTEGER,
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
    """)


def migrate_sales_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            sale_id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_number TEXT UNIQUE,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER,
            username TEXT NOT NULL DEFAULT 'system',
            cashier_name TEXT NOT NULL DEFAULT 'system',
            subtotal REAL NOT NULL DEFAULT 0,
            discount_amount REAL NOT NULL DEFAULT 0,
            tax REAL NOT NULL DEFAULT 0,
            tax_amount REAL NOT NULL DEFAULT 0,
            total REAL NOT NULL DEFAULT 0,
            total_amount REAL NOT NULL DEFAULT 0,
            payment_method TEXT NOT NULL DEFAULT 'CASH' CHECK (payment_method IN ('CASH', 'CARD', 'TRANSFER', 'MIXED')),
            payment_status TEXT NOT NULL DEFAULT 'PAID',
            amount_paid REAL NOT NULL DEFAULT 0,
            change_given REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (username) REFERENCES users (username)
        );
    """)

    columns = get_table_columns(cursor, "sales")
    column_defaults = {
        "receipt_number": "TEXT",
        "created_at": "DATETIME",
        "cashier_name": "TEXT NOT NULL DEFAULT 'system'",
        "username": "TEXT NOT NULL DEFAULT 'system'",
        "user_id": "INTEGER",
        "discount_amount": "REAL NOT NULL DEFAULT 0",
        "tax_amount": "REAL NOT NULL DEFAULT 0",
        "total_amount": "REAL NOT NULL DEFAULT 0",
        "payment_method": "TEXT NOT NULL DEFAULT 'CASH'",
        "payment_status": "TEXT NOT NULL DEFAULT 'PAID'",
        "amount_paid": "REAL NOT NULL DEFAULT 0",
        "change_given": "REAL NOT NULL DEFAULT 0",
    }
    for column, definition in column_defaults.items():
        if column not in columns:
            cursor.execute(f"ALTER TABLE sales ADD COLUMN {column} {definition}")

    cursor.execute("UPDATE sales SET username = cashier_name WHERE username = 'system' AND cashier_name IS NOT NULL")
    cursor.execute("UPDATE sales SET tax_amount = tax WHERE tax_amount = 0 AND tax != 0")
    cursor.execute("UPDATE sales SET total_amount = total WHERE total_amount = 0 AND total != 0")
    cursor.execute("UPDATE sales SET amount_paid = total_amount WHERE amount_paid = 0 AND total_amount != 0")
    cursor.execute("UPDATE sales SET created_at = timestamp WHERE created_at IS NULL")
    cursor.execute("""
        UPDATE sales
        SET user_id = (SELECT id FROM users WHERE users.username = sales.username)
        WHERE user_id IS NULL
    """)

    rows = cursor.execute(
        "SELECT sale_id, COALESCE(created_at, timestamp, CURRENT_TIMESTAMP) AS sale_date FROM sales WHERE receipt_number IS NULL OR receipt_number = '' ORDER BY sale_id"
    ).fetchall()
    counters = {}
    for row in rows:
        date_key = str(row["sale_date"])[0:10].replace("-", "")
        counters[date_key] = counters.get(date_key, 0) + 1
        cursor.execute(
            "UPDATE sales SET receipt_number = ? WHERE sale_id = ?",
            (f"POS-{date_key}-{counters[date_key]:04d}", row["sale_id"])
        )

    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_receipt_number ON sales (receipt_number)")


def migrate_sale_items_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL,
            product_id TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price_at_sale REAL NOT NULL,
            FOREIGN KEY (sale_id) REFERENCES sales (sale_id)
        );
    """)


def migrate_sales_returns_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales_returns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            total_refunded REAL NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sale_id) REFERENCES sales (sale_id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales_return_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            return_id INTEGER NOT NULL,
            sale_item_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            refund_amount REAL NOT NULL,
            FOREIGN KEY (return_id) REFERENCES sales_returns (id),
            FOREIGN KEY (sale_item_id) REFERENCES sale_items (id)
        );
    """)


def migrate_inventory_compatibility(cursor):
    if view_exists(cursor, "inventory"):
        cursor.execute("DROP VIEW inventory")
    cursor.execute("""
        CREATE VIEW inventory AS
        SELECT
            sku AS product_id,
            name,
            selling_price AS price,
            quantity_in_stock AS stock
        FROM products
        WHERE is_active = 1;
    """)


def seed_initial_data():
    """Seeds default supermarket inventory items if the product catalog is empty."""
    sample_items = [
        ("1001", "1001", "Server Rack Organizer", 45.00, 15),
        ("1002", "1002", "CCTV Smart Camera", 85.50, 24),
        ("1003", "1003", "Cat6 Ethernet Cable 10m", 12.00, 50),
        ("1004", "1004", "Smart Switch Node", 28.00, 8)
    ]

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM products")
        if cursor.fetchone()[0] == 0:
            cursor.executemany(
                """INSERT INTO products (
                    category_id, supplier_id, sku, barcode, name, cost_price,
                    selling_price, quantity_in_stock, reorder_level, is_active
                ) VALUES (1, 1, ?, ?, ?, 0, ?, ?, 0, 1)""",
                sample_items
            )
            print("Baseline stock seeded into database.")