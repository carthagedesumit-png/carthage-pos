"""Customer, loyalty, wallet, and credit API endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, Query, status

from auth import UserSession
from app.api.dependencies import get_current_session
from app.api.pagination import data_response, paginate
from app.api.schemas import (
    AdjustmentRequest,
    AmountRequest,
    CreditTermsRequest,
    CustomerCreateRequest,
    CustomerGroupRequest,
    CustomerUpdateRequest,
    LoyaltyAdjustmentRequest,
)
from app.customers.credit_service import (
    get_credit_outstanding,
    make_credit_payment,
    set_credit_terms,
)
from app.customers.customer_service import (
    create_customer,
    create_customer_group,
    deactivate_customer,
    get_customer_by_id,
    reactivate_customer,
    search_customer_groups,
    search_customers,
    update_customer,
    update_customer_group,
)
from app.customers.loyalty_service import (
    adjust_loyalty_points,
    get_loyalty_balance,
    redeem_loyalty_points,
)
from app.customers.wallet_service import (
    adjust_wallet,
    deposit_wallet,
    get_wallet_balance,
    withdraw_wallet,
)


router = APIRouter()


@router.get("/customers", tags=["customers"])
def list_customers(
    q: Optional[str] = None,
    include_inactive: bool = False,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    session: UserSession = Depends(get_current_session),
):
    return paginate(search_customers(session, q, include_inactive), page, per_page)


@router.post("/customers", status_code=status.HTTP_201_CREATED, tags=["customers"])
def add_customer(payload: CustomerCreateRequest, session: UserSession = Depends(get_current_session)):
    return data_response(create_customer(session, **payload.model_dump(mode="json")))


@router.get("/customers/{customer_id}", tags=["customers"])
def customer_detail(customer_id: int, session: UserSession = Depends(get_current_session)):
    search_customers(session)
    customer = get_customer_by_id(customer_id)
    if not customer:
        raise ValueError("Customer not found.")
    return data_response(customer)


@router.patch("/customers/{customer_id}", tags=["customers"])
def edit_customer(
    customer_id: int,
    payload: CustomerUpdateRequest,
    session: UserSession = Depends(get_current_session),
):
    return data_response(update_customer(
        session, customer_id, **payload.model_dump(mode="json", exclude_unset=True)
    ))


@router.post("/customers/{customer_id}/deactivate", tags=["customers"])
def disable_customer(customer_id: int, session: UserSession = Depends(get_current_session)):
    return data_response(deactivate_customer(session, customer_id))


@router.post("/customers/{customer_id}/reactivate", tags=["customers"])
def enable_customer(customer_id: int, session: UserSession = Depends(get_current_session)):
    return data_response(reactivate_customer(session, customer_id))


@router.get("/customer-groups", tags=["customers"])
def list_customer_groups(
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    session: UserSession = Depends(get_current_session),
):
    return paginate(search_customer_groups(session, q), page, per_page)


@router.post("/customer-groups", status_code=status.HTTP_201_CREATED, tags=["customers"])
def add_customer_group(
    payload: CustomerGroupRequest,
    session: UserSession = Depends(get_current_session),
):
    return data_response(create_customer_group(session, **payload.model_dump()))


@router.patch("/customer-groups/{group_id}", tags=["customers"])
def edit_customer_group(
    group_id: int,
    payload: CustomerGroupRequest,
    session: UserSession = Depends(get_current_session),
):
    return data_response(update_customer_group(session, group_id, **payload.model_dump()))


@router.get("/customers/{customer_id}/loyalty", tags=["loyalty"])
def loyalty_balance(customer_id: int, _session: UserSession = Depends(get_current_session)):
    return data_response({"customer_id": customer_id, "balance": get_loyalty_balance(customer_id)})


@router.post("/customers/{customer_id}/loyalty/adjust", tags=["loyalty"])
def change_loyalty(
    customer_id: int,
    payload: LoyaltyAdjustmentRequest,
    session: UserSession = Depends(get_current_session),
):
    return data_response(adjust_loyalty_points(session, customer_id, payload.points, payload.notes))


@router.post("/customers/{customer_id}/loyalty/redeem", tags=["loyalty"])
def redeem_loyalty(
    customer_id: int,
    payload: LoyaltyAdjustmentRequest,
    session: UserSession = Depends(get_current_session),
):
    return data_response(redeem_loyalty_points(session, customer_id, payload.points, payload.notes))


@router.get("/customers/{customer_id}/wallet", tags=["wallet"])
def wallet_balance(customer_id: int, _session: UserSession = Depends(get_current_session)):
    return data_response({"customer_id": customer_id, "balance": get_wallet_balance(customer_id)})


@router.post("/customers/{customer_id}/wallet/deposit", tags=["wallet"])
def wallet_deposit(
    customer_id: int,
    payload: AmountRequest,
    session: UserSession = Depends(get_current_session),
):
    return data_response(deposit_wallet(session, customer_id, payload.amount, payload.notes))


@router.post("/customers/{customer_id}/wallet/withdraw", tags=["wallet"])
def wallet_withdraw(
    customer_id: int,
    payload: AmountRequest,
    session: UserSession = Depends(get_current_session),
):
    return data_response(withdraw_wallet(session, customer_id, payload.amount, payload.notes))


@router.post("/customers/{customer_id}/wallet/adjust", tags=["wallet"])
def wallet_adjust(
    customer_id: int,
    payload: AdjustmentRequest,
    session: UserSession = Depends(get_current_session),
):
    return data_response(adjust_wallet(session, customer_id, payload.amount_delta, payload.notes))


@router.get("/customers/{customer_id}/credit", tags=["credit"])
def credit_balance(customer_id: int, _session: UserSession = Depends(get_current_session)):
    return data_response({"customer_id": customer_id, "outstanding": get_credit_outstanding(customer_id)})


@router.put("/customers/{customer_id}/credit/terms", tags=["credit"])
def credit_terms(
    customer_id: int,
    payload: CreditTermsRequest,
    session: UserSession = Depends(get_current_session),
):
    return data_response(set_credit_terms(
        session, customer_id, payload.credit_limit,
        payload.due_date.isoformat() if payload.due_date else None,
    ))


@router.post("/customers/{customer_id}/credit/payments", tags=["credit"])
def credit_payment(
    customer_id: int,
    payload: AmountRequest,
    session: UserSession = Depends(get_current_session),
):
    return data_response(make_credit_payment(session, customer_id, payload.amount, payload.notes))
