from sqlite3 import IntegrityError

from auth import require_inventory_management
from app.database.db_manager import get_connection

MOVEMENT_PURCHASE = "PURCHASE"
MOVEMENT_SALE = "SALE"
MOVEMENT_ADJUSTMENT = "ADJUSTMENT"
MOVEMENT_RETURN = "RETURN"
VALID_MOVEMENT_TYPES = {MOVEMENT_PURCHASE, MOVEMENT_SALE, MOVEMENT_ADJUSTMENT, MOVEMENT_RETURN}


def create_product(
    session,
    sku,
    name,
    selling_price,
    category_id=None,
    supplier_id=None,
    barcode=None,
    cost_price=0,
    quantity_in_stock=0,
    reorder_level=0,
    description=None,
):
    require_inventory_management(session)
    sku = normalize_required(sku, "SKU")
    name = normalize_required(name, "Product name")
    validate_non_negative(selling_price, "Selling price")
    validate_non_negative(cost_price, "Cost price")
    validate_stock_value(quantity_in_stock, "Quantity in stock")
    validate_stock_value(reorder_level, "Reorder level")

    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO products (
                    category_id, supplier_id, sku, barcode, name, description,
                    cost_price, selling_price, quantity_in_stock, reorder_level, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    category_id,
                    supplier_id,
                    sku,
                    barcode or sku,
                    name,
                    description,
                    float(cost_price),
                    float(selling_price),
                    int(quantity_in_stock),
                    int(reorder_level),
                )
            )
            product_id = cursor.lastrowid
            if quantity_in_stock:
                log_stock_movement(
                    conn,
                    product_id,
                    MOVEMENT_PURCHASE,
                    int(quantity_in_stock),
                    0,
                    int(quantity_in_stock),
                    session.user_id,
                    "Initial stock"
                )
    except IntegrityError as exc:
        raise ValueError("SKU or barcode already exists.") from exc

    return get_product_by_id(product_id)


def update_product(session, product_id, **updates):
    require_inventory_management(session)
    allowed = {
        "category_id", "supplier_id", "sku", "barcode", "name", "description",
        "cost_price", "selling_price", "reorder_level", "is_active"
    }
    changes = {key: value for key, value in updates.items() if key in allowed}
    if not changes:
        return get_product_by_id(product_id)

    for field in ("cost_price", "selling_price"):
        if field in changes:
            validate_non_negative(changes[field], field.replace("_", " ").title())
    if "reorder_level" in changes:
        validate_stock_value(changes["reorder_level"], "Reorder level")
    if "sku" in changes:
        changes["sku"] = normalize_required(changes["sku"], "SKU")
    if "name" in changes:
        changes["name"] = normalize_required(changes["name"], "Product name")

    assignments = ", ".join([f"{field} = ?" for field in changes])
    values = list(changes.values()) + [product_id]

    try:
        with get_connection() as conn:
            cursor = conn.execute(
                f"UPDATE products SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                values
            )
            if cursor.rowcount == 0:
                raise ValueError("Product not found.")
    except IntegrityError as exc:
        raise ValueError("SKU or barcode already exists.") from exc

    return get_product_by_id(product_id)


def deactivate_product(session, product_id):
    return update_product(session, product_id, is_active=0)


def adjust_stock(session, product_id, new_quantity, notes=None):
    require_inventory_management(session)
    validate_stock_value(new_quantity, "New quantity")
    with get_connection() as conn:
        product = get_product_by_id(product_id, conn=conn)
        if not product:
            raise ValueError("Product not found.")
        previous_quantity = product["quantity_in_stock"]
        new_quantity = int(new_quantity)
        movement_quantity = new_quantity - previous_quantity
        conn.execute(
            "UPDATE products SET quantity_in_stock = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_quantity, product_id)
        )
        log_stock_movement(
            conn,
            product_id,
            MOVEMENT_ADJUSTMENT,
            movement_quantity,
            previous_quantity,
            new_quantity,
            session.user_id,
            notes
        )
    return get_product_by_id(product_id)


def receive_stock(session, product_id, quantity, notes=None):
    require_inventory_management(session)
    validate_positive_quantity(quantity)
    return apply_stock_delta(product_id, int(quantity), MOVEMENT_PURCHASE, session.user_id, notes)


def record_sale_stock_movement(conn, product_id, quantity, user_id, notes=None):
    validate_positive_quantity(quantity)
    product = get_product_by_id(product_id, conn=conn)
    if not product:
        raise ValueError("Product not found.")
    previous_quantity = product["quantity_in_stock"]
    new_quantity = previous_quantity - int(quantity)
    if new_quantity < 0:
        raise ValueError(f"Insufficient stock for {product['name']}.")
    conn.execute(
        "UPDATE products SET quantity_in_stock = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (new_quantity, product_id)
    )
    log_stock_movement(
        conn,
        product_id,
        MOVEMENT_SALE,
        -int(quantity),
        previous_quantity,
        new_quantity,
        user_id,
        notes
    )
    return new_quantity


def apply_stock_delta(product_id, delta, movement_type, user_id, notes=None):
    if movement_type not in VALID_MOVEMENT_TYPES:
        raise ValueError("Invalid stock movement type.")
    with get_connection() as conn:
        product = get_product_by_id(product_id, conn=conn)
        if not product:
            raise ValueError("Product not found.")
        previous_quantity = product["quantity_in_stock"]
        new_quantity = previous_quantity + int(delta)
        if new_quantity < 0:
            raise ValueError("Stock cannot become negative.")
        conn.execute(
            "UPDATE products SET quantity_in_stock = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_quantity, product_id)
        )
        log_stock_movement(conn, product_id, movement_type, int(delta), previous_quantity, new_quantity, user_id, notes)
    return get_product_by_id(product_id)


def get_low_stock_products(limit=None):
    query = """
        SELECT * FROM products
        WHERE is_active = 1 AND quantity_in_stock <= reorder_level
        ORDER BY quantity_in_stock ASC, name ASC
    """
    params = []
    if limit:
        query += " LIMIT ?"
        params.append(int(limit))
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def search_products(term=None, include_inactive=False):
    filters = []
    params = []
    if not include_inactive:
        filters.append("is_active = 1")
    if term:
        filters.append("(sku LIKE ? OR barcode LIKE ? OR name LIKE ?)")
        pattern = f"%{term}%"
        params.extend([pattern, pattern, pattern])
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(
            f"SELECT * FROM products {where_clause} ORDER BY name ASC",
            params
        ).fetchall()]


def fetch_product_for_sale(identifier):
    with get_connection() as conn:
        row = conn.execute(
            """SELECT id, sku AS product_id, name, selling_price AS price, quantity_in_stock AS stock
               FROM products
               WHERE is_active = 1 AND (sku = ? OR barcode = ? OR CAST(id AS TEXT) = ?)""",
            (identifier, identifier, identifier)
        ).fetchone()
        return dict(row) if row else None


def fetch_all_inventory_for_sale():
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(
            """SELECT sku AS product_id, name, selling_price AS price, quantity_in_stock AS stock
               FROM products
               WHERE is_active = 1
               ORDER BY name ASC"""
        ).fetchall()]


def get_product_by_id(product_id, conn=None):
    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True
    try:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        return dict(row) if row else None
    finally:
        if close_conn:
            conn.close()


def log_stock_movement(conn, product_id, movement_type, quantity, previous_quantity, new_quantity, user_id, notes=None):
    if movement_type not in VALID_MOVEMENT_TYPES:
        raise ValueError("Invalid stock movement type.")
    conn.execute(
        """INSERT INTO stock_movements (
            product_id, movement_type, quantity, previous_quantity, new_quantity, user_id, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (product_id, movement_type, int(quantity), int(previous_quantity), int(new_quantity), user_id, notes)
    )


def normalize_required(value, label):
    value = (value or "").strip()
    if not value:
        raise ValueError(f"{label} is required.")
    return value


def validate_non_negative(value, label):
    if float(value) < 0:
        raise ValueError(f"{label} cannot be negative.")


def validate_stock_value(value, label):
    if int(value) < 0:
        raise ValueError(f"{label} cannot be negative.")


def validate_positive_quantity(quantity):
    if int(quantity) <= 0:
        raise ValueError("Quantity must be positive.")