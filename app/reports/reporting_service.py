from datetime import date, timedelta
from typing import Any, Optional, Union

from app.database.db_manager import get_connection


DateInput = Union[str, date]
ReportRow = dict[str, Any]


def get_sales_summary() -> ReportRow:
    """Return backward-compatible, refund-aware lifetime sales totals."""
    report = _build_period_report("0001-01-01", "9999-12-31", top_limit=0)
    return {
        "transaction_count": report["transaction_count"],
        "gross_sales": report["gross_sales"],
        "total_refunds": report["refund_total"],
        "total_sales": report["total_sales"],
        "total_tax": report["tax_total"],
        "average_sale": report["average_sale"],
    }


def get_daily_sales_report(
    report_date: Optional[DateInput] = None,
    top_limit: int = 10,
) -> ReportRow:
    """Return business analytics for one calendar date.

    When ``report_date`` is omitted, the local calendar date is used to preserve
    the original no-argument behavior.
    """
    normalized_date = _normalize_date(report_date or date.today(), "report_date")
    report = _build_period_report(normalized_date, normalized_date, top_limit)
    report["report_date"] = normalized_date
    return report


def get_date_range_sales_report(
    start_date: DateInput,
    end_date: DateInput,
    top_limit: int = 10,
) -> ReportRow:
    """Return business analytics for an inclusive calendar date range."""
    normalized_start = _normalize_date(start_date, "start_date")
    normalized_end = _normalize_date(end_date, "end_date")
    if normalized_start > normalized_end:
        raise ValueError("start_date cannot be after end_date.")

    report = _build_period_report(normalized_start, normalized_end, top_limit)
    report["start_date"] = normalized_start
    report["end_date"] = normalized_end
    return report


def get_sales_report(start_date: DateInput, end_date: DateInput) -> ReportRow:
    """Return the enriched date-range report under the legacy method name."""
    return get_date_range_sales_report(start_date, end_date)


def get_top_selling_products(limit: int = 10) -> list[ReportRow]:
    """Return refund-aware lifetime product sales under the legacy contract."""
    _validate_limit(limit)
    with get_connection() as conn:
        rows = _fetch_period_product_metrics(
            conn, "0001-01-01", "9999-12-31", limit
        )
    return [
        {
            "id": row["id"],
            "sku": row["sku"],
            "name": row["name"],
            "units_sold": row["items_sold"],
            "revenue": row["net_revenue"],
        }
        for row in rows
    ]


def get_product_performance_report(
    limit: int = 10,
    slow_moving_days: int = 30,
) -> ReportRow:
    """Return ranked lifetime product performance collections.

    Slow-moving products are active products with no sale during the trailing
    ``slow_moving_days`` calendar days, including products never sold.
    """
    _validate_limit(limit)
    if not isinstance(slow_moving_days, int) or slow_moving_days < 1:
        raise ValueError("slow_moving_days must be a positive integer.")

    with get_connection() as conn:
        metrics = _fetch_lifetime_product_metrics(conn)

    sold = [item for item in metrics if item["items_sold"] > 0]
    active = [item for item in metrics if item["is_active"]]
    cutoff = date.today() - timedelta(days=slow_moving_days)
    slow_moving = [
        item
        for item in active
        if item["last_sold_at"] is None
        or date.fromisoformat(item["last_sold_at"][0:10]) < cutoff
    ]

    return {
        "best_selling_products": sorted(
            sold, key=lambda item: (-item["items_sold"], -item["net_revenue"], item["name"])
        )[:limit],
        "worst_selling_active_products": sorted(
            active, key=lambda item: (item["items_sold"], item["net_revenue"], item["name"])
        )[:limit],
        "highest_revenue_products": sorted(
            sold, key=lambda item: (-item["net_revenue"], -item["items_sold"], item["name"])
        )[:limit],
        "highest_estimated_profit_products": sorted(
            sold, key=lambda item: (-item["estimated_profit"], -item["items_sold"], item["name"])
        )[:limit],
        "slow_moving_products": sorted(
            slow_moving,
            key=lambda item: (item["last_sold_at"] is not None, item["last_sold_at"] or "", item["name"]),
        )[:limit],
        "slow_moving_days": slow_moving_days,
    }


def get_cashier_performance_report() -> list[ReportRow]:
    """Return refund-aware lifetime sales performance per selling user."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            WITH sale_totals AS (
                SELECT user_id,
                       COUNT(*) AS transaction_count,
                       COALESCE(SUM(subtotal), 0) AS gross_sales,
                       COALESCE(SUM(discount_amount), 0) AS discount_total,
                       COALESCE(SUM(subtotal - discount_amount), 0) AS merchandise_revenue
                FROM sales
                GROUP BY user_id
            ), sold_items AS (
                SELECT s.user_id,
                       COALESCE(SUM(si.quantity), 0) AS sold_quantity,
                       COALESCE(SUM(si.quantity * COALESCE(p.cost_price, 0)), 0) AS sold_cost
                FROM sales s
                JOIN sale_items si ON si.sale_id = s.sale_id
                LEFT JOIN products p ON p.id = CAST(si.product_id AS INTEGER)
                GROUP BY s.user_id
            ), refunds AS (
                SELECT s.user_id,
                       COALESCE(SUM(sr.total_refunded), 0) AS refund_total
                FROM sales s
                JOIN sales_returns sr ON sr.sale_id = s.sale_id
                GROUP BY s.user_id
            ), returned_items AS (
                SELECT s.user_id,
                       COALESCE(SUM(sri.quantity), 0) AS returned_quantity,
                       COALESCE(SUM(sri.quantity * COALESCE(p.cost_price, 0)), 0) AS returned_cost
                FROM sales s
                JOIN sale_items si ON si.sale_id = s.sale_id
                JOIN sales_return_items sri ON sri.sale_item_id = si.id
                LEFT JOIN products p ON p.id = CAST(si.product_id AS INTEGER)
                GROUP BY s.user_id
            )
            SELECT u.id AS user_id,
                   u.username,
                   u.full_name,
                   u.role,
                   st.transaction_count,
                   st.gross_sales,
                   COALESCE(r.refund_total, 0) AS refunds,
                   st.gross_sales - st.discount_total - COALESCE(r.refund_total, 0) AS net_sales,
                   st.discount_total,
                   COALESCE(si.sold_quantity, 0) - COALESCE(ri.returned_quantity, 0) AS items_sold,
                   st.merchandise_revenue - COALESCE(r.refund_total, 0)
                       - (COALESCE(si.sold_cost, 0) - COALESCE(ri.returned_cost, 0))
                       AS estimated_profit,
                   CASE WHEN st.transaction_count = 0 THEN 0
                        ELSE (st.gross_sales - st.discount_total - COALESCE(r.refund_total, 0))
                             / st.transaction_count
                   END AS average_transaction_value
            FROM sale_totals st
            LEFT JOIN users u ON u.id = st.user_id
            LEFT JOIN sold_items si ON si.user_id = st.user_id
            LEFT JOIN refunds r ON r.user_id = st.user_id
            LEFT JOIN returned_items ri ON ri.user_id = st.user_id
            ORDER BY net_sales DESC, st.transaction_count DESC, u.username
            """
        ).fetchall()

    return [
        {
            "user_id": row["user_id"],
            "username": row["username"],
            "full_name": row["full_name"],
            "role": row["role"],
            "transaction_count": int(row["transaction_count"]),
            "gross_sales": _money(row["gross_sales"]),
            "refunds": _money(row["refunds"]),
            "net_sales": _money(row["net_sales"]),
            "discount_total": _money(row["discount_total"]),
            "items_sold": int(row["items_sold"]),
            "estimated_profit": _money(row["estimated_profit"]),
            "average_transaction_value": _money(row["average_transaction_value"]),
        }
        for row in rows
    ]


def get_low_stock_products() -> list[ReportRow]:
    """Return active products at or below their configured reorder level."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, sku, barcode, name, quantity_in_stock, reorder_level
            FROM products
            WHERE is_active = 1 AND quantity_in_stock <= reorder_level
            ORDER BY quantity_in_stock ASC, name ASC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def get_payment_method_report() -> list[ReportRow]:
    """Return refund-aware lifetime sales grouped by payment method."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            WITH refunds AS (
                SELECT sale_id, SUM(total_refunded) AS total_refunded
                FROM sales_returns GROUP BY sale_id
            )
            SELECT s.payment_method,
                   COUNT(*) AS transaction_count,
                   COALESCE(SUM(s.total_amount), 0) AS gross_sales,
                   COALESCE(SUM(r.total_refunded), 0) AS total_refunds,
                   COALESCE(SUM(s.total_amount - COALESCE(r.total_refunded, 0)), 0) AS total_sales
            FROM sales s
            LEFT JOIN refunds r ON r.sale_id = s.sale_id
            GROUP BY s.payment_method
            ORDER BY total_sales DESC
            """
        ).fetchall()

    return [
        {
            "payment_method": row["payment_method"],
            "transaction_count": int(row["transaction_count"]),
            "gross_sales": _money(row["gross_sales"]),
            "total_refunds": _money(row["total_refunds"]),
            "total_sales": _money(row["total_sales"]),
        }
        for row in rows
    ]


def get_inventory_valuation() -> ReportRow:
    """Return current inventory value at catalog cost and retail prices."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS total_products,
                   COALESCE(SUM(quantity_in_stock), 0) AS total_units,
                   COALESCE(SUM(quantity_in_stock * COALESCE(cost_price, 0)), 0) AS inventory_cost,
                   COALESCE(SUM(quantity_in_stock * selling_price), 0) AS inventory_retail
            FROM products
            """
        ).fetchone()

    inventory_cost = _money(row["inventory_cost"])
    inventory_retail = _money(row["inventory_retail"])
    return {
        "total_products": int(row["total_products"]),
        "total_units": int(row["total_units"]),
        "inventory_cost": inventory_cost,
        "inventory_retail": inventory_retail,
        "potential_profit": _money(inventory_retail - inventory_cost),
    }


def _build_period_report(start_date: str, end_date: str, top_limit: int) -> ReportRow:
    _validate_limit(top_limit, allow_zero=True)
    with get_connection() as conn:
        row = conn.execute(
            """
            WITH sale_totals AS (
                SELECT COUNT(*) AS transaction_count,
                       COALESCE(SUM(subtotal), 0) AS gross_sales,
                       COALESCE(SUM(total_amount), 0) AS collected_total,
                       COALESCE(SUM(discount_amount), 0) AS discount_total,
                       COALESCE(SUM(tax_amount), 0) AS tax_total,
                       COALESCE(SUM(subtotal - discount_amount), 0) AS merchandise_revenue
                FROM sales
                WHERE DATE(created_at, 'localtime') BETWEEN DATE(?) AND DATE(?)
            ), sold_items AS (
                SELECT COALESCE(SUM(si.quantity), 0) AS sold_quantity,
                       COALESCE(SUM(si.quantity * COALESCE(p.cost_price, 0)), 0) AS sold_cost
                FROM sale_items si
                JOIN sales s ON s.sale_id = si.sale_id
                LEFT JOIN products p ON p.id = CAST(si.product_id AS INTEGER)
                WHERE DATE(s.created_at, 'localtime') BETWEEN DATE(?) AND DATE(?)
            ), refund_totals AS (
                SELECT COALESCE(SUM(total_refunded), 0) AS refund_total
                FROM sales_returns
                WHERE DATE(created_at, 'localtime') BETWEEN DATE(?) AND DATE(?)
            ), returned_items AS (
                SELECT COALESCE(SUM(sri.quantity), 0) AS returned_quantity,
                       COALESCE(SUM(sri.quantity * COALESCE(p.cost_price, 0)), 0) AS returned_cost
                FROM sales_return_items sri
                JOIN sales_returns sr ON sr.id = sri.return_id
                JOIN sale_items si ON si.id = sri.sale_item_id
                LEFT JOIN products p ON p.id = CAST(si.product_id AS INTEGER)
                WHERE DATE(sr.created_at, 'localtime') BETWEEN DATE(?) AND DATE(?)
            )
            SELECT st.transaction_count,
                   st.gross_sales,
                   rt.refund_total,
                   st.discount_total,
                   st.tax_total,
                   st.gross_sales - st.discount_total - rt.refund_total AS net_sales,
                   st.collected_total - rt.refund_total AS legacy_total_sales,
                   si.sold_quantity - ri.returned_quantity AS items_sold,
                   st.merchandise_revenue - rt.refund_total
                       - (si.sold_cost - ri.returned_cost) AS estimated_profit,
                   CASE WHEN st.transaction_count = 0 THEN 0
                        ELSE (st.gross_sales - st.discount_total - rt.refund_total)
                             / st.transaction_count
                   END AS average_transaction_value
            FROM sale_totals st
            CROSS JOIN sold_items si
            CROSS JOIN refund_totals rt
            CROSS JOIN returned_items ri
            """,
            (
                start_date, end_date,
                start_date, end_date,
                start_date, end_date,
                start_date, end_date,
            ),
        ).fetchone()
        top_products = (
            _fetch_period_product_metrics(conn, start_date, end_date, top_limit)
            if top_limit
            else []
        )

    return {
        "gross_sales": _money(row["gross_sales"]),
        "refund_total": _money(row["refund_total"]),
        "discount_total": _money(row["discount_total"]),
        "net_sales": _money(row["net_sales"]),
        "transaction_count": int(row["transaction_count"]),
        "items_sold": int(row["items_sold"]),
        "estimated_profit": _money(row["estimated_profit"]),
        "average_transaction_value": _money(row["average_transaction_value"]),
        "tax_total": _money(row["tax_total"]),
        "top_selling_products": top_products,
        # Legacy aliases retained for current callers.
        "total_sales": _money(row["legacy_total_sales"]),
        "total_refunds": _money(row["refund_total"]),
        "total_tax": _money(row["tax_total"]),
        "average_sale": _money(
            row["legacy_total_sales"] / row["transaction_count"]
            if row["transaction_count"]
            else 0
        ),
    }


def _fetch_period_product_metrics(
    conn: Any,
    start_date: str,
    end_date: str,
    limit: int,
) -> list[ReportRow]:
    rows = conn.execute(
        """
        WITH activity AS (
            SELECT p.id, p.sku, p.name,
                   si.quantity AS item_delta,
                   (si.quantity * si.price_at_sale)
                       - CASE WHEN s.subtotal > 0
                              THEN s.discount_amount * (si.quantity * si.price_at_sale / s.subtotal)
                              ELSE 0 END AS revenue_delta,
                   si.quantity * COALESCE(p.cost_price, 0) AS cost_delta
            FROM sale_items si
            JOIN sales s ON s.sale_id = si.sale_id
            JOIN products p ON p.id = CAST(si.product_id AS INTEGER)
            WHERE DATE(s.created_at, 'localtime') BETWEEN DATE(?) AND DATE(?)
            UNION ALL
            SELECT p.id, p.sku, p.name,
                   -sri.quantity AS item_delta,
                   -sri.refund_amount AS revenue_delta,
                   -sri.quantity * COALESCE(p.cost_price, 0) AS cost_delta
            FROM sales_return_items sri
            JOIN sales_returns sr ON sr.id = sri.return_id
            JOIN sale_items si ON si.id = sri.sale_item_id
            JOIN products p ON p.id = CAST(si.product_id AS INTEGER)
            WHERE DATE(sr.created_at, 'localtime') BETWEEN DATE(?) AND DATE(?)
        )
        SELECT id, sku, name,
               SUM(item_delta) AS items_sold,
               SUM(revenue_delta) AS net_revenue,
               SUM(revenue_delta - cost_delta) AS estimated_profit
        FROM activity
        GROUP BY id, sku, name
        HAVING SUM(item_delta) > 0
        ORDER BY items_sold DESC, net_revenue DESC, name ASC
        LIMIT ?
        """,
        (start_date, end_date, start_date, end_date, limit),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "sku": row["sku"],
            "name": row["name"],
            "items_sold": int(row["items_sold"]),
            "net_revenue": _money(row["net_revenue"]),
            "estimated_profit": _money(row["estimated_profit"]),
        }
        for row in rows
    ]


def _fetch_lifetime_product_metrics(conn: Any) -> list[ReportRow]:
    rows = conn.execute(
        """
        WITH sold AS (
            SELECT CAST(si.product_id AS INTEGER) AS product_id,
                   SUM(si.quantity) AS sold_quantity,
                   SUM((si.quantity * si.price_at_sale)
                       - CASE WHEN s.subtotal > 0
                              THEN s.discount_amount * (si.quantity * si.price_at_sale / s.subtotal)
                              ELSE 0 END) AS sale_revenue,
                   MAX(DATE(s.created_at, 'localtime')) AS last_sold_at
            FROM sale_items si
            JOIN sales s ON s.sale_id = si.sale_id
            GROUP BY CAST(si.product_id AS INTEGER)
        ), returned AS (
            SELECT CAST(si.product_id AS INTEGER) AS product_id,
                   SUM(sri.quantity) AS returned_quantity,
                   SUM(sri.refund_amount) AS refund_amount
            FROM sales_return_items sri
            JOIN sale_items si ON si.id = sri.sale_item_id
            GROUP BY CAST(si.product_id AS INTEGER)
        )
        SELECT p.id, p.sku, p.name, p.is_active,
               COALESCE(s.sold_quantity, 0) - COALESCE(r.returned_quantity, 0) AS items_sold,
               COALESCE(s.sale_revenue, 0) - COALESCE(r.refund_amount, 0) AS net_revenue,
               COALESCE(s.sale_revenue, 0) - COALESCE(r.refund_amount, 0)
                   - ((COALESCE(s.sold_quantity, 0) - COALESCE(r.returned_quantity, 0))
                      * COALESCE(p.cost_price, 0)) AS estimated_profit,
               s.last_sold_at
        FROM products p
        LEFT JOIN sold s ON s.product_id = p.id
        LEFT JOIN returned r ON r.product_id = p.id
        """
    ).fetchall()
    return [
        {
            "id": row["id"],
            "sku": row["sku"],
            "name": row["name"],
            "is_active": bool(row["is_active"]),
            "items_sold": int(row["items_sold"]),
            "net_revenue": _money(row["net_revenue"]),
            "estimated_profit": _money(row["estimated_profit"]),
            "last_sold_at": row["last_sold_at"],
        }
        for row in rows
    ]


def _normalize_date(value: DateInput, field_name: str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid YYYY-MM-DD date.") from exc


def _validate_limit(limit: int, allow_zero: bool = False) -> None:
    minimum = 0 if allow_zero else 1
    if not isinstance(limit, int) or limit < minimum:
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"limit must be a {qualifier} integer.")


def _money(value: Any) -> float:
    return round(float(value or 0), 2)
