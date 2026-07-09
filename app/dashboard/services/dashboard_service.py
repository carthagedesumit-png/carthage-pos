from datetime import date, datetime
from math import ceil

from app.core.exceptions import DocumentError, SalesError
from app.database.db_manager import get_connection
from app.documents.document_service import generate_sales_receipt
from app.sales.sales_service import PAYMENT_METHODS, print_receipt_data


def money(value):
    return f"₦{float(value or 0):,.2f}"


def _table_exists(conn, table_name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _columns(conn, table_name):
    if not _table_exists(conn, table_name):
        return set()
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def count_table(conn, table_name):
    try:
        if not _table_exists(conn, table_name):
            return 0
        return conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    except Exception:
        return 0


def get_recent_sales(conn, limit=5):
    if not _table_exists(conn, "sales"):
        return []

    columns = _columns(conn, "sales")
    date_column = "created_at" if "created_at" in columns else "timestamp"

    receipt_column = "receipt_number" if "receipt_number" in columns else "sale_id"
    amount_column = "total_amount" if "total_amount" in columns else "total"

    query = f"""
        SELECT {receipt_column} AS receipt,
               {amount_column} AS amount,
               COALESCE({date_column}, '') AS sale_time
        FROM sales
        ORDER BY {date_column} DESC
        LIMIT ?
    """

    try:
        return [
            {
                "receipt": row["receipt"],
                "customer": "Guest",
                "amount": money(row["amount"]),
                "store": "Main Store",
                "time": row["sale_time"],
            }
            for row in conn.execute(query, (limit,))
        ]
    except Exception:
        return []


def get_low_stock_items(conn, limit=5):
    if not _table_exists(conn, "store_inventory"):
        return []

    try:
        return [
            {
                "name": row["name"],
                "quantity": row["quantity_on_hand"],
                "reorder_level": row["reorder_level"],
            }
            for row in conn.execute(
                """
                SELECT p.name, si.quantity_on_hand, si.reorder_level
                FROM store_inventory si
                LEFT JOIN products p ON p.id = si.product_id
                WHERE si.quantity_on_hand <= si.reorder_level
                ORDER BY si.quantity_on_hand ASC
                LIMIT ?
                """,
                (limit,),
            )
        ]
    except Exception:
        return []


def _safe_int(value, default=None, minimum=None, maximum=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None and parsed < minimum:
        return minimum
    if maximum is not None and parsed > maximum:
        return maximum
    return parsed


def _safe_text(value):
    return str(value or "").strip()


def _row_value(row, key, default=None):
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def _customer_name(row):
    business = _safe_text(_row_value(row, "customer_business_name"))
    first = _safe_text(_row_value(row, "customer_first_name"))
    last = _safe_text(_row_value(row, "customer_last_name"))
    name = business or " ".join(part for part in [first, last] if part)
    return name or _safe_text(_row_value(row, "customer_code")) or "Guest"


def _sale_status(payment_status, refund_total, total_amount):
    refunded = float(refund_total or 0)
    total = float(total_amount or 0)
    if refunded > 0 and refunded >= total:
        return "refunded"
    if refunded > 0:
        return "partial refund"
    return _safe_text(payment_status).lower() or "paid"


def _normalize_sales_filters(filters=None):
    filters = filters or {}
    refunded = _safe_text(filters.get("refunded")).lower()
    if refunded not in {"all", "refunded", "non-refunded"}:
        refunded = "all"
    payment_method = _safe_text(filters.get("payment_method")).upper()
    if payment_method and payment_method not in PAYMENT_METHODS:
        payment_method = ""
    return {
        "date_from": _safe_text(filters.get("date_from")),
        "date_to": _safe_text(filters.get("date_to")),
        "store_id": _safe_int(filters.get("store_id")),
        "cashier_id": _safe_int(filters.get("cashier_id")),
        "customer_id": _safe_int(filters.get("customer_id")),
        "payment_method": payment_method,
        "search": _safe_text(filters.get("search") or filters.get("q")),
        "refunded": refunded,
        "page": _safe_int(filters.get("page"), default=1, minimum=1),
        "page_size": _safe_int(filters.get("page_size"), default=25, minimum=1, maximum=100),
    }


def _dashboard_access_scope(session=None):
    """Placeholder boundary for future role-aware dashboard authentication."""
    if session is None:
        return {"role": "admin", "store_ids": None}
    if getattr(session, "role", None) == "admin":
        return {"role": "admin", "store_ids": None}
    store_id = getattr(session, "store_id", None)
    if getattr(session, "role", None) == "manager":
        return {"role": "manager", "store_ids": [store_id]}
    return {"role": "cashier", "store_ids": [store_id]}


def _sales_query_parts(conn, filters, session=None):
    sales_columns = _columns(conn, "sales")
    stores_columns = _columns(conn, "stores")
    users_columns = _columns(conn, "users")
    customers_columns = _columns(conn, "customers")

    date_column = "created_at" if "created_at" in sales_columns else "timestamp"
    receipt_expr = "s.receipt_number" if "receipt_number" in sales_columns else "CAST(s.sale_id AS TEXT)"
    tender_expr = "s.tender_type" if "tender_type" in sales_columns else "s.payment_method"
    total_expr = "s.total_amount" if "total_amount" in sales_columns else "s.total"
    subtotal_expr = "s.subtotal" if "subtotal" in sales_columns else total_expr
    discount_expr = "s.discount_amount" if "discount_amount" in sales_columns else "0"
    payment_status_expr = "s.payment_status" if "payment_status" in sales_columns else "'PAID'"
    customer_id_expr = "s.customer_id" if "customer_id" in sales_columns else "NULL"
    user_id_expr = "s.user_id" if "user_id" in sales_columns else "NULL"
    store_id_expr = "s.store_id" if "store_id" in sales_columns else "NULL"
    username_expr = "s.username" if "username" in sales_columns else "s.cashier_name"

    select_fields = [
        "s.sale_id",
        f"{receipt_expr} AS receipt_number",
        f"COALESCE(s.{date_column}, '') AS sale_time",
        f"{store_id_expr} AS store_id",
        f"{user_id_expr} AS user_id",
        f"{customer_id_expr} AS customer_id",
        f"COALESCE({username_expr}, 'system') AS cashier_username",
        f"COALESCE({subtotal_expr}, 0) AS gross_amount",
        f"COALESCE({discount_expr}, 0) AS discount_amount",
        f"COALESCE({total_expr}, 0) AS total_amount",
        f"COALESCE({tender_expr}, s.payment_method, 'CASH') AS payment_method",
        f"COALESCE({payment_status_expr}, 'PAID') AS payment_status",
        "COALESCE(r.total_refunded, 0) AS refund_total",
    ]
    joins = [
        """LEFT JOIN (
               SELECT sale_id, SUM(total_refunded) AS total_refunded
               FROM sales_returns GROUP BY sale_id
           ) r ON r.sale_id = s.sale_id"""
    ]
    if stores_columns and "store_id" in sales_columns:
        store_name = "st.name" if "name" in stores_columns else "st.code"
        joins.append("LEFT JOIN stores st ON st.id = s.store_id")
        select_fields.append(f"COALESCE({store_name}, st.code, 'Store #' || s.store_id) AS store_name")
        select_fields.append("st.code AS store_code")
    else:
        select_fields.append("'Main Store' AS store_name")
        select_fields.append("NULL AS store_code")
    if users_columns and "user_id" in sales_columns:
        user_name = "u.full_name" if "full_name" in users_columns else "u.username"
        joins.append("LEFT JOIN users u ON u.id = s.user_id")
        select_fields.append(f"COALESCE({user_name}, u.username, {username_expr}, 'system') AS cashier_name")
    else:
        select_fields.append(f"COALESCE({username_expr}, 'system') AS cashier_name")
    if customers_columns and "customer_id" in sales_columns:
        joins.append("LEFT JOIN customers c ON c.id = s.customer_id")
        for column in ["customer_code", "first_name", "last_name", "business_name"]:
            expr = f"c.{column}" if column in customers_columns else "NULL"
            select_fields.append(f"{expr} AS customer_{column}")
    else:
        for column in ["customer_code", "first_name", "last_name", "business_name"]:
            select_fields.append(f"NULL AS customer_{column}")

    where = ["1 = 1"]
    params = []
    scope = _dashboard_access_scope(session)
    if scope["store_ids"] and "store_id" in sales_columns:
        allowed_ids = [store_id for store_id in scope["store_ids"] if store_id is not None]
        if allowed_ids:
            where.append(f"s.store_id IN ({','.join('?' for _ in allowed_ids)})")
            params.extend(allowed_ids)
    if filters["store_id"] is not None and "store_id" in sales_columns:
        where.append("s.store_id = ?")
        params.append(filters["store_id"])
    if filters["cashier_id"] is not None and "user_id" in sales_columns:
        where.append("s.user_id = ?")
        params.append(filters["cashier_id"])
    if filters["customer_id"] is not None and "customer_id" in sales_columns:
        where.append("s.customer_id = ?")
        params.append(filters["customer_id"])
    if filters["date_from"]:
        where.append(f"DATE(s.{date_column}) >= DATE(?)")
        params.append(filters["date_from"])
    if filters["date_to"]:
        where.append(f"DATE(s.{date_column}) <= DATE(?)")
        params.append(filters["date_to"])
    if filters["payment_method"]:
        where.append(f"UPPER(COALESCE({tender_expr}, s.payment_method, '')) = ?")
        params.append(filters["payment_method"])
    if filters["refunded"] == "refunded":
        where.append("COALESCE(r.total_refunded, 0) > 0")
    elif filters["refunded"] == "non-refunded":
        where.append("COALESCE(r.total_refunded, 0) = 0")
    if filters["search"]:
        pattern = f"%{filters['search']}%"
        search_terms = [f"{receipt_expr} LIKE ?", "CAST(s.sale_id AS TEXT) LIKE ?", f"{username_expr} LIKE ?"]
        params.extend([pattern, pattern, pattern])
        if customers_columns and "customer_id" in sales_columns:
            for column in ["customer_code", "first_name", "last_name", "business_name"]:
                if column in customers_columns:
                    search_terms.append(f"c.{column} LIKE ?")
                    params.append(pattern)
        where.append(f"({' OR '.join(search_terms)})")

    return {
        "select": ", ".join(select_fields),
        "joins": "\n".join(joins),
        "where": " AND ".join(where),
        "params": params,
        "date_column": date_column,
        "total_expr": total_expr,
        "subtotal_expr": subtotal_expr,
        "discount_expr": discount_expr,
    }


def _format_sale_row(row):
    gross = float(row["gross_amount"] or 0)
    discount = float(row["discount_amount"] or 0)
    refund_total = float(row["refund_total"] or 0)
    total = float(row["total_amount"] or 0)
    net = total - refund_total
    return {
        "sale_id": row["sale_id"],
        "receipt_number": row["receipt_number"] or f"Sale #{row['sale_id']}",
        "sale_time": row["sale_time"] or "",
        "customer_name": _customer_name(row),
        "store": row["store_name"] or row["store_code"] or "Main Store",
        "cashier": row["cashier_name"] or row["cashier_username"] or "system",
        "cashier_id": row["user_id"],
        "customer_id": row["customer_id"],
        "store_id": row["store_id"],
        "payment_method": row["payment_method"] or "CASH",
        "gross_amount": gross,
        "gross_amount_display": money(gross),
        "discount_amount": discount,
        "discount_display": money(discount),
        "refund_total": refund_total,
        "refund_display": money(refund_total),
        "net_amount": net,
        "net_amount_display": money(net),
        "sale_status": _sale_status(row["payment_status"], refund_total, total),
    }


def _dashboard_sales_summary_from_parts(conn, parts):
    row = conn.execute(
        f"""SELECT COUNT(*) AS transaction_count,
                   COALESCE(SUM(COALESCE({parts['subtotal_expr']}, 0)), 0) AS gross_sales,
                   COALESCE(SUM(COALESCE({parts['discount_expr']}, 0)), 0) AS discounts,
                   COALESCE(SUM(COALESCE(r.total_refunded, 0)), 0) AS refunds,
                   COALESCE(SUM(COALESCE({parts['total_expr']}, 0) - COALESCE(r.total_refunded, 0)), 0) AS net_sales
            FROM sales s
            {parts['joins']}
            WHERE {parts['where']}""",
        parts["params"],
    ).fetchone()
    transactions = int(row["transaction_count"] or 0)
    net_sales = float(row["net_sales"] or 0)
    return {
        "transaction_count": transactions,
        "gross_sales": float(row["gross_sales"] or 0),
        "gross_sales_display": money(row["gross_sales"]),
        "discounts": float(row["discounts"] or 0),
        "discounts_display": money(row["discounts"]),
        "refunds": float(row["refunds"] or 0),
        "refunds_display": money(row["refunds"]),
        "net_sales": net_sales,
        "net_sales_display": money(net_sales),
        "average_sale": net_sales / transactions if transactions else 0,
        "average_sale_display": money(net_sales / transactions if transactions else 0),
    }


def get_dashboard_sales_summary(filters=None, session=None):
    filters = _normalize_sales_filters(filters)
    with get_connection() as conn:
        if not _table_exists(conn, "sales"):
            return {
                "transaction_count": 0,
                "gross_sales": 0,
                "gross_sales_display": money(0),
                "discounts": 0,
                "discounts_display": money(0),
                "refunds": 0,
                "refunds_display": money(0),
                "net_sales": 0,
                "net_sales_display": money(0),
                "average_sale": 0,
                "average_sale_display": money(0),
            }
        parts = _sales_query_parts(conn, filters, session=session)
        return _dashboard_sales_summary_from_parts(conn, parts)


def list_dashboard_sales(filters=None, session=None):
    filters = _normalize_sales_filters(filters)
    if filters["date_from"] and filters["date_to"] and filters["date_from"] > filters["date_to"]:
        filters["date_from"], filters["date_to"] = filters["date_to"], filters["date_from"]

    with get_connection() as conn:
        if not _table_exists(conn, "sales"):
            total = 0
            rows = []
            summary = get_dashboard_sales_summary(filters, session=session)
        else:
            parts = _sales_query_parts(conn, filters, session=session)
            total = conn.execute(
                f"""SELECT COUNT(*)
                    FROM sales s
                    {parts['joins']}
                    WHERE {parts['where']}""",
                parts["params"],
            ).fetchone()[0]
            total_pages = max(1, ceil(total / filters["page_size"]))
            filters["page"] = min(filters["page"], total_pages)
            offset = (filters["page"] - 1) * filters["page_size"]
            rows = conn.execute(
                f"""SELECT {parts['select']}
                    FROM sales s
                    {parts['joins']}
                    WHERE {parts['where']}
                    ORDER BY COALESCE(s.{parts['date_column']}, s.timestamp) DESC, s.sale_id DESC
                    LIMIT ? OFFSET ?""",
                [*parts["params"], filters["page_size"], offset],
            ).fetchall()
            summary = _dashboard_sales_summary_from_parts(conn, parts)

    total_pages = max(1, ceil(total / filters["page_size"]))
    page = filters["page"]
    return {
        "items": [_format_sale_row(row) for row in rows],
        "summary": summary,
        "filters": filters,
        "pagination": {
            "page": page,
            "page_size": filters["page_size"],
            "total": total,
            "total_pages": total_pages,
            "has_previous": page > 1,
            "has_next": page < total_pages,
            "previous_page": page - 1 if page > 1 else None,
            "next_page": page + 1 if page < total_pages else None,
        },
    }


def get_dashboard_sale_detail(sale_id, session=None):
    try:
        receipt_data = print_receipt_data(int(sale_id))
    except (SalesError, ValueError):
        return None

    sale = receipt_data["sale"]
    scope = _dashboard_access_scope(session)
    if scope["store_ids"] and sale.get("store_id") not in scope["store_ids"]:
        return None

    with get_connection() as conn:
        returns = [
            dict(row)
            for row in conn.execute(
                """SELECT sr.id, sr.reason, sr.total_refunded, sr.created_at,
                          COALESCE(u.full_name, u.username, 'system') AS processed_by
                   FROM sales_returns sr
                   LEFT JOIN users u ON u.id = sr.user_id
                   WHERE sr.sale_id = ?
                   ORDER BY sr.created_at DESC, sr.id DESC""",
                (sale["sale_id"],),
            ).fetchall()
        ]
        store = None
        if sale.get("store_id") is not None and _table_exists(conn, "stores"):
            row = conn.execute(
                "SELECT id, code, name, address, phone, email FROM stores WHERE id = ?",
                (sale["store_id"],),
            ).fetchone()
            store = dict(row) if row else None

    receipt_preview = ""
    receipt_error = None
    try:
        document = generate_sales_receipt(sale["sale_id"])
        receipt_preview = document.get("text") or ""
    except (DocumentError, SalesError, ValueError) as exc:
        receipt_error = str(exc)

    refund_total = sum(float(item["total_refunded"] or 0) for item in returns)
    sale["refund_total"] = refund_total
    sale["net_amount"] = float(sale.get("total_amount") or sale.get("total") or 0) - refund_total
    sale["sale_status"] = _sale_status(
        sale.get("payment_status"),
        refund_total,
        sale.get("total_amount") or sale.get("total"),
    )

    return {
        "sale": sale,
        "items": receipt_data["items"],
        "payments": receipt_data.get("payments", []),
        "customer": receipt_data.get("customer"),
        "store": store,
        "returns": returns,
        "receipt_preview": receipt_preview,
        "receipt_error": receipt_error,
    }


def get_dashboard_summary():
    today = date.today().isoformat()

    with get_connection() as conn:
        sales_columns = _columns(conn, "sales")
        date_expr = "created_at" if "created_at" in sales_columns else "timestamp"

        transactions = 0
        today_sales = 0

        if _table_exists(conn, "sales"):
            try:
                sales_row = conn.execute(
                    f"""
                    SELECT COUNT(*) AS transactions,
                           COALESCE(SUM(total_amount), 0) AS today_sales
                    FROM sales
                    WHERE DATE({date_expr}) = DATE(?)
                    """,
                    (today,),
                ).fetchone()

                transactions = sales_row["transactions"]
                today_sales = sales_row["today_sales"]
            except Exception:
                pass

        low_stock = 0
        if _table_exists(conn, "store_inventory"):
            low_stock = conn.execute(
                """
                SELECT COUNT(*)
                FROM store_inventory
                WHERE quantity_on_hand <= reorder_level
                """
            ).fetchone()[0]

        inventory_value = 0
        if _table_exists(conn, "store_inventory"):
            inventory_value = conn.execute(
                """
                SELECT COALESCE(SUM(quantity_on_hand * average_cost), 0)
                FROM store_inventory
                """
            ).fetchone()[0]

        outstanding_credit = 0
        credit_columns = _columns(conn, "credit_transactions")
        if "balance_after" in credit_columns:
            outstanding_credit = conn.execute(
                "SELECT COALESCE(SUM(balance_after), 0) FROM credit_transactions"
            ).fetchone()[0]

        return {
            "today_sales": money(today_sales),
            "today_profit": money(0),
            "transactions": transactions,
            "low_stock": low_stock,
            "outstanding_credit": money(outstanding_credit),
            "inventory_value": money(inventory_value),
            "customers": count_table(conn, "customers"),
            "stores": count_table(conn, "stores"),
            "users": count_table(conn, "users"),
            "license_status": "Active",
            "backup_status": "Healthy",
            "api_status": "Online",
            "hardware_status": "Pending",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "recent_sales": get_recent_sales(conn),
            "low_stock_items": get_low_stock_items(conn),
            "notifications": [
                {"message": "Dashboard live widgets active", "time": "Now"},
                {"message": "API service online", "time": "Today"},
                {"message": "Backup system healthy", "time": "Today"},
            ],
        }
