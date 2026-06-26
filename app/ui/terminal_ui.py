import os

from app.core.pos_engine import ShoppingCart, fetch_all_inventory, fetch_dashboard_metrics
from app.database.db_manager import get_connection


def clear_screen():
    """Clears the terminal screen for a clean user experience."""
    os.system('cls' if os.name == 'nt' else 'clear')


def show_inventory():
    """Fetches and prints out the entire supermarket stock grid."""
    inventory = fetch_all_inventory()
    print("\n" + "=" * 55)
    print(f" {'CARTHAGE SYSTEMS INVENTORY CONTROL':^53} ")
    print("=" * 55)
    print(f"{'SKU/ID':<8} | {'Product Description':<25} | {'Price':<8} | {'Stock':<6}")
    print("-" * 55)
    for item in inventory:
        print(f"{item['product_id']:<8} | {item['name']:<25} | ${item['price']:<7.2f} | {item['stock']:<6}")
    print("=" * 55)


def commit_transaction(cart_data, cashier_name="System Admin"):
    """Saves the completed transaction to the database and updates stock."""
    if not cart_data["items"]:
        raise ValueError("Cannot commit an empty transaction.")

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO sales (cashier_name, subtotal, tax, total) VALUES (?, ?, ?, ?)",
            (cashier_name, cart_data["subtotal"], cart_data["tax"], cart_data["grand_total"])
        )
        sale_id = cursor.lastrowid

        for item in cart_data["items"]:
            if item["quantity"] <= 0:
                raise ValueError("Transaction quantities must be positive.")

            cursor.execute(
                "SELECT stock FROM inventory WHERE product_id = ?",
                (item["product_id"],)
            )
            stock_row = cursor.fetchone()
            if not stock_row:
                raise ValueError(f"Product {item['product_id']} no longer exists.")
            if stock_row["stock"] < item["quantity"]:
                raise ValueError(f"Insufficient stock for {item['name']}.")

            cursor.execute(
                """INSERT INTO sale_items (sale_id, product_id, quantity, price_at_sale)
                   VALUES (?, ?, ?, ?)""",
                (sale_id, item["product_id"], item["quantity"], item["price"])
            )
            cursor.execute(
                "UPDATE inventory SET stock = stock - ? WHERE product_id = ?",
                (item["quantity"], item["product_id"])
            )
        conn.commit()


def print_receipt(cart_data):
    """Formats and prints an industry-standard invoice receipt."""
    clear_screen()
    print("\n" + "*" * 45)
    print(f"{'CARTHAGE SYSTEMS SUPERMARKET':^45}")
    print(f"{'TERMINAL ENGINE v1.0':^45}")
    print("*" * 45)
    print(f"{'Item Description':<22} | {'Qty':<4} | {'Total':<12}")
    print("-" * 45)
    for item in cart_data["items"]:
        print(f"{item['name']:<22} | {item['quantity']:<4} | ${item['total']:<11.2f}")
    print("-" * 45)
    print(f"{'Subtotal:':<29} ${cart_data['subtotal']:.2f}")
    print(f"{'VAT (7.5%):':<29} ${cart_data['tax']:.2f}")
    print(f"{'Grand Total:':<29} ${cart_data['grand_total']:.2f}")
    print("*" * 45)
    print(f"{'THANK YOU FOR YOUR PATRONAGE!':^45}")
    print("*" * 45 + "\n")


def show_dashboard():
    """Displays the executive metrics dashboard console."""
    clear_screen()
    data = fetch_dashboard_metrics()

    print("\n" + "=" * 55)
    print(f"| {'CARTHAGE SYSTEMS EXECUTIVE DASHBOARD':^51} |")
    print("=" * 55)
    print(f" Total Transactions Processed : {data['transaction_count']}")
    print(f" Gross Revenue Collected      : ${data['total_revenue']:.2f}")
    print(f" Total Tax Collected (VAT)    : ${data['total_tax']:.2f}")
    print("-" * 55)
    print(" TOP PERFORMING PRODUCTS:")

    if not data["top_items"]:
        print("    No sales recorded yet.")
    else:
        for idx, item in enumerate(data["top_items"], 1):
            print(f"    {idx}. {item['name']:<25} | Units Sold: {item['total_sold']}")

    print("=" * 55)
    input("\nPress [Enter] to return to the main menu...")


def run_pos_terminal(cashier_name="System Admin"):
    """Main terminal command execution loop."""
    cart = ShoppingCart()

    while True:
        print("\n" + "=" * 65)
        print(f" CARTHAGE INTERACTIVE TERMINAL | Station: 01 | Active Cashier: {cashier_name}")
        print("=" * 65)
        print("[1] View Live Stock  [2] Scan/Add Item  [3] View Cart & Checkout")
        print("[4] Sales Dashboard  [5] Exit Engine")
        print("-" * 65)

        choice = input("Select operation code: ").strip()

        if choice == "1":
            show_inventory()
        elif choice == "2":
            pid = input("Scan Barcode / Enter Product ID: ").strip()
            try:
                qty = int(input("Enter Quantity (Press Enter for 1): ") or 1)
                result = cart.add_item(pid, qty)
                print(result["message"])
            except ValueError:
                print("Invalid input. Quantity must be a clean integer.")
        elif choice == "3":
            if not cart.items:
                print("The active checkout session cart is completely empty.")
                continue

            cart_data = cart.calculate_totals()
            print("\nCURRENT CART PREVIEW:")
            for item in cart_data["items"]:
                print(f" - {item['name']} (x{item['quantity']}): ${item['total']:.2f}")
            print(f"Pending Grand Total: ${cart_data['grand_total']:.2f}")

            confirm = input("\nProceed to Final Payment & Print Receipt? (yes/no): ").strip().lower()
            if confirm == "yes":
                try:
                    commit_transaction(cart_data, cashier_name=cashier_name)
                except ValueError as exc:
                    print(f"Checkout failed: {exc}")
                    continue
                print_receipt(cart_data)
                cart.clear()
            else:
                print("Checkout hold. Returning to terminal.")
        elif choice == "4":
            show_dashboard()
        elif choice == "5":
            print("Shutting down core engine threads. Terminal offline.")
            break
        else:
            print("Undefined command entry.")