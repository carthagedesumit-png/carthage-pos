"""Authentication, users, stores, products, and inventory endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, Query, status

from auth import (
    UserSession,
    change_password,
    create_user,
    deactivate_user,
    get_user_by_id,
    reactivate_user,
    search_users,
)
from app.api.dependencies import (
    accessible_store_ids,
    get_bearer_token,
    get_current_session,
    resolve_store_scope,
)
from app.api.pagination import data_response, paginate
from app.api.schemas import (
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    ProductCreateRequest,
    ProductUpdateRequest,
    StockAdjustmentRequest,
    StockReceiveRequest,
    StoreCreateRequest,
    StoreSwitchRequest,
    StoreUpdateRequest,
    SessionResponse,
    UserCreateRequest,
)
from app.api.session_service import (
    change_session_store,
    issue_session,
    revoke_session,
    session_to_dict,
)
from app.inventory.inventory_service import (
    adjust_stock,
    create_product,
    get_low_stock_products,
    get_product_by_id,
    receive_stock,
    search_products,
    update_product,
)
from app.stores.store_service import (
    create_store,
    deactivate_store,
    get_store_by_id,
    reactivate_store,
    search_stores,
    update_store,
)


router = APIRouter()


@router.post("/auth/login", tags=["authentication"], response_model=LoginResponse)
def login(payload: LoginRequest):
    return data_response(issue_session(payload.username, payload.password, payload.store_id))


@router.post("/auth/logout", tags=["authentication"])
def logout(
    token: str = Depends(get_bearer_token),
    _session: UserSession = Depends(get_current_session),
):
    revoke_session(token)
    return data_response({"logged_out": True})


@router.get("/auth/me", tags=["authentication"], response_model=SessionResponse)
def current_user(session: UserSession = Depends(get_current_session)):
    return data_response(session_to_dict(session))


@router.post("/auth/switch-store", tags=["authentication"], response_model=SessionResponse)
def select_store(
    payload: StoreSwitchRequest,
    token: str = Depends(get_bearer_token),
    _session: UserSession = Depends(get_current_session),
):
    return data_response(session_to_dict(change_session_store(token, payload.store_id)))


@router.get("/users", tags=["users"])
def list_users(
    q: Optional[str] = None,
    include_inactive: bool = False,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    session: UserSession = Depends(get_current_session),
):
    return paginate(search_users(session, q, include_inactive), page, per_page)


@router.post("/users", status_code=status.HTTP_201_CREATED, tags=["users"])
def add_user(payload: UserCreateRequest, session: UserSession = Depends(get_current_session)):
    return data_response(create_user(**payload.model_dump(), acting_session=session))


@router.get("/users/{user_id}", tags=["users"])
def user_detail(user_id: int, session: UserSession = Depends(get_current_session)):
    search_users(session)
    user = get_user_by_id(user_id)
    if not user:
        raise ValueError("User not found.")
    return data_response(user)


@router.post("/users/{user_id}/password", tags=["users"])
def set_password(
    user_id: int,
    payload: PasswordChangeRequest,
    session: UserSession = Depends(get_current_session),
):
    change_password(user_id, payload.new_password, acting_session=session)
    return data_response({"password_changed": True})


@router.post("/users/{user_id}/deactivate", tags=["users"])
def disable_user(user_id: int, session: UserSession = Depends(get_current_session)):
    deactivate_user(user_id, acting_session=session)
    return data_response(get_user_by_id(user_id))


@router.post("/users/{user_id}/reactivate", tags=["users"])
def enable_user(user_id: int, session: UserSession = Depends(get_current_session)):
    reactivate_user(user_id, acting_session=session)
    return data_response(get_user_by_id(user_id))


@router.get("/stores", tags=["stores"])
def list_stores(
    q: Optional[str] = None,
    include_inactive: bool = False,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    session: UserSession = Depends(get_current_session),
):
    stores = search_stores(q, include_inactive)
    allowed = accessible_store_ids(session)
    if allowed is not None:
        stores = [store for store in stores if store["id"] in allowed]
    return paginate(stores, page, per_page)


@router.post("/stores", status_code=status.HTTP_201_CREATED, tags=["stores"])
def add_store(payload: StoreCreateRequest, session: UserSession = Depends(get_current_session)):
    return data_response(create_store(session, **payload.model_dump()))


@router.get("/stores/{store_id}", tags=["stores"])
def store_detail(store_id: int, session: UserSession = Depends(get_current_session)):
    resolve_store_scope(session, store_id)
    store = get_store_by_id(store_id)
    if not store:
        raise ValueError("Store not found.")
    return data_response(store)


@router.patch("/stores/{store_id}", tags=["stores"])
def edit_store(
    store_id: int,
    payload: StoreUpdateRequest,
    session: UserSession = Depends(get_current_session),
):
    return data_response(update_store(session, store_id, **payload.model_dump(exclude_unset=True)))


@router.post("/stores/{store_id}/deactivate", tags=["stores"])
def disable_store(store_id: int, session: UserSession = Depends(get_current_session)):
    return data_response(deactivate_store(session, store_id))


@router.post("/stores/{store_id}/reactivate", tags=["stores"])
def enable_store(store_id: int, session: UserSession = Depends(get_current_session)):
    return data_response(reactivate_store(session, store_id))


@router.get("/products", tags=["products"])
def list_products(
    q: Optional[str] = None,
    include_inactive: bool = False,
    store_id: Optional[int] = Query(default=None, gt=0),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    session: UserSession = Depends(get_current_session),
):
    selected = resolve_store_scope(session, store_id)
    return paginate(search_products(q, include_inactive, selected), page, per_page)


@router.post("/products", status_code=status.HTTP_201_CREATED, tags=["products"])
def add_product(payload: ProductCreateRequest, session: UserSession = Depends(get_current_session)):
    return data_response(create_product(session, **payload.model_dump(exclude_none=True)))


@router.get("/products/{product_id}", tags=["products"])
def product_detail(
    product_id: int,
    store_id: Optional[int] = Query(default=None, gt=0),
    session: UserSession = Depends(get_current_session),
):
    selected = resolve_store_scope(session, store_id)
    product = get_product_by_id(product_id, store_id=selected)
    if not product:
        raise ValueError("Product not found.")
    return data_response(product)


@router.patch("/products/{product_id}", tags=["products"])
def edit_product(
    product_id: int,
    payload: ProductUpdateRequest,
    store_id: Optional[int] = Query(default=None, gt=0),
    session: UserSession = Depends(get_current_session),
):
    selected = resolve_store_scope(session, store_id, manage=True)
    return data_response(update_product(session, product_id, store_id=selected, **payload.model_dump(exclude_unset=True)))


@router.get("/inventory/low-stock", tags=["inventory"])
def low_stock(
    store_id: Optional[int] = Query(default=None, gt=0),
    limit: Optional[int] = Query(default=None, gt=0),
    session: UserSession = Depends(get_current_session),
):
    selected = resolve_store_scope(session, store_id)
    return data_response(get_low_stock_products(limit=limit, store_id=selected))


@router.post("/inventory/{product_id}/adjust", tags=["inventory"])
def change_stock(
    product_id: int,
    payload: StockAdjustmentRequest,
    session: UserSession = Depends(get_current_session),
):
    selected = resolve_store_scope(session, payload.store_id, manage=True)
    return data_response(adjust_stock(session, product_id, payload.new_quantity, payload.notes, selected))


@router.post("/inventory/{product_id}/receive", tags=["inventory"])
def receive_inventory(
    product_id: int,
    payload: StockReceiveRequest,
    session: UserSession = Depends(get_current_session),
):
    selected = resolve_store_scope(session, payload.store_id, manage=True)
    return data_response(receive_stock(session, product_id, payload.quantity, payload.notes, selected))
