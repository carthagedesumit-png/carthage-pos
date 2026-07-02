"""Customer-domain authorization policies."""

from typing import Any

from auth import ROLE_ADMIN, ROLE_MANAGER, AuthorizationError, validate_session


MANAGEMENT_ROLES = {ROLE_ADMIN, ROLE_MANAGER}


def require_customer_access(session: Any):
    return validate_session(session)


def require_customer_management(session: Any):
    session = validate_session(session)
    if session.role not in MANAGEMENT_ROLES:
        raise AuthorizationError("Only admin and manager users can manage customers.")
    return session
