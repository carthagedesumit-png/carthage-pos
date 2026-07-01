from app.inventory.inventory_service import fetch_all_inventory_for_sale, fetch_product_for_sale
from app.reports.reporting_service import get_sales_summary, get_top_selling_products


def fetch_product(product_id, store_id=None):
    """Retrieves a single active product's sale details by SKU/barcode/internal ID."""
    return fetch_product_for_sale(product_id, store_id=store_id)


def fetch_all_inventory(store_id=None):
    """Retrieves all active items in the inventory."""
    return fetch_all_inventory_for_sale(store_id=store_id)


class ShoppingCart:
    def __init__(self, store_id=None):
        self.items = {}  # Format: {product_id: quantity}; product_id is products.id
        self.store_id = store_id

    def add_item(self, product_id, quantity=1):
        """Validates real-time stock levels and adds items to the active session cart."""
        if not isinstance(quantity, int) or quantity <= 0:
            return {
                "success": False,
                "message": "Quantity must be a positive whole number."
            }

        product = fetch_product(product_id, store_id=self.store_id)
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
            product = fetch_product(str(product_id), store_id=self.store_id)
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


def fetch_dashboard_metrics(store_ids=None):
    """Aggregates sales records from the database to generate business metrics."""
    summary = get_sales_summary(store_ids=store_ids)
    return {
        "total_revenue": summary["total_sales"],
        "total_tax": summary["total_tax"],
        "transaction_count": summary["transaction_count"],
        "top_items": [
            {"name": product["name"], "total_sold": product["units_sold"]}
            for product in get_top_selling_products(limit=3, store_ids=store_ids)
        ],
    }
