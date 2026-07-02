"""Sales, returns, procurement, suppliers, and transfer endpoints."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, status

from auth import UserSession
from app.api.dependencies import (
    accessible_store_ids,
    get_current_session,
    require_management,
    resolve_store_scope,
)
from app.api.pagination import data_response, paginate
from app.api.schemas import (
    NotesRequest,
    PurchaseOrderCreateRequest,
    ReceivePurchaseRequest,
    RefundRequest,
    ReturnCreateRequest,
    SaleCreateRequest,
    SupplierRequest,
    SupplierUpdateRequest,
    TransferActivityRequest,
    TransferCreateRequest,
)
from app.procurement.purchase_service import (
    cancel_purchase_order,
    create_purchase_order,
    get_purchase_order,
    receive_purchase_order,
    search_purchase_orders,
    submit_purchase_order,
)
from app.procurement.supplier_service import (
    create_supplier,
    deactivate_supplier,
    get_supplier_by_id,
    reactivate_supplier,
    search_suppliers,
    update_supplier,
)
from app.sales.sales_service import (
    create_sale,
    get_return_data,
    print_receipt_data,
    process_return,
    refund_sale,
    search_sales,
)
from app.stores.transfer_service import (
    approve_transfer,
    cancel_transfer,
    create_transfer,
    dispatch_transfer,
    get_transfer,
    receive_transfer,
    search_transfers,
)


router = APIRouter()


@router.get("/sales", tags=["sales"])
def list_sales(
    store_id: Optional[int] = Query(default=None, gt=0),
    customer_id: Optional[int] = Query(default=None, gt=0),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    session: UserSession = Depends(get_current_session),
):
    selected = resolve_store_scope(session, store_id)
    rows = search_sales(session, selected, customer_id, date_from, date_to)
    return paginate(rows, page, per_page)


@router.post("/sales", status_code=status.HTTP_201_CREATED, tags=["sales"])
def add_sale(payload: SaleCreateRequest, session: UserSession = Depends(get_current_session)):
    values = payload.model_dump(mode="json", exclude_none=True)
    values["items"] = values.pop("items")
    return data_response(create_sale(session, **values))


@router.get("/sales/{sale_id}", tags=["sales"])
def sale_detail(sale_id: int, session: UserSession = Depends(get_current_session)):
    result = print_receipt_data(sale_id)
    resolve_store_scope(session, result["sale"]["store_id"])
    return data_response(result)


@router.post("/sales/{sale_id}/returns", status_code=status.HTTP_201_CREATED, tags=["returns"])
def add_return(
    sale_id: int,
    payload: ReturnCreateRequest,
    session: UserSession = Depends(get_current_session),
):
    return data_response(process_return(session, sale_id, [item.model_dump() for item in payload.items], payload.reason))


@router.post("/sales/{sale_id}/refund", status_code=status.HTTP_201_CREATED, tags=["returns"])
def refund_full_sale(
    sale_id: int,
    payload: RefundRequest,
    session: UserSession = Depends(get_current_session),
):
    return data_response(refund_sale(session, sale_id, payload.reason))


@router.get("/returns/{return_id}", tags=["returns"])
def return_detail(return_id: int, session: UserSession = Depends(get_current_session)):
    result = get_return_data(return_id)
    sale = print_receipt_data(result["return"]["sale_id"])["sale"]
    resolve_store_scope(session, sale["store_id"])
    return data_response(result)


@router.get("/suppliers", tags=["suppliers"])
def list_suppliers(
    q: Optional[str] = None,
    include_inactive: bool = False,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    session: UserSession = Depends(get_current_session),
):
    require_management(session)
    return paginate(search_suppliers(q, include_inactive), page, per_page)


@router.post("/suppliers", status_code=status.HTTP_201_CREATED, tags=["suppliers"])
def add_supplier(payload: SupplierRequest, session: UserSession = Depends(get_current_session)):
    return data_response(create_supplier(session, **payload.model_dump()))


@router.get("/suppliers/{supplier_id}", tags=["suppliers"])
def supplier_detail(supplier_id: int, session: UserSession = Depends(get_current_session)):
    require_management(session)
    supplier = get_supplier_by_id(supplier_id)
    if not supplier:
        raise ValueError("Supplier not found.")
    return data_response(supplier)


@router.patch("/suppliers/{supplier_id}", tags=["suppliers"])
def edit_supplier(
    supplier_id: int,
    payload: SupplierUpdateRequest,
    session: UserSession = Depends(get_current_session),
):
    return data_response(update_supplier(session, supplier_id, **payload.model_dump(exclude_unset=True)))


@router.post("/suppliers/{supplier_id}/deactivate", tags=["suppliers"])
def disable_supplier(supplier_id: int, session: UserSession = Depends(get_current_session)):
    return data_response(deactivate_supplier(session, supplier_id))


@router.post("/suppliers/{supplier_id}/reactivate", tags=["suppliers"])
def enable_supplier(supplier_id: int, session: UserSession = Depends(get_current_session)):
    return data_response(reactivate_supplier(session, supplier_id))


@router.get("/purchase-orders", tags=["procurement"])
def list_purchase_orders(
    q: Optional[str] = None,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    session: UserSession = Depends(get_current_session),
):
    require_management(session)
    rows = search_purchase_orders(q, status_filter)
    allowed = accessible_store_ids(session)
    if allowed is not None:
        rows = [row for row in rows if row["store_id"] in allowed]
    return paginate(rows, page, per_page)


@router.post("/purchase-orders", status_code=status.HTTP_201_CREATED, tags=["procurement"])
def add_purchase_order(
    payload: PurchaseOrderCreateRequest,
    session: UserSession = Depends(get_current_session),
):
    return data_response(create_purchase_order(session, **payload.model_dump(mode="json", exclude_none=True)))


@router.get("/purchase-orders/{purchase_order_id}", tags=["procurement"])
def purchase_order_detail(
    purchase_order_id: int,
    session: UserSession = Depends(get_current_session),
):
    require_management(session)
    result = get_purchase_order(purchase_order_id)
    if not result:
        raise ValueError("Purchase order not found.")
    resolve_store_scope(session, result["purchase_order"]["store_id"], manage=True)
    return data_response(result)


@router.post("/purchase-orders/{purchase_order_id}/submit", tags=["procurement"])
def submit_order(purchase_order_id: int, session: UserSession = Depends(get_current_session)):
    return data_response(submit_purchase_order(session, purchase_order_id))


@router.post("/purchase-orders/{purchase_order_id}/cancel", tags=["procurement"])
def cancel_order(purchase_order_id: int, session: UserSession = Depends(get_current_session)):
    return data_response(cancel_purchase_order(session, purchase_order_id))


@router.post("/purchase-orders/{purchase_order_id}/receive", tags=["procurement"])
def receive_order(
    purchase_order_id: int,
    payload: ReceivePurchaseRequest,
    session: UserSession = Depends(get_current_session),
):
    return data_response(receive_purchase_order(
        session, purchase_order_id,
        [item.model_dump(exclude_none=True) for item in payload.line_items], payload.notes,
    ))


@router.get("/transfers", tags=["transfers"])
def list_transfers(
    q: Optional[str] = None,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    store_id: Optional[int] = Query(default=None, gt=0),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    session: UserSession = Depends(get_current_session),
):
    rows = search_transfers(session, q, status_filter, store_id)
    return paginate(rows, page, per_page)


@router.post("/transfers", status_code=status.HTTP_201_CREATED, tags=["transfers"])
def add_transfer(payload: TransferCreateRequest, session: UserSession = Depends(get_current_session)):
    return data_response(create_transfer(session, **payload.model_dump(exclude_none=True)))


@router.get("/transfers/{transfer_id}", tags=["transfers"])
def transfer_detail(transfer_id: int, session: UserSession = Depends(get_current_session)):
    require_management(session)
    result = get_transfer(transfer_id)
    if not result:
        raise ValueError("Transfer not found.")
    header = result["transfer"]
    allowed = accessible_store_ids(session)
    if allowed is not None and not ({header["source_store_id"], header["destination_store_id"]} & set(allowed)):
        from auth import AuthorizationError
        raise AuthorizationError("Transfer is outside this user's store access.")
    return data_response(result)


@router.post("/transfers/{transfer_id}/approve", tags=["transfers"])
def approve(transfer_id: int, session: UserSession = Depends(get_current_session)):
    return data_response(approve_transfer(session, transfer_id))


@router.post("/transfers/{transfer_id}/dispatch", tags=["transfers"])
def dispatch(
    transfer_id: int,
    payload: TransferActivityRequest,
    session: UserSession = Depends(get_current_session),
):
    return data_response(dispatch_transfer(
        session, transfer_id, [item.model_dump(exclude_none=True) for item in payload.line_items], payload.notes,
    ))


@router.post("/transfers/{transfer_id}/receive", tags=["transfers"])
def receive(
    transfer_id: int,
    payload: TransferActivityRequest,
    session: UserSession = Depends(get_current_session),
):
    return data_response(receive_transfer(
        session, transfer_id, [item.model_dump(exclude_none=True) for item in payload.line_items], payload.notes,
    ))


@router.post("/transfers/{transfer_id}/cancel", tags=["transfers"])
def cancel(
    transfer_id: int,
    payload: NotesRequest,
    session: UserSession = Depends(get_current_session),
):
    return data_response(cancel_transfer(session, transfer_id, payload.notes))
