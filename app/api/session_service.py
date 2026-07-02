"""Persisted, revocable bearer sessions for the HTTP API."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Optional

from auth import (
    AuthenticationError,
    AuthorizationError,
    UserSession,
    authenticate_user,
    switch_store,
    validate_session,
)
from app.core.config import get_config
from app.core.logging_utils import get_logger, log_event
from app.database.db_manager import get_connection
from app.database.transactions import transaction


logger = get_logger("api.authentication")


def issue_session(username: str, password: str, store_id: Optional[int] = None) -> dict:
    session = authenticate_user(username, password, store_id=store_id)
    if session is None:
        raise AuthenticationError("Invalid username or password.")
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(hours=get_config().api.session_hours)
    with transaction() as conn:
        conn.execute(
            """INSERT INTO api_sessions (
                   token_hash, user_id, store_id, expires_at
               ) VALUES (?, ?, ?, ?)""",
            (_token_hash(token), session.user_id, session.store_id,
             expires_at.isoformat(timespec="seconds")),
        )
    log_event(logger, "api_session_created", user_id=session.user_id, store_id=session.store_id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(timespec="seconds"),
        "session": session_to_dict(session),
    }


def resolve_session(token: str) -> UserSession:
    if not token:
        raise AuthenticationError("Bearer token is required.")
    with get_connection() as conn:
        row = conn.execute(
            """SELECT aps.user_id, aps.store_id, aps.expires_at, aps.revoked_at,
                      u.username, u.full_name, u.role
               FROM api_sessions aps
               JOIN users u ON u.id = aps.user_id
               WHERE aps.token_hash = ?""",
            (_token_hash(token),),
        ).fetchone()
    if not row or row["revoked_at"]:
        raise AuthenticationError("API session is invalid or revoked.")
    if datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
        raise AuthenticationError("API session has expired.")
    candidate = UserSession(
        user_id=row["user_id"], username=row["username"],
        full_name=row["full_name"], role=row["role"], store_id=row["store_id"],
    )
    try:
        session = validate_session(candidate)
    except AuthorizationError as exc:
        raise AuthenticationError("API session is no longer valid.") from exc
    with get_connection() as conn:
        conn.execute(
            "UPDATE api_sessions SET last_used_at = CURRENT_TIMESTAMP WHERE token_hash = ?",
            (_token_hash(token),),
        )
    return session


def revoke_session(token: str) -> None:
    with transaction() as conn:
        cursor = conn.execute(
            """UPDATE api_sessions SET revoked_at = CURRENT_TIMESTAMP
               WHERE token_hash = ? AND revoked_at IS NULL""",
            (_token_hash(token),),
        )
        if cursor.rowcount == 0:
            raise AuthenticationError("API session is invalid or already revoked.")
    log_event(logger, "api_session_revoked")


def change_session_store(token: str, store_id: int) -> UserSession:
    current = resolve_session(token)
    scoped = switch_store(current, store_id)
    with transaction() as conn:
        conn.execute(
            "UPDATE api_sessions SET store_id = ?, last_used_at = CURRENT_TIMESTAMP WHERE token_hash = ?",
            (scoped.store_id, _token_hash(token)),
        )
    log_event(logger, "api_session_store_changed", user_id=scoped.user_id, store_id=scoped.store_id)
    return scoped


def session_to_dict(session: UserSession) -> dict:
    return {
        "user_id": session.user_id,
        "username": session.username,
        "full_name": session.full_name,
        "role": session.role,
        "store_id": session.store_id,
    }


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
