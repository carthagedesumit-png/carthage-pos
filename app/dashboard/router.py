from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.dashboard.services.dashboard_service import (
    get_dashboard_crm_summary,
    get_dashboard_customer_activity,
    get_dashboard_customer_detail,
    get_dashboard_inventory_summary,
    get_dashboard_inventory_valuation,
    get_dashboard_low_stock_inventory,
    get_dashboard_product_detail,
    get_dashboard_procurement_activity,
    get_dashboard_procurement_summary,
    get_dashboard_purchase_order_detail,
    get_dashboard_sale_detail,
    get_dashboard_sales_summary,
    get_dashboard_summary,
    get_dashboard_supplier_detail,
    get_dashboard_top_customers,
    list_dashboard_customers,
    list_dashboard_inventory,
    list_dashboard_procurement,
    list_dashboard_sales,
    list_dashboard_suppliers,
)
from app.dashboard.services.report_service import (
    REPORT_TYPES,
    get_dashboard_report_cashiers,
    get_dashboard_report_customers,
    get_dashboard_report_export_placeholder,
    get_dashboard_report_inventory,
    get_dashboard_report_procurement,
    get_dashboard_report_products,
    get_dashboard_report_refunds,
    get_dashboard_report_sales,
    get_dashboard_report_stores,
    get_dashboard_reports_summary,
)

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
def dashboard_sales(
    request: Request,
    date_from: str = "",
    date_to: str = "",
    store_id: int | None = Query(default=None),
    cashier_id: int | None = Query(default=None),
    customer_id: int | None = Query(default=None),
    payment_method: str = "",
    search: str = "",
    refunded: str = "all",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
):
    result = list_dashboard_sales(
        {
            "date_from": date_from,
            "date_to": date_to,
            "store_id": store_id,
            "cashier_id": cashier_id,
            "customer_id": customer_id,
            "payment_method": payment_method,
            "search": search,
            "refunded": refunded,
            "page": page,
            "page_size": page_size,
        }
    )
    return templates.TemplateResponse(
        "sales.html",
        {
            "request": request,
            "title": "Sales Workspace - Carthage POS",
            "header": get_header(),
            "active_page": "sales",
            "page_title": "Sales Workspace",
            "page_subtitle": "Review sales, payments, refunds, receipts, and store performance.",
            "sales": result["items"],
            "summary": result["summary"],
            "filters": result["filters"],
            "pagination": result["pagination"],
            "payment_methods": ["", "CASH", "CARD", "TRANSFER", "WALLET", "CREDIT", "MIXED"],
            "refund_filters": ["all", "refunded", "non-refunded"],
        },
    )


@router.get("/sales/{sale_id}", response_class=HTMLResponse)
def dashboard_sale_detail(request: Request, sale_id: int):
    detail = get_dashboard_sale_detail(sale_id)
    if not detail:
        return templates.TemplateResponse(
            "sale_detail.html",
            {
                "request": request,
                "title": "Sale Not Found - Carthage POS",
                "header": get_header(),
                "active_page": "sales",
                "detail": None,
                "sale_id": sale_id,
            },
            status_code=404,
        )
    return templates.TemplateResponse(
        "sale_detail.html",
        {
            "request": request,
            "title": f"Sale {detail['sale']['receipt_number']} - Carthage POS",
            "header": get_header(),
            "active_page": "sales",
            "detail": detail,
            "sale_id": sale_id,
        },
    )


@router.get("/inventory", response_class=HTMLResponse)
def dashboard_inventory(
    request: Request,
    search: str = "",
    store_id: int | None = Query(default=None),
    category_id: int | None = Query(default=None),
    supplier_id: int | None = Query(default=None),
    low_stock: bool = False,
    out_of_stock: bool = False,
    active: str = "active",
    has_barcode: str = "all",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
):
    result = list_dashboard_inventory(
        {
            "search": search,
            "store_id": store_id,
            "category_id": category_id,
            "supplier_id": supplier_id,
            "low_stock": low_stock,
            "out_of_stock": out_of_stock,
            "active": active,
            "has_barcode": has_barcode,
            "page": page,
            "page_size": page_size,
        }
    )
    return templates.TemplateResponse(
        "inventory.html",
        {
            "request": request,
            "title": "Inventory Workspace - Carthage Business Operating System",
            "header": get_header(),
            "active_page": "inventory",
            "page_title": "Inventory Workspace",
            "page_subtitle": "Manage products, store stock, valuation, barcodes, and label readiness.",
            "products": result["items"],
            "summary": result["summary"],
            "filters": result["filters"],
            "pagination": result["pagination"],
            "active_filters": ["active", "inactive", "all"],
            "barcode_filters": ["all", "has", "missing"],
        },
    )


@router.get("/inventory/products/{product_id}", response_class=HTMLResponse)
def dashboard_product_detail(request: Request, product_id: int):
    detail = get_dashboard_product_detail(product_id)
    if not detail:
        return templates.TemplateResponse(
            "product_detail.html",
            {
                "request": request,
                "title": "Product Not Found - Carthage Business Operating System",
                "header": get_header(),
                "active_page": "inventory",
                "detail": None,
                "product_id": product_id,
            },
            status_code=404,
        )
    return templates.TemplateResponse(
        "product_detail.html",
        {
            "request": request,
            "title": f"{detail['product']['name']} - Carthage Business Operating System",
            "header": get_header(),
            "active_page": "inventory",
            "detail": detail,
            "product_id": product_id,
        },
    )


@router.get("/customers", response_class=HTMLResponse)
def dashboard_customers(
    request: Request,
    search: str = "",
    customer_group: str = "",
    active: str = "active",
    has_credit: bool = False,
    has_wallet_balance: bool = False,
    loyalty_customer: bool = False,
    joined_from: str = "",
    joined_to: str = "",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
):
    result = list_dashboard_customers(
        {
            "search": search,
            "customer_group": customer_group,
            "active": active,
            "has_credit": has_credit,
            "has_wallet_balance": has_wallet_balance,
            "loyalty_customer": loyalty_customer,
            "joined_from": joined_from,
            "joined_to": joined_to,
            "page": page,
            "page_size": page_size,
        }
    )
    return templates.TemplateResponse(
        "customers.html",
        {
            "request": request,
            "title": "CRM Workspace - Carthage Business Operating System",
            "header": get_header(),
            "active_page": "customers",
            "page_title": "CRM Workspace",
            "page_subtitle": "Review customers, loyalty, wallets, credit exposure, and purchase activity.",
            "customers": result["items"],
            "summary": result["summary"],
            "filters": result["filters"],
            "pagination": result["pagination"],
            "active_filters": ["active", "inactive", "all"],
        },
    )


@router.get("/customers/{customer_id}", response_class=HTMLResponse)
def dashboard_customer_detail(request: Request, customer_id: int):
    detail = get_dashboard_customer_detail(customer_id)
    if not detail:
        return templates.TemplateResponse(
            "customer_detail.html",
            {
                "request": request,
                "title": "Customer Not Found - Carthage Business Operating System",
                "header": get_header(),
                "active_page": "customers",
                "detail": None,
                "customer_id": customer_id,
            },
            status_code=404,
        )
    return templates.TemplateResponse(
        "customer_detail.html",
        {
            "request": request,
            "title": f"{detail['customer']['name']} - Carthage Business Operating System",
            "header": get_header(),
            "active_page": "customers",
            "detail": detail,
            "customer_id": customer_id,
        },
    )


@router.get("/procurement", response_class=HTMLResponse)
def dashboard_procurement(
    request: Request,
    search: str = "",
    supplier_id: int | None = Query(default=None),
    store_id: int | None = Query(default=None),
    status: str = "",
    date_from: str = "",
    date_to: str = "",
    pending_only: bool = False,
    partially_received: bool = False,
    completed: bool = False,
    cancelled: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
):
    result = list_dashboard_procurement(
        {
            "search": search,
            "supplier_id": supplier_id,
            "store_id": store_id,
            "status": status,
            "date_from": date_from,
            "date_to": date_to,
            "pending_only": pending_only,
            "partially_received": partially_received,
            "completed": completed,
            "cancelled": cancelled,
            "page": page,
            "page_size": page_size,
        }
    )
    return templates.TemplateResponse(
        "procurement.html",
        {
            "request": request,
            "title": "Procurement Workspace - Carthage Business Operating System",
            "header": get_header(),
            "active_page": "procurement",
            "page_title": "Procurement Workspace",
            "page_subtitle": "Review suppliers, purchase orders, receiving progress, and replenishment exposure.",
            "purchase_orders": result["items"],
            "summary": result["summary"],
            "filters": result["filters"],
            "pagination": result["pagination"],
            "status_filters": ["", "DRAFT", "SUBMITTED", "PARTIALLY_RECEIVED", "FULLY_RECEIVED", "CANCELLED"],
        },
    )


@router.get("/procurement/purchase-orders/{purchase_order_id}", response_class=HTMLResponse)
def dashboard_purchase_order_detail(request: Request, purchase_order_id: int):
    detail = get_dashboard_purchase_order_detail(purchase_order_id)
    if not detail:
        return templates.TemplateResponse(
            "purchase_order_detail.html",
            {
                "request": request,
                "title": "Purchase Order Not Found - Carthage Business Operating System",
                "header": get_header(),
                "active_page": "procurement",
                "detail": None,
                "purchase_order_id": purchase_order_id,
            },
            status_code=404,
        )
    return templates.TemplateResponse(
        "purchase_order_detail.html",
        {
            "request": request,
            "title": f"{detail['purchase_order']['reference_number']} - Carthage Business Operating System",
            "header": get_header(),
            "active_page": "procurement",
            "detail": detail,
            "purchase_order_id": purchase_order_id,
        },
    )


@router.get("/procurement/suppliers/{supplier_id}", response_class=HTMLResponse)
def dashboard_supplier_detail(request: Request, supplier_id: int):
    detail = get_dashboard_supplier_detail(supplier_id)
    if not detail:
        return templates.TemplateResponse(
            "supplier_detail.html",
            {
                "request": request,
                "title": "Supplier Not Found - Carthage Business Operating System",
                "header": get_header(),
                "active_page": "procurement",
                "detail": None,
                "supplier_id": supplier_id,
            },
            status_code=404,
        )
    return templates.TemplateResponse(
        "supplier_detail.html",
        {
            "request": request,
            "title": f"{detail['supplier']['name']} - Carthage Business Operating System",
            "header": get_header(),
            "active_page": "procurement",
            "detail": detail,
            "supplier_id": supplier_id,
        },
    )


def report_filter_payload(
    date_from: str = "",
    date_to: str = "",
    store_id: int | None = None,
    cashier_id: int | None = None,
    customer_id: int | None = None,
    product_id: int | None = None,
    category_id: int | None = None,
    supplier_id: int | None = None,
    report_type: str = "overview",
):
    return {
        "date_from": date_from,
        "date_to": date_to,
        "store_id": store_id,
        "cashier_id": cashier_id,
        "customer_id": customer_id,
        "product_id": product_id,
        "category_id": category_id,
        "supplier_id": supplier_id,
        "report_type": report_type,
    }


@router.get("/reports", response_class=HTMLResponse)
def dashboard_reports(
    request: Request,
    date_from: str = "",
    date_to: str = "",
    store_id: int | None = Query(default=None),
    cashier_id: int | None = Query(default=None),
    customer_id: int | None = Query(default=None),
    product_id: int | None = Query(default=None),
    category_id: int | None = Query(default=None),
    supplier_id: int | None = Query(default=None),
    report_type: str = "overview",
):
    result = get_dashboard_reports_summary(
        report_filter_payload(
            date_from, date_to, store_id, cashier_id, customer_id,
            product_id, category_id, supplier_id, report_type,
        )
    )
    return templates.TemplateResponse(
        "reports.html",
        {
            "request": request,
            "title": "Reports Workspace - Carthage Business Operating System",
            "header": get_header(),
            "active_page": "reports",
            "page_title": "Reports & Analytics Workspace",
            "page_subtitle": "Executive intelligence across sales, profit, inventory, customers, stores, procurement, and refunds.",
            "report": result,
            "filters": result["filters"],
            "report_types": REPORT_TYPES,
        },
    )


@router.get("/reports/sales", response_class=HTMLResponse)
def dashboard_reports_sales(request: Request, date_from: str = "", date_to: str = "", store_id: int | None = Query(default=None), cashier_id: int | None = Query(default=None), customer_id: int | None = Query(default=None)):
    filters = report_filter_payload(date_from, date_to, store_id, cashier_id, customer_id, None, None, None, "sales")
    return templates.TemplateResponse("report_detail.html", {"request": request, "title": "Sales Reports - Carthage Business Operating System", "header": get_header(), "active_page": "reports", "section": "sales", "page_title": "Sales Reports", "page_subtitle": "Sales, refunds, discounts, profit, average transaction value, and top product trends.", "filters": get_dashboard_report_sales(filters)["filters"], "report": get_dashboard_report_sales(filters), "report_types": REPORT_TYPES})


@router.get("/reports/inventory", response_class=HTMLResponse)
def dashboard_reports_inventory(request: Request, store_id: int | None = Query(default=None), product_id: int | None = Query(default=None), category_id: int | None = Query(default=None), supplier_id: int | None = Query(default=None)):
    filters = report_filter_payload("", "", store_id, None, None, product_id, category_id, supplier_id, "inventory")
    report = get_dashboard_report_inventory(filters)
    return templates.TemplateResponse("report_detail.html", {"request": request, "title": "Inventory Reports - Carthage Business Operating System", "header": get_header(), "active_page": "reports", "section": "inventory", "page_title": "Inventory Reports", "page_subtitle": "Inventory valuation, low-stock analytics, category value, and product stock exposure.", "filters": report["filters"], "report": report, "report_types": REPORT_TYPES})


@router.get("/reports/customers", response_class=HTMLResponse)
def dashboard_reports_customers(request: Request, date_from: str = "", date_to: str = "", store_id: int | None = Query(default=None), customer_id: int | None = Query(default=None)):
    filters = report_filter_payload(date_from, date_to, store_id, None, customer_id, None, None, None, "customers")
    report = get_dashboard_report_customers(filters)
    return templates.TemplateResponse("report_detail.html", {"request": request, "title": "Customer Reports - Carthage Business Operating System", "header": get_header(), "active_page": "reports", "section": "customers", "page_title": "Customer Reports", "page_subtitle": "Customer value, credit exposure, wallet balances, loyalty, and purchase concentration.", "filters": report["filters"], "report": report, "report_types": REPORT_TYPES})


@router.get("/reports/procurement", response_class=HTMLResponse)
def dashboard_reports_procurement(request: Request, date_from: str = "", date_to: str = "", store_id: int | None = Query(default=None), supplier_id: int | None = Query(default=None)):
    filters = report_filter_payload(date_from, date_to, store_id, None, None, None, None, supplier_id, "procurement")
    report = get_dashboard_report_procurement(filters)
    return templates.TemplateResponse("report_detail.html", {"request": request, "title": "Procurement Reports - Carthage Business Operating System", "header": get_header(), "active_page": "reports", "section": "procurement", "page_title": "Procurement Reports", "page_subtitle": "Purchase order value, supplier activity, receiving progress, and open replenishment.", "filters": report["filters"], "report": report, "report_types": REPORT_TYPES})


@router.get("/reports/stores", response_class=HTMLResponse)
def dashboard_reports_stores(request: Request, store_id: int | None = Query(default=None)):
    filters = report_filter_payload("", "", store_id, None, None, None, None, None, "stores")
    report = get_dashboard_report_stores(filters)
    return templates.TemplateResponse("report_detail.html", {"request": request, "title": "Store Reports - Carthage Business Operating System", "header": get_header(), "active_page": "reports", "section": "stores", "page_title": "Store Reports", "page_subtitle": "Branch comparison across sales, refunds, transactions, and inventory value.", "filters": report["filters"], "report": report, "report_types": REPORT_TYPES})


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


@router.get("/api/sales")
def dashboard_sales_api(
    date_from: str = "",
    date_to: str = "",
    store_id: int | None = Query(default=None),
    cashier_id: int | None = Query(default=None),
    customer_id: int | None = Query(default=None),
    payment_method: str = "",
    search: str = "",
    refunded: str = "all",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
):
    return list_dashboard_sales(
        {
            "date_from": date_from,
            "date_to": date_to,
            "store_id": store_id,
            "cashier_id": cashier_id,
            "customer_id": customer_id,
            "payment_method": payment_method,
            "search": search,
            "refunded": refunded,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/api/sales-summary")
def dashboard_sales_summary_api(
    date_from: str = "",
    date_to: str = "",
    store_id: int | None = Query(default=None),
    cashier_id: int | None = Query(default=None),
    customer_id: int | None = Query(default=None),
    payment_method: str = "",
    search: str = "",
    refunded: str = "all",
):
    return get_dashboard_sales_summary(
        {
            "date_from": date_from,
            "date_to": date_to,
            "store_id": store_id,
            "cashier_id": cashier_id,
            "customer_id": customer_id,
            "payment_method": payment_method,
            "search": search,
            "refunded": refunded,
        }
    )


@router.get("/api/sales/{sale_id}")
def dashboard_sale_detail_api(sale_id: int):
    detail = get_dashboard_sale_detail(sale_id)
    if not detail:
        return {"sale": None, "items": [], "payments": [], "returns": [], "receipt_preview": ""}
    return detail


@router.get("/api/inventory")
def dashboard_inventory_api(
    search: str = "",
    store_id: int | None = Query(default=None),
    category_id: int | None = Query(default=None),
    supplier_id: int | None = Query(default=None),
    low_stock: bool = False,
    out_of_stock: bool = False,
    active: str = "active",
    has_barcode: str = "all",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
):
    return list_dashboard_inventory(
        {
            "search": search,
            "store_id": store_id,
            "category_id": category_id,
            "supplier_id": supplier_id,
            "low_stock": low_stock,
            "out_of_stock": out_of_stock,
            "active": active,
            "has_barcode": has_barcode,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/api/inventory/summary")
def dashboard_inventory_summary_api(
    search: str = "",
    store_id: int | None = Query(default=None),
    category_id: int | None = Query(default=None),
    supplier_id: int | None = Query(default=None),
    low_stock: bool = False,
    out_of_stock: bool = False,
    active: str = "active",
    has_barcode: str = "all",
):
    return get_dashboard_inventory_summary(
        {
            "search": search,
            "store_id": store_id,
            "category_id": category_id,
            "supplier_id": supplier_id,
            "low_stock": low_stock,
            "out_of_stock": out_of_stock,
            "active": active,
            "has_barcode": has_barcode,
        }
    )


@router.get("/api/inventory/low-stock")
def dashboard_inventory_low_stock_api(limit: int = Query(default=50, ge=1, le=250)):
    return get_dashboard_low_stock_inventory(limit=limit)


@router.get("/api/inventory/valuation")
def dashboard_inventory_valuation_api(
    search: str = "",
    store_id: int | None = Query(default=None),
    category_id: int | None = Query(default=None),
    supplier_id: int | None = Query(default=None),
    active: str = "active",
):
    return get_dashboard_inventory_valuation(
        {
            "search": search,
            "store_id": store_id,
            "category_id": category_id,
            "supplier_id": supplier_id,
            "active": active,
        }
    )


@router.get("/api/inventory/products/{product_id}")
def dashboard_inventory_product_api(product_id: int):
    detail = get_dashboard_product_detail(product_id)
    if not detail:
        return {
            "product": None,
            "identifiers": [],
            "stock_by_store": [],
            "movements": [],
            "procurement": [],
            "label_actions": [],
        }
    return detail


@router.get("/api/customers")
def dashboard_customers_api(
    search: str = "",
    customer_group: str = "",
    active: str = "active",
    has_credit: bool = False,
    has_wallet_balance: bool = False,
    loyalty_customer: bool = False,
    joined_from: str = "",
    joined_to: str = "",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
):
    return list_dashboard_customers(
        {
            "search": search,
            "customer_group": customer_group,
            "active": active,
            "has_credit": has_credit,
            "has_wallet_balance": has_wallet_balance,
            "loyalty_customer": loyalty_customer,
            "joined_from": joined_from,
            "joined_to": joined_to,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/api/customers/summary")
def dashboard_customers_summary_api(
    search: str = "",
    customer_group: str = "",
    active: str = "active",
    has_credit: bool = False,
    has_wallet_balance: bool = False,
    loyalty_customer: bool = False,
    joined_from: str = "",
    joined_to: str = "",
):
    return get_dashboard_crm_summary(
        {
            "search": search,
            "customer_group": customer_group,
            "active": active,
            "has_credit": has_credit,
            "has_wallet_balance": has_wallet_balance,
            "loyalty_customer": loyalty_customer,
            "joined_from": joined_from,
            "joined_to": joined_to,
        }
    )


@router.get("/api/customers/top")
def dashboard_top_customers_api(limit: int = Query(default=10, ge=1, le=100)):
    return get_dashboard_top_customers(limit=limit)


@router.get("/api/customers/{customer_id}/activity")
def dashboard_customer_activity_api(customer_id: int):
    activity = get_dashboard_customer_activity(customer_id)
    if activity is None:
        return {"recent_sales": [], "wallet": [], "loyalty": [], "credit": []}
    return activity


@router.get("/api/customers/{customer_id}")
def dashboard_customer_detail_api(customer_id: int):
    detail = get_dashboard_customer_detail(customer_id)
    if not detail:
        return {
            "customer": None,
            "profile": None,
            "activity": {"recent_sales": [], "wallet": [], "loyalty": [], "credit": []},
            "actions": [],
        }
    return detail


@router.get("/api/procurement")
def dashboard_procurement_api(
    search: str = "",
    supplier_id: int | None = Query(default=None),
    store_id: int | None = Query(default=None),
    status: str = "",
    date_from: str = "",
    date_to: str = "",
    pending_only: bool = False,
    partially_received: bool = False,
    completed: bool = False,
    cancelled: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
):
    return list_dashboard_procurement(
        {
            "search": search,
            "supplier_id": supplier_id,
            "store_id": store_id,
            "status": status,
            "date_from": date_from,
            "date_to": date_to,
            "pending_only": pending_only,
            "partially_received": partially_received,
            "completed": completed,
            "cancelled": cancelled,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/api/procurement/summary")
def dashboard_procurement_summary_api(
    search: str = "",
    supplier_id: int | None = Query(default=None),
    store_id: int | None = Query(default=None),
    status: str = "",
    date_from: str = "",
    date_to: str = "",
    pending_only: bool = False,
    partially_received: bool = False,
    completed: bool = False,
    cancelled: bool = False,
):
    return get_dashboard_procurement_summary(
        {
            "search": search,
            "supplier_id": supplier_id,
            "store_id": store_id,
            "status": status,
            "date_from": date_from,
            "date_to": date_to,
            "pending_only": pending_only,
            "partially_received": partially_received,
            "completed": completed,
            "cancelled": cancelled,
        }
    )


@router.get("/api/procurement/activity")
def dashboard_procurement_activity_api(limit: int = Query(default=25, ge=1, le=100)):
    return get_dashboard_procurement_activity(limit=limit)


@router.get("/api/procurement/suppliers")
def dashboard_procurement_suppliers_api(
    search: str = "",
    active: str = "all",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
):
    return list_dashboard_suppliers(
        {"search": search, "active": active, "page": page, "page_size": page_size}
    )


@router.get("/api/procurement/suppliers/{supplier_id}")
def dashboard_procurement_supplier_detail_api(supplier_id: int):
    detail = get_dashboard_supplier_detail(supplier_id)
    if not detail:
        return {
            "supplier": None,
            "recent_purchase_orders": [],
            "performance": {},
            "actions": [],
        }
    return detail


@router.get("/api/procurement/purchase-orders/{purchase_order_id}")
def dashboard_procurement_purchase_order_api(purchase_order_id: int):
    detail = get_dashboard_purchase_order_detail(purchase_order_id)
    if not detail:
        return {
            "purchase_order": None,
            "supplier": None,
            "items": [],
            "receipts": [],
            "actions": [],
        }
    return detail


@router.get("/api/reports/summary")
def dashboard_reports_summary_api(
    date_from: str = "",
    date_to: str = "",
    store_id: int | None = Query(default=None),
    cashier_id: int | None = Query(default=None),
    customer_id: int | None = Query(default=None),
    product_id: int | None = Query(default=None),
    category_id: int | None = Query(default=None),
    supplier_id: int | None = Query(default=None),
    report_type: str = "overview",
):
    return get_dashboard_reports_summary(
        report_filter_payload(
            date_from, date_to, store_id, cashier_id, customer_id,
            product_id, category_id, supplier_id, report_type,
        )
    )


@router.get("/api/reports/sales")
def dashboard_reports_sales_api(date_from: str = "", date_to: str = "", store_id: int | None = Query(default=None), cashier_id: int | None = Query(default=None), customer_id: int | None = Query(default=None)):
    return get_dashboard_report_sales(
        report_filter_payload(date_from, date_to, store_id, cashier_id, customer_id, None, None, None, "sales")
    )


@router.get("/api/reports/products")
def dashboard_reports_products_api(store_id: int | None = Query(default=None), product_id: int | None = Query(default=None), category_id: int | None = Query(default=None), supplier_id: int | None = Query(default=None)):
    return get_dashboard_report_products(
        report_filter_payload("", "", store_id, None, None, product_id, category_id, supplier_id, "products")
    )


@router.get("/api/reports/cashiers")
def dashboard_reports_cashiers_api(store_id: int | None = Query(default=None), cashier_id: int | None = Query(default=None)):
    return get_dashboard_report_cashiers(
        report_filter_payload("", "", store_id, cashier_id, None, None, None, None, "cashiers")
    )


@router.get("/api/reports/stores")
def dashboard_reports_stores_api(store_id: int | None = Query(default=None)):
    return get_dashboard_report_stores(
        report_filter_payload("", "", store_id, None, None, None, None, None, "stores")
    )


@router.get("/api/reports/customers")
def dashboard_reports_customers_api(date_from: str = "", date_to: str = "", store_id: int | None = Query(default=None), customer_id: int | None = Query(default=None)):
    return get_dashboard_report_customers(
        report_filter_payload(date_from, date_to, store_id, None, customer_id, None, None, None, "customers")
    )


@router.get("/api/reports/inventory")
def dashboard_reports_inventory_api(store_id: int | None = Query(default=None), product_id: int | None = Query(default=None), category_id: int | None = Query(default=None), supplier_id: int | None = Query(default=None)):
    return get_dashboard_report_inventory(
        report_filter_payload("", "", store_id, None, None, product_id, category_id, supplier_id, "inventory")
    )


@router.get("/api/reports/procurement")
def dashboard_reports_procurement_api(date_from: str = "", date_to: str = "", store_id: int | None = Query(default=None), supplier_id: int | None = Query(default=None)):
    return get_dashboard_report_procurement(
        report_filter_payload(date_from, date_to, store_id, None, None, None, None, supplier_id, "procurement")
    )


@router.get("/api/reports/refunds")
def dashboard_reports_refunds_api(date_from: str = "", date_to: str = "", store_id: int | None = Query(default=None), cashier_id: int | None = Query(default=None), customer_id: int | None = Query(default=None)):
    return get_dashboard_report_refunds(
        report_filter_payload(date_from, date_to, store_id, cashier_id, customer_id, None, None, None, "refunds")
    )


@router.get("/api/reports/export/{export_format}")
def dashboard_reports_export_api(export_format: str, date_from: str = "", date_to: str = "", store_id: int | None = Query(default=None), report_type: str = "overview"):
    return get_dashboard_report_export_placeholder(
        report_filter_payload(date_from, date_to, store_id, None, None, None, None, None, report_type),
        export_format=export_format,
    )


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
    return top_products()


@router.get("/api/insights")
def dashboard_insights():
    return {"insights": business_insights()}
