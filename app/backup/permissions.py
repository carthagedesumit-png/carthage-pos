"""Role checks for disaster-recovery operations."""

from auth import ROLE_ADMIN, ROLE_MANAGER, require_user_management, validate_session
from app.core.exceptions import AuthorizationError


def require_backup_access(session):
    session = validate_session(session)
    if session.role not in {ROLE_ADMIN, ROLE_MANAGER}:
        raise AuthorizationError("Only admin and manager users may access backups.")
    return session


def require_backup_admin(session):
    return require_user_management(session)
