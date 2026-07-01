from decimal import Decimal, ROUND_HALF_UP
from sqlite3 import IntegrityError
from typing import Any, Optional

from auth import require_inventory_management, require_store_access
from app.core.exceptions import ProcurementError
from app.core.logging_utils import get_logger, log_event
from app.core.validation import iso_date, non_negative_number, positive_int, required_text
from app.database.db_manager import get_connection
from app.database.transactions import transaction
from app.inventory.inventory_service import (
    MOVEMENT_PURCHASE,
    ensure_store_inventory,
    get_store_inventory,
    log_stock_movement,
    update_store_inventory_balance,
)


STATUS_DRAFT = "DRAFT"
STATUS_SUBMITTED = "SUBMITTED"
STATUS_PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
STATUS_FULLY_RECEIVED = "FULLY_RECEIVED"
STATUS_CANCELLED = "CANCELLED"
RECEIVABLE_STATUSES = {STATUS_SUBMITTED, STATUS_PARTIALLY_RECEIVED}
PurchaseOrder = dict[str, Any]
logger = get_logger("procurement")


def create_purchase_order(
    session: Any,
    supplier_id: int,
    reference_number: str,
    line_items: list[dict[str, Any]],
    expected_delivery_date: Optional[str] = None,
    notes: Optional[str] = None,
    store_id: Optional[int] = None,
) -> PurchaseOrder:
    """Create a draft purchase order with validated product lines."""
    session = require_inventory_management(session)
    store_id = int(store_id or session.store_id)
    session = require_store_access(session, store_id, manage=True)
    reference_number = _required(reference_number, "Reference number")
    expected_delivery_date = _normalize_optional_date(expected_delivery_date)
    if not line_items:
        raise ProcurementError("Purchase order must contain at least one line item.")

    try:
        with transaction() as conn:
            supplier = conn.execute(
                "SELECT id, is_active FROM suppliers WHERE id = ?", (supplier_id,)
            ).fetchone()
            if not supplier:
                raise ProcurementError("Supplier not found.")
            if not supplier["is_active"]:
                raise ProcurementError("Inactive suppliers cannot be used for new purchase orders.")

            prepared_items = _prepare_order_items(conn, line_items)
            cursor = conn.execute(
                """INSERT INTO purchase_orders (
                       supplier_id, store_id, reference_number, status, expected_delivery_date,
                       created_by, notes
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    supplier_id,
                    store_id,
                    reference_number,
                    STATUS_DRAFT,
                    expected_delivery_date,
                    session.user_id,
                    _optional(notes),
                ),
            )
            purchase_order_id = cursor.lastrowid
            conn.executemany(
                """INSERT INTO purchase_order_items (
                       purchase_order_id, product_id, ordered_quantity,
                       received_quantity, unit_cost, subtotal
                   ) VALUES (?, ?, ?, 0, ?, ?)""",
                [
                    (
                        purchase_order_id,
                        item["product_id"],
                        item["ordered_quantity"],
                        item["unit_cost"],
                        item["subtotal"],
                    )
                    for item in prepared_items
                ],
            )
    except IntegrityError as exc:
        raise ProcurementError("Purchase order reference or product line already exists.") from exc
    log_event(
        logger,
        "purchase_order_created",
        purchase_order_id=purchase_order_id,
        reference_number=reference_number,
        store_id=store_id,
        supplier_id=supplier_id,
        user_id=session.user_id,
    )
    return get_purchase_order(purchase_order_id)


def submit_purchase_order(session: Any, purchase_order_id: int) -> PurchaseOrder:
    """Move a draft purchase order into the receivable workflow."""
    session = require_inventory_management(session)
    with transaction() as conn:
        order = conn.execute(
            "SELECT store_id FROM purchase_orders WHERE id = ?", (purchase_order_id,)
        ).fetchone()
        if not order:
            raise ProcurementError("Purchase order not found.")
        require_store_access(session, order["store_id"], manage=True)
        cursor = conn.execute(
            """UPDATE purchase_orders
               SET status = ?, submitted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND status = ?""",
            (STATUS_SUBMITTED, purchase_order_id, STATUS_DRAFT),
        )
        if cursor.rowcount == 0:
            _raise_invalid_transition(conn, purchase_order_id, "submitted")
    return get_purchase_order(purchase_order_id)


def cancel_purchase_order(session: Any, purchase_order_id: int) -> PurchaseOrder:
    """Cancel an unreceived draft or submitted purchase order."""
    session = require_inventory_management(session)
    with transaction() as conn:
        order = conn.execute(
            "SELECT store_id FROM purchase_orders WHERE id = ?", (purchase_order_id,)
        ).fetchone()
        if not order:
            raise ProcurementError("Purchase order not found.")
        require_store_access(session, order["store_id"], manage=True)
        cursor = conn.execute(
            """UPDATE purchase_orders
               SET status = ?, cancelled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND status IN (?, ?)""",
            (STATUS_CANCELLED, purchase_order_id, STATUS_DRAFT, STATUS_SUBMITTED),
        )
        if cursor.rowcount == 0:
            _raise_invalid_transition(conn, purchase_order_id, "cancelled")
    return get_purchase_order(purchase_order_id)


def receive_purchase_order(
    session: Any,
    purchase_order_id: int,
    line_items: list[dict[str, Any]],
    notes: Optional[str] = None,
) -> dict[str, Any]:
    """Receive one delivery atomically and update moving-average product cost."""
    session = require_inventory_management(session)
    if not line_items:
        raise ProcurementError("Receipt must contain at least one line item.")

    with transaction() as conn:
        purchase_order = conn.execute(
            """SELECT po.*, s.is_active AS supplier_is_active
               FROM purchase_orders po
               JOIN suppliers s ON s.id = po.supplier_id
               WHERE po.id = ?""",
            (purchase_order_id,),
        ).fetchone()
        if not purchase_order:
            raise ProcurementError("Purchase order not found.")
        if purchase_order["status"] not in RECEIVABLE_STATUSES:
            raise ProcurementError("Purchase order is not open for receiving.")
        session = require_store_access(
            session, purchase_order["store_id"], manage=True
        )

        prepared_items = _prepare_receipt_items(conn, purchase_order_id, line_items)
        sequence = conn.execute(
            "SELECT COUNT(*) FROM purchase_receipts WHERE purchase_order_id = ?",
            (purchase_order_id,),
        ).fetchone()[0] + 1
        receipt_number = f"GRN-{purchase_order_id:06d}-{sequence:04d}"
        cursor = conn.execute(
            """INSERT INTO purchase_receipts (
                   purchase_order_id, receipt_number, received_by, notes
               ) VALUES (?, ?, ?, ?)""",
            (purchase_order_id, receipt_number, session.user_id, _optional(notes)),
        )
        receipt_id = cursor.lastrowid

        for item in prepared_items:
            ensure_store_inventory(
                conn,
                purchase_order["store_id"],
                item["product_id"],
                average_cost=item["unit_cost"],
            )
            inventory = get_store_inventory(
                item["product_id"], purchase_order["store_id"], conn=conn
            )
            previous_quantity = int(inventory["quantity_on_hand"])
            previous_cost = float(inventory["average_cost"] or 0)
            new_quantity = previous_quantity + item["quantity"]
            new_cost = _average_cost(
                previous_quantity,
                previous_cost,
                item["quantity"],
                item["unit_cost"],
            )
            update_store_inventory_balance(
                conn,
                purchase_order["store_id"],
                item["product_id"],
                new_quantity,
                average_cost=new_cost,
            )
            conn.execute(
                "UPDATE products SET supplier_id = ? WHERE id = ?",
                (purchase_order["supplier_id"], item["product_id"]),
            )
            conn.execute(
                """UPDATE purchase_order_items
                   SET received_quantity = received_quantity + ? WHERE id = ?""",
                (item["quantity"], item["purchase_order_item_id"]),
            )
            conn.execute(
                """INSERT INTO purchase_receipt_items (
                       receipt_id, purchase_order_item_id, quantity, unit_cost,
                       subtotal, previous_quantity, new_quantity, previous_cost, new_cost
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    receipt_id,
                    item["purchase_order_item_id"],
                    item["quantity"],
                    item["unit_cost"],
                    item["subtotal"],
                    previous_quantity,
                    new_quantity,
                    previous_cost,
                    new_cost,
                ),
            )
            log_stock_movement(
                conn,
                item["product_id"],
                MOVEMENT_PURCHASE,
                item["quantity"],
                previous_quantity,
                new_quantity,
                session.user_id,
                f"Receipt {receipt_number} for PO {purchase_order['reference_number']}",
                store_id=purchase_order["store_id"],
            )

        outstanding = conn.execute(
            """SELECT COUNT(*) FROM purchase_order_items
               WHERE purchase_order_id = ? AND received_quantity < ordered_quantity""",
            (purchase_order_id,),
        ).fetchone()[0]
        status = STATUS_FULLY_RECEIVED if outstanding == 0 else STATUS_PARTIALLY_RECEIVED
        conn.execute(
            "UPDATE purchase_orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, purchase_order_id),
        )
    log_event(
        logger,
        "purchase_order_received",
        purchase_order_id=purchase_order_id,
        receipt_id=receipt_id,
        receipt_number=receipt_number,
        store_id=purchase_order["store_id"],
        user_id=session.user_id,
        status=status,
    )
    return get_purchase_receipt(receipt_id)


def get_purchase_order(purchase_order_id: int) -> Optional[PurchaseOrder]:
    """Return a purchase order with line and receipt audit history."""
    with get_connection() as conn:
        order = conn.execute(
            """SELECT po.*, s.name AS supplier_name, u.username AS created_by_username
               FROM purchase_orders po
               JOIN suppliers s ON s.id = po.supplier_id
               JOIN users u ON u.id = po.created_by
               WHERE po.id = ?""",
            (purchase_order_id,),
        ).fetchone()
        if not order:
            return None
        items = [
            dict(row)
            for row in conn.execute(
                """SELECT poi.*, p.sku, p.name AS product_name,
                          poi.ordered_quantity - poi.received_quantity AS remaining_quantity
                   FROM purchase_order_items poi
                   JOIN products p ON p.id = poi.product_id
                   WHERE poi.purchase_order_id = ? ORDER BY poi.id""",
                (purchase_order_id,),
            ).fetchall()
        ]
        receipts = [
            dict(row)
            for row in conn.execute(
                """SELECT pr.*, u.username AS received_by_username
                   FROM purchase_receipts pr
                   JOIN users u ON u.id = pr.received_by
                   WHERE pr.purchase_order_id = ? ORDER BY pr.id""",
                (purchase_order_id,),
            ).fetchall()
        ]
    return {"purchase_order": dict(order), "items": items, "receipts": receipts}


def get_purchase_receipt(receipt_id: int) -> Optional[dict[str, Any]]:
    """Return one goods receipt with immutable quantity and cost audit fields."""
    with get_connection() as conn:
        receipt = conn.execute(
            """SELECT pr.*, u.username AS received_by_username
               FROM purchase_receipts pr
               JOIN users u ON u.id = pr.received_by WHERE pr.id = ?""",
            (receipt_id,),
        ).fetchone()
        if not receipt:
            return None
        items = [
            dict(row)
            for row in conn.execute(
                """SELECT pri.*, poi.product_id, p.sku, p.name AS product_name
                   FROM purchase_receipt_items pri
                   JOIN purchase_order_items poi ON poi.id = pri.purchase_order_item_id
                   JOIN products p ON p.id = poi.product_id
                   WHERE pri.receipt_id = ? ORDER BY pri.id""",
                (receipt_id,),
            ).fetchall()
        ]
    return {"receipt": dict(receipt), "items": items}


def search_purchase_orders(
    term: Optional[str] = None,
    status: Optional[str] = None,
) -> list[PurchaseOrder]:
    """Search purchase order headers by reference or supplier name."""
    filters = []
    params: list[Any] = []
    if term and term.strip():
        pattern = f"%{term.strip()}%"
        filters.append("(po.reference_number LIKE ? OR s.name LIKE ?)")
        params.extend([pattern, pattern])
    valid_statuses = {
        STATUS_DRAFT, STATUS_SUBMITTED, STATUS_PARTIALLY_RECEIVED,
        STATUS_FULLY_RECEIVED, STATUS_CANCELLED,
    }
    if status:
        normalized_status = str(status).strip().upper()
        if normalized_status not in valid_statuses:
            raise ValueError("Invalid purchase order status.")
        filters.append("po.status = ?")
        params.append(normalized_status)
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    with get_connection() as conn:
        return [
            dict(row)
            for row in conn.execute(
                f"""SELECT po.*, s.name AS supplier_name, u.username AS created_by_username
                    FROM purchase_orders po
                    JOIN suppliers s ON s.id = po.supplier_id
                    JOIN users u ON u.id = po.created_by
                    {where_clause}
                    ORDER BY po.created_at DESC, po.id DESC""",
                params,
            ).fetchall()
        ]


def _prepare_order_items(conn: Any, line_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared = []
    product_ids = set()
    for item in line_items:
        product_id = item.get("product_id")
        if product_id in product_ids:
            raise ValueError("A product may only appear once on a purchase order.")
        product_ids.add(product_id)
        quantity = _positive_quantity(item.get("quantity"))
        unit_cost = _non_negative_cost(item.get("unit_cost"))
        product = conn.execute(
            "SELECT id, is_active FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if not product or not product["is_active"]:
            raise ValueError("Product not found or inactive.")
        prepared.append({
            "product_id": product_id,
            "ordered_quantity": quantity,
            "unit_cost": unit_cost,
            "subtotal": _money(quantity * unit_cost),
        })
    return prepared


def _prepare_receipt_items(
    conn: Any,
    purchase_order_id: int,
    line_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    prepared = []
    line_ids = set()
    for item in line_items:
        line_id = item.get("purchase_order_item_id")
        if line_id in line_ids:
            raise ValueError("A purchase order line may only appear once per receipt.")
        line_ids.add(line_id)
        quantity = _positive_quantity(item.get("quantity"))
        order_item = conn.execute(
            "SELECT * FROM purchase_order_items WHERE id = ? AND purchase_order_id = ?",
            (line_id, purchase_order_id),
        ).fetchone()
        if not order_item:
            raise ValueError("Purchase order line not found.")
        remaining = order_item["ordered_quantity"] - order_item["received_quantity"]
        if quantity > remaining:
            raise ValueError("Received quantity cannot exceed the outstanding order quantity.")
        unit_cost = _non_negative_cost(item.get("unit_cost", order_item["unit_cost"]))
        prepared.append({
            "purchase_order_item_id": line_id,
            "product_id": order_item["product_id"],
            "quantity": quantity,
            "unit_cost": unit_cost,
            "subtotal": _money(quantity * unit_cost),
        })
    return prepared


def _raise_invalid_transition(conn: Any, purchase_order_id: int, action: str) -> None:
    row = conn.execute(
        "SELECT status FROM purchase_orders WHERE id = ?", (purchase_order_id,)
    ).fetchone()
    if not row:
        raise ValueError("Purchase order not found.")
    raise ValueError(f"Purchase order in status {row['status']} cannot be {action}.")


def _average_cost(
    previous_quantity: int,
    previous_cost: float,
    received_quantity: int,
    received_cost: float,
) -> float:
    new_quantity = previous_quantity + received_quantity
    if new_quantity <= 0:
        return _cost(received_cost)
    weighted = (
        Decimal(str(previous_quantity)) * Decimal(str(previous_cost))
        + Decimal(str(received_quantity)) * Decimal(str(received_cost))
    ) / Decimal(str(new_quantity))
    return float(weighted.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _normalize_optional_date(value: Optional[str]) -> Optional[str]:
    return iso_date(
        value,
        "Expected delivery date",
        error_type=ProcurementError,
    )


def _positive_quantity(value: Any) -> int:
    return positive_int(value, error_type=ProcurementError)


def _non_negative_cost(value: Any) -> float:
    return _cost(
        non_negative_number(value, "Unit cost", error_type=ProcurementError)
    )


def _required(value: Any, label: str) -> str:
    return required_text(value, label, error_type=ProcurementError)


def _optional(value: Any) -> Optional[str]:
    normalized = str(value or "").strip()
    return normalized or None


def _money(value: Any) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _cost(value: Any) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
