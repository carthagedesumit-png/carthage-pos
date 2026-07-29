"""Authentication helpers for server-rendered dashboard pages."""

import secrets

from fastapi import Request

from app.api.session_service import resolve_session
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.database.db_manager import get_connection


SESSION_COOKIE = "cbos_dashboard_session"
CSRF_COOKIE = "cbos_csrf"


def dashboard_session(request: Request, required=False):
    token = request.cookies.get(SESSION_COOKIE)
    authorization = request.headers.get("Authorization", "")
    if not token and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        if required:
            raise AuthenticationError("Please sign in to access CBOS.")
        return None
    try:
        session = resolve_session(token)
        if request.url.path not in {"/dashboard/change-password", "/dashboard/logout"}:
            with get_connection() as conn:
                row = conn.execute("SELECT force_password_change FROM users WHERE id=?", (session.user_id,)).fetchone()
            if row and row["force_password_change"]:
                if required:
                    raise AuthorizationError("You must change your temporary password before continuing.")
                return None
        return session
    except (AuthenticationError, AuthorizationError):
        if required:
            raise
        return None


def csrf_token(request: Request):
    return request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)


def can_manage_inventory(session):
    return bool(session and session.can_manage_inventory())
