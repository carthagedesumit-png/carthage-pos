import os

from auth import AuthorizationError, UserSession, require_inventory_management
from app.core.pos_engine import ShoppingCart, fetch_all_inventory, fetch_dashboard_metrics
from app.inventory.inventory_service import adjust_stock
from app.sales.sales_service import PAYMENT_CASH, create_sale


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


def update_inventory_stock(session, product_id, stock):
    """Role-protected inventory management operation."""
    return adjust_stock(session, product_id, stock, notes="Manual terminal stock update")


def commit_transaction(cart_data, session, payment_method=PAYMENT_CASH, amount_paid=None):
    """Saves the completed transaction through the sales engine."""
    if not isinstance(session, UserSession):
        raise ValueError("A valid authenticated user session is required.")
    if amount_paid is None:
        amount_paid = cart_data["grand_total"]
    sale_items = [
        {"product_id": item["product_id"], "quantity": item["quantity"], "unit_price": item["price"]}
        for item in cart_data["items"]
    ]
    return create_sale(
        session,
        sale_items,
        payment_method=payment_method,
        amount_paid=amount_paid,
        tax_rate=0.075,
    )


def print_receipt(receipt_data):
    """Formats and prints an industry-standard invoice receipt."""
    sale = receipt_data["sale"]
    clear_screen()
    print("\n" + "*" * 45)
    print(f"{'CARTHAGE SYSTEMS SUPERMARKET':^45}")
    print(f"{sale['receipt_number']:^45}")
    print("*" * 45)
    print(f"{'Item Description':<22} | {'Qty':<4} | {'Total':<12}")
    print("-" * 45)
    for item in receipt_data["items"]:
        print(f"{item['name']:<22} | {item['quantity']:<4} | ${item['line_total']:<11.2f}")
    print("-" * 45)
    print(f"{'Subtotal:':<29} ${sale['subtotal']:.2f}")
    print(f"{'Discount:':<29} ${sale['discount_amount']:.2f}")
    print(f"{'Tax:':<29} ${sale['tax_amount']:.2f}")
    print(f"{'Grand Total:':<29} ${sale['total_amount']:.2f}")
    print(f"{'Paid:':<29} ${sale['amount_paid']:.2f}")
    print(f"{'Change:':<29} ${sale['change_given']:.2f}")
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


def run_pos_terminal(session):
    """Main terminal command execution loop."""
    if not isinstance(session, UserSession):
        raise ValueError("A valid authenticated user session is required.")

    cart = ShoppingCart()

    while True:
        print("\n" + "=" * 72)
        print(
            " CARTHAGE INTERACTIVE TERMINAL | Station: 01 | "
            f"Active Cashier: {session.username} | Role: {session.role}"
        )
        print("=" * 72)
        print("[1] View Live Stock  [2] Scan/Add Item  [3] View Cart & Checkout")
        print("[4] Sales Dashboard  [5] Inventory Admin  [6] Exit Engine")
        print("-" * 72)

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
                    receipt_data = commit_transaction(cart_data, session=session)
                except ValueError as exc:
                    print(f"Checkout failed: {exc}")
                    continue
                print_receipt(receipt_data)
                cart.clear()
            else:
                print("Checkout hold. Returning to terminal.")
        elif choice == "4":
            show_dashboard()
        elif choice == "5":
            try:
                require_inventory_management(session)
            except AuthorizationError as exc:
                print(f"Access denied: {exc}")
                continue
            print("Inventory administration is authorized for this session.")
        elif choice == "6":
            print("Shutting down core engine threads. Terminal offline.")
            break
        else:
            print("Undefined command entry.")