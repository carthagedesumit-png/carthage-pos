import os

from auth import AuthorizationError, UserSession, require_inventory_management
from app.core.config import get_config
from app.core.pos_engine import ShoppingCart, fetch_all_inventory, fetch_dashboard_metrics
from app.documents.document_service import generate_sales_receipt
from app.hardware.hardware_service import (
    clear_display,
    lookup_scanned_product,
    maybe_open_drawer_after_sale,
    open_cash_drawer,
    print_receipt as print_hardware_receipt,
    print_test_page,
    show_cart_item,
    show_payment_confirmation,
    show_totals,
    show_welcome,
)
from app.inventory.inventory_service import adjust_stock
from app.sales.sales_service import PAYMENT_CASH, create_sale


def clear_screen():
    """Clears the terminal screen for a clean user experience."""
    os.system('cls' if os.name == 'nt' else 'clear')


def show_inventory(store_id=None):
    """Fetches and prints out the entire supermarket stock grid."""
    inventory = fetch_all_inventory(store_id=store_id)
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
        {"product_id": item["product_id"], "quantity": item["quantity"]}
        for item in cart_data["items"]
    ]
    receipt_data = create_sale(
        session,
        sale_items,
        payment_method=payment_method,
        amount_paid=amount_paid,
        tax_rate=0.075,
        store_id=session.store_id,
    )
    try:
        maybe_open_drawer_after_sale(session, receipt_data)
        show_payment_confirmation(session, receipt_data["sale"]["total_amount"])
    except Exception:
        pass
    return receipt_data


def print_receipt(receipt_data, session=None):
    """Print the document-engine thermal representation for a completed sale."""
    clear_screen()
    document = generate_sales_receipt(
        receipt_data["sale"]["sale_id"],
        width_mm=get_config().receipt.width_mm,
    )
    print(document["text"])
    if get_config().hardware.printer_enabled and isinstance(session, UserSession):
        try:
            result = print_hardware_receipt(session, receipt_data["sale"]["sale_id"])
            if not result["success"]:
                print(f"Printer unavailable: {result['error']}")
        except Exception:
            print("Printer unavailable; receipt remains displayed above.")


def show_dashboard(store_id=None):
    """Displays the executive metrics dashboard console."""
    clear_screen()
    data = fetch_dashboard_metrics(store_ids=[store_id] if store_id else None)

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

    cart = ShoppingCart(store_id=session.store_id)
    show_welcome(session)

    while True:
        print("\n" + "=" * 72)
        print(
            " CARTHAGE INTERACTIVE TERMINAL | Station: 01 | "
            f"Active Cashier: {session.username} | Role: {session.role}"
        )
        print("=" * 72)
        print("[1] View Live Stock  [2] Scan/Add Item  [3] View Cart & Checkout")
        print("[4] Sales Dashboard  [5] Inventory Admin  [6] Exit Engine")
        print("[7] Test Printer     [8] Open Cash Drawer")
        print("-" * 72)

        choice = input("Select operation code: ").strip()

        if choice == "1":
            show_inventory(store_id=session.store_id)
        elif choice == "2":
            pid = input("Scan Barcode / Enter Product ID: ").strip()
            try:
                qty = int(input("Enter Quantity (Press Enter for 1): ") or 1)
                product = lookup_scanned_product(
                    session, pid, store_id=session.store_id, allow_manual_fallback=True
                )
                result = cart.add_item(product["id"], qty)
                print(result["message"])
                if result["success"]:
                    show_cart_item(session, product["name"], qty, product["price"])
            except ValueError as exc:
                print(f"Invalid scan or quantity: {exc}")
        elif choice == "3":
            if not cart.items:
                print("The active checkout session cart is completely empty.")
                continue

            cart_data = cart.calculate_totals()
            print("\nCURRENT CART PREVIEW:")
            for item in cart_data["items"]:
                print(f" - {item['name']} (x{item['quantity']}): ${item['total']:.2f}")
            print(f"Pending Grand Total: ${cart_data['grand_total']:.2f}")
            show_totals(session, cart_data["subtotal"], cart_data["grand_total"])

            confirm = input("\nProceed to Final Payment & Print Receipt? (yes/no): ").strip().lower()
            if confirm == "yes":
                try:
                    receipt_data = commit_transaction(cart_data, session=session)
                except ValueError as exc:
                    print(f"Checkout failed: {exc}")
                    continue
                print_receipt(receipt_data, session=session)
                cart.clear()
            else:
                print("Checkout hold. Returning to terminal.")
        elif choice == "4":
            show_dashboard(store_id=session.store_id)
        elif choice == "5":
            try:
                require_inventory_management(session)
            except AuthorizationError as exc:
                print(f"Access denied: {exc}")
                continue
            print("Inventory administration is authorized for this session.")
        elif choice == "6":
            clear_display(session)
            print("Shutting down core engine threads. Terminal offline.")
            break
        elif choice == "7":
            try:
                result = print_test_page(session)
                print("Printer test submitted." if result["success"] else f"Printer test failed: {result['error']}")
            except AuthorizationError as exc:
                print(f"Access denied: {exc}")
        elif choice == "8":
            try:
                result = open_cash_drawer(session)
                print("Cash drawer opened." if result["success"] else f"Cash drawer unavailable: {result['error']}")
            except AuthorizationError as exc:
                print(f"Access denied: {exc}")
        else:
            print("Undefined command entry.")
