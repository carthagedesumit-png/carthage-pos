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


def _normalize_inventory_filters(filters=None):
    filters = filters or {}
    status = _safe_text(filters.get("status") or filters.get("active")).lower()
    if status not in {"active", "inactive", "all"}:
        status = "active"
    barcode = _safe_text(filters.get("barcode") or filters.get("has_barcode")).lower()
    if barcode in {"1", "true", "yes", "has", "has_barcode"}:
        barcode = "has"
    elif barcode in {"0", "false", "no", "missing", "missing_barcode"}:
        barcode = "missing"
    elif barcode not in {"all", ""}:
        barcode = "all"
    else:
        barcode = "all"
    return {
        "search": _safe_text(filters.get("search") or filters.get("q")),
        "store_id": _safe_int(filters.get("store_id")),
        "category_id": _safe_int(filters.get("category_id")),
        "supplier_id": _safe_int(filters.get("supplier_id")),
        "low_stock": str(filters.get("low_stock") or "").lower() in {"1", "true", "yes", "on"},
        "out_of_stock": str(filters.get("out_of_stock") or "").lower() in {"1", "true", "yes", "on"},
        "active": status,
        "barcode": barcode,
        "page": _safe_int(filters.get("page"), default=1, minimum=1),
        "page_size": _safe_int(filters.get("page_size"), default=25, minimum=1, maximum=100),
    }


def _barcode_exists_expr(has_identifiers):
    identifier_exists = (
        " OR EXISTS (SELECT 1 FROM product_identifiers pi "
        "WHERE pi.product_id = p.id AND pi.is_active = 1)"
        if has_identifiers else ""
    )
    return f"(p.barcode IS NOT NULL AND TRIM(p.barcode) != ''{identifier_exists})"


def _inventory_query_parts(conn, filters, session=None):
    product_columns = _columns(conn, "products")
    inventory_columns = _columns(conn, "store_inventory")
    store_columns = _columns(conn, "stores")
    category_columns = _columns(conn, "categories")
    supplier_columns = _columns(conn, "suppliers")
    has_identifiers = _table_exists(conn, "product_identifiers")
    has_inventory = bool(inventory_columns)

    quantity_expr = "si.quantity_on_hand" if has_inventory else "p.quantity_in_stock"
    reorder_expr = "si.reorder_level" if has_inventory else "p.reorder_level"
    average_cost_expr = "si.average_cost" if has_inventory else "p.cost_price"
    store_id_expr = "si.store_id" if has_inventory else "NULL"
    store_name_expr = "COALESCE(st.name, st.code, 'Store #' || si.store_id)" if has_inventory and store_columns else "'Main Store'"
    barcode_expr = (
        "COALESCE((SELECT pi.value FROM product_identifiers pi "
        "WHERE pi.product_id = p.id AND pi.is_active = 1 AND pi.is_primary = 1 "
        "ORDER BY pi.id DESC LIMIT 1), p.barcode, '')"
        if has_identifiers else "COALESCE(p.barcode, '')"
    )

    select_fields = [
        "p.id AS product_id",
        "p.name AS product_name",
        "p.sku",
        f"{barcode_expr} AS primary_barcode",
        "p.barcode AS legacy_barcode",
        "p.category_id" if "category_id" in product_columns else "NULL AS category_id",
        "p.supplier_id" if "supplier_id" in product_columns else "NULL AS supplier_id",
        f"{store_id_expr} AS store_id",
        f"{store_name_expr} AS store_name",
        f"COALESCE({quantity_expr}, 0) AS quantity_on_hand",
        f"COALESCE({reorder_expr}, 0) AS reorder_level",
        f"COALESCE({average_cost_expr}, 0) AS average_cost",
        "COALESCE(p.selling_price, 0) AS selling_price",
        "COALESCE(p.is_active, 1) AS is_active",
        "COALESCE(cat.name, 'Uncategorized') AS category_name" if category_columns else "'Uncategorized' AS category_name",
        "COALESCE(sup.name, 'Unassigned') AS supplier_name" if supplier_columns else "'Unassigned' AS supplier_name",
    ]
    joins = []
    if has_inventory:
        joins.append("LEFT JOIN store_inventory si ON si.product_id = p.id")
        if store_columns:
            joins.append("LEFT JOIN stores st ON st.id = si.store_id")
    if category_columns and "category_id" in product_columns:
        joins.append("LEFT JOIN categories cat ON cat.id = p.category_id")
    if supplier_columns and "supplier_id" in product_columns:
        joins.append("LEFT JOIN suppliers sup ON sup.id = p.supplier_id")

    where = ["1 = 1"]
    params = []
    scope = _dashboard_access_scope(session)
    if scope["store_ids"] and has_inventory:
        allowed_ids = [store_id for store_id in scope["store_ids"] if store_id is not None]
        if allowed_ids:
            where.append(f"si.store_id IN ({','.join('?' for _ in allowed_ids)})")
            params.extend(allowed_ids)
    if filters["store_id"] is not None and has_inventory:
        where.append("si.store_id = ?")
        params.append(filters["store_id"])
    if filters["category_id"] is not None and "category_id" in product_columns:
        where.append("p.category_id = ?")
        params.append(filters["category_id"])
    if filters["supplier_id"] is not None and "supplier_id" in product_columns:
        where.append("p.supplier_id = ?")
        params.append(filters["supplier_id"])
    if filters["active"] == "active":
        where.append("COALESCE(p.is_active, 1) = 1")
    elif filters["active"] == "inactive":
        where.append("COALESCE(p.is_active, 1) = 0")
    if filters["low_stock"]:
        where.append(f"COALESCE({quantity_expr}, 0) <= COALESCE({reorder_expr}, 0)")
    if filters["out_of_stock"]:
        where.append(f"COALESCE({quantity_expr}, 0) = 0")
    barcode_exists = _barcode_exists_expr(has_identifiers)
    if filters["barcode"] == "has":
        where.append(barcode_exists)
    elif filters["barcode"] == "missing":
        where.append(f"NOT {barcode_exists}")
    if filters["search"]:
        pattern = f"%{filters['search']}%"
        terms = ["p.name LIKE ?", "p.sku LIKE ?", "p.barcode LIKE ?"]
        params.extend([pattern, pattern, pattern])
        if has_identifiers:
            terms.append(
                "EXISTS (SELECT 1 FROM product_identifiers pi "
                "WHERE pi.product_id = p.id AND pi.is_active = 1 AND pi.value LIKE ?)"
            )
            params.append(pattern)
        where.append(f"({' OR '.join(terms)})")

    return {
        "select": ", ".join(select_fields),
        "from": "products p",
        "joins": "\n".join(joins),
        "where": " AND ".join(where),
        "params": params,
        "quantity_expr": quantity_expr,
        "reorder_expr": reorder_expr,
        "average_cost_expr": average_cost_expr,
        "barcode_exists": barcode_exists,
        "has_inventory": has_inventory,
    }


def _format_inventory_row(row):
    quantity = int(row["quantity_on_hand"] or 0)
    reorder = int(row["reorder_level"] or 0)
    average_cost = float(row["average_cost"] or 0)
    selling_price = float(row["selling_price"] or 0)
    value = quantity * average_cost
    barcode = row["primary_barcode"] or row["legacy_barcode"] or ""
    if quantity <= 0:
        stock_status = "out of stock"
    elif quantity <= reorder:
        stock_status = "low stock"
    else:
        stock_status = "in stock"
    return {
        "product_id": row["product_id"],
        "name": row["product_name"] or "Unnamed product",
        "sku": row["sku"] or f"PRODUCT-{row['product_id']}",
        "barcode": barcode,
        "has_barcode": bool(barcode),
        "category": row["category_name"] or "Uncategorized",
        "supplier": row["supplier_name"] or "Unassigned",
        "store": row["store_name"] or "Main Store",
        "store_id": row["store_id"],
        "quantity_on_hand": quantity,
        "reorder_level": reorder,
        "average_cost": average_cost,
        "average_cost_display": money(average_cost),
        "selling_price": selling_price,
        "selling_price_display": money(selling_price),
        "inventory_value": value,
        "inventory_value_display": money(value),
        "is_active": bool(row["is_active"]),
        "active_status": "active" if row["is_active"] else "inactive",
        "stock_status": stock_status,
    }


def _empty_inventory_summary():
    return {
        "product_rows": 0,
        "active_rows": 0,
        "inventory_value": 0,
        "inventory_value_display": money(0),
        "low_stock": 0,
        "out_of_stock": 0,
        "missing_barcode": 0,
    }


def _dashboard_inventory_summary_from_parts(conn, parts):
    row = conn.execute(
        f"""SELECT COUNT(*) AS product_rows,
                   COALESCE(SUM(CASE WHEN COALESCE(p.is_active, 1) = 1 THEN 1 ELSE 0 END), 0) AS active_rows,
                   COALESCE(SUM(COALESCE({parts['quantity_expr']}, 0) * COALESCE({parts['average_cost_expr']}, 0)), 0) AS inventory_value,
                   COALESCE(SUM(CASE WHEN COALESCE({parts['quantity_expr']}, 0) <= COALESCE({parts['reorder_expr']}, 0) THEN 1 ELSE 0 END), 0) AS low_stock,
                   COALESCE(SUM(CASE WHEN COALESCE({parts['quantity_expr']}, 0) = 0 THEN 1 ELSE 0 END), 0) AS out_of_stock,
                   COALESCE(SUM(CASE WHEN NOT {parts['barcode_exists']} THEN 1 ELSE 0 END), 0) AS missing_barcode
            FROM {parts['from']}
            {parts['joins']}
            WHERE {parts['where']}""",
        parts["params"],
    ).fetchone()
    value = float(row["inventory_value"] or 0)
    return {
        "product_rows": int(row["product_rows"] or 0),
        "active_rows": int(row["active_rows"] or 0),
        "inventory_value": value,
        "inventory_value_display": money(value),
        "low_stock": int(row["low_stock"] or 0),
        "out_of_stock": int(row["out_of_stock"] or 0),
        "missing_barcode": int(row["missing_barcode"] or 0),
    }


def get_dashboard_inventory_summary(filters=None, session=None):
    filters = _normalize_inventory_filters(filters)
    with get_connection() as conn:
        if not _table_exists(conn, "products"):
            return _empty_inventory_summary()
        parts = _inventory_query_parts(conn, filters, session=session)
        return _dashboard_inventory_summary_from_parts(conn, parts)


def list_dashboard_inventory(filters=None, session=None):
    filters = _normalize_inventory_filters(filters)
    with get_connection() as conn:
        if not _table_exists(conn, "products"):
            total = 0
            rows = []
            summary = _empty_inventory_summary()
        else:
            parts = _inventory_query_parts(conn, filters, session=session)
            total = conn.execute(
                f"""SELECT COUNT(*)
                    FROM {parts['from']}
                    {parts['joins']}
                    WHERE {parts['where']}""",
                parts["params"],
            ).fetchone()[0]
            total_pages = max(1, ceil(total / filters["page_size"]))
            filters["page"] = min(filters["page"], total_pages)
            offset = (filters["page"] - 1) * filters["page_size"]
            rows = conn.execute(
                f"""SELECT {parts['select']}
                    FROM {parts['from']}
                    {parts['joins']}
                    WHERE {parts['where']}
                    ORDER BY p.name COLLATE NOCASE, p.id, store_name
                    LIMIT ? OFFSET ?""",
                [*parts["params"], filters["page_size"], offset],
            ).fetchall()
            summary = _dashboard_inventory_summary_from_parts(conn, parts)

    total_pages = max(1, ceil(total / filters["page_size"]))
    page = filters["page"]
    return {
        "items": [_format_inventory_row(row) for row in rows],
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


def get_dashboard_low_stock_inventory(limit=50, session=None):
    result = list_dashboard_inventory(
        {"low_stock": True, "active": "active", "page": 1, "page_size": limit},
        session=session,
    )
    return result["items"]


def get_dashboard_inventory_valuation(filters=None, session=None):
    filters = _normalize_inventory_filters(filters)
    summary = get_dashboard_inventory_summary(filters, session=session)
    by_store = []
    with get_connection() as conn:
        if _table_exists(conn, "products") and _table_exists(conn, "store_inventory"):
            parts = _inventory_query_parts(conn, filters, session=session)
            if _table_exists(conn, "stores"):
                rows = conn.execute(
                    f"""SELECT si.store_id,
                               COALESCE(st.name, st.code, 'Store #' || si.store_id) AS store_name,
                               COALESCE(SUM(si.quantity_on_hand * si.average_cost), 0) AS inventory_value,
                               COALESCE(SUM(si.quantity_on_hand), 0) AS quantity_on_hand
                        FROM products p
                        LEFT JOIN store_inventory si ON si.product_id = p.id
                        LEFT JOIN stores st ON st.id = si.store_id
                        WHERE {parts['where']}
                        GROUP BY si.store_id, store_name
                        ORDER BY inventory_value DESC""",
                    parts["params"],
                ).fetchall()
                by_store = [
                    {
                        "store_id": row["store_id"],
                        "store": row["store_name"] or "Main Store",
                        "quantity_on_hand": int(row["quantity_on_hand"] or 0),
                        "inventory_value": float(row["inventory_value"] or 0),
                        "inventory_value_display": money(row["inventory_value"]),
                    }
                    for row in rows
                ]
    return {"summary": summary, "by_store": by_store}


def get_dashboard_product_detail(product_id, session=None):
    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        return None
    with get_connection() as conn:
        if not _table_exists(conn, "products"):
            return None
        product_columns = _columns(conn, "products")
        joins = []
        fields = ["p.*"]
        if _table_exists(conn, "categories") and "category_id" in product_columns:
            joins.append("LEFT JOIN categories cat ON cat.id = p.category_id")
            fields.append("COALESCE(cat.name, 'Uncategorized') AS category_name")
        else:
            fields.append("'Uncategorized' AS category_name")
        if _table_exists(conn, "suppliers") and "supplier_id" in product_columns:
            joins.append("LEFT JOIN suppliers sup ON sup.id = p.supplier_id")
            fields.append("COALESCE(sup.name, 'Unassigned') AS supplier_name")
        else:
            fields.append("'Unassigned' AS supplier_name")
        row = conn.execute(
            f"SELECT {', '.join(fields)} FROM products p {' '.join(joins)} WHERE p.id = ?",
            (product_id,),
        ).fetchone()
        if not row:
            return None
        product = dict(row)

        identifiers = []
        if _table_exists(conn, "product_identifiers"):
            identifiers = [
                dict(item)
                for item in conn.execute(
                    """SELECT id, identifier_type, format, value, is_primary, is_active, created_at
                       FROM product_identifiers
                       WHERE product_id = ?
                       ORDER BY is_primary DESC, is_active DESC, id DESC""",
                    (product_id,),
                ).fetchall()
            ]
        elif product.get("barcode"):
            identifiers = [{
                "id": None,
                "identifier_type": "PRIMARY",
                "format": "LEGACY",
                "value": product["barcode"],
                "is_primary": 1,
                "is_active": 1,
                "created_at": product.get("created_at"),
            }]

        stock_by_store = []
        if _table_exists(conn, "store_inventory"):
            store_join = "LEFT JOIN stores st ON st.id = si.store_id" if _table_exists(conn, "stores") else ""
            store_name = "COALESCE(st.name, st.code, 'Store #' || si.store_id)" if _table_exists(conn, "stores") else "'Main Store'"
            stock_by_store = [
                {
                    **dict(item),
                    "inventory_value": float(item["quantity_on_hand"] or 0) * float(item["average_cost"] or 0),
                    "inventory_value_display": money(float(item["quantity_on_hand"] or 0) * float(item["average_cost"] or 0)),
                }
                for item in conn.execute(
                    f"""SELECT si.store_id, {store_name} AS store_name,
                               si.quantity_on_hand, si.reorder_level, si.average_cost, si.updated_at
                        FROM store_inventory si
                        {store_join}
                        WHERE si.product_id = ?
                        ORDER BY store_name""",
                    (product_id,),
                ).fetchall()
            ]

        movements = []
        if _table_exists(conn, "stock_movements"):
            movements = [
                dict(item)
                for item in conn.execute(
                    """SELECT sm.id, sm.movement_type, sm.quantity, sm.previous_quantity,
                              sm.new_quantity, sm.notes, sm.created_at,
                              COALESCE(st.name, st.code, 'Store #' || sm.store_id) AS store_name,
                              COALESCE(u.full_name, u.username, 'system') AS username
                       FROM stock_movements sm
                       LEFT JOIN stores st ON st.id = sm.store_id
                       LEFT JOIN users u ON u.id = sm.user_id
                       WHERE sm.product_id = ?
                       ORDER BY sm.created_at DESC, sm.id DESC
                       LIMIT 25""",
                    (product_id,),
                ).fetchall()
            ]

        procurement = []
        if _table_exists(conn, "purchase_order_items") and _table_exists(conn, "purchase_orders"):
            procurement = [
                dict(item)
                for item in conn.execute(
                    """SELECT po.id, po.reference_number, po.status, po.created_at,
                              poi.ordered_quantity, poi.received_quantity, poi.unit_cost, poi.subtotal,
                              COALESCE(s.name, 'Unassigned') AS supplier_name,
                              COALESCE(st.name, st.code, 'Store #' || po.store_id) AS store_name
                       FROM purchase_order_items poi
                       JOIN purchase_orders po ON po.id = poi.purchase_order_id
                       LEFT JOIN suppliers s ON s.id = po.supplier_id
                       LEFT JOIN stores st ON st.id = po.store_id
                       WHERE poi.product_id = ?
                       ORDER BY po.created_at DESC, po.id DESC
                       LIMIT 10""",
                    (product_id,),
                ).fetchall()
            ]

    primary_barcode = next((item["value"] for item in identifiers if item.get("is_primary") and item.get("is_active")), None)
    product["primary_barcode"] = primary_barcode or product.get("barcode") or ""
    product["has_barcode"] = bool(product["primary_barcode"])
    product["selling_price_display"] = money(product.get("selling_price"))
    product["cost_price_display"] = money(product.get("cost_price"))
    return {
        "product": product,
        "identifiers": identifiers,
        "stock_by_store": stock_by_store,
        "movements": movements,
        "procurement": procurement,
        "label_actions": [
            {"label": "Preview Label", "enabled": False},
            {"label": "Print Label", "enabled": False},
        ],
    }


def _normalize_crm_filters(filters=None):
    filters = filters or {}
    status = _safe_text(filters.get("status") or filters.get("active")).lower()
    if status not in {"active", "inactive", "all"}:
        status = "active"
    group_value = filters.get("customer_group")
    if group_value in (None, ""):
        group_value = filters.get("group_id")
    return {
        "search": _safe_text(filters.get("search") or filters.get("q")),
        "customer_group": _safe_text(group_value),
        "active": status,
        "has_credit": str(filters.get("has_credit") or "").lower() in {"1", "true", "yes", "on"},
        "has_wallet_balance": str(filters.get("has_wallet_balance") or "").lower() in {"1", "true", "yes", "on"},
        "loyalty_customer": str(filters.get("loyalty_customer") or "").lower() in {"1", "true", "yes", "on"},
        "joined_from": _safe_text(filters.get("joined_from") or filters.get("date_from")),
        "joined_to": _safe_text(filters.get("joined_to") or filters.get("date_to")),
        "page": _safe_int(filters.get("page"), default=1, minimum=1),
        "page_size": _safe_int(filters.get("page_size"), default=25, minimum=1, maximum=100),
    }


def _customer_display_name(row):
    business = _safe_text(_row_value(row, "business_name"))
    first = _safe_text(_row_value(row, "first_name"))
    last = _safe_text(_row_value(row, "last_name"))
    name = business or " ".join(part for part in [first, last] if part)
    return name or _safe_text(_row_value(row, "customer_code")) or f"Customer #{_row_value(row, 'id', '')}"


def _ledger_sum_expr(table_name, amount_column):
    return (
        f"(SELECT COALESCE(SUM({amount_column}), 0) FROM {table_name} "
        f"WHERE {table_name}.customer_id = c.id)"
    )


def _crm_sales_stats_exprs(has_sales, sales_columns):
    if not has_sales or "customer_id" not in sales_columns:
        return {
            "purchase_count": "0",
            "lifetime_value": "0",
            "last_purchase_date": "NULL",
        }
    total_expr = "s.total_amount" if "total_amount" in sales_columns else "s.total"
    date_expr = "s.created_at" if "created_at" in sales_columns else "s.timestamp"
    return {
        "purchase_count": "(SELECT COUNT(*) FROM sales s WHERE s.customer_id = c.id)",
        "lifetime_value": f"(SELECT COALESCE(SUM({total_expr}), 0) FROM sales s WHERE s.customer_id = c.id)",
        "last_purchase_date": f"(SELECT MAX({date_expr}) FROM sales s WHERE s.customer_id = c.id)",
    }


def _crm_query_parts(conn, filters, session=None):
    customer_columns = _columns(conn, "customers")
    group_columns = _columns(conn, "customer_groups")
    sales_columns = _columns(conn, "sales")
    has_groups = bool(group_columns) and "group_id" in customer_columns
    has_sales = _table_exists(conn, "sales")
    has_wallet = _table_exists(conn, "wallet_transactions")
    has_loyalty = _table_exists(conn, "loyalty_transactions")
    has_credit = _table_exists(conn, "credit_transactions")

    wallet_expr = _ledger_sum_expr("wallet_transactions", "amount_delta") if has_wallet else "0"
    loyalty_expr = _ledger_sum_expr("loyalty_transactions", "points_delta") if has_loyalty else "0"
    credit_expr = _ledger_sum_expr("credit_transactions", "amount_delta") if has_credit else "0"
    sales_exprs = _crm_sales_stats_exprs(has_sales, sales_columns)

    select_fields = [
        "c.id",
        "c.customer_code" if "customer_code" in customer_columns else "CAST(c.id AS TEXT) AS customer_code",
        "c.first_name" if "first_name" in customer_columns else "'' AS first_name",
        "c.last_name" if "last_name" in customer_columns else "'' AS last_name",
        "c.business_name" if "business_name" in customer_columns else "NULL AS business_name",
        "c.phone_number" if "phone_number" in customer_columns else "NULL AS phone_number",
        "c.email" if "email" in customer_columns else "NULL AS email",
        "c.created_at" if "created_at" in customer_columns else "NULL AS created_at",
        "COALESCE(c.is_active, 1) AS is_active" if "is_active" in customer_columns else "1 AS is_active",
        "c.group_id" if "group_id" in customer_columns else "NULL AS group_id",
        "COALESCE(c.credit_limit, 0) AS credit_limit" if "credit_limit" in customer_columns else "0 AS credit_limit",
        f"{wallet_expr} AS wallet_balance",
        f"{loyalty_expr} AS loyalty_points",
        f"{credit_expr} AS outstanding_credit",
        f"{sales_exprs['purchase_count']} AS purchase_count",
        f"{sales_exprs['lifetime_value']} AS lifetime_value",
        f"{sales_exprs['last_purchase_date']} AS last_purchase_date",
    ]
    joins = []
    if has_groups:
        joins.append("LEFT JOIN customer_groups cg ON cg.id = c.group_id")
        select_fields.append("COALESCE(cg.name, 'Retail') AS group_name")
    else:
        select_fields.append("'Retail' AS group_name")

    where = ["1 = 1"]
    params = []
    if filters["active"] == "active" and "is_active" in customer_columns:
        where.append("COALESCE(c.is_active, 1) = 1")
    elif filters["active"] == "inactive" and "is_active" in customer_columns:
        where.append("COALESCE(c.is_active, 1) = 0")
    if filters["customer_group"] and has_groups:
        group_id = _safe_int(filters["customer_group"])
        if group_id is not None:
            where.append("c.group_id = ?")
            params.append(group_id)
        else:
            where.append("cg.name LIKE ?")
            params.append(f"%{filters['customer_group']}%")
    if filters["joined_from"] and "created_at" in customer_columns:
        where.append("DATE(c.created_at) >= DATE(?)")
        params.append(filters["joined_from"])
    if filters["joined_to"] and "created_at" in customer_columns:
        where.append("DATE(c.created_at) <= DATE(?)")
        params.append(filters["joined_to"])
    if filters["has_credit"]:
        where.append(f"({credit_expr}) > 0")
    if filters["has_wallet_balance"]:
        where.append(f"({wallet_expr}) > 0")
    if filters["loyalty_customer"]:
        where.append(f"({loyalty_expr}) > 0")
    if filters["search"]:
        pattern = f"%{filters['search']}%"
        search_terms = []
        for column in ["customer_code", "first_name", "last_name", "business_name", "phone_number", "email"]:
            if column in customer_columns:
                search_terms.append(f"c.{column} LIKE ?")
                params.append(pattern)
        if search_terms:
            where.append(f"({' OR '.join(search_terms)})")

    return {
        "select": ", ".join(select_fields),
        "from": "customers c",
        "joins": "\n".join(joins),
        "where": " AND ".join(where),
        "params": params,
        "wallet_expr": wallet_expr,
        "loyalty_expr": loyalty_expr,
        "credit_expr": credit_expr,
        "purchase_count_expr": sales_exprs["purchase_count"],
        "lifetime_value_expr": sales_exprs["lifetime_value"],
    }


def _format_crm_row(row):
    wallet = float(row["wallet_balance"] or 0)
    credit = float(row["outstanding_credit"] or 0)
    lifetime_value = float(row["lifetime_value"] or 0)
    loyalty = int(row["loyalty_points"] or 0)
    return {
        "customer_id": row["id"],
        "customer_code": row["customer_code"] or f"Customer #{row['id']}",
        "name": _customer_display_name(row),
        "phone": row["phone_number"] or "",
        "email": row["email"] or "",
        "group": row["group_name"] or "Retail",
        "wallet_balance": wallet,
        "wallet_balance_display": money(wallet),
        "loyalty_points": loyalty,
        "outstanding_credit": credit,
        "outstanding_credit_display": money(credit),
        "lifetime_value": lifetime_value,
        "lifetime_value_display": money(lifetime_value),
        "last_purchase_date": row["last_purchase_date"] or "",
        "purchase_count": int(row["purchase_count"] or 0),
        "is_active": bool(row["is_active"]),
        "active_status": "active" if row["is_active"] else "inactive",
        "credit_status": "credit due" if credit > 0 else "clear",
        "loyalty_status": "loyalty" if loyalty > 0 else "standard",
    }


def _empty_crm_summary():
    return {
        "customer_count": 0,
        "active_customers": 0,
        "wallet_balance": 0,
        "wallet_balance_display": money(0),
        "loyalty_points": 0,
        "outstanding_credit": 0,
        "outstanding_credit_display": money(0),
        "lifetime_value": 0,
        "lifetime_value_display": money(0),
    }


def _dashboard_crm_summary_from_parts(conn, parts):
    row = conn.execute(
        f"""SELECT COUNT(*) AS customer_count,
                   COALESCE(SUM(CASE WHEN COALESCE(c.is_active, 1) = 1 THEN 1 ELSE 0 END), 0) AS active_customers,
                   COALESCE(SUM({parts['wallet_expr']}), 0) AS wallet_balance,
                   COALESCE(SUM({parts['loyalty_expr']}), 0) AS loyalty_points,
                   COALESCE(SUM({parts['credit_expr']}), 0) AS outstanding_credit,
                   COALESCE(SUM({parts['lifetime_value_expr']}), 0) AS lifetime_value
            FROM {parts['from']}
            {parts['joins']}
            WHERE {parts['where']}""",
        parts["params"],
    ).fetchone()
    wallet = float(row["wallet_balance"] or 0)
    credit = float(row["outstanding_credit"] or 0)
    lifetime_value = float(row["lifetime_value"] or 0)
    return {
        "customer_count": int(row["customer_count"] or 0),
        "active_customers": int(row["active_customers"] or 0),
        "wallet_balance": wallet,
        "wallet_balance_display": money(wallet),
        "loyalty_points": int(row["loyalty_points"] or 0),
        "outstanding_credit": credit,
        "outstanding_credit_display": money(credit),
        "lifetime_value": lifetime_value,
        "lifetime_value_display": money(lifetime_value),
    }


def get_dashboard_crm_summary(filters=None, session=None):
    filters = _normalize_crm_filters(filters)
    with get_connection() as conn:
        if not _table_exists(conn, "customers"):
            return _empty_crm_summary()
        parts = _crm_query_parts(conn, filters, session=session)
        return _dashboard_crm_summary_from_parts(conn, parts)


def list_dashboard_customers(filters=None, session=None):
    filters = _normalize_crm_filters(filters)
    if filters["joined_from"] and filters["joined_to"] and filters["joined_from"] > filters["joined_to"]:
        filters["joined_from"], filters["joined_to"] = filters["joined_to"], filters["joined_from"]
    with get_connection() as conn:
        if not _table_exists(conn, "customers"):
            total = 0
            rows = []
            summary = _empty_crm_summary()
        else:
            parts = _crm_query_parts(conn, filters, session=session)
            total = conn.execute(
                f"""SELECT COUNT(*)
                    FROM {parts['from']}
                    {parts['joins']}
                    WHERE {parts['where']}""",
                parts["params"],
            ).fetchone()[0]
            total_pages = max(1, ceil(total / filters["page_size"]))
            filters["page"] = min(filters["page"], total_pages)
            offset = (filters["page"] - 1) * filters["page_size"]
            rows = conn.execute(
                f"""SELECT {parts['select']}
                    FROM {parts['from']}
                    {parts['joins']}
                    WHERE {parts['where']}
                    ORDER BY lifetime_value DESC, last_purchase_date DESC, c.first_name COLLATE NOCASE, c.last_name COLLATE NOCASE
                    LIMIT ? OFFSET ?""",
                [*parts["params"], filters["page_size"], offset],
            ).fetchall()
            summary = _dashboard_crm_summary_from_parts(conn, parts)

    total_pages = max(1, ceil(total / filters["page_size"]))
    page = filters["page"]
    return {
        "items": [_format_crm_row(row) for row in rows],
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


def get_dashboard_top_customers(limit=10, session=None):
    result = list_dashboard_customers(
        {"active": "all", "page": 1, "page_size": limit},
        session=session,
    )
    return result["items"]


def _ledger_activity(conn, table_name, amount_column, customer_id, limit=25):
    if not _table_exists(conn, table_name):
        return []
    return [
        dict(row)
        for row in conn.execute(
            f"""SELECT id, transaction_type, {amount_column} AS amount_delta,
                      balance_after, sale_id, sales_return_id, store_id, notes, created_at
                FROM {table_name}
                WHERE customer_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?""",
            (customer_id, limit),
        ).fetchall()
    ]


def get_dashboard_customer_activity(customer_id, session=None):
    try:
        customer_id = int(customer_id)
    except (TypeError, ValueError):
        return None
    with get_connection() as conn:
        if not _table_exists(conn, "customers"):
            return None
        if not conn.execute("SELECT 1 FROM customers WHERE id = ?", (customer_id,)).fetchone():
            return None
        sales = []
        if _table_exists(conn, "sales") and "customer_id" in _columns(conn, "sales"):
            sales_columns = _columns(conn, "sales")
            total_expr = "total_amount" if "total_amount" in sales_columns else "total"
            date_expr = "created_at" if "created_at" in sales_columns else "timestamp"
            receipt_expr = "receipt_number" if "receipt_number" in sales_columns else "sale_id"
            sales = [
                dict(row)
                for row in conn.execute(
                    f"""SELECT sale_id, {receipt_expr} AS receipt_number,
                              {date_expr} AS sale_time, {total_expr} AS total_amount,
                              payment_method
                       FROM sales
                       WHERE customer_id = ?
                       ORDER BY {date_expr} DESC, sale_id DESC
                       LIMIT 25""",
                    (customer_id,),
                ).fetchall()
            ]
        return {
            "recent_sales": sales,
            "wallet": _ledger_activity(conn, "wallet_transactions", "amount_delta", customer_id),
            "loyalty": _ledger_activity(conn, "loyalty_transactions", "points_delta", customer_id),
            "credit": _ledger_activity(conn, "credit_transactions", "amount_delta", customer_id),
        }


def get_dashboard_customer_detail(customer_id, session=None):
    try:
        customer_id = int(customer_id)
    except (TypeError, ValueError):
        return None
    with get_connection() as conn:
        if not _table_exists(conn, "customers"):
            return None
        filters = {"active": "all", "page": 1, "page_size": 1}
        parts = _crm_query_parts(conn, _normalize_crm_filters(filters), session=session)
        row = conn.execute(
            f"""SELECT {parts['select']}
                FROM {parts['from']}
                {parts['joins']}
                WHERE c.id = ?""",
            (customer_id,),
        ).fetchone()
        if not row:
            return None
        customer = _format_crm_row(row)
        raw = dict(row)
        for field in ["address", "city", "state", "country", "date_of_birth", "gender", "tax_number", "notes", "created_at"]:
            raw[field] = _row_value(row, field)
        activity = get_dashboard_customer_activity(customer_id, session=session)
    return {
        "customer": customer,
        "profile": raw,
        "activity": activity or {"recent_sales": [], "wallet": [], "loyalty": [], "credit": []},
        "actions": [
            {"label": "Statement", "enabled": False},
            {"label": "Print", "enabled": False},
            {"label": "Export", "enabled": False},
        ],
    }


PROCUREMENT_STATUSES = {
    "DRAFT",
    "SUBMITTED",
    "PARTIALLY_RECEIVED",
    "FULLY_RECEIVED",
    "CANCELLED",
}


def _safe_bool(value):
    return str(value or "").lower() in {"1", "true", "yes", "on"}


def _empty_procurement_summary():
    return {
        "purchase_order_count": 0,
        "pending_count": 0,
        "partial_count": 0,
        "completed_count": 0,
        "cancelled_count": 0,
        "supplier_count": 0,
        "ordered_quantity": 0,
        "received_quantity": 0,
        "estimated_value": 0,
        "estimated_value_display": money(0),
    }


def _normalize_procurement_filters(filters=None):
    filters = filters or {}
    status = _safe_text(filters.get("status")).upper()
    if status not in PROCUREMENT_STATUSES:
        status = ""
    return {
        "search": _safe_text(filters.get("search") or filters.get("q")),
        "supplier_id": _safe_int(filters.get("supplier_id")),
        "store_id": _safe_int(filters.get("store_id")),
        "status": status,
        "date_from": _safe_text(filters.get("date_from")),
        "date_to": _safe_text(filters.get("date_to")),
        "pending_only": _safe_bool(filters.get("pending_only")),
        "partially_received": _safe_bool(filters.get("partially_received")),
        "completed": _safe_bool(filters.get("completed")),
        "cancelled": _safe_bool(filters.get("cancelled")),
        "page": _safe_int(filters.get("page"), default=1, minimum=1),
        "page_size": _safe_int(filters.get("page_size"), default=25, minimum=1, maximum=100),
    }


def _po_badge(status, ordered_quantity, received_quantity):
    status = _safe_text(status).upper()
    ordered = int(ordered_quantity or 0)
    received = int(received_quantity or 0)
    if status == "CANCELLED":
        return "cancelled"
    if status == "DRAFT":
        return "draft"
    if ordered > 0 and received >= ordered:
        return "complete"
    if received > 0 or status == "PARTIALLY_RECEIVED":
        return "partial"
    return "outstanding"


def _procurement_query_parts(conn, filters, session=None):
    supplier_columns = _columns(conn, "suppliers")
    store_columns = _columns(conn, "stores")
    user_columns = _columns(conn, "users")
    has_items = _table_exists(conn, "purchase_order_items")

    item_join = (
        """LEFT JOIN (
               SELECT purchase_order_id,
                      COALESCE(SUM(ordered_quantity), 0) AS ordered_quantity,
                      COALESCE(SUM(received_quantity), 0) AS received_quantity,
                      COALESCE(SUM(subtotal), 0) AS estimated_value
               FROM purchase_order_items
               GROUP BY purchase_order_id
           ) poi ON poi.purchase_order_id = po.id"""
        if has_items else
        """LEFT JOIN (
               SELECT NULL AS purchase_order_id, 0 AS ordered_quantity,
                      0 AS received_quantity, 0 AS estimated_value
           ) poi ON 1 = 0"""
    )
    joins = [item_join]
    if supplier_columns:
        joins.append("LEFT JOIN suppliers s ON s.id = po.supplier_id")
    if store_columns:
        joins.append("LEFT JOIN stores st ON st.id = po.store_id")
    if user_columns:
        joins.append("LEFT JOIN users u ON u.id = po.created_by")

    supplier_name = "COALESCE(s.name, 'Supplier #' || po.supplier_id)" if supplier_columns else "'Supplier #' || po.supplier_id"
    store_name = "COALESCE(st.name, st.code, 'Store #' || po.store_id)" if store_columns else "'Store #' || po.store_id"
    user_name = "COALESCE(u.full_name, u.username, 'User #' || po.created_by)" if user_columns else "'User #' || po.created_by"

    select_fields = [
        "po.id",
        "po.supplier_id",
        "po.store_id",
        "po.reference_number",
        "po.status",
        "po.expected_delivery_date",
        "po.created_at",
        "po.submitted_at",
        "po.cancelled_at",
        "po.created_by",
        "po.notes",
        f"{supplier_name} AS supplier_name",
        f"{store_name} AS store_name",
        f"{user_name} AS created_by_name",
        "COALESCE(poi.ordered_quantity, 0) AS ordered_quantity",
        "COALESCE(poi.received_quantity, 0) AS received_quantity",
        "COALESCE(poi.estimated_value, 0) AS estimated_value",
    ]

    where = ["1 = 1"]
    params = []
    scope = _dashboard_access_scope(session)
    if scope["store_ids"]:
        allowed_ids = [store_id for store_id in scope["store_ids"] if store_id is not None]
        if allowed_ids:
            where.append(f"po.store_id IN ({','.join('?' for _ in allowed_ids)})")
            params.extend(allowed_ids)
    if filters["supplier_id"] is not None:
        where.append("po.supplier_id = ?")
        params.append(filters["supplier_id"])
    if filters["store_id"] is not None:
        where.append("po.store_id = ?")
        params.append(filters["store_id"])
    if filters["status"]:
        where.append("po.status = ?")
        params.append(filters["status"])
    if filters["date_from"]:
        where.append("DATE(po.created_at) >= DATE(?)")
        params.append(filters["date_from"])
    if filters["date_to"]:
        where.append("DATE(po.created_at) <= DATE(?)")
        params.append(filters["date_to"])
    if filters["pending_only"]:
        where.append(
            "po.status NOT IN ('FULLY_RECEIVED', 'CANCELLED') "
            "AND COALESCE(poi.received_quantity, 0) < COALESCE(poi.ordered_quantity, 0)"
        )
    if filters["partially_received"]:
        where.append(
            "(po.status = 'PARTIALLY_RECEIVED' OR "
            "(COALESCE(poi.received_quantity, 0) > 0 "
            "AND COALESCE(poi.received_quantity, 0) < COALESCE(poi.ordered_quantity, 0)))"
        )
    if filters["completed"]:
        where.append(
            "(po.status = 'FULLY_RECEIVED' OR "
            "(COALESCE(poi.ordered_quantity, 0) > 0 "
            "AND COALESCE(poi.received_quantity, 0) >= COALESCE(poi.ordered_quantity, 0)))"
        )
    if filters["cancelled"]:
        where.append("po.status = 'CANCELLED'")
    if filters["search"]:
        pattern = f"%{filters['search']}%"
        terms = ["po.reference_number LIKE ?", "po.status LIKE ?", "po.notes LIKE ?"]
        params.extend([pattern, pattern, pattern])
        if supplier_columns:
            terms.append("s.name LIKE ?")
            params.append(pattern)
        where.append(f"({' OR '.join(terms)})")

    return {
        "select": ", ".join(select_fields),
        "joins": "\n".join(joins),
        "where": " AND ".join(where),
        "params": params,
    }


def _format_procurement_row(row):
    ordered = int(row["ordered_quantity"] or 0)
    received = int(row["received_quantity"] or 0)
    remaining = max(ordered - received, 0)
    value = float(row["estimated_value"] or 0)
    badge = _po_badge(row["status"], ordered, received)
    return {
        "id": row["id"],
        "purchase_order_id": row["id"],
        "reference_number": row["reference_number"] or f"PO-{row['id']}",
        "supplier_id": row["supplier_id"],
        "supplier_name": row["supplier_name"],
        "store_id": row["store_id"],
        "store_name": row["store_name"],
        "status": row["status"] or "DRAFT",
        "status_label": _safe_text(row["status"]).replace("_", " ").title() or "Draft",
        "badge": badge,
        "expected_delivery_date": row["expected_delivery_date"] or "",
        "created_at": row["created_at"] or "",
        "submitted_at": row["submitted_at"] or "",
        "cancelled_at": row["cancelled_at"] or "",
        "created_by": row["created_by_name"] or "system",
        "ordered_quantity": ordered,
        "received_quantity": received,
        "remaining_quantity": remaining,
        "estimated_value": value,
        "estimated_value_display": money(value),
    }


def _dashboard_procurement_summary_from_parts(conn, parts):
    row = conn.execute(
        f"""SELECT COUNT(*) AS purchase_order_count,
                   COALESCE(SUM(CASE WHEN po.status NOT IN ('FULLY_RECEIVED', 'CANCELLED')
                       AND COALESCE(poi.received_quantity, 0) < COALESCE(poi.ordered_quantity, 0)
                       THEN 1 ELSE 0 END), 0) AS pending_count,
                   COALESCE(SUM(CASE WHEN po.status = 'PARTIALLY_RECEIVED'
                       OR (COALESCE(poi.received_quantity, 0) > 0
                           AND COALESCE(poi.received_quantity, 0) < COALESCE(poi.ordered_quantity, 0))
                       THEN 1 ELSE 0 END), 0) AS partial_count,
                   COALESCE(SUM(CASE WHEN po.status = 'FULLY_RECEIVED'
                       OR (COALESCE(poi.ordered_quantity, 0) > 0
                           AND COALESCE(poi.received_quantity, 0) >= COALESCE(poi.ordered_quantity, 0))
                       THEN 1 ELSE 0 END), 0) AS completed_count,
                   COALESCE(SUM(CASE WHEN po.status = 'CANCELLED' THEN 1 ELSE 0 END), 0) AS cancelled_count,
                   COALESCE(SUM(COALESCE(poi.ordered_quantity, 0)), 0) AS ordered_quantity,
                   COALESCE(SUM(COALESCE(poi.received_quantity, 0)), 0) AS received_quantity,
                   COALESCE(SUM(COALESCE(poi.estimated_value, 0)), 0) AS estimated_value
            FROM purchase_orders po
            {parts['joins']}
            WHERE {parts['where']}""",
        parts["params"],
    ).fetchone()
    supplier_count = count_table(conn, "suppliers")
    value = float(row["estimated_value"] or 0)
    return {
        "purchase_order_count": int(row["purchase_order_count"] or 0),
        "pending_count": int(row["pending_count"] or 0),
        "partial_count": int(row["partial_count"] or 0),
        "completed_count": int(row["completed_count"] or 0),
        "cancelled_count": int(row["cancelled_count"] or 0),
        "supplier_count": supplier_count,
        "ordered_quantity": int(row["ordered_quantity"] or 0),
        "received_quantity": int(row["received_quantity"] or 0),
        "estimated_value": value,
        "estimated_value_display": money(value),
    }


def get_dashboard_procurement_summary(filters=None, session=None):
    filters = _normalize_procurement_filters(filters)
    with get_connection() as conn:
        if not _table_exists(conn, "purchase_orders"):
            return _empty_procurement_summary()
        parts = _procurement_query_parts(conn, filters, session=session)
        return _dashboard_procurement_summary_from_parts(conn, parts)


def list_dashboard_procurement(filters=None, session=None):
    filters = _normalize_procurement_filters(filters)
    if filters["date_from"] and filters["date_to"] and filters["date_from"] > filters["date_to"]:
        filters["date_from"], filters["date_to"] = filters["date_to"], filters["date_from"]
    with get_connection() as conn:
        if not _table_exists(conn, "purchase_orders"):
            total = 0
            rows = []
            summary = _empty_procurement_summary()
        else:
            parts = _procurement_query_parts(conn, filters, session=session)
            total = conn.execute(
                f"""SELECT COUNT(*)
                    FROM purchase_orders po
                    {parts['joins']}
                    WHERE {parts['where']}""",
                parts["params"],
            ).fetchone()[0]
            total_pages = max(1, ceil(total / filters["page_size"]))
            filters["page"] = min(filters["page"], total_pages)
            offset = (filters["page"] - 1) * filters["page_size"]
            rows = conn.execute(
                f"""SELECT {parts['select']}
                    FROM purchase_orders po
                    {parts['joins']}
                    WHERE {parts['where']}
                    ORDER BY COALESCE(po.submitted_at, po.created_at) DESC, po.id DESC
                    LIMIT ? OFFSET ?""",
                [*parts["params"], filters["page_size"], offset],
            ).fetchall()
            summary = _dashboard_procurement_summary_from_parts(conn, parts)

    total_pages = max(1, ceil(total / filters["page_size"]))
    page = filters["page"]
    return {
        "items": [_format_procurement_row(row) for row in rows],
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


def get_dashboard_purchase_order_detail(purchase_order_id, session=None):
    try:
        purchase_order_id = int(purchase_order_id)
    except (TypeError, ValueError):
        return None
    with get_connection() as conn:
        if not _table_exists(conn, "purchase_orders"):
            return None
        filters = _normalize_procurement_filters({"page": 1, "page_size": 1})
        parts = _procurement_query_parts(conn, filters, session=session)
        row = conn.execute(
            f"""SELECT {parts['select']}
                FROM purchase_orders po
                {parts['joins']}
                WHERE po.id = ?""",
            (purchase_order_id,),
        ).fetchone()
        if not row:
            return None
        purchase_order = _format_procurement_row(row)
        purchase_order["notes"] = row["notes"] or ""

        supplier = None
        if _table_exists(conn, "suppliers"):
            supplier_row = conn.execute(
                "SELECT * FROM suppliers WHERE id = ?",
                (purchase_order["supplier_id"],),
            ).fetchone()
            supplier = dict(supplier_row) if supplier_row else None

        items = []
        if _table_exists(conn, "purchase_order_items"):
            product_join = "LEFT JOIN products p ON p.id = poi.product_id" if _table_exists(conn, "products") else ""
            product_fields = "COALESCE(p.sku, '') AS sku, COALESCE(p.name, 'Product #' || poi.product_id) AS product_name" if _table_exists(conn, "products") else "'' AS sku, 'Product #' || poi.product_id AS product_name"
            items = [
                {
                    **dict(item),
                    "remaining_quantity": int(item["ordered_quantity"] or 0) - int(item["received_quantity"] or 0),
                    "unit_cost_display": money(item["unit_cost"]),
                    "subtotal_display": money(item["subtotal"]),
                }
                for item in conn.execute(
                    f"""SELECT poi.*, {product_fields}
                        FROM purchase_order_items poi
                        {product_join}
                        WHERE poi.purchase_order_id = ?
                        ORDER BY poi.id""",
                    (purchase_order_id,),
                ).fetchall()
            ]

        receipts = []
        if _table_exists(conn, "purchase_receipts"):
            receipt_items_join = (
                "LEFT JOIN purchase_receipt_items pri ON pri.receipt_id = pr.id"
                if _table_exists(conn, "purchase_receipt_items") else
                "LEFT JOIN (SELECT NULL AS receipt_id, 0 AS quantity, 0 AS subtotal) pri ON 1 = 0"
            )
            receipts = [
                {
                    **dict(receipt),
                    "quantity_received": int(receipt["quantity_received"] or 0),
                    "receipt_value": float(receipt["receipt_value"] or 0),
                    "receipt_value_display": money(receipt["receipt_value"]),
                }
                for receipt in conn.execute(
                    f"""SELECT pr.id, pr.receipt_number, pr.notes, pr.received_at,
                              COALESCE(u.full_name, u.username, 'system') AS received_by,
                              COALESCE(SUM(pri.quantity), 0) AS quantity_received,
                              COALESCE(SUM(pri.subtotal), 0) AS receipt_value
                       FROM purchase_receipts pr
                       LEFT JOIN users u ON u.id = pr.received_by
                       {receipt_items_join}
                       WHERE pr.purchase_order_id = ?
                       GROUP BY pr.id
                       ORDER BY pr.received_at DESC, pr.id DESC""",
                    (purchase_order_id,),
                ).fetchall()
            ]
    return {
        "purchase_order": purchase_order,
        "supplier": supplier,
        "items": items,
        "receipts": receipts,
        "actions": [
            {"label": "Purchase Order", "enabled": False},
            {"label": "Goods Received Note", "enabled": False},
            {"label": "Print", "enabled": False},
        ],
    }


def list_dashboard_suppliers(filters=None, session=None):
    filters = filters or {}
    normalized = {
        "search": _safe_text(filters.get("search") or filters.get("q")),
        "active": _safe_text(filters.get("active") or "all").lower(),
        "page": _safe_int(filters.get("page"), default=1, minimum=1),
        "page_size": _safe_int(filters.get("page_size"), default=25, minimum=1, maximum=100),
    }
    if normalized["active"] not in {"active", "inactive", "all"}:
        normalized["active"] = "all"
    with get_connection() as conn:
        if not _table_exists(conn, "suppliers"):
            total = 0
            rows = []
        else:
            where = ["1 = 1"]
            params = []
            if normalized["active"] == "active":
                where.append("COALESCE(s.is_active, 1) = 1")
            elif normalized["active"] == "inactive":
                where.append("COALESCE(s.is_active, 1) = 0")
            if normalized["search"]:
                pattern = f"%{normalized['search']}%"
                where.append("(s.name LIKE ? OR s.phone LIKE ? OR s.email LIKE ? OR s.address LIKE ?)")
                params.extend([pattern, pattern, pattern, pattern])
            where_clause = " AND ".join(where)
            total = conn.execute(
                f"SELECT COUNT(*) FROM suppliers s WHERE {where_clause}", params
            ).fetchone()[0]
            total_pages = max(1, ceil(total / normalized["page_size"]))
            normalized["page"] = min(normalized["page"], total_pages)
            offset = (normalized["page"] - 1) * normalized["page_size"]
            if _table_exists(conn, "purchase_orders") and _table_exists(conn, "purchase_order_items"):
                rows = conn.execute(
                    f"""SELECT s.*,
                               COALESCE(COUNT(po.id), 0) AS purchase_order_count,
                               COALESCE(SUM(CASE WHEN po.status NOT IN ('FULLY_RECEIVED', 'CANCELLED') THEN 1 ELSE 0 END), 0) AS outstanding_orders,
                               COALESCE(SUM(po_totals.estimated_value), 0) AS purchase_value,
                               MAX(po.created_at) AS last_purchase_date
                        FROM suppliers s
                        LEFT JOIN purchase_orders po ON po.supplier_id = s.id
                        LEFT JOIN (
                            SELECT purchase_order_id, COALESCE(SUM(subtotal), 0) AS estimated_value
                            FROM purchase_order_items
                            GROUP BY purchase_order_id
                        ) po_totals ON po_totals.purchase_order_id = po.id
                        WHERE {where_clause}
                        GROUP BY s.id
                        ORDER BY s.name COLLATE NOCASE
                        LIMIT ? OFFSET ?""",
                    [*params, normalized["page_size"], offset],
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""SELECT s.*, 0 AS purchase_order_count, 0 AS outstanding_orders,
                               0 AS purchase_value, NULL AS last_purchase_date
                        FROM suppliers s
                        WHERE {where_clause}
                        ORDER BY s.name COLLATE NOCASE
                        LIMIT ? OFFSET ?""",
                    [*params, normalized["page_size"], offset],
                ).fetchall()
    page = normalized["page"]
    total_pages = max(1, ceil(total / normalized["page_size"]))
    return {
        "items": [_format_supplier_row(row) for row in rows],
        "filters": normalized,
        "pagination": {
            "page": page,
            "page_size": normalized["page_size"],
            "total": total,
            "total_pages": total_pages,
            "has_previous": page > 1,
            "has_next": page < total_pages,
            "previous_page": page - 1 if page > 1 else None,
            "next_page": page + 1 if page < total_pages else None,
        },
    }


def _format_supplier_row(row):
    value = float(row["purchase_value"] or 0)
    return {
        "id": row["id"],
        "name": row["name"] or f"Supplier #{row['id']}",
        "phone": row["phone"] or "",
        "email": row["email"] or "",
        "address": row["address"] or "",
        "is_active": bool(row["is_active"]),
        "active_status": "active" if row["is_active"] else "inactive",
        "purchase_order_count": int(row["purchase_order_count"] or 0),
        "outstanding_orders": int(row["outstanding_orders"] or 0),
        "purchase_value": value,
        "purchase_value_display": money(value),
        "last_purchase_date": row["last_purchase_date"] or "",
    }


def get_dashboard_supplier_detail(supplier_id, session=None):
    try:
        supplier_id = int(supplier_id)
    except (TypeError, ValueError):
        return None
    with get_connection() as conn:
        if not _table_exists(conn, "suppliers"):
            return None
        if _table_exists(conn, "purchase_orders") and _table_exists(conn, "purchase_order_items"):
            row = conn.execute(
                """SELECT s.*,
                          COALESCE(COUNT(po.id), 0) AS purchase_order_count,
                          COALESCE(SUM(CASE WHEN po.status NOT IN ('FULLY_RECEIVED', 'CANCELLED') THEN 1 ELSE 0 END), 0) AS outstanding_orders,
                          COALESCE(SUM(po_totals.estimated_value), 0) AS purchase_value,
                          MAX(po.created_at) AS last_purchase_date
                   FROM suppliers s
                   LEFT JOIN purchase_orders po ON po.supplier_id = s.id
                   LEFT JOIN (
                       SELECT purchase_order_id, COALESCE(SUM(subtotal), 0) AS estimated_value
                       FROM purchase_order_items
                       GROUP BY purchase_order_id
                   ) po_totals ON po_totals.purchase_order_id = po.id
                   WHERE s.id = ?
                   GROUP BY s.id""",
                (supplier_id,),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT s.*, 0 AS purchase_order_count, 0 AS outstanding_orders,
                          0 AS purchase_value, NULL AS last_purchase_date
                   FROM suppliers s
                   WHERE s.id = ?""",
                (supplier_id,),
            ).fetchone()
        if not row:
            return None
        supplier = _format_supplier_row(row)
        recent_orders = []
        if _table_exists(conn, "purchase_orders"):
            filters = _normalize_procurement_filters({"supplier_id": supplier_id, "page": 1, "page_size": 10})
            parts = _procurement_query_parts(conn, filters, session=session)
            recent_orders = [
                _format_procurement_row(item)
                for item in conn.execute(
                    f"""SELECT {parts['select']}
                        FROM purchase_orders po
                        {parts['joins']}
                        WHERE {parts['where']}
                        ORDER BY po.created_at DESC, po.id DESC
                        LIMIT 10""",
                    parts["params"],
                ).fetchall()
            ]
    return {
        "supplier": supplier,
        "recent_purchase_orders": recent_orders,
        "performance": {
            "purchase_order_count": supplier["purchase_order_count"],
            "outstanding_orders": supplier["outstanding_orders"],
            "purchase_value": supplier["purchase_value"],
            "purchase_value_display": supplier["purchase_value_display"],
            "last_purchase_date": supplier["last_purchase_date"],
        },
        "actions": [
            {"label": "Supplier Statement", "enabled": False},
            {"label": "Export", "enabled": False},
            {"label": "Print", "enabled": False},
        ],
    }


def get_dashboard_procurement_activity(limit=25, session=None):
    limit = _safe_int(limit, default=25, minimum=1, maximum=100)
    with get_connection() as conn:
        if not _table_exists(conn, "purchase_orders"):
            return {"purchase_orders": [], "receipts": []}
        filters = _normalize_procurement_filters({"page": 1, "page_size": limit})
        parts = _procurement_query_parts(conn, filters, session=session)
        orders = [
            _format_procurement_row(row)
            for row in conn.execute(
                f"""SELECT {parts['select']}
                    FROM purchase_orders po
                    {parts['joins']}
                    WHERE {parts['where']}
                    ORDER BY po.created_at DESC, po.id DESC
                    LIMIT ?""",
                [*parts["params"], limit],
            ).fetchall()
        ]
        receipts = []
        if _table_exists(conn, "purchase_receipts"):
            receipt_items_join = (
                "LEFT JOIN purchase_receipt_items pri ON pri.receipt_id = pr.id"
                if _table_exists(conn, "purchase_receipt_items") else
                "LEFT JOIN (SELECT NULL AS receipt_id, 0 AS quantity, 0 AS subtotal) pri ON 1 = 0"
            )
            receipts = [
                {
                    **dict(row),
                    "receipt_value": float(row["receipt_value"] or 0),
                    "receipt_value_display": money(row["receipt_value"]),
                }
                for row in conn.execute(
                    f"""SELECT pr.id, pr.receipt_number, pr.purchase_order_id, pr.received_at,
                              pr.notes, po.reference_number,
                              COALESCE(s.name, 'Supplier #' || po.supplier_id) AS supplier_name,
                              COALESCE(u.full_name, u.username, 'system') AS received_by,
                              COALESCE(SUM(pri.quantity), 0) AS quantity_received,
                              COALESCE(SUM(pri.subtotal), 0) AS receipt_value
                       FROM purchase_receipts pr
                       JOIN purchase_orders po ON po.id = pr.purchase_order_id
                       LEFT JOIN suppliers s ON s.id = po.supplier_id
                       LEFT JOIN users u ON u.id = pr.received_by
                       {receipt_items_join}
                       GROUP BY pr.id
                       ORDER BY pr.received_at DESC, pr.id DESC
                       LIMIT ?""",
                    (limit,),
                ).fetchall()
            ]
    return {"purchase_orders": orders, "receipts": receipts}


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
