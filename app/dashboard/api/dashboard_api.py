from fastapi import APIRouter

from app.dashboard.charts.chart_service import sales_last_30_days
from app.dashboard.widgets.recent_sales import recent_sales
from app.dashboard.widgets.top_products import top_products
from app.dashboard.widgets.low_stock import low_stock

router = APIRouter(prefix="/dashboard/api", tags=["Dashboard API"])


@router.get("/sales-chart")
def sales_chart():
    return sales_last_30_days()


@router.get("/recent-sales")
def recent():
    return recent_sales()


@router.get("/top-products")
def products():
    return top_products()


@router.get("/low-stock")
def stock():
    return low_stock()
