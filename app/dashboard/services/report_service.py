from datetime import date
from typing import Any

from app.dashboard.services.dashboard_service import (
    _columns,
    _safe_int,
    _safe_text,
    _table_exists,
    get_dashboard_crm_summary,
    get_dashboard_inventory_summary,
    get_dashboard_procurement_summary,
    get_dashboard_sales_summary,
    list_dashboard_customers,
    list_dashboard_inventory,
    list_dashboard_procurement,
    money,
)
from app.database.db_manager import get_connection
from app.reports import reporting_service


REPORT_TYPES = [
    "overview",
    "sales",
    "products",
    "cashiers",
    "stores",
    "customers",
    "inventory",
    "procurement",
    "refunds",
]


def normalize_report_filters(filters=None):
    filters = filters or {}
    report_type = _safe_text(filters.get("report_type")).lower() or "overview"
    if report_type not in REPORT_TYPES:
        report_type = "overview"
    date_from = _safe_text(filters.get("date_from"))
    date_to = _safe_text(filters.get("date_to"))
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from
    return {
        "date_from": date_from,
        "date_to": date_to,
        "store_id": _safe_int(filters.get("store_id")),
        "cashier_id": _safe_int(filters.get("cashier_id")),
        "customer_id": _safe_int(filters.get("customer_id")),
        "product_id": _safe_int(filters.get("product_id")),
        "category_id": _safe_int(filters.get("category_id")),
        "supplier_id": _safe_int(filters.get("supplier_id")),
        "report_type": report_type,
        "limit": _safe_int(filters.get("limit"), default=10, minimum=1, maximum=100),
    }


def _store_ids(filters):
    return [filters["store_id"]] if filters.get("store_id") is not None else None


def _period(filters):
    return (
        filters.get("date_from") or "0001-01-01",
        filters.get("date_to") or "9999-12-31",
    )


def _safe_call(default, func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception:
        return default


def _display_sales_report(report):
    return {
        **report,
        "gross_sales_display": money(report.get("gross_sales")),
        "refund_total_display": money(report.get("refund_total") or report.get("total_refunds")),
        "discount_total_display": money(report.get("discount_total")),
        "net_sales_display": money(report.get("net_sales") or report.get("total_sales")),
        "estimated_profit_display": money(report.get("estimated_profit")),
        "average_transaction_value_display": money(
            report.get("average_transaction_value") or report.get("average_sale")
        ),
    }


def _display_money_fields(rows, fields):
    formatted = []
    for row in rows:
        item = dict(row)
        for field in fields:
            item[f"{field}_display"] = money(item.get(field))
        formatted.append(item)
    return formatted


def get_dashboard_report_sales(filters=None):
    filters = normalize_report_filters(filters)
    start_date, end_date = _period(filters)
    report = _safe_call(
        {
            "gross_sales": 0,
            "refund_total": 0,
            "discount_total": 0,
            "net_sales": 0,
            "transaction_count": 0,
            "items_sold": 0,
            "estimated_profit": 0,
            "average_transaction_value": 0,
            "tax_total": 0,
            "top_selling_products": [],
        },
        reporting_service.get_date_range_sales_report,
        start_date,
        end_date,
        top_limit=filters["limit"],
        store_ids=_store_ids(filters),
    )
    dashboard_summary = get_dashboard_sales_summary(
        {
            "date_from": filters["date_from"],
            "date_to": filters["date_to"],
            "store_id": filters["store_id"],
            "cashier_id": filters["cashier_id"],
            "customer_id": filters["customer_id"],
        }
    )
    return {
        "filters": filters,
        "summary": _display_sales_report(report),
        "dashboard_summary": dashboard_summary,
        "top_products": report.get("top_selling_products", []),
    }


def get_dashboard_report_products(filters=None):
    filters = normalize_report_filters(filters)
    performance = _safe_call(
        {
            "best_selling_products": [],
            "worst_selling_active_products": [],
            "highest_revenue_products": [],
            "highest_estimated_profit_products": [],
            "slow_moving_products": [],
            "slow_moving_days": 0,
        },
        reporting_service.get_product_performance_report,
        limit=filters["limit"],
        store_ids=_store_ids(filters),
    )
    product_ids = _report_product_filter_ids(filters)
    if product_ids is not None:
        for key, rows in performance.items():
            if isinstance(rows, list):
                performance[key] = [row for row in rows if row.get("id") in product_ids]
    return {"filters": filters, "performance": performance}


def _report_product_filter_ids(filters):
    if (
        filters.get("product_id") is None
        and filters.get("category_id") is None
        and filters.get("supplier_id") is None
    ):
        return None
    with get_connection() as conn:
        if not _table_exists(conn, "products"):
            return set()
        product_columns = _columns(conn, "products")
        where = ["1 = 1"]
        params = []
        if filters.get("product_id") is not None:
            where.append("id = ?")
            params.append(filters["product_id"])
        if filters.get("category_id") is not None and "category_id" in product_columns:
            where.append("category_id = ?")
            params.append(filters["category_id"])
        if filters.get("supplier_id") is not None and "supplier_id" in product_columns:
            where.append("supplier_id = ?")
            params.append(filters["supplier_id"])
        rows = conn.execute(
            f"SELECT id FROM products WHERE {' AND '.join(where)}",
            params,
        ).fetchall()
    return {row["id"] for row in rows}


def get_dashboard_report_cashiers(filters=None):
    filters = normalize_report_filters(filters)
    rows = _safe_call(
        [],
        reporting_service.get_cashier_performance_report,
        store_ids=_store_ids(filters),
    )
    if filters["cashier_id"] is not None:
        rows = [row for row in rows if row.get("user_id") == filters["cashier_id"]]
    return {"filters": filters, "items": rows}


def get_dashboard_report_stores(filters=None):
    filters = normalize_report_filters(filters)
    rows = _safe_call(
        [],
        reporting_service.get_branch_comparison_report,
        store_ids=_store_ids(filters),
    )
    return {"filters": filters, "items": rows}


def get_dashboard_report_customers(filters=None):
    filters = normalize_report_filters(filters)
    result = list_dashboard_customers(
        {
            "active": "all",
            "page": 1,
            "page_size": filters["limit"],
        }
    )
    customers = result["items"]
    if filters["customer_id"] is not None:
        customers = [row for row in customers if row.get("customer_id") == filters["customer_id"]]
    top_customers = _safe_call(
        [],
        reporting_service.get_top_customers,
        limit=filters["limit"],
        store_ids=_store_ids(filters),
    )
    credit = _safe_call([], reporting_service.get_outstanding_credit_report, store_ids=_store_ids(filters))
    return {
        "filters": filters,
        "summary": get_dashboard_crm_summary({"active": "all"}),
        "items": customers,
        "top_customers": top_customers,
        "credit": credit,
    }


def get_dashboard_report_inventory(filters=None):
    filters = normalize_report_filters(filters)
    inventory_filters = {
        "store_id": filters["store_id"],
        "category_id": filters["category_id"],
        "supplier_id": filters["supplier_id"],
        "active": "all",
        "page": 1,
        "page_size": filters["limit"],
    }
    inventory = list_dashboard_inventory(inventory_filters)
    valuation = _safe_call(
        {
            "total_products": 0,
            "total_units": 0,
            "inventory_cost": 0,
            "inventory_retail": 0,
            "potential_profit": 0,
            "valuation_method": "moving_average_cost",
        },
        reporting_service.get_inventory_valuation,
        store_ids=_store_ids(filters),
    )
    low_stock = _safe_call(
        [],
        reporting_service.get_low_stock_products,
        store_ids=_store_ids(filters),
    )
    categories = _safe_call(
        [],
        reporting_service.get_stock_value_by_category,
        store_ids=_store_ids(filters),
    )
    return {
        "filters": filters,
        "summary": get_dashboard_inventory_summary(inventory_filters),
        "valuation": _display_money_fields([valuation], ["inventory_cost", "inventory_retail", "potential_profit"])[0],
        "items": inventory["items"],
        "low_stock": low_stock,
        "categories": categories,
    }


def get_dashboard_report_procurement(filters=None):
    filters = normalize_report_filters(filters)
    procurement_filters = {
        "supplier_id": filters["supplier_id"],
        "store_id": filters["store_id"],
        "date_from": filters["date_from"],
        "date_to": filters["date_to"],
        "page": 1,
        "page_size": filters["limit"],
    }
    procurement = list_dashboard_procurement(procurement_filters)
    return {
        "filters": filters,
        "summary": get_dashboard_procurement_summary(procurement_filters),
        "items": procurement["items"],
    }


def get_dashboard_report_refunds(filters=None):
    filters = normalize_report_filters(filters)
    with get_connection() as conn:
        if not (_table_exists(conn, "sales_returns") and _table_exists(conn, "sales")):
            return {
                "filters": filters,
                "summary": {
                    "refund_count": 0,
                    "refund_total": 0,
                    "refund_total_display": money(0),
                },
                "items": [],
            }
        sales_columns = _columns(conn, "sales")
        returns_columns = _columns(conn, "sales_returns")
        receipt_expr = "s.receipt_number" if "receipt_number" in sales_columns else "CAST(s.sale_id AS TEXT)"
        sale_date_expr = "s.created_at" if "created_at" in sales_columns else "s.timestamp"
        where = ["1 = 1"]
        params: list[Any] = []
        if filters["date_from"]:
            where.append("DATE(sr.created_at) >= DATE(?)")
            params.append(filters["date_from"])
        if filters["date_to"]:
            where.append("DATE(sr.created_at) <= DATE(?)")
            params.append(filters["date_to"])
        if filters["store_id"] is not None and "store_id" in sales_columns:
            where.append("s.store_id = ?")
            params.append(filters["store_id"])
        if filters["cashier_id"] is not None and "user_id" in sales_columns:
            where.append("s.user_id = ?")
            params.append(filters["cashier_id"])
        if filters["customer_id"] is not None and "customer_id" in sales_columns:
            where.append("s.customer_id = ?")
            params.append(filters["customer_id"])
        where_clause = " AND ".join(where)
        rows = conn.execute(
            f"""SELECT sr.id, sr.sale_id, {receipt_expr} AS receipt_number,
                      sr.reason, sr.total_refunded, sr.created_at,
                      {sale_date_expr} AS sale_time,
                      COALESCE(u.full_name, u.username, 'system') AS processed_by
               FROM sales_returns sr
               JOIN sales s ON s.sale_id = sr.sale_id
               LEFT JOIN users u ON u.id = sr.user_id
               WHERE {where_clause}
               ORDER BY sr.created_at DESC, sr.id DESC
               LIMIT ?""",
            [*params, filters["limit"]],
        ).fetchall()
        total = conn.execute(
            f"""SELECT COUNT(*) AS refund_count,
                      COALESCE(SUM(sr.total_refunded), 0) AS refund_total
               FROM sales_returns sr
               JOIN sales s ON s.sale_id = sr.sale_id
               WHERE {where_clause}""",
            params,
        ).fetchone()
    items = [
        {
            **dict(row),
            "total_refunded_display": money(row["total_refunded"]),
        }
        for row in rows
    ]
    refund_total = float(total["refund_total"] or 0)
    return {
        "filters": filters,
        "summary": {
            "refund_count": int(total["refund_count"] or 0),
            "refund_total": refund_total,
            "refund_total_display": money(refund_total),
        },
        "items": items,
    }


def get_dashboard_reports_summary(filters=None):
    filters = normalize_report_filters(filters)
    sales = get_dashboard_report_sales(filters)
    products = get_dashboard_report_products(filters)
    cashiers = get_dashboard_report_cashiers(filters)
    stores = get_dashboard_report_stores(filters)
    customers = get_dashboard_report_customers(filters)
    inventory = get_dashboard_report_inventory(filters)
    procurement = get_dashboard_report_procurement(filters)
    refunds = get_dashboard_report_refunds(filters)
    cards = [
        {"label": "Net Sales", "value": sales["summary"]["net_sales_display"], "accent": "accent-blue"},
        {"label": "Estimated Profit", "value": sales["summary"]["estimated_profit_display"], "accent": "accent-green"},
        {"label": "Inventory Value", "value": inventory["valuation"]["inventory_cost_display"], "accent": "accent-amber"},
        {"label": "Refunds", "value": refunds["summary"]["refund_total_display"], "accent": "accent-red"},
    ]
    return {
        "filters": filters,
        "cards": cards,
        "sales": sales,
        "products": products,
        "cashiers": cashiers,
        "stores": stores,
        "customers": customers,
        "inventory": inventory,
        "procurement": procurement,
        "refunds": refunds,
        "exports": get_dashboard_report_export_placeholder(filters),
        "generated_at": date.today().isoformat(),
    }


def get_dashboard_report_export_placeholder(filters=None, export_format=None):
    filters = normalize_report_filters(filters)
    requested = _safe_text(export_format or filters.get("export_format")).lower()
    if requested not in {"csv", "excel", "pdf", "print", ""}:
        requested = ""
    return {
        "status": "coming_soon",
        "message": "Report export and print actions are coming soon.",
        "requested_format": requested,
        "available_formats": ["csv", "excel", "pdf", "print"],
        "filters": filters,
    }
