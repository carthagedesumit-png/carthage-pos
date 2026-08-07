from dataclasses import asdict, is_dataclass
from math import ceil

from auth import UserSession
from app.core.config import get_config
from app.core.version import VersionInfo
from app.database.db_manager import get_connection
from app.dashboard.services.dashboard_service import (
    _columns,
    _safe_int,
    _safe_text,
    _table_exists,
    count_table,
)


SENSITIVE_TOKENS = (
    "password", "secret", "token", "private", "activation",
    "license_key", "license_file", "key_file",
)


def _safe_call(default, func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        return {**default, "error": type(exc).__name__} if isinstance(default, dict) else default


def _dashboard_admin_session():
    with get_connection() as conn:
        if not _table_exists(conn, "users"):
            return None
        columns = _columns(conn, "users")
        fields = ["id", "username", "full_name", "role"]
        home_store = "home_store_id" if "home_store_id" in columns else "NULL AS home_store_id"
        row = conn.execute(
            f"""SELECT {', '.join(fields)}, {home_store}
                FROM users
                WHERE role = 'admin' AND COALESCE(is_active, 1) = 1
                ORDER BY id
                LIMIT 1"""
        ).fetchone()
    if not row:
        return None
    return UserSession(
        user_id=row["id"],
        username=row["username"],
        full_name=row["full_name"],
        role=row["role"],
        store_id=row["home_store_id"],
    )


def _database_version():
    with get_connection() as conn:
        try:
            return int(conn.execute("PRAGMA user_version").fetchone()[0])
        except Exception:
            return 0


def _format_user(row):
    active = bool(row["is_active"])
    locked = bool(row["is_locked"])
    return {
        "id": row["id"],
        "username": row["username"],
        "full_name": row["full_name"] or row["username"],
        "role": row["role"] or "",
        "is_active": active,
        "active_status": "locked" if locked else ("active" if active else "inactive"),
        "is_locked": locked,
        "email": row["email"] or "",
        "failed_login_count": int(row["failed_login_count"] or 0),
        "force_password_change": bool(row["force_password_change"]),
        "created_at": row["created_at"] or "",
        "last_login": row["last_login"] or "",
        "home_store_id": row["home_store_id"],
        "home_store": row["home_store_name"] or "",
        "assigned_stores": row["assigned_stores"] or "",
    }


def list_dashboard_system_users(filters=None):
    filters = filters or {}
    normalized = {
        "search": _safe_text(filters.get("search") or filters.get("q")),
        "role": _safe_text(filters.get("role")).lower(),
        "active": _safe_text(filters.get("active") or "all").lower(),
        "page": _safe_int(filters.get("page"), default=1, minimum=1),
        "page_size": _safe_int(filters.get("page_size"), default=25, minimum=1, maximum=100),
    }
    if normalized["role"] not in {"", "admin", "manager", "cashier", "auditor", "inventory_officer"}:
        normalized["role"] = ""
    if normalized["active"] not in {"active", "inactive", "locked", "all"}:
        normalized["active"] = "all"
    with get_connection() as conn:
        if not _table_exists(conn, "users"):
            total = 0
            rows = []
        else:
            user_columns = _columns(conn, "users")
            where = ["u.username != 'system'"]
            params = []
            if normalized["role"]:
                where.append("u.role = ?")
                params.append(normalized["role"])
            if normalized["active"] == "active":
                where.append("COALESCE(u.is_active, 1) = 1")
            elif normalized["active"] == "inactive":
                where.append("COALESCE(u.is_active, 1) = 0")
            elif normalized["active"] == "locked":
                where.append("COALESCE(u.is_locked, 0) = 1")
            if normalized["search"]:
                pattern = f"%{normalized['search']}%"
                where.append("(u.username LIKE ? OR u.full_name LIKE ? OR u.role LIKE ? OR u.email LIKE ?)")
                params.extend([pattern, pattern, pattern, pattern])
            joins = []
            home_store_expr = "NULL AS home_store_id"
            home_store_name = "'' AS home_store_name"
            if "home_store_id" in user_columns:
                home_store_expr = "u.home_store_id"
                if _table_exists(conn, "stores"):
                    joins.append("LEFT JOIN stores hs ON hs.id = u.home_store_id")
                    home_store_name = "COALESCE(hs.name, hs.code, 'Store #' || u.home_store_id) AS home_store_name"
            assigned_stores = "'' AS assigned_stores"
            if _table_exists(conn, "user_store_access") and _table_exists(conn, "stores"):
                assigned_stores = """COALESCE((
                    SELECT GROUP_CONCAT(COALESCE(st.name, st.code), ', ')
                    FROM user_store_access usa
                    JOIN stores st ON st.id = usa.store_id
                    WHERE usa.user_id = u.id
                ), '') AS assigned_stores"""
            where_clause = " AND ".join(where)
            total = conn.execute(
                f"SELECT COUNT(*) FROM users u {' '.join(joins)} WHERE {where_clause}",
                params,
            ).fetchone()[0]
            total_pages = max(1, ceil(total / normalized["page_size"]))
            normalized["page"] = min(normalized["page"], total_pages)
            offset = (normalized["page"] - 1) * normalized["page_size"]
            rows = conn.execute(
                f"""SELECT u.id, u.username, u.full_name, u.role, u.email,
                          COALESCE(u.is_active, 1) AS is_active,
                          COALESCE(u.is_locked, 0) AS is_locked,
                          COALESCE(u.failed_login_count, 0) AS failed_login_count,
                          COALESCE(u.force_password_change, 0) AS force_password_change,
                          u.created_at, u.last_login, {home_store_expr} AS home_store_id,
                          {home_store_name}, {assigned_stores}
                   FROM users u
                   {' '.join(joins)}
                   WHERE {where_clause}
                   ORDER BY u.username COLLATE NOCASE
                   LIMIT ? OFFSET ?""",
                [*params, normalized["page_size"], offset],
            ).fetchall()
    page = normalized["page"]
    total_pages = max(1, ceil(total / normalized["page_size"]))
    return {
        "items": [_format_user(row) for row in rows],
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


def get_dashboard_system_user_detail(user_id, session=None):
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    if session is not None:
        from app.administration.user_service import get_managed_user
        managed = get_managed_user(session, user_id)
        return {"user": managed, "activity": managed["audit"], "sessions": managed["sessions"],
                "permissions": managed["permissions"], "actions": []}
    result = list_dashboard_system_users({"active": "all", "page_size": 100})
    user = next((item for item in result["items"] if item["id"] == user_id), None)
    if not user:
        return None
    return {
        "user": user,
        "activity": _user_activity(user_id),
        "actions": [
            {"label": "Edit User", "enabled": False},
            {"label": "Reset Password", "enabled": False},
            {"label": "Deactivate User", "enabled": False},
        ],
    }


def _dashboard_user_totals():
    with get_connection() as conn:
        if not _table_exists(conn, "users"):
            return {"total": 0, "active": 0, "inactive": 0}
        row = conn.execute(
            """SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN COALESCE(is_active, 1) = 1 THEN 1 ELSE 0 END) AS active,
                    SUM(CASE WHEN COALESCE(is_active, 1) = 0 THEN 1 ELSE 0 END) AS inactive
               FROM users
               WHERE username != 'system'"""
        ).fetchone()
    return {
        "total": int(row["total"] or 0),
        "active": int(row["active"] or 0),
        "inactive": int(row["inactive"] or 0),
    }


def _user_activity(user_id):
    activity = []
    with get_connection() as conn:
        if _table_exists(conn, "hardware_events") and "user_id" in _columns(conn, "hardware_events"):
            activity.extend([
                dict(row)
                for row in conn.execute(
                    """SELECT event_type AS type, device_type AS subject, created_at
                       FROM hardware_events
                       WHERE user_id = ?
                       ORDER BY created_at DESC, id DESC
                       LIMIT 5""",
                    (user_id,),
                ).fetchall()
            ])
    return activity


def get_dashboard_system_licensing():
    from app.licensing.license_service import get_license_status
    from app.licensing.editions import list_editions

    status = _safe_call(
        {"state": "UNKNOWN", "valid": False, "edition": "COMMUNITY", "notifications": []},
        get_license_status,
    )
    config = get_config().licensing
    return {
        "status": status,
        "editions": _safe_call([], list_editions),
        "configuration": {
            "enforcement_enabled": config.enforcement_enabled,
            "developer_mode": config.developer_mode,
            "default_edition": config.default_edition,
            "trial_edition": config.trial_edition,
            "grace_period_days": config.grace_period_days,
            "evaluation_days": config.evaluation_days,
            "license_file": _mask_value(config.license_file),
            "public_key_file": _mask_value(config.public_key_file),
        },
        "actions": [
            {"label": "Activate License", "enabled": False},
            {"label": "Import License", "enabled": False},
            {"label": "Deactivate", "enabled": False},
        ],
    }


def get_dashboard_system_backups():
    from app.backup.backup_service import get_backup_status, list_backups

    session = _dashboard_admin_session()
    if session:
        status = _safe_call(
            {"backup_count": 0, "latest_backup": None, "total_size": 0},
            get_backup_status,
            session,
        )
        backups = _safe_call([], list_backups, session)
    else:
        status = {"backup_count": 0, "latest_backup": None, "total_size": 0, "message": "No active administrator session is available."}
        backups = []
    return {
        "status": status,
        "items": backups[:10],
        "actions": [
            {"label": "Create Backup", "enabled": False},
            {"label": "Verify Backup", "enabled": False},
            {"label": "Restore", "enabled": False},
        ],
    }


def get_dashboard_system_deployment():
    from app.deployment.update_service import get_update_status
    from app.deployment.verification_service import (
        get_current_deployment_status,
        get_installer_information,
    )

    return {
        "status": _safe_call(
            {"healthy": False, "installed": False, "checks": []},
            get_current_deployment_status,
        ),
        "installer": _safe_call({}, get_installer_information),
        "updates": _safe_call({"status": "UNKNOWN"}, get_update_status),
        "actions": [
            {"label": "Run Verification", "enabled": False},
            {"label": "Repair Install", "enabled": False},
            {"label": "Check Updates", "enabled": False},
        ],
    }


def get_dashboard_system_hardware():
    from app.hardware.manager import get_hardware_manager

    status = _safe_call(
        {"printer": {}, "cash_drawer": {}, "scanner": {}, "customer_display": {}},
        get_hardware_manager().status,
    )
    return {
        "status": status,
        "actions": [
            {"label": "Print Test Page", "enabled": False},
            {"label": "Open Cash Drawer", "enabled": False},
            {"label": "Test Display", "enabled": False},
        ],
    }


def _mask_value(value):
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 8:
        return "****"
    return f"{text[:3]}...{text[-3:]}"


def _mask_config(data, path=""):
    if is_dataclass(data):
        data = asdict(data)
    if isinstance(data, dict):
        masked = {}
        for key, value in data.items():
            key_path = f"{path}.{key}" if path else str(key)
            if any(token in str(key).lower() or token in key_path.lower() for token in SENSITIVE_TOKENS):
                masked[key] = _mask_value(value)
            elif isinstance(value, (dict, list)) or is_dataclass(value):
                masked[key] = _mask_config(value, key_path)
            else:
                masked[key] = value
        return masked
    if isinstance(data, list):
        return [_mask_config(item, path) for item in data]
    return data


def get_dashboard_system_configuration():
    config = get_config()
    sections = _mask_config(config)
    rows = []
    for section, values in sections.items():
        if isinstance(values, dict):
            for key, value in values.items():
                rows.append({"section": section, "key": key, "value": value})
        else:
            rows.append({"section": "application", "key": section, "value": values})
    return {
        "sections": sections,
        "rows": rows,
        "masked": True,
        "actions": [
            {"label": "Edit Configuration", "enabled": False},
            {"label": "Reload Settings", "enabled": False},
        ],
    }


def get_dashboard_system_activity(limit=25):
    limit = _safe_int(limit, default=25, minimum=1, maximum=100)
    events = []
    with get_connection() as conn:
        if _table_exists(conn, "users"):
            events.extend([
                {
                    "type": "user_login",
                    "subject": row["username"],
                    "created_at": row["last_login"],
                }
                for row in conn.execute(
                    """SELECT username, last_login FROM users
                       WHERE last_login IS NOT NULL
                       ORDER BY last_login DESC
                       LIMIT ?""",
                    (limit,),
                ).fetchall()
            ])
        if _table_exists(conn, "hardware_events"):
            events.extend([
                {
                    "type": row["event_type"],
                    "subject": row["device_type"],
                    "created_at": row["created_at"],
                }
                for row in conn.execute(
                    """SELECT event_type, device_type, created_at
                       FROM hardware_events
                       ORDER BY created_at DESC, id DESC
                       LIMIT ?""",
                    (limit,),
                ).fetchall()
            ])
    return sorted(events, key=lambda item: item.get("created_at") or "", reverse=True)[:limit]


def get_dashboard_system_summary():
    user_totals = _dashboard_user_totals()
    licensing = get_dashboard_system_licensing()
    backups = get_dashboard_system_backups()
    deployment = get_dashboard_system_deployment()
    hardware = get_dashboard_system_hardware()
    configuration = get_dashboard_system_configuration()
    versions = VersionInfo(database_version=_database_version()).to_dict()
    api_status = "Online"
    license_state = licensing["status"].get("state", "UNKNOWN")
    backup_count = int(backups["status"].get("backup_count") or 0)
    deployment_status = "Healthy" if deployment["status"].get("healthy") else "Needs Attention"
    printer = hardware["status"].get("printer", {})
    hardware_status = "Ready" if printer.get("available") else "Limited"
    with get_connection() as conn:
        store_count = count_table(conn, "stores")
    return {
        "application_version": versions["application_version"],
        "database_version": versions["database_version"],
        "api_status": api_status,
        "license_status": license_state,
        "backup_status": "Ready" if backup_count else "No Backups",
        "deployment_status": deployment_status,
        "hardware_status": hardware_status,
        "user_count": user_totals["total"],
        "active_users": user_totals["active"],
        "inactive_users": user_totals["inactive"],
        "store_count": store_count,
        "configuration_summary": {
            "currency": configuration["sections"]["deployment"]["currency"],
            "timezone": configuration["sections"]["deployment"]["timezone"],
            "backup_schedule": configuration["sections"]["backup"]["schedule"],
            "printer_enabled": configuration["sections"]["hardware"]["printer_enabled"],
        },
        "cards": [
            {"label": "API", "value": api_status, "accent": "accent-blue"},
            {"label": "License", "value": license_state, "accent": "accent-green"},
            {"label": "Backups", "value": backup_count, "accent": "accent-amber"},
            {"label": "Users", "value": user_totals["total"], "accent": "accent-red"},
        ],
        "versions": versions,
        "licensing": licensing,
        "backups": backups,
        "deployment": deployment,
        "hardware": hardware,
        "configuration": configuration,
        "activity": get_dashboard_system_activity(limit=10),
    }
