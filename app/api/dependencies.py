"""Shared FastAPI authentication and store-scope dependencies."""

from typing import Optional

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth import ROLE_ADMIN, ROLE_MANAGER, UserSession, require_store_access
from app.api.session_service import resolve_session
from app.core.exceptions import AuthenticationError
from app.stores.store_service import get_user_store_assignment


bearer_scheme = HTTPBearer(auto_error=False)


def get_bearer_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Bearer token is required.")
    return credentials.credentials


def get_current_session(token: str = Depends(get_bearer_token)) -> UserSession:
    return resolve_session(token)


def resolve_store_scope(
    session: UserSession,
    store_id: Optional[int],
    *,
    manage: bool = False,
) -> int:
    selected = int(store_id or session.store_id)
    return require_store_access(session, selected, manage=manage).store_id


def accessible_store_ids(session: UserSession) -> Optional[list[int]]:
    if session.role == ROLE_ADMIN:
        return None
    if session.role == ROLE_MANAGER:
        assignment = get_user_store_assignment(session.user_id)
        return [store["id"] for store in assignment["stores"] if store["is_active"]]
    return [session.store_id]


def require_management(session: UserSession) -> UserSession:
    if session.role not in {ROLE_ADMIN, ROLE_MANAGER}:
        from auth import AuthorizationError
        raise AuthorizationError("Only admin and manager users may perform this operation.")
    return session
