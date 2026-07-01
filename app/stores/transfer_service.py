from decimal import Decimal, ROUND_HALF_UP
from sqlite3 import IntegrityError
from typing import Any, Optional

from auth import require_inventory_management, require_store_access
from app.core.exceptions import TransferError
from app.core.logging_utils import get_logger, log_event
from app.core.validation import positive_int, required_text
from app.database.db_manager import get_connection
from app.database.transactions import transaction
from app.inventory.inventory_service import (
    MOVEMENT_ADJUSTMENT,
    ensure_store_inventory,
    get_store_inventory,
    log_stock_movement,
    update_store_inventory_balance,
)


STATUS_REQUESTED = "REQUESTED"
STATUS_APPROVED = "APPROVED"
STATUS_IN_TRANSIT = "IN_TRANSIT"
STATUS_RECEIVED = "RECEIVED"
STATUS_CANCELLED = "CANCELLED"
logger = get_logger("transfers")


def create_transfer(
    session: Any,
    reference_number: str,
    source_store_id: int,
    destination_store_id: int,
    line_items: list[dict[str, Any]],
    notes: Optional[str] = None,
) -> dict[str, Any]:
    """Request a transfer between two active stores."""
    session = require_inventory_management(session, store_id=source_store_id)
    require_store_access(session, source_store_id, manage=True)
    reference_number = _required(reference_number, "Transfer reference")
    if source_store_id == destination_store_id:
        raise TransferError("Source and destination stores must be different.")
    if not line_items:
        raise TransferError("Transfer must contain at least one line item.")

    try:
        with transaction() as conn:
            _require_active_store(conn, source_store_id)
            _require_active_store(conn, destination_store_id)
            prepared = _prepare_request_items(conn, line_items)
            cursor = conn.execute(
                """INSERT INTO stock_transfers (
                       reference_number, source_store_id, destination_store_id,
                       status, requested_by, notes
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    reference_number,
                    source_store_id,
                    destination_store_id,
                    STATUS_REQUESTED,
                    session.user_id,
                    _optional(notes),
                ),
            )
            transfer_id = cursor.lastrowid
            conn.executemany(
                """INSERT INTO stock_transfer_items (
                       transfer_id, product_id, requested_quantity
                   ) VALUES (?, ?, ?)""",
                [
                    (transfer_id, item["product_id"], item["quantity"])
                    for item in prepared
                ],
            )
            _log_event(
                conn, transfer_id, None, STATUS_REQUESTED, session.user_id, notes
            )
    except IntegrityError as exc:
        raise TransferError("Transfer reference or product line already exists.") from exc
    log_event(logger, "transfer_created", transfer_id=transfer_id, user_id=session.user_id)
    return get_transfer(transfer_id)


def approve_transfer(session: Any, transfer_id: int) -> dict[str, Any]:
    """Approve a requested transfer after source-store authorization."""
    session = require_inventory_management(session)
    with transaction() as conn:
        transfer = _get_transfer_header(conn, transfer_id)
        require_store_access(session, transfer["source_store_id"], manage=True)
        if transfer["status"] != STATUS_REQUESTED:
            raise TransferError("Only requested transfers can be approved.")
        _validate_source_stock(conn, transfer_id, transfer["source_store_id"])
        conn.execute(
            """UPDATE stock_transfers
               SET status = ?, approved_by = ?, approved_at = CURRENT_TIMESTAMP,
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (STATUS_APPROVED, session.user_id, transfer_id),
        )
        _log_event(
            conn, transfer_id, STATUS_REQUESTED, STATUS_APPROVED, session.user_id
        )
    log_event(logger, "transfer_approved", transfer_id=transfer_id, user_id=session.user_id)
    return get_transfer(transfer_id)


def dispatch_transfer(
    session: Any,
    transfer_id: int,
    line_items: list[dict[str, Any]],
    notes: Optional[str] = None,
) -> dict[str, Any]:
    """Dispatch part or all of an approved transfer from source inventory."""
    session = require_inventory_management(session)
    if not line_items:
        raise TransferError("Dispatch must contain at least one line item.")
    with transaction() as conn:
        transfer = _get_transfer_header(conn, transfer_id)
        require_store_access(session, transfer["source_store_id"], manage=True)
        if transfer["status"] not in {STATUS_APPROVED, STATUS_IN_TRANSIT}:
            raise TransferError("Transfer is not approved for dispatch.")
        prepared = _prepare_transfer_activity(
            conn, transfer_id, line_items, activity="dispatch"
        )
        cursor = conn.execute(
            """INSERT INTO stock_transfer_dispatches (
                   transfer_id, dispatched_by, notes
               ) VALUES (?, ?, ?)""",
            (transfer_id, session.user_id, _optional(notes)),
        )
        dispatch_id = cursor.lastrowid

        for item in prepared:
            inventory = get_store_inventory(
                item["product_id"], transfer["source_store_id"], conn=conn
            )
            if not inventory or inventory["quantity_on_hand"] < item["quantity"]:
                raise TransferError("Insufficient source-store inventory for transfer.")
            previous_quantity = inventory["quantity_on_hand"]
            new_quantity = previous_quantity - item["quantity"]
            unit_cost = float(inventory["average_cost"] or 0)
            dispatch_value = _money(item["quantity"] * unit_cost)
            update_store_inventory_balance(
                conn,
                transfer["source_store_id"],
                item["product_id"],
                new_quantity,
            )
            conn.execute(
                """UPDATE stock_transfer_items
                   SET dispatched_quantity = dispatched_quantity + ?,
                       dispatched_value = dispatched_value + ?
                   WHERE id = ?""",
                (item["quantity"], dispatch_value, item["transfer_item_id"]),
            )
            conn.execute(
                """INSERT INTO stock_transfer_dispatch_items (
                       dispatch_id, transfer_item_id, quantity
                   ) VALUES (?, ?, ?)""",
                (dispatch_id, item["transfer_item_id"], item["quantity"]),
            )
            log_stock_movement(
                conn,
                item["product_id"],
                MOVEMENT_ADJUSTMENT,
                -item["quantity"],
                previous_quantity,
                new_quantity,
                session.user_id,
                f"Transfer {transfer['reference_number']} dispatched",
                store_id=transfer["source_store_id"],
                transfer_id=transfer_id,
            )

        previous_status = transfer["status"]
        conn.execute(
            """UPDATE stock_transfers
               SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (STATUS_IN_TRANSIT, transfer_id),
        )
        if previous_status != STATUS_IN_TRANSIT:
            _log_event(
                conn,
                transfer_id,
                previous_status,
                STATUS_IN_TRANSIT,
                session.user_id,
                notes,
            )
    log_event(logger, "transfer_dispatched", transfer_id=transfer_id, user_id=session.user_id)
    return get_transfer(transfer_id)


def receive_transfer(
    session: Any,
    transfer_id: int,
    line_items: list[dict[str, Any]],
    notes: Optional[str] = None,
) -> dict[str, Any]:
    """Receive dispatched transfer quantities into destination inventory."""
    session = require_inventory_management(session)
    if not line_items:
        raise TransferError("Transfer receipt must contain at least one line item.")
    with transaction() as conn:
        transfer = _get_transfer_header(conn, transfer_id)
        require_store_access(session, transfer["destination_store_id"], manage=True)
        if transfer["status"] != STATUS_IN_TRANSIT:
            raise TransferError("Transfer has no inventory available for receipt.")
        prepared = _prepare_transfer_activity(
            conn, transfer_id, line_items, activity="receive"
        )
        cursor = conn.execute(
            """INSERT INTO stock_transfer_receipts (
                   transfer_id, received_by, notes
               ) VALUES (?, ?, ?)""",
            (transfer_id, session.user_id, _optional(notes)),
        )
        receipt_id = cursor.lastrowid

        for item in prepared:
            transfer_item = conn.execute(
                "SELECT * FROM stock_transfer_items WHERE id = ?",
                (item["transfer_item_id"],),
            ).fetchone()
            available_quantity = (
                transfer_item["dispatched_quantity"]
                - transfer_item["received_quantity"]
            )
            available_value = (
                float(transfer_item["dispatched_value"])
                - float(transfer_item["received_value"])
            )
            unit_cost = available_value / available_quantity if available_quantity else 0
            received_value = _money(item["quantity"] * unit_cost)
            ensure_store_inventory(
                conn,
                transfer["destination_store_id"],
                item["product_id"],
                average_cost=unit_cost,
            )
            inventory = get_store_inventory(
                item["product_id"], transfer["destination_store_id"], conn=conn
            )
            previous_quantity = inventory["quantity_on_hand"]
            previous_cost = float(inventory["average_cost"] or 0)
            new_quantity = previous_quantity + item["quantity"]
            new_cost = _average_cost(
                previous_quantity,
                previous_cost,
                item["quantity"],
                unit_cost,
            )
            update_store_inventory_balance(
                conn,
                transfer["destination_store_id"],
                item["product_id"],
                new_quantity,
                average_cost=new_cost,
            )
            conn.execute(
                """UPDATE stock_transfer_items
                   SET received_quantity = received_quantity + ?,
                       received_value = received_value + ?
                   WHERE id = ?""",
                (item["quantity"], received_value, item["transfer_item_id"]),
            )
            conn.execute(
                """INSERT INTO stock_transfer_receipt_items (
                       receipt_id, transfer_item_id, quantity
                   ) VALUES (?, ?, ?)""",
                (receipt_id, item["transfer_item_id"], item["quantity"]),
            )
            log_stock_movement(
                conn,
                item["product_id"],
                MOVEMENT_ADJUSTMENT,
                item["quantity"],
                previous_quantity,
                new_quantity,
                session.user_id,
                f"Transfer {transfer['reference_number']} received",
                store_id=transfer["destination_store_id"],
                transfer_id=transfer_id,
            )

        incomplete = conn.execute(
            """SELECT COUNT(*) FROM stock_transfer_items
               WHERE transfer_id = ? AND received_quantity < requested_quantity""",
            (transfer_id,),
        ).fetchone()[0]
        if incomplete == 0:
            conn.execute(
                """UPDATE stock_transfers
                   SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (STATUS_RECEIVED, transfer_id),
            )
            _log_event(
                conn,
                transfer_id,
                STATUS_IN_TRANSIT,
                STATUS_RECEIVED,
                session.user_id,
                notes,
            )
    log_event(logger, "transfer_received", transfer_id=transfer_id, user_id=session.user_id)
    return get_transfer(transfer_id)


def cancel_transfer(session: Any, transfer_id: int, notes: Optional[str] = None):
    """Cancel a transfer only before any stock has been dispatched."""
    session = require_inventory_management(session)
    with transaction() as conn:
        transfer = _get_transfer_header(conn, transfer_id)
        require_store_access(session, transfer["source_store_id"], manage=True)
        dispatched = conn.execute(
            "SELECT COALESCE(SUM(dispatched_quantity), 0) FROM stock_transfer_items WHERE transfer_id = ?",
            (transfer_id,),
        ).fetchone()[0]
        if transfer["status"] not in {STATUS_REQUESTED, STATUS_APPROVED} or dispatched:
            raise TransferError("Transfer cannot be cancelled after dispatch.")
        conn.execute(
            """UPDATE stock_transfers
               SET status = ?, cancelled_at = CURRENT_TIMESTAMP,
                   updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (STATUS_CANCELLED, transfer_id),
        )
        _log_event(
            conn,
            transfer_id,
            transfer["status"],
            STATUS_CANCELLED,
            session.user_id,
            notes,
        )
    log_event(logger, "transfer_cancelled", transfer_id=transfer_id, user_id=session.user_id)
    return get_transfer(transfer_id)


def get_transfer(transfer_id: int) -> Optional[dict[str, Any]]:
    """Return a transfer with item balances and complete workflow history."""
    with get_connection() as conn:
        header = conn.execute(
            """SELECT st.*, source.code AS source_store_code,
                      destination.code AS destination_store_code
               FROM stock_transfers st
               JOIN stores source ON source.id = st.source_store_id
               JOIN stores destination ON destination.id = st.destination_store_id
               WHERE st.id = ?""",
            (transfer_id,),
        ).fetchone()
        if not header:
            return None
        items = [
            dict(row)
            for row in conn.execute(
                """SELECT sti.*, p.sku, p.name AS product_name,
                          sti.requested_quantity - sti.dispatched_quantity
                              AS remaining_to_dispatch,
                          sti.dispatched_quantity - sti.received_quantity
                              AS quantity_in_transit
                   FROM stock_transfer_items sti
                   JOIN products p ON p.id = sti.product_id
                   WHERE sti.transfer_id = ? ORDER BY sti.id""",
                (transfer_id,),
            ).fetchall()
        ]
        events = [
            dict(row)
            for row in conn.execute(
                """SELECT ste.*, u.username
                   FROM stock_transfer_events ste
                   JOIN users u ON u.id = ste.user_id
                   WHERE ste.transfer_id = ? ORDER BY ste.id""",
                (transfer_id,),
            ).fetchall()
        ]
        dispatches = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM stock_transfer_dispatches WHERE transfer_id = ? ORDER BY id",
                (transfer_id,),
            ).fetchall()
        ]
        receipts = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM stock_transfer_receipts WHERE transfer_id = ? ORDER BY id",
                (transfer_id,),
            ).fetchall()
        ]
    return {
        "transfer": dict(header),
        "items": items,
        "events": events,
        "dispatches": dispatches,
        "receipts": receipts,
    }


def _prepare_request_items(conn, line_items):
    prepared = []
    product_ids = set()
    for item in line_items:
        product_id = item.get("product_id")
        if product_id in product_ids:
            raise ValueError("A product may only appear once on a transfer.")
        product_ids.add(product_id)
        quantity = _positive_quantity(item.get("quantity"))
        product = conn.execute(
            "SELECT id FROM products WHERE id = ? AND is_active = 1", (product_id,)
        ).fetchone()
        if not product:
            raise ValueError("Product not found or inactive.")
        prepared.append({"product_id": product_id, "quantity": quantity})
    return prepared


def _prepare_transfer_activity(conn, transfer_id, line_items, activity):
    prepared = []
    line_ids = set()
    for item in line_items:
        line_id = item.get("transfer_item_id")
        if line_id in line_ids:
            raise ValueError("A transfer line may only appear once per operation.")
        line_ids.add(line_id)
        quantity = _positive_quantity(item.get("quantity"))
        row = conn.execute(
            "SELECT * FROM stock_transfer_items WHERE id = ? AND transfer_id = ?",
            (line_id, transfer_id),
        ).fetchone()
        if not row:
            raise ValueError("Transfer line not found.")
        if activity == "dispatch":
            available = row["requested_quantity"] - row["dispatched_quantity"]
        else:
            available = row["dispatched_quantity"] - row["received_quantity"]
        if quantity > available:
            raise ValueError(
                f"{activity.title()} quantity exceeds the available transfer balance."
            )
        prepared.append(
            {
                "transfer_item_id": line_id,
                "product_id": row["product_id"],
                "quantity": quantity,
            }
        )
    return prepared


def _validate_source_stock(conn, transfer_id, source_store_id):
    rows = conn.execute(
        "SELECT product_id, requested_quantity FROM stock_transfer_items WHERE transfer_id = ?",
        (transfer_id,),
    ).fetchall()
    for row in rows:
        inventory = get_store_inventory(
            row["product_id"], source_store_id, conn=conn
        )
        if not inventory or inventory["quantity_on_hand"] < row["requested_quantity"]:
            raise ValueError("Insufficient source-store inventory for transfer approval.")


def _get_transfer_header(conn, transfer_id):
    row = conn.execute(
        "SELECT * FROM stock_transfers WHERE id = ?", (transfer_id,)
    ).fetchone()
    if not row:
        raise ValueError("Transfer not found.")
    return row


def _require_active_store(conn, store_id):
    if not conn.execute(
        "SELECT 1 FROM stores WHERE id = ? AND is_active = 1", (store_id,)
    ).fetchone():
        raise ValueError("Store not found or inactive.")


def _log_event(conn, transfer_id, from_status, to_status, user_id, notes=None):
    conn.execute(
        """INSERT INTO stock_transfer_events (
               transfer_id, from_status, to_status, user_id, notes
           ) VALUES (?, ?, ?, ?, ?)""",
        (transfer_id, from_status, to_status, user_id, _optional(notes)),
    )


def _average_cost(previous_quantity, previous_cost, incoming_quantity, incoming_cost):
    total_quantity = previous_quantity + incoming_quantity
    if total_quantity <= 0:
        return 0.0
    value = (
        Decimal(str(previous_quantity)) * Decimal(str(previous_cost))
        + Decimal(str(incoming_quantity)) * Decimal(str(incoming_cost))
    ) / Decimal(str(total_quantity))
    return float(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _positive_quantity(value):
    return positive_int(value, error_type=TransferError)


def _required(value, label):
    return required_text(value, label, error_type=TransferError)


def _optional(value):
    normalized = str(value or "").strip()
    return normalized or None


def _money(value):
    return float(
        Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )

