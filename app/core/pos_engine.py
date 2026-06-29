from app.database.db_manager import get_connection
from app.inventory.inventory_service import fetch_all_inventory_for_sale, fetch_product_for_sale


def fetch_product(product_id):
    """Retrieves a single active product's sale details by SKU/barcode/internal ID."""
    return fetch_product_for_sale(product_id)


def fetch_all_inventory():
    """Retrieves all active items in the inventory."""
    return fetch_all_inventory_for_sale()


class ShoppingCart:
    def __init__(self):
        self.items = {}  # Format: {product_id: quantity}; product_id is products.id

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

        product_key = product["id"]
        current_stock = product["stock"]
        requested_total = self.items.get(product_key, 0) + quantity

        if requested_total > current_stock:
            return {
                "success": False,
                "message": f"Insufficient stock. Only {current_stock} available."
            }

        self.items[product_key] = requested_total
        return {"success": True, "message": f"Added {quantity}x {product['name']} to cart."}

    def calculate_totals(self, tax_rate=0.075):
        """Processes subtotals, VAT calculations, and absolute grand totals."""
        subtotal = 0.0
        cart_details = []

        for product_id, qty in self.items.items():
            product = fetch_product(str(product_id))
            if not product:
                raise ValueError(f"Product {product_id} no longer exists in inventory.")
            item_total = product["price"] * qty
            subtotal += item_total
            cart_details.append({
                "product_id": product_id,
                "sku": product["product_id"],
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
            SELECT p.name, SUM(si.quantity) as total_sold
            FROM sale_items si
            JOIN products p ON CAST(si.product_id AS INTEGER) = p.id
            GROUP BY p.id
            ORDER BY total_sold DESC
            LIMIT 3
        """)
        metrics["top_items"] = [dict(row) for row in cursor.fetchall()]

    return metrics