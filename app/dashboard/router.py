from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.dashboard.services.dashboard_service import get_dashboard_summary

templates = Jinja2Templates(directory="app/dashboard/templates")

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def get_header():
    return {
        "user": "Administrator",
        "store": "Main Store",
    }


def render_workspace(
    request: Request,
    *,
    active_page: str,
    page_title: str,
    page_subtitle: str,
    cards: list[dict],
    main_panel_title: str,
    main_panel_text: str,
    steps: list[dict],
):
    return templates.TemplateResponse(
        "workspace.html",
        {
            "request": request,
            "title": f"{page_title} - Carthage POS",
            "header": get_header(),
            "active_page": active_page,
            "page_title": page_title,
            "page_subtitle": page_subtitle,
            "cards": cards,
            "main_panel_title": main_panel_title,
            "main_panel_text": main_panel_text,
            "steps": steps,
        },
    )


@router.get("/", response_class=HTMLResponse)
def dashboard_home(request: Request):
    return templates.TemplateResponse(
        "overview.html",
        {
            "request": request,
            "title": "Carthage POS Executive Dashboard",
            "metrics": get_dashboard_summary(),
            "header": get_header(),
            "active_page": "dashboard",
        },
    )


@router.get("/sales", response_class=HTMLResponse)
def dashboard_sales(request: Request):
    return render_workspace(
        request,
        active_page="sales",
        page_title="Sales Workspace",
        page_subtitle="Monitor transactions, returns, payments, receipts, and sales performance.",
        cards=[
            {"label": "Today Sales", "value": get_dashboard_summary()["today_sales"]},
            {"label": "Transactions", "value": get_dashboard_summary()["transactions"]},
            {"label": "Refunds", "value": "0"},
        ],
        main_panel_title="Sales Operations",
        main_panel_text="Sales order review, returns, payment summaries, and receipt actions will live here.",
        steps=[
            {"title": "Recent sales", "text": "Connect full sales table with filtering."},
            {"title": "Returns", "text": "Add refund and credit note review workflow."},
            {"title": "Payments", "text": "Add payment method breakdown."},
        ],
    )


@router.get("/inventory", response_class=HTMLResponse)
def dashboard_inventory(request: Request):
    summary = get_dashboard_summary()
    return render_workspace(
        request,
        active_page="inventory",
        page_title="Inventory Workspace",
        page_subtitle="Manage products, stock levels, valuation, barcode labels, and transfers.",
        cards=[
            {"label": "Inventory Value", "value": summary["inventory_value"]},
            {"label": "Low Stock", "value": summary["low_stock"]},
            {"label": "Stores", "value": summary["stores"]},
        ],
        main_panel_title="Inventory Control",
        main_panel_text="Product lists, store stock, low-stock alerts, valuation, barcode and label workflows will live here.",
        steps=[
            {"title": "Products", "text": "Add product browser and filters."},
            {"title": "Barcode labels", "text": "Add label preview and print actions."},
            {"title": "Transfers", "text": "Add inter-store transfer status table."},
        ],
    )


@router.get("/customers", response_class=HTMLResponse)
def dashboard_customers(request: Request):
    summary = get_dashboard_summary()
    return render_workspace(
        request,
        active_page="customers",
        page_title="Customer Workspace",
        page_subtitle="Manage customers, loyalty, wallet balances, and credit accounts.",
        cards=[
            {"label": "Customers", "value": summary["customers"]},
            {"label": "Outstanding Credit", "value": summary["outstanding_credit"]},
            {"label": "Loyalty Status", "value": "Active"},
        ],
        main_panel_title="Customer Relationship Management",
        main_panel_text="Customer profiles, purchase history, loyalty, wallet and credit management will live here.",
        steps=[
            {"title": "Customer list", "text": "Add searchable customer table."},
            {"title": "Credit accounts", "text": "Add outstanding credit review."},
            {"title": "Loyalty", "text": "Add loyalty point activity."},
        ],
    )


@router.get("/procurement", response_class=HTMLResponse)
def dashboard_procurement(request: Request):
    return render_workspace(
        request,
        active_page="procurement",
        page_title="Procurement Workspace",
        page_subtitle="Track suppliers, purchase orders, receipts, and replenishment.",
        cards=[
            {"label": "Pending POs", "value": "0"},
            {"label": "Suppliers", "value": "0"},
            {"label": "Awaiting Receipt", "value": "0"},
        ],
        main_panel_title="Procurement Control",
        main_panel_text="Purchase order tracking, supplier performance, and receiving workflows will live here.",
        steps=[
            {"title": "Purchase orders", "text": "Add PO list and status filtering."},
            {"title": "Receiving", "text": "Add goods received review."},
            {"title": "Suppliers", "text": "Add supplier activity dashboard."},
        ],
    )


@router.get("/reports", response_class=HTMLResponse)
def dashboard_reports(request: Request):
    return render_workspace(
        request,
        active_page="reports",
        page_title="Reports Workspace",
        page_subtitle="Access business intelligence, analytics, exports, and scheduled reports.",
        cards=[
            {"label": "Sales Reports", "value": "Ready"},
            {"label": "Inventory Reports", "value": "Ready"},
            {"label": "Customer Reports", "value": "Ready"},
        ],
        main_panel_title="Analytics Center",
        main_panel_text="Sales trends, profit analytics, store comparisons, inventory valuation and export tools will live here.",
        steps=[
            {"title": "Charts", "text": "Add interactive reporting charts."},
            {"title": "Exports", "text": "Add CSV/Excel/PDF export actions."},
            {"title": "Scheduled reports", "text": "Add schedule foundation."},
        ],
    )


@router.get("/system", response_class=HTMLResponse)
def dashboard_system(request: Request):
    summary = get_dashboard_summary()
    return render_workspace(
        request,
        active_page="system",
        page_title="System Workspace",
        page_subtitle="Monitor licensing, backups, deployment, API health, and hardware.",
        cards=[
            {"label": "API", "value": summary["api_status"]},
            {"label": "License", "value": summary["license_status"]},
            {"label": "Backup", "value": summary["backup_status"]},
        ],
        main_panel_title="System Administration",
        main_panel_text="Licensing, backup, deployment, updates, hardware and configuration controls will live here.",
        steps=[
            {"title": "Licensing", "text": "Add license status and activation management."},
            {"title": "Backups", "text": "Add backup verification and restore actions."},
            {"title": "Hardware", "text": "Add printer, scanner and drawer status."},
        ],
    )


@router.get("/api/summary")
def dashboard_summary():
    return get_dashboard_summary()


@router.get("/health")
def dashboard_health():
    return {"status": "ok", "module": "dashboard"}


@router.get("/login", response_class=HTMLResponse)
def dashboard_login(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "title": "Dashboard Login",
            "header": {"user": "Guest", "store": ""},
        },
    )


from app.dashboard.services.bi_service import sales_trend, top_products, business_insights


@router.get("/api/sales-trend")
def dashboard_sales_trend():
    return {"trend": sales_trend()}


@router.get("/api/top-products")
def dashboard_top_products():
    return {"products": top_products()}


@router.get("/api/insights")
def dashboard_insights():
    return {"insights": business_insights()}
