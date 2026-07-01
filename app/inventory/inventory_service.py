from sqlite3 import IntegrityError
from auth import require_inventory_management
from app.database.db_manager import get_connection


MOVEMENT_PURCHASE = "PURCHASE"
MOVEMENT_SALE = "SALE"
MOVEMENT_ADJUSTMENT = "ADJUSTMENT"
MOVEMENT_RETURN = "RETURN"
VALID_MOVEMENT_TYPES = {
    MOVEMENT_PURCHASE, MOVEMENT_SALE, MOVEMENT_ADJUSTMENT, MOVEMENT_RETURN,
}


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
    store_id=None,
):
    session = require_inventory_management(session, store_id=store_id)
    store_id = int(store_id or session.store_id)
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 1)""",
                (
                    category_id, supplier_id, sku, barcode or sku, name, description,
                    float(cost_price), float(selling_price),
                ),
            )
            product_id = cursor.lastrowid
            conn.execute(
                """INSERT INTO store_inventory (
                       store_id, product_id, quantity_on_hand, reorder_level, average_cost
                   )
                   SELECT id, ?, 0, ?, ? FROM stores WHERE is_active = 1""",
                (product_id, int(reorder_level), float(cost_price)),
            )
            conn.execute(
                """UPDATE store_inventory SET quantity_on_hand = ?
                   WHERE store_id = ? AND product_id = ?""",
                (int(quantity_in_stock), store_id, product_id),
            )
            sync_product_aggregate(conn, product_id)
            if quantity_in_stock:
                log_stock_movement(
                    conn, product_id, MOVEMENT_PURCHASE, int(quantity_in_stock), 0,
                    int(quantity_in_stock), session.user_id, "Initial stock", store_id=store_id,
                )
    except IntegrityError as exc:
        raise ValueError("SKU or barcode already exists.") from exc
    return get_product_by_id(product_id, store_id=store_id)


def update_product(session, product_id, store_id=None, **updates):
    session = require_inventory_management(session, store_id=store_id)
    store_id = int(store_id or session.store_id)
    allowed = {
        "category_id", "supplier_id", "sku", "barcode", "name", "description",
        "cost_price", "selling_price", "reorder_level", "is_active",
    }
    changes = {key: value for key, value in updates.items() if key in allowed}
    if not changes:
        return get_product_by_id(product_id, store_id=store_id)
    for field in ("cost_price", "selling_price"):
        if field in changes:
            validate_non_negative(changes[field], field.replace("_", " ").title())
    if "reorder_level" in changes:
        validate_stock_value(changes["reorder_level"], "Reorder level")
    if "sku" in changes:
        changes["sku"] = normalize_required(changes["sku"], "SKU")
    if "name" in changes:
        changes["name"] = normalize_required(changes["name"], "Product name")

    store_reorder = changes.pop("reorder_level", None)
    store_cost = changes.get("cost_price")
    try:
        with get_connection() as conn:
            if not conn.execute("SELECT 1 FROM products WHERE id = ?", (product_id,)).fetchone():
                raise ValueError("Product not found.")
            if changes:
                assignments = ", ".join(f"{field} = ?" for field in changes)
                conn.execute(
                    f"UPDATE products SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    [*changes.values(), product_id],
                )
            ensure_store_inventory(conn, store_id, product_id)
            if store_reorder is not None:
                conn.execute(
                    """UPDATE store_inventory SET reorder_level = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE store_id = ? AND product_id = ?""",
                    (int(store_reorder), store_id, product_id),
                )
            if store_cost is not None:
                conn.execute(
                    """UPDATE store_inventory SET average_cost = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE store_id = ? AND product_id = ?""",
                    (float(store_cost), store_id, product_id),
                )
            sync_product_aggregate(conn, product_id)
    except IntegrityError as exc:
        raise ValueError("SKU or barcode already exists.") from exc
    return get_product_by_id(product_id, store_id=store_id)


def deactivate_product(session, product_id, store_id=None):
    return update_product(session, product_id, store_id=store_id, is_active=0)


def adjust_stock(session, product_id, new_quantity, notes=None, store_id=None):
    session = require_inventory_management(session, store_id=store_id)
    store_id = int(store_id or session.store_id)
    validate_stock_value(new_quantity, "New quantity")
    with get_connection() as conn:
        inventory = get_store_inventory(product_id, store_id, conn=conn)
        if not inventory:
            ensure_store_inventory(conn, store_id, product_id)
            inventory = get_store_inventory(product_id, store_id, conn=conn)
        previous_quantity = inventory["quantity_on_hand"]
        new_quantity = int(new_quantity)
        conn.execute(
            """UPDATE store_inventory
               SET quantity_on_hand = ?, updated_at = CURRENT_TIMESTAMP
               WHERE store_id = ? AND product_id = ?""",
            (new_quantity, store_id, product_id),
        )
        sync_product_aggregate(conn, product_id)
        log_stock_movement(
            conn, product_id, MOVEMENT_ADJUSTMENT, new_quantity - previous_quantity,
            previous_quantity, new_quantity, session.user_id, notes, store_id=store_id,
        )
    return get_product_by_id(product_id, store_id=store_id)


def receive_stock(session, product_id, quantity, notes=None, store_id=None):
    session = require_inventory_management(session, store_id=store_id)
    store_id = int(store_id or session.store_id)
    validate_positive_quantity(quantity)
    return apply_stock_delta(
        product_id, int(quantity), MOVEMENT_PURCHASE, session.user_id, notes,
        store_id=store_id,
    )


def record_sale_stock_movement(
    conn, product_id, quantity, user_id, notes=None, store_id=None,
):
    validate_positive_quantity(quantity)
    store_id = int(store_id or get_default_store_id(conn))
    ensure_store_inventory(conn, store_id, product_id)
    inventory = get_store_inventory(product_id, store_id, conn=conn)
    previous_quantity = inventory["quantity_on_hand"]
    new_quantity = previous_quantity - int(quantity)
    if new_quantity < 0:
        product = get_product_by_id(product_id, conn=conn)
        raise ValueError(f"Insufficient stock for {product['name']} at the selected store.")
    conn.execute(
        """UPDATE store_inventory SET quantity_on_hand = ?, updated_at = CURRENT_TIMESTAMP
           WHERE store_id = ? AND product_id = ?""",
        (new_quantity, store_id, product_id),
    )
    sync_product_aggregate(conn, product_id)
    log_stock_movement(
        conn, product_id, MOVEMENT_SALE, -int(quantity), previous_quantity,
        new_quantity, user_id, notes, store_id=store_id,
    )
    return new_quantity


def apply_stock_delta(
    product_id, delta, movement_type, user_id, notes=None, store_id=None,
    transfer_id=None,
):
    if movement_type not in VALID_MOVEMENT_TYPES:
        raise ValueError("Invalid stock movement type.")
    with get_connection() as conn:
        store_id = int(store_id or get_default_store_id(conn))
        ensure_store_inventory(conn, store_id, product_id)
        inventory = get_store_inventory(product_id, store_id, conn=conn)
        previous_quantity = inventory["quantity_on_hand"]
        new_quantity = previous_quantity + int(delta)
        if new_quantity < 0:
            raise ValueError("Stock cannot become negative.")
        conn.execute(
            """UPDATE store_inventory SET quantity_on_hand = ?, updated_at = CURRENT_TIMESTAMP
               WHERE store_id = ? AND product_id = ?""",
            (new_quantity, store_id, product_id),
        )
        sync_product_aggregate(conn, product_id)
        log_stock_movement(
            conn, product_id, movement_type, int(delta), previous_quantity,
            new_quantity, user_id, notes, store_id=store_id, transfer_id=transfer_id,
        )
    return get_product_by_id(product_id, store_id=store_id)


def get_low_stock_products(limit=None, store_id=None):
    with get_connection() as conn:
        store_id = int(store_id or get_default_store_id(conn))
        query = """
            SELECT p.*, si.quantity_on_hand AS quantity_in_stock,
                   si.reorder_level, si.average_cost, si.store_id
            FROM products p
            JOIN store_inventory si ON si.product_id = p.id
            WHERE p.is_active = 1 AND si.store_id = ?
              AND si.quantity_on_hand <= si.reorder_level
            ORDER BY si.quantity_on_hand ASC, p.name ASC
        """
        params = [store_id]
        if limit:
            query += " LIMIT ?"
            params.append(int(limit))
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def search_products(term=None, include_inactive=False, store_id=None):
    filters = []
    params = []
    if not include_inactive:
        filters.append("p.is_active = 1")
    if term:
        filters.append("(p.sku LIKE ? OR p.barcode LIKE ? OR p.name LIKE ?)")
        pattern = f"%{term}%"
        params.extend([pattern, pattern, pattern])
    with get_connection() as conn:
        store_id = int(store_id or get_default_store_id(conn))
        filters.append("si.store_id = ?")
        params.append(store_id)
        return [
            dict(row)
            for row in conn.execute(
                f"""SELECT p.*, si.quantity_on_hand AS store_quantity,
                           si.reorder_level AS store_reorder_level,
                           si.average_cost AS store_average_cost, si.store_id
                    FROM products p
                    JOIN store_inventory si ON si.product_id = p.id
                    WHERE {' AND '.join(filters)} ORDER BY p.name ASC""",
                params,
            ).fetchall()
        ]


def fetch_product_for_sale(identifier, store_id=None):
    with get_connection() as conn:
        store_id = int(store_id or get_default_store_id(conn))
        row = conn.execute(
            """SELECT p.id, p.sku AS product_id, p.name,
                      p.selling_price AS price, si.quantity_on_hand AS stock,
                      si.average_cost AS cost_price, si.store_id
               FROM products p
               JOIN store_inventory si ON si.product_id = p.id AND si.store_id = ?
               WHERE p.is_active = 1
                 AND (p.sku = ? OR p.barcode = ? OR CAST(p.id AS TEXT) = ?)""",
            (store_id, identifier, identifier, identifier),
        ).fetchone()
        return dict(row) if row else None


def fetch_all_inventory_for_sale(store_id=None):
    with get_connection() as conn:
        store_id = int(store_id or get_default_store_id(conn))
        return [
            dict(row)
            for row in conn.execute(
                """SELECT p.sku AS product_id, p.name, p.selling_price AS price,
                          si.quantity_on_hand AS stock, si.store_id
                   FROM products p
                   JOIN store_inventory si ON si.product_id = p.id AND si.store_id = ?
                   WHERE p.is_active = 1 ORDER BY p.name ASC""",
                (store_id,),
            ).fetchall()
        ]


def get_product_by_id(product_id, conn=None, store_id=None):
    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True
    try:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if not row:
            return None
        product = dict(row)
        if store_id is not None:
            inventory = get_store_inventory(product_id, store_id, conn=conn)
            product["quantity_in_stock"] = inventory["quantity_on_hand"] if inventory else 0
            product["reorder_level"] = inventory["reorder_level"] if inventory else 0
            product["cost_price"] = inventory["average_cost"] if inventory else product["cost_price"]
            product["store_id"] = int(store_id)
        return product
    finally:
        if close_conn:
            conn.close()


def get_store_inventory(product_id, store_id, conn=None):
    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True
    try:
        row = conn.execute(
            """SELECT * FROM store_inventory WHERE store_id = ? AND product_id = ?""",
            (store_id, product_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        if close_conn:
            conn.close()


def ensure_store_inventory(conn, store_id, product_id, reorder_level=0, average_cost=None):
    product = conn.execute("SELECT cost_price FROM products WHERE id = ?", (product_id,)).fetchone()
    if not product:
        raise ValueError("Product not found.")
    if not conn.execute(
        "SELECT 1 FROM stores WHERE id = ? AND is_active = 1", (store_id,)
    ).fetchone():
        raise ValueError("Store not found or inactive.")
    conn.execute(
        """INSERT OR IGNORE INTO store_inventory (
               store_id, product_id, quantity_on_hand, reorder_level, average_cost
           ) VALUES (?, ?, 0, ?, ?)""",
        (
            store_id, product_id, int(reorder_level),
            float(product["cost_price"] if average_cost is None else average_cost),
        ),
    )


def update_store_inventory_balance(
    conn, store_id, product_id, new_quantity, average_cost=None,
):
    """Update a store balance inside an existing transaction and sync compatibility totals."""
    ensure_store_inventory(conn, store_id, product_id, average_cost=average_cost)
    assignments = "quantity_on_hand = ?, updated_at = CURRENT_TIMESTAMP"
    values = [int(new_quantity)]
    if average_cost is not None:
        assignments += ", average_cost = ?"
        values.append(float(average_cost))
    values.extend([store_id, product_id])
    conn.execute(
        f"UPDATE store_inventory SET {assignments} WHERE store_id = ? AND product_id = ?",
        values,
    )
    sync_product_aggregate(conn, product_id)


def sync_product_aggregate(conn, product_id):
    row = conn.execute(
        """SELECT COALESCE(SUM(quantity_on_hand), 0) AS quantity,
                  COALESCE(SUM(quantity_on_hand * average_cost), 0) AS value,
                  COALESCE(MAX(reorder_level), 0) AS reorder_level
           FROM store_inventory WHERE product_id = ?""",
        (product_id,),
    ).fetchone()
    quantity = int(row["quantity"])
    cost = float(row["value"] / quantity) if quantity else 0.0
    conn.execute(
        """UPDATE products SET quantity_in_stock = ?, cost_price = ?, reorder_level = ?,
                   updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
        (quantity, cost, int(row["reorder_level"]), product_id),
    )


def log_stock_movement(
    conn, product_id, movement_type, quantity, previous_quantity, new_quantity,
    user_id, notes=None, store_id=None, transfer_id=None,
):
    if movement_type not in VALID_MOVEMENT_TYPES:
        raise ValueError("Invalid stock movement type.")
    store_id = int(store_id or get_default_store_id(conn))
    conn.execute(
        """INSERT INTO stock_movements (
               product_id, movement_type, quantity, previous_quantity, new_quantity,
               user_id, store_id, transfer_id, notes
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            product_id, movement_type, int(quantity), int(previous_quantity),
            int(new_quantity), user_id, store_id, transfer_id, notes,
        ),
    )


def get_default_store_id(conn=None):
    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True
    try:
        row = conn.execute("SELECT id FROM stores WHERE code = 'MAIN' COLLATE NOCASE").fetchone()
        if not row:
            raise ValueError("Default MAIN store is not configured.")
        return row["id"]
    finally:
        if close_conn:
            conn.close()


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
