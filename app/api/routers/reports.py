"""Store-aware analytics endpoints."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query

from auth import UserSession
from app.api.dependencies import get_current_session
from app.api.pagination import data_response, paginate
from app.reports.reporting_service import (
    get_branch_comparison_report,
    get_cashier_performance_report,
    get_customer_lifetime_value,
    get_customer_purchase_history,
    get_daily_sales_report,
    get_date_range_sales_report,
    get_inventory_valuation,
    get_loyalty_liability_report,
    get_most_loyal_customers,
    get_outstanding_credit_report,
    get_sales_summary,
    get_top_customers,
    get_wallet_balances_report,
)


router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/sales-summary")
def sales_summary(
    store_ids: Optional[list[int]] = Query(default=None, alias="store_id"),
    session: UserSession = Depends(get_current_session),
):
    return data_response(get_sales_summary(store_ids=store_ids, session=session))


@router.get("/daily-sales")
def daily_sales(
    report_date: Optional[date] = None,
    top_limit: int = Query(10, ge=1, le=100),
    store_ids: Optional[list[int]] = Query(default=None, alias="store_id"),
    session: UserSession = Depends(get_current_session),
):
    return data_response(get_daily_sales_report(
        report_date, top_limit=top_limit, store_ids=store_ids, session=session
    ))


@router.get("/date-range-sales")
def date_range_sales(
    start_date: date,
    end_date: date,
    top_limit: int = Query(10, ge=1, le=100),
    store_ids: Optional[list[int]] = Query(default=None, alias="store_id"),
    session: UserSession = Depends(get_current_session),
):
    return data_response(get_date_range_sales_report(
        start_date, end_date, top_limit=top_limit, store_ids=store_ids, session=session
    ))


@router.get("/inventory-valuation")
def inventory_valuation(
    store_ids: Optional[list[int]] = Query(default=None, alias="store_id"),
    session: UserSession = Depends(get_current_session),
):
    return data_response(get_inventory_valuation(store_ids=store_ids, session=session))


@router.get("/cashier-performance")
def cashier_performance(
    store_ids: Optional[list[int]] = Query(default=None, alias="store_id"),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    session: UserSession = Depends(get_current_session),
):
    return paginate(get_cashier_performance_report(store_ids=store_ids, session=session), page, per_page)


@router.get("/store-comparison")
def store_comparison(
    store_ids: Optional[list[int]] = Query(default=None, alias="store_id"),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    session: UserSession = Depends(get_current_session),
):
    return paginate(get_branch_comparison_report(store_ids=store_ids, session=session), page, per_page)


@router.get("/customers/top")
def top_customers(
    limit: int = Query(10, ge=1, le=100),
    store_ids: Optional[list[int]] = Query(default=None, alias="store_id"),
    session: UserSession = Depends(get_current_session),
):
    return data_response(get_top_customers(limit, store_ids=store_ids, session=session))


@router.get("/customers/loyal")
def loyal_customers(
    limit: int = Query(10, ge=1, le=100),
    store_ids: Optional[list[int]] = Query(default=None, alias="store_id"),
    session: UserSession = Depends(get_current_session),
):
    return data_response(get_most_loyal_customers(limit, store_ids=store_ids, session=session))


@router.get("/customers/{customer_id}/history")
def customer_history(
    customer_id: int,
    store_ids: Optional[list[int]] = Query(default=None, alias="store_id"),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    session: UserSession = Depends(get_current_session),
):
    rows = get_customer_purchase_history(customer_id, store_ids=store_ids, session=session)
    return paginate(rows, page, per_page)


@router.get("/customers/{customer_id}/lifetime-value")
def customer_lifetime_value(
    customer_id: int,
    store_ids: Optional[list[int]] = Query(default=None, alias="store_id"),
    session: UserSession = Depends(get_current_session),
):
    return data_response(get_customer_lifetime_value(customer_id, store_ids=store_ids, session=session))


@router.get("/outstanding-credit")
def outstanding_credit(
    store_ids: Optional[list[int]] = Query(default=None, alias="store_id"),
    session: UserSession = Depends(get_current_session),
):
    return data_response(get_outstanding_credit_report(store_ids=store_ids, session=session))


@router.get("/wallet-balances")
def wallet_balances(
    store_ids: Optional[list[int]] = Query(default=None, alias="store_id"),
    session: UserSession = Depends(get_current_session),
):
    return data_response(get_wallet_balances_report(store_ids=store_ids, session=session))


@router.get("/loyalty-liabilities")
def loyalty_liabilities(
    store_ids: Optional[list[int]] = Query(default=None, alias="store_id"),
    session: UserSession = Depends(get_current_session),
):
    return data_response(get_loyalty_liability_report(store_ids=store_ids, session=session))
