import os
import sqlite3

from app.core.version import DATABASE_SCHEMA_VERSION


DEFAULT_SYSTEM_USERNAME = "system"
MOVEMENT_TYPES = {"PURCHASE", "SALE", "ADJUSTMENT", "RETURN"}
PAYMENT_METHODS = {"CASH", "CARD", "TRANSFER", "WALLET", "CREDIT", "MIXED"}


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
        migrate_stores_and_assignments(cursor)
        migrate_api_sessions(cursor)
        migrate_administration_tables(cursor)
        migrate_checkout_tables(cursor)
        migrate_hardware_events(cursor)
        migrate_categories_table(cursor)
        migrate_suppliers_table(cursor)
        migrate_products_table(cursor)
        migrate_barcode_and_label_tables(cursor)
        migrate_store_inventory(cursor)
        migrate_stock_transfers(cursor)
        migrate_stock_movements_table(cursor)
        migrate_procurement_tables(cursor)
        migrate_customer_tables(cursor)
        migrate_sales_table(cursor)
        migrate_sale_items_table(cursor)
        migrate_sales_returns_table(cursor)
        migrate_customer_financial_tables(cursor)
        migrate_finance_tables(cursor)
        migrate_pilot_operations_tables(cursor)
        migrate_executive_analytics_tables(cursor)
        migrate_pilot_operations_tables(cursor)
        migrate_inventory_compatibility(cursor)
        cursor.execute(f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION}")
    print("Carthage POS Database Initialized Successfully.")

def migrate_pilot_operations_tables(cursor):
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS user_dashboard_preferences (user_id INTEGER PRIMARY KEY, preferences TEXT NOT NULL DEFAULT '{}', updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS maintenance_history (id INTEGER PRIMARY KEY AUTOINCREMENT, operation TEXT NOT NULL, status TEXT NOT NULL, details TEXT, user_id INTEGER NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS recovery_events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, status TEXT NOT NULL, details TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    """)

def migrate_executive_analytics_tables(cursor):
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS executive_report_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            frequency TEXT NOT NULL CHECK(frequency IN ('DAILY','WEEKLY','MONTHLY','QUARTERLY')),
            store_id INTEGER, format TEXT NOT NULL DEFAULT 'PDF', recipients TEXT,
            is_active INTEGER NOT NULL DEFAULT 1, created_by INTEGER NOT NULL,
            last_run_at DATETIME, next_run_at DATETIME, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(store_id) REFERENCES stores(id), FOREIGN KEY(created_by) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS executive_analytics_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            store_id INTEGER, event_type TEXT NOT NULL, details TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id));
    """)

def migrate_pilot_operations_tables(cursor):
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS user_dashboard_preferences (
            user_id INTEGER PRIMARY KEY, preferences TEXT NOT NULL DEFAULT '{}',
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS maintenance_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, operation TEXT NOT NULL,
            status TEXT NOT NULL, details TEXT, user_id INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS recovery_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
            status TEXT NOT NULL, details TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    """)


def migrate_finance_tables(cursor):
    """Create store-scoped double-entry accounting and cash-operation storage."""
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS finance_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL, account_type TEXT NOT NULL CHECK(account_type IN
            ('ASSET','LIABILITY','EQUITY','INCOME','EXPENSE')), parent_id INTEGER,
            is_system INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(parent_id) REFERENCES finance_accounts(id));
        CREATE TABLE IF NOT EXISTS finance_periods (
            id INTEGER PRIMARY KEY AUTOINCREMENT, store_id INTEGER NOT NULL,
            name TEXT NOT NULL, start_date DATE NOT NULL, end_date DATE NOT NULL,
            is_locked INTEGER NOT NULL DEFAULT 0, locked_by INTEGER, locked_at DATETIME,
            UNIQUE(store_id,start_date,end_date), FOREIGN KEY(store_id) REFERENCES stores(id));
        CREATE TABLE IF NOT EXISTS finance_journals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, store_id INTEGER NOT NULL,
            entry_date DATE NOT NULL, reference TEXT, description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','POSTED','VOID')),
            source_type TEXT, source_id INTEGER, created_by INTEGER NOT NULL,
            posted_by INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, posted_at DATETIME,
            FOREIGN KEY(store_id) REFERENCES stores(id), FOREIGN KEY(created_by) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS finance_journal_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT, journal_id INTEGER NOT NULL,
            account_id INTEGER NOT NULL, description TEXT, debit REAL NOT NULL DEFAULT 0,
            credit REAL NOT NULL DEFAULT 0, tax_rate_id INTEGER,
            FOREIGN KEY(journal_id) REFERENCES finance_journals(id),
            FOREIGN KEY(account_id) REFERENCES finance_accounts(id));
        CREATE TABLE IF NOT EXISTS finance_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
            account_id INTEGER NOT NULL, is_active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(account_id) REFERENCES finance_accounts(id));
        CREATE TABLE IF NOT EXISTS finance_vendors (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
            email TEXT, phone TEXT, is_active INTEGER NOT NULL DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS finance_expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT, store_id INTEGER NOT NULL,
            expense_date DATE NOT NULL, category_id INTEGER NOT NULL, vendor_id INTEGER,
            amount REAL NOT NULL, tax_amount REAL NOT NULL DEFAULT 0, description TEXT NOT NULL,
            expense_type TEXT NOT NULL DEFAULT 'OPERATING', status TEXT NOT NULL DEFAULT 'PENDING',
            attachment_name TEXT, attachment_type TEXT, recurring_rule TEXT,
            created_by INTEGER NOT NULL, approved_by INTEGER, journal_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP, approved_at DATETIME,
            FOREIGN KEY(store_id) REFERENCES stores(id), FOREIGN KEY(category_id) REFERENCES finance_categories(id));
        CREATE TABLE IF NOT EXISTS finance_income (
            id INTEGER PRIMARY KEY AUTOINCREMENT, store_id INTEGER NOT NULL,
            income_date DATE NOT NULL, income_type TEXT NOT NULL, amount REAL NOT NULL,
            tax_amount REAL NOT NULL DEFAULT 0, description TEXT NOT NULL,
            created_by INTEGER NOT NULL, journal_id INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS finance_cash_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, store_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            opening_amount REAL NOT NULL, expected_amount REAL, closing_amount REAL, variance REAL,
            status TEXT NOT NULL DEFAULT 'OPEN', opened_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            closed_at DATETIME);
        CREATE TABLE IF NOT EXISTS finance_cash_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT, store_id INTEGER NOT NULL,
            cash_session_id INTEGER, movement_type TEXT NOT NULL, amount REAL NOT NULL,
            reason TEXT NOT NULL, destination_store_id INTEGER, created_by INTEGER NOT NULL,
            journal_id INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS finance_tax_rates (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, rate REAL NOT NULL,
            pricing_mode TEXT NOT NULL DEFAULT 'EXCLUSIVE', liability_account_id INTEGER,
            is_active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS finance_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, store_id INTEGER, user_id INTEGER NOT NULL,
            event_type TEXT NOT NULL, entity_type TEXT, entity_id INTEGER, details TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS finance_account_mappings (
            mapping_key TEXT PRIMARY KEY, account_id INTEGER NOT NULL,
            updated_by INTEGER, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(account_id) REFERENCES finance_accounts(id));
        CREATE TABLE IF NOT EXISTS finance_posting_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
            source_module TEXT NOT NULL, source_record_id INTEGER NOT NULL,
            store_id INTEGER NOT NULL, transaction_date DATE NOT NULL,
            description TEXT NOT NULL, reference TEXT, status TEXT NOT NULL DEFAULT 'PENDING',
            journal_id INTEGER, idempotency_key TEXT NOT NULL UNIQUE, error_message TEXT,
            attempts INTEGER NOT NULL DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            posted_at DATETIME, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(journal_id) REFERENCES finance_journals(id));
        CREATE TABLE IF NOT EXISTS finance_opening_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT, store_id INTEGER NOT NULL,
            effective_date DATE NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT',
            equity_account_id INTEGER NOT NULL, journal_id INTEGER, created_by INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP, posted_at DATETIME,
            UNIQUE(store_id,effective_date), FOREIGN KEY(journal_id) REFERENCES finance_journals(id));
        CREATE TABLE IF NOT EXISTS finance_opening_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL,
            account_id INTEGER NOT NULL, debit REAL NOT NULL DEFAULT 0, credit REAL NOT NULL DEFAULT 0,
            description TEXT, FOREIGN KEY(batch_id) REFERENCES finance_opening_batches(id));
        CREATE INDEX IF NOT EXISTS idx_finance_journals_store_date ON finance_journals(store_id,entry_date);
        CREATE INDEX IF NOT EXISTS idx_finance_lines_account ON finance_journal_lines(account_id,journal_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_one_open_cash
            ON finance_cash_sessions(store_id,user_id) WHERE status='OPEN';
        CREATE TRIGGER IF NOT EXISTS finance_posted_journal_immutable BEFORE UPDATE ON finance_journals
            WHEN OLD.status='POSTED' BEGIN SELECT RAISE(ABORT,'Posted journals are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS finance_posted_journal_no_delete BEFORE DELETE ON finance_journals
            WHEN OLD.status='POSTED' BEGIN SELECT RAISE(ABORT,'Posted journals are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS finance_posted_lines_immutable_update BEFORE UPDATE ON finance_journal_lines
            WHEN (SELECT status FROM finance_journals WHERE id=OLD.journal_id)='POSTED'
            BEGIN SELECT RAISE(ABORT,'Posted journal lines are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS finance_posted_lines_immutable_delete BEFORE DELETE ON finance_journal_lines
            WHEN (SELECT status FROM finance_journals WHERE id=OLD.journal_id)='POSTED'
            BEGIN SELECT RAISE(ABORT,'Posted journal lines are immutable'); END;
    """)
    cash_columns = get_table_columns(cursor, "finance_cash_sessions")
    for column, definition in {
        "variance_explanation": "TEXT",
        "closed_by": "INTEGER REFERENCES users(id)",
    }.items():
        if column not in cash_columns:
            cursor.execute(f"ALTER TABLE finance_cash_sessions ADD COLUMN {column} {definition}")
    defaults = [
        ('1000','Cash on Hand','ASSET'),('1010','Bank','ASSET'),('1100','Accounts Receivable','ASSET'),
        ('1200','Inventory','ASSET'),('2000','Accounts Payable','LIABILITY'),('2100','Tax Payable','LIABILITY'),
        ('3000','Owner Equity','EQUITY'),('4000','Sales Revenue','INCOME'),('4100','Service Income','INCOME'),
        ('4200','Other Income','INCOME'),('5000','Cost of Goods Sold','EXPENSE'),
        ('6000','Operating Expenses','EXPENSE'),('6100','Petty Cash Expense','EXPENSE')]
    cursor.executemany("INSERT OR IGNORE INTO finance_accounts(code,name,account_type,is_system) VALUES(?,?,?,1)",defaults)
    cursor.execute("INSERT OR IGNORE INTO finance_categories(name,account_id) SELECT 'General Operating',id FROM finance_accounts WHERE code='6000'")
    mappings = [('cash','1000'),('bank','1010'),('card_clearing','1010'),('transfer_clearing','1010'),
        ('accounts_receivable','1100'),('inventory_asset','1200'),('accounts_payable','2000'),
        ('wallet_liability','2000'),('tax_payable','2100'),('opening_equity','3000'),
        ('sales_revenue','4000'),('other_income','4200'),('cost_of_goods_sold','5000'),
        ('operating_expense','6000'),('discounts','6000'),('stock_loss','6000'),
        ('stock_gain','4200'),('cash_variance','6000')]
    cursor.executemany("INSERT OR IGNORE INTO finance_account_mappings(mapping_key,account_id) SELECT ?,id FROM finance_accounts WHERE code=?",mappings)


def migrate_api_sessions(cursor):
    """Create revocable, store-aware API bearer sessions."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS api_sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            store_id INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME NOT NULL,
            last_used_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            revoked_at DATETIME,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (store_id) REFERENCES stores (id)
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_api_sessions_user ON api_sessions (user_id, expires_at)"
    )
    columns = get_table_columns(cursor, "api_sessions")
    if "session_reference" not in columns:
        cursor.execute("ALTER TABLE api_sessions ADD COLUMN session_reference TEXT")
        cursor.execute(
            "UPDATE api_sessions SET session_reference = lower(hex(randomblob(16))) "
            "WHERE session_reference IS NULL"
        )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_api_sessions_reference "
        "ON api_sessions (session_reference)"
    )


def migrate_administration_tables(cursor):
    """Add non-sensitive account security, password history, and user audit storage."""
    columns = get_table_columns(cursor, "users")
    additions = {
        "email": "TEXT COLLATE NOCASE",
        "failed_login_count": "INTEGER NOT NULL DEFAULT 0",
        "is_locked": "INTEGER NOT NULL DEFAULT 0",
        "force_password_change": "INTEGER NOT NULL DEFAULT 0",
        "updated_at": "DATETIME",
    }
    for name, definition in additions.items():
        if name not in columns:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
    cursor.execute("UPDATE users SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)")
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique "
        "ON users (email COLLATE NOCASE) WHERE email IS NOT NULL AND email != ''"
    )
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_password_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            password_hash TEXT NOT NULL,
            changed_by INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (changed_by) REFERENCES users (id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            acting_user_id INTEGER,
            event_type TEXT NOT NULL,
            details TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (acting_user_id) REFERENCES users (id)
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_audit_subject "
        "ON user_audit_events (user_id, created_at)"
    )

def migrate_checkout_tables(cursor):
    """Persist resumable carts and their reservation/audit state."""
    cursor.execute("""CREATE TABLE IF NOT EXISTS checkout_carts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, store_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','SUSPENDED','COMPLETED','VOIDED')),
        customer_id INTEGER, discount_type TEXT, discount_value REAL NOT NULL DEFAULT 0,
        discount_reason TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, completed_sale_id INTEGER,
        FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(store_id) REFERENCES stores(id),
        FOREIGN KEY(customer_id) REFERENCES customers(id), FOREIGN KEY(completed_sale_id) REFERENCES sales(sale_id))""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS checkout_cart_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, cart_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL CHECK(quantity > 0), created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(cart_id,product_id),
        FOREIGN KEY(cart_id) REFERENCES checkout_carts(id), FOREIGN KEY(product_id) REFERENCES products(id))""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS checkout_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, cart_id INTEGER, user_id INTEGER NOT NULL,
        event_type TEXT NOT NULL, details TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(cart_id) REFERENCES checkout_carts(id), FOREIGN KEY(user_id) REFERENCES users(id))""")


def migrate_hardware_events(cursor):
    """Create a non-sensitive operational audit trail for peripheral actions."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hardware_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            device_type TEXT NOT NULL,
            operation TEXT NOT NULL,
            success INTEGER NOT NULL,
            user_id INTEGER,
            store_id INTEGER,
            details TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (store_id) REFERENCES stores (id)
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_hardware_events_created ON hardware_events (created_at, device_type)"
    )
    columns = get_table_columns(cursor, "hardware_events")
    for name, definition in {
        "sale_id": "INTEGER REFERENCES sales(sale_id)",
        "reason": "TEXT",
        "attempt_type": "TEXT",
    }.items():
        if name not in columns:
            cursor.execute(f"ALTER TABLE hardware_events ADD COLUMN {name} {definition}")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_hardware_events_sale ON hardware_events (sale_id, created_at)"
    )


def migrate_users_table(cursor):
    if not table_exists(cursor, "users"):
        create_users_table(cursor)
        return

    columns = get_table_columns(cursor, "users")
    required_columns = {"id", "username", "password_hash", "full_name", "role", "is_active", "created_at", "last_login"}
    table_sql = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'"
    ).fetchone()[0]
    supports_extended_roles = "auditor" in (table_sql or "")
    if required_columns.issubset(columns) and supports_extended_roles:
        return
    cursor.execute("PRAGMA foreign_keys = OFF")
    cursor.execute("PRAGMA legacy_alter_table = ON")
    cursor.execute("ALTER TABLE users RENAME TO users_legacy")
    create_users_table(cursor)

    legacy_columns = get_table_columns(cursor, "users_legacy")
    select_full_name = "full_name" if "full_name" in legacy_columns else "username"
    select_role = "role" if "role" in legacy_columns else "'cashier'"
    select_is_active = "is_active" if "is_active" in legacy_columns else "1"
    select_created_at = "created_at" if "created_at" in legacy_columns else "CURRENT_TIMESTAMP"
    select_last_login = "last_login" if "last_login" in legacy_columns else "NULL"

    select_home_store = "home_store_id" if "home_store_id" in legacy_columns else "NULL"
    cursor.execute(f"""
        INSERT OR IGNORE INTO users (
            username, password_hash, full_name, role, is_active, created_at, last_login, home_store_id
        )
        SELECT username, password_hash, {select_full_name}, {select_role}, {select_is_active},
               {select_created_at}, {select_last_login}, {select_home_store}
        FROM users_legacy
        WHERE username IS NOT NULL AND password_hash IS NOT NULL
    """)
    cursor.execute("DROP TABLE users_legacy")
    cursor.execute("PRAGMA legacy_alter_table = OFF")


def create_users_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK (
                role IN ('admin', 'manager', 'cashier', 'auditor', 'inventory_officer')
            ),
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_login DATETIME,
            home_store_id INTEGER
        );
    """)


def ensure_system_user(cursor):
    cursor.execute("""
        INSERT OR IGNORE INTO users (username, password_hash, full_name, role, is_active)
        VALUES ('system', 'SYSTEM_ACCOUNT_NO_LOGIN', 'System Account', 'admin', 0)
    """)


def migrate_stores_and_assignments(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL COLLATE NOCASE UNIQUE,
            name TEXT NOT NULL,
            address TEXT,
            phone TEXT,
            email TEXT,
            manager_user_id INTEGER,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (manager_user_id) REFERENCES users (id)
        );
    """)
    cursor.execute("""
        INSERT OR IGNORE INTO stores (id, code, name, is_active)
        VALUES (1, 'MAIN', 'Main Store', 1)
    """)
    default_store_id = cursor.execute(
        "SELECT id FROM stores WHERE code = 'MAIN' COLLATE NOCASE"
    ).fetchone()[0]

    user_columns = get_table_columns(cursor, "users")
    if "home_store_id" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN home_store_id INTEGER REFERENCES stores(id)")
    cursor.execute(
        "UPDATE users SET home_store_id = ? WHERE home_store_id IS NULL",
        (default_store_id,),
    )
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_store_access (
            user_id INTEGER NOT NULL,
            store_id INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, store_id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (store_id) REFERENCES stores (id)
        );
    """)
    cursor.execute("""
        INSERT OR IGNORE INTO user_store_access (user_id, store_id)
        SELECT id, home_store_id FROM users WHERE home_store_id IS NOT NULL
    """)


def migrate_categories_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    columns = get_table_columns(cursor, "categories")
    if "is_active" not in columns:
        cursor.execute("ALTER TABLE categories ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    if "updated_at" not in columns:
        cursor.execute("ALTER TABLE categories ADD COLUMN updated_at DATETIME")
        cursor.execute("UPDATE categories SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP)")
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
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    columns = get_table_columns(cursor, "suppliers")
    if "is_active" not in columns:
        cursor.execute("ALTER TABLE suppliers ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    if "updated_at" not in columns:
        cursor.execute("ALTER TABLE suppliers ADD COLUMN updated_at DATETIME")
        cursor.execute("UPDATE suppliers SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP)")
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
    if "unit" not in columns:
        cursor.execute("ALTER TABLE products ADD COLUMN unit TEXT NOT NULL DEFAULT 'each'")
    if "promotion_price" not in columns:
        cursor.execute("ALTER TABLE products ADD COLUMN promotion_price REAL")

    for row in legacy_rows:
        cursor.execute("""
            INSERT OR IGNORE INTO products (
                category_id, supplier_id, sku, barcode, name, cost_price,
                selling_price, quantity_in_stock, reorder_level, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (1, 1, row["product_id"], row["product_id"], row["name"], 0, row["price"], row["stock"], 0))


def migrate_barcode_and_label_tables(cursor):
    """Create normalized identifier, label job, and audit records safely."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS product_identifiers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            identifier_type TEXT NOT NULL
                CHECK (identifier_type IN ('PRIMARY', 'SECONDARY', 'SUPPLIER', 'QR')),
            format TEXT NOT NULL
                CHECK (format IN ('CODE39', 'CODE128', 'EAN8', 'EAN13', 'UPCA', 'QR')),
            value TEXT NOT NULL COLLATE NOCASE UNIQUE,
            is_primary INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products (id),
            FOREIGN KEY (created_by) REFERENCES users (id)
        )
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_product_identifier_primary
        ON product_identifiers (product_id) WHERE is_primary = 1 AND is_active = 1
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_product_identifier_product "
        "ON product_identifiers (product_id, is_active)"
    )
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS barcode_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            identifier_id INTEGER,
            action TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            format TEXT,
            user_id INTEGER,
            store_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products (id),
            FOREIGN KEY (identifier_id) REFERENCES product_identifiers (id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (store_id) REFERENCES stores (id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS label_print_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_reference TEXT NOT NULL COLLATE NOCASE UNIQUE,
            store_id INTEGER NOT NULL,
            template_code TEXT NOT NULL,
            printer_profile TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('PENDING', 'PRINTED', 'FAILED')),
            is_reprint INTEGER NOT NULL DEFAULT 0,
            original_job_id INTEGER,
            requested_by INTEGER NOT NULL,
            requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME,
            error_message TEXT,
            FOREIGN KEY (store_id) REFERENCES stores (id),
            FOREIGN KEY (original_job_id) REFERENCES label_print_jobs (id),
            FOREIGN KEY (requested_by) REFERENCES users (id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS label_print_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            identifier_id INTEGER,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            FOREIGN KEY (job_id) REFERENCES label_print_jobs (id),
            FOREIGN KEY (product_id) REFERENCES products (id),
            FOREIGN KEY (identifier_id) REFERENCES product_identifiers (id)
        )
    """)
    cursor.execute("""
        INSERT OR IGNORE INTO product_identifiers (
            product_id, identifier_type, format, value, is_primary, is_active
        )
        SELECT id, 'PRIMARY', 'CODE128', barcode, 1, 1
        FROM products WHERE barcode IS NOT NULL AND TRIM(barcode) != ''
    """)


def migrate_store_inventory(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_inventory (
            store_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity_on_hand INTEGER NOT NULL DEFAULT 0 CHECK (quantity_on_hand >= 0),
            reorder_level INTEGER NOT NULL DEFAULT 0 CHECK (reorder_level >= 0),
            average_cost REAL NOT NULL DEFAULT 0 CHECK (average_cost >= 0),
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (store_id, product_id),
            FOREIGN KEY (store_id) REFERENCES stores (id),
            FOREIGN KEY (product_id) REFERENCES products (id)
        );
    """)
    default_store_id = cursor.execute(
        "SELECT id FROM stores WHERE code = 'MAIN' COLLATE NOCASE"
    ).fetchone()[0]
    cursor.execute("""
        INSERT OR IGNORE INTO store_inventory (
            store_id, product_id, quantity_on_hand, reorder_level, average_cost
        )
        SELECT ?, id, quantity_in_stock, reorder_level, COALESCE(cost_price, 0)
        FROM products
    """, (default_store_id,))


def migrate_stock_transfers(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference_number TEXT NOT NULL COLLATE NOCASE UNIQUE,
            source_store_id INTEGER NOT NULL,
            destination_store_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'REQUESTED'
                CHECK (status IN ('REQUESTED', 'APPROVED', 'IN_TRANSIT', 'RECEIVED', 'CANCELLED')),
            requested_by INTEGER NOT NULL,
            approved_by INTEGER,
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            approved_at DATETIME,
            cancelled_at DATETIME,
            FOREIGN KEY (source_store_id) REFERENCES stores (id),
            FOREIGN KEY (destination_store_id) REFERENCES stores (id),
            FOREIGN KEY (requested_by) REFERENCES users (id),
            FOREIGN KEY (approved_by) REFERENCES users (id),
            CHECK (source_store_id != destination_store_id)
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_transfer_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transfer_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            requested_quantity INTEGER NOT NULL CHECK (requested_quantity > 0),
            dispatched_quantity INTEGER NOT NULL DEFAULT 0,
            received_quantity INTEGER NOT NULL DEFAULT 0,
            dispatched_value REAL NOT NULL DEFAULT 0,
            received_value REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (transfer_id) REFERENCES stock_transfers (id),
            FOREIGN KEY (product_id) REFERENCES products (id),
            UNIQUE (transfer_id, product_id),
            CHECK (received_quantity <= dispatched_quantity),
            CHECK (dispatched_quantity <= requested_quantity)
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_transfer_dispatches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transfer_id INTEGER NOT NULL,
            dispatched_by INTEGER NOT NULL,
            notes TEXT,
            dispatched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (transfer_id) REFERENCES stock_transfers (id),
            FOREIGN KEY (dispatched_by) REFERENCES users (id)
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_transfer_dispatch_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dispatch_id INTEGER NOT NULL,
            transfer_item_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            FOREIGN KEY (dispatch_id) REFERENCES stock_transfer_dispatches (id),
            FOREIGN KEY (transfer_item_id) REFERENCES stock_transfer_items (id),
            UNIQUE (dispatch_id, transfer_item_id)
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_transfer_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transfer_id INTEGER NOT NULL,
            received_by INTEGER NOT NULL,
            notes TEXT,
            received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (transfer_id) REFERENCES stock_transfers (id),
            FOREIGN KEY (received_by) REFERENCES users (id)
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_transfer_receipt_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id INTEGER NOT NULL,
            transfer_item_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            FOREIGN KEY (receipt_id) REFERENCES stock_transfer_receipts (id),
            FOREIGN KEY (transfer_item_id) REFERENCES stock_transfer_items (id),
            UNIQUE (receipt_id, transfer_item_id)
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_transfer_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transfer_id INTEGER NOT NULL,
            from_status TEXT,
            to_status TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (transfer_id) REFERENCES stock_transfers (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
    """)


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
            store_id INTEGER,
            transfer_id INTEGER,
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products (id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (store_id) REFERENCES stores (id),
            FOREIGN KEY (transfer_id) REFERENCES stock_transfers (id)
        );
    """)
    columns = get_table_columns(cursor, "stock_movements")
    if "store_id" not in columns:
        cursor.execute("ALTER TABLE stock_movements ADD COLUMN store_id INTEGER REFERENCES stores(id)")
    if "transfer_id" not in columns:
        cursor.execute("ALTER TABLE stock_movements ADD COLUMN transfer_id INTEGER REFERENCES stock_transfers(id)")
    default_store_id = cursor.execute(
        "SELECT id FROM stores WHERE code = 'MAIN' COLLATE NOCASE"
    ).fetchone()[0]
    cursor.execute(
        "UPDATE stock_movements SET store_id = ? WHERE store_id IS NULL",
        (default_store_id,),
    )


def migrate_customer_tables(cursor):
    """Create the global customer directory and customer-group catalog."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customer_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            default_discount REAL NOT NULL DEFAULT 0
                CHECK (default_discount >= 0 AND default_discount <= 100),
            pricing_priority INTEGER NOT NULL DEFAULT 0,
            description TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.executemany(
        """INSERT OR IGNORE INTO customer_groups (
               name, default_discount, pricing_priority, description
           ) VALUES (?, ?, ?, ?)""",
        [
            ("Retail", 0, 0, "Standard retail customers"),
            ("Wholesale", 0, 20, "Volume and wholesale customers"),
            ("VIP", 0, 30, "Priority loyalty customers"),
            ("Corporate", 0, 20, "Business and corporate accounts"),
            ("Staff", 0, 10, "Internal staff customers"),
        ],
    )
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_code TEXT NOT NULL COLLATE NOCASE UNIQUE,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            business_name TEXT,
            phone_number TEXT,
            email TEXT COLLATE NOCASE,
            address TEXT,
            city TEXT,
            state TEXT,
            country TEXT,
            date_of_birth DATE,
            gender TEXT,
            tax_number TEXT,
            notes TEXT,
            group_id INTEGER,
            credit_limit REAL NOT NULL DEFAULT 0 CHECK (credit_limit >= 0),
            credit_due_date DATE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_by INTEGER NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (group_id) REFERENCES customer_groups (id),
            FOREIGN KEY (created_by) REFERENCES users (id)
        )
    """)
    cursor.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_phone_unique
           ON customers (phone_number) WHERE phone_number IS NOT NULL AND phone_number != ''"""
    )
    cursor.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_email_unique
           ON customers (email COLLATE NOCASE) WHERE email IS NOT NULL AND email != ''"""
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_customers_group ON customers (group_id)")


def migrate_sales_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            sale_id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_number TEXT UNIQUE,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER,
            store_id INTEGER,
            register_name TEXT NOT NULL DEFAULT 'REGISTER-1',
            username TEXT NOT NULL DEFAULT 'system',
            cashier_name TEXT NOT NULL DEFAULT 'system',
            subtotal REAL NOT NULL DEFAULT 0,
            discount_amount REAL NOT NULL DEFAULT 0,
            tax REAL NOT NULL DEFAULT 0,
            tax_amount REAL NOT NULL DEFAULT 0,
            total REAL NOT NULL DEFAULT 0,
            total_amount REAL NOT NULL DEFAULT 0,
            payment_method TEXT NOT NULL DEFAULT 'CASH' CHECK (payment_method IN ('CASH', 'CARD', 'TRANSFER', 'WALLET', 'CREDIT', 'MIXED')),
            payment_status TEXT NOT NULL DEFAULT 'PAID',
            amount_paid REAL NOT NULL DEFAULT 0,
            change_given REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (store_id) REFERENCES stores (id),
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
        "store_id": "INTEGER REFERENCES stores(id)",
        "register_name": "TEXT NOT NULL DEFAULT 'REGISTER-1'",
        "discount_amount": "REAL NOT NULL DEFAULT 0",
        "tax_amount": "REAL NOT NULL DEFAULT 0",
        "total_amount": "REAL NOT NULL DEFAULT 0",
        "payment_method": "TEXT NOT NULL DEFAULT 'CASH'",
        "payment_status": "TEXT NOT NULL DEFAULT 'PAID'",
        "amount_paid": "REAL NOT NULL DEFAULT 0",
        "change_given": "REAL NOT NULL DEFAULT 0",
        "customer_id": "INTEGER REFERENCES customers(id)",
        "customer_group_id": "INTEGER REFERENCES customer_groups(id)",
        "loyalty_points_earned": "INTEGER NOT NULL DEFAULT 0",
        "loyalty_points_redeemed": "INTEGER NOT NULL DEFAULT 0",
        "loyalty_redemption_amount": "REAL NOT NULL DEFAULT 0",
        "wallet_amount": "REAL NOT NULL DEFAULT 0",
        "credit_amount": "REAL NOT NULL DEFAULT 0",
        "tender_type": "TEXT NOT NULL DEFAULT 'CASH'",
        "source_cart_id": "INTEGER REFERENCES checkout_carts(id)",
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
    default_store_id = cursor.execute(
        "SELECT id FROM stores WHERE code = 'MAIN' COLLATE NOCASE"
    ).fetchone()[0]
    cursor.execute(
        "UPDATE sales SET store_id = ? WHERE store_id IS NULL",
        (default_store_id,),
    )

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
    cursor.execute("UPDATE sales SET tender_type = payment_method WHERE tender_type = 'CASH' AND payment_method != 'CASH'")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_customer ON sales (customer_id)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_source_cart ON sales (source_cart_id) WHERE source_cart_id IS NOT NULL")


def migrate_sale_items_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL,
            product_id TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price_at_sale REAL NOT NULL,
            unit_cost_at_sale REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (sale_id) REFERENCES sales (sale_id)
        );
    """)
    columns = get_table_columns(cursor, "sale_items")
    if "unit_cost_at_sale" not in columns:
        cursor.execute("ALTER TABLE sale_items ADD COLUMN unit_cost_at_sale REAL NOT NULL DEFAULT 0")
        cursor.execute("""
            UPDATE sale_items
            SET unit_cost_at_sale = COALESCE(
                (SELECT cost_price FROM products WHERE products.id = CAST(sale_items.product_id AS INTEGER)),
                0
            )
        """)


def migrate_procurement_tables(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS purchase_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER NOT NULL,
            store_id INTEGER NOT NULL,
            reference_number TEXT NOT NULL COLLATE NOCASE UNIQUE,
            status TEXT NOT NULL DEFAULT 'DRAFT'
                CHECK (status IN ('DRAFT', 'SUBMITTED', 'PARTIALLY_RECEIVED', 'FULLY_RECEIVED', 'CANCELLED')),
            expected_delivery_date DATE,
            created_by INTEGER NOT NULL,
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            submitted_at DATETIME,
            cancelled_at DATETIME,
            FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
            FOREIGN KEY (store_id) REFERENCES stores (id),
            FOREIGN KEY (created_by) REFERENCES users (id)
        );
    """)
    purchase_order_columns = get_table_columns(cursor, "purchase_orders")
    if "store_id" not in purchase_order_columns:
        cursor.execute("ALTER TABLE purchase_orders ADD COLUMN store_id INTEGER REFERENCES stores(id)")
    default_store_id = cursor.execute(
        "SELECT id FROM stores WHERE code = 'MAIN' COLLATE NOCASE"
    ).fetchone()[0]
    cursor.execute(
        "UPDATE purchase_orders SET store_id = ? WHERE store_id IS NULL",
        (default_store_id,),
    )
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS purchase_order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            ordered_quantity INTEGER NOT NULL CHECK (ordered_quantity > 0),
            received_quantity INTEGER NOT NULL DEFAULT 0
                CHECK (received_quantity >= 0 AND received_quantity <= ordered_quantity),
            unit_cost REAL NOT NULL CHECK (unit_cost >= 0),
            subtotal REAL NOT NULL CHECK (subtotal >= 0),
            FOREIGN KEY (purchase_order_id) REFERENCES purchase_orders (id),
            FOREIGN KEY (product_id) REFERENCES products (id),
            UNIQUE (purchase_order_id, product_id)
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS purchase_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_order_id INTEGER NOT NULL,
            receipt_number TEXT NOT NULL COLLATE NOCASE UNIQUE,
            received_by INTEGER NOT NULL,
            notes TEXT,
            received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (purchase_order_id) REFERENCES purchase_orders (id),
            FOREIGN KEY (received_by) REFERENCES users (id)
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS purchase_receipt_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id INTEGER NOT NULL,
            purchase_order_item_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            unit_cost REAL NOT NULL CHECK (unit_cost >= 0),
            subtotal REAL NOT NULL CHECK (subtotal >= 0),
            previous_quantity INTEGER NOT NULL,
            new_quantity INTEGER NOT NULL,
            previous_cost REAL NOT NULL,
            new_cost REAL NOT NULL,
            FOREIGN KEY (receipt_id) REFERENCES purchase_receipts (id),
            FOREIGN KEY (purchase_order_item_id) REFERENCES purchase_order_items (id),
            UNIQUE (receipt_id, purchase_order_item_id)
        );
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_purchase_orders_supplier ON purchase_orders (supplier_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_purchase_order_items_product ON purchase_order_items (product_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_purchase_receipts_order ON purchase_receipts (purchase_order_id)"
    )


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
    columns = get_table_columns(cursor, "sales_returns")
    additions = {
        "store_id": "INTEGER REFERENCES stores(id)",
        "refund_method": "TEXT NOT NULL DEFAULT 'ORIGINAL_TENDER'",
        "payment_id": "INTEGER REFERENCES sale_payments(id)",
        "idempotency_key": "TEXT",
    }
    for column, definition in additions.items():
        if column not in columns:
            cursor.execute(f"ALTER TABLE sales_returns ADD COLUMN {column} {definition}")
    cursor.execute("UPDATE sales_returns SET store_id=(SELECT store_id FROM sales WHERE sales.sale_id=sales_returns.sale_id) WHERE store_id IS NULL")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_returns_idempotency ON sales_returns(idempotency_key) WHERE idempotency_key IS NOT NULL")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_returns_store_created ON sales_returns(store_id,created_at)")
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


def migrate_customer_financial_tables(cursor):
    """Create immutable loyalty, wallet, credit, and tender audit ledgers."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sale_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL,
            payment_method TEXT NOT NULL
                CHECK (payment_method IN ('CASH', 'CARD', 'TRANSFER', 'WALLET', 'CREDIT')),
            amount REAL NOT NULL CHECK (amount >= 0),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sale_id) REFERENCES sales (sale_id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sale_payments_sale ON sale_payments (sale_id)")
    payment_columns = get_table_columns(cursor, "sale_payments")
    if "reference" not in payment_columns:
        cursor.execute("ALTER TABLE sale_payments ADD COLUMN reference TEXT")
    cursor.execute("""INSERT INTO sale_payments(sale_id,payment_method,amount)
        SELECT s.sale_id,s.payment_method,s.total_amount FROM sales s
        WHERE s.payment_method!='MIXED' AND NOT EXISTS
          (SELECT 1 FROM sale_payments sp WHERE sp.sale_id=s.sale_id)""")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sale_payments_method_created ON sale_payments(payment_method,created_at)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS loyalty_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            transaction_type TEXT NOT NULL
                CHECK (transaction_type IN ('EARN', 'REDEEM', 'ADJUSTMENT', 'EXPIRATION', 'REFUND')),
            points_delta INTEGER NOT NULL,
            balance_after INTEGER NOT NULL CHECK (balance_after >= 0),
            sale_id INTEGER,
            sales_return_id INTEGER,
            store_id INTEGER,
            user_id INTEGER NOT NULL,
            notes TEXT,
            expires_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers (id),
            FOREIGN KEY (sale_id) REFERENCES sales (sale_id),
            FOREIGN KEY (sales_return_id) REFERENCES sales_returns (id),
            FOREIGN KEY (store_id) REFERENCES stores (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wallet_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            transaction_type TEXT NOT NULL
                CHECK (transaction_type IN ('DEPOSIT', 'WITHDRAWAL', 'SALE', 'REFUND', 'ADJUSTMENT')),
            amount_delta REAL NOT NULL,
            balance_after REAL NOT NULL CHECK (balance_after >= 0),
            sale_id INTEGER,
            sales_return_id INTEGER,
            store_id INTEGER,
            user_id INTEGER NOT NULL,
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers (id),
            FOREIGN KEY (sale_id) REFERENCES sales (sale_id),
            FOREIGN KEY (sales_return_id) REFERENCES sales_returns (id),
            FOREIGN KEY (store_id) REFERENCES stores (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS credit_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            transaction_type TEXT NOT NULL
                CHECK (transaction_type IN ('CHARGE', 'PAYMENT', 'REFUND', 'ADJUSTMENT')),
            amount_delta REAL NOT NULL,
            balance_after REAL NOT NULL CHECK (balance_after >= 0),
            sale_id INTEGER,
            sales_return_id INTEGER,
            store_id INTEGER,
            user_id INTEGER NOT NULL,
            due_date DATE,
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers (id),
            FOREIGN KEY (sale_id) REFERENCES sales (sale_id),
            FOREIGN KEY (sales_return_id) REFERENCES sales_returns (id),
            FOREIGN KEY (store_id) REFERENCES stores (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    for table in ("loyalty_transactions", "wallet_transactions", "credit_transactions"):
        cursor.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_customer ON {table} (customer_id, created_at)"
        )
        cursor.execute(f"""
            CREATE TRIGGER IF NOT EXISTS trg_{table}_immutable_update
            BEFORE UPDATE ON {table}
            BEGIN
                SELECT RAISE(ABORT, 'Financial ledger entries are immutable');
            END
        """)
        cursor.execute(f"""
            CREATE TRIGGER IF NOT EXISTS trg_{table}_immutable_delete
            BEFORE DELETE ON {table}
            BEGIN
                SELECT RAISE(ABORT, 'Financial ledger entries are immutable');
            END
        """)

    cursor.execute("""
        INSERT INTO sale_payments (sale_id, payment_method, amount)
        SELECT s.sale_id,
               CASE WHEN s.payment_method IN ('CASH', 'CARD', 'TRANSFER')
                    THEN s.payment_method ELSE 'CASH' END,
               s.total_amount
        FROM sales s
        WHERE NOT EXISTS (
            SELECT 1 FROM sale_payments sp WHERE sp.sale_id = s.sale_id
        )
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
            default_store_id = cursor.execute(
                "SELECT id FROM stores WHERE code = 'MAIN' COLLATE NOCASE"
            ).fetchone()[0]
            cursor.execute("""
                INSERT OR IGNORE INTO store_inventory (
                    store_id, product_id, quantity_on_hand, reorder_level, average_cost
                )
                SELECT ?, id, quantity_in_stock, reorder_level, COALESCE(cost_price, 0)
                FROM products
            """, (default_store_id,))
            print("Baseline stock seeded into database.")
