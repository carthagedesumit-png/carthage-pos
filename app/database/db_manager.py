import os
import sqlite3


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


def initialize_database():
    """Creates application tables and applies lightweight SQLite migrations."""
    queries = [
        """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'cashier',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS inventory (
            product_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            stock INTEGER NOT NULL DEFAULT 0
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS sales (
            sale_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            cashier_name TEXT NOT NULL DEFAULT 'System Admin',
            subtotal REAL NOT NULL,
            tax REAL NOT NULL,
            total REAL NOT NULL,
            FOREIGN KEY (cashier_name) REFERENCES users (username)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL,
            product_id TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price_at_sale REAL NOT NULL,
            FOREIGN KEY (sale_id) REFERENCES sales (sale_id),
            FOREIGN KEY (product_id) REFERENCES inventory (product_id)
        );
        """
    ]

    with get_connection() as conn:
        cursor = conn.cursor()
        for query in queries:
            cursor.execute(query)

        cursor.execute("PRAGMA table_info(sales)")
        sales_columns = {row["name"] for row in cursor.fetchall()}
        if "cashier_name" not in sales_columns:
            cursor.execute(
                "ALTER TABLE sales ADD COLUMN cashier_name TEXT NOT NULL DEFAULT 'System Admin'"
            )
    print("Carthage POS Database Initialized Successfully.")


def seed_initial_data():
    """Seeds default supermarket inventory items if the table is clean and empty."""
    sample_items = [
        ("1001", "Server Rack Organizer", 45.00, 15),
        ("1002", "CCTV Smart Camera", 85.50, 24),
        ("1003", "Cat6 Ethernet Cable 10m", 12.00, 50),
        ("1004", "Smart Switch Node", 28.00, 8)
    ]

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM inventory")
        if cursor.fetchone()[0] == 0:
            cursor.executemany(
                "INSERT INTO inventory (product_id, name, price, stock) VALUES (?, ?, ?, ?)",
                sample_items
            )
            print("Baseline stock seeded into database.")