from app.database.db_manager import get_connection


def fetch_product(product_id):
    """Retrieves a single product's details from the database by its barcode/ID."""
    query = "SELECT product_id, name, price, stock FROM inventory WHERE product_id = ?"
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (product_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
    return None


def fetch_all_inventory():
    """Retrieves all active items in the inventory."""
    query = "SELECT product_id, name, price, stock FROM inventory"
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query)
        return [dict(row) for row in cursor.fetchall()]


class ShoppingCart:
    def __init__(self):
        self.items = {}  # Format: {product_id: quantity}

    def add_item(self, product_id, quantity=1):
        """Validates real-time stock levels and adds items to the active session cart."""
        if not isinstance(quantity, int) or quantity <= 0:
            return {
                "success": False,
                "message": "Quantity must be a positive whole number."
            }

        product = fetch_product(product_id)
        if not product:
            return {"success": False, "message": "Product not found in database."}

        current_stock = product["stock"]
        requested_total = self.items.get(product_id, 0) + quantity

        if requested_total > current_stock:
            return {
                "success": False,
                "message": f"Insufficient stock. Only {current_stock} available."
            }

        self.items[product_id] = requested_total
        return {"success": True, "message": f"Added {quantity}x {product['name']} to cart."}

    def calculate_totals(self, tax_rate=0.075):
        """Processes subtotals, VAT calculations, and absolute grand totals."""
        subtotal = 0.0
        cart_details = []

        for pid, qty in self.items.items():
            product = fetch_product(pid)
            if not product:
                raise ValueError(f"Product {pid} no longer exists in inventory.")
            item_total = product["price"] * qty
            subtotal += item_total
            cart_details.append({
                "product_id": pid,
                "name": product["name"],
                "price": product["price"],
                "quantity": qty,
                "total": item_total
            })

        tax = subtotal * tax_rate
        grand_total = subtotal + tax

        return {
            "items": cart_details,
            "subtotal": subtotal,
            "tax": tax,
            "grand_total": grand_total
        }

    def clear(self):
        self.items.clear()


def fetch_dashboard_metrics():
    """Aggregates sales records from the database to generate business metrics."""
    metrics = {
        "total_revenue": 0.0,
        "total_tax": 0.0,
        "transaction_count": 0,
        "top_items": []
    }

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT SUM(total) as rev, SUM(tax) as tx, COUNT(sale_id) as cnt FROM sales")
        summary = cursor.fetchone()
        if summary and summary["cnt"] > 0:
            metrics["total_revenue"] = summary["rev"] or 0.0
            metrics["total_tax"] = summary["tx"] or 0.0
            metrics["transaction_count"] = summary["cnt"]

        cursor.execute("""
            SELECT i.name, SUM(si.quantity) as total_sold
            FROM sale_items si
            JOIN inventory i ON si.product_id = i.product_id
            GROUP BY si.product_id
            ORDER BY total_sold DESC
            LIMIT 3
        """)
        metrics["top_items"] = [dict(row) for row in cursor.fetchall()]

    return metrics