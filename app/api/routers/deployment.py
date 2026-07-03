"""Version, deployment health, installer, and update-status endpoints."""

from fastapi import APIRouter, Depends, Query

from auth import UserSession, require_user_management
from app.api.dependencies import get_current_session, require_management
from app.api.pagination import data_response
from app.core.config import get_config
from app.core.version import (
    APP_VERSION, DATABASE_SCHEMA_VERSION, INSTALLER_VERSION,
    VersionInfo, compatibility_report,
)
from app.deployment.update_service import get_update_status
from app.deployment.verification_service import (
    get_current_deployment_status, get_installer_information, verify_installation,
)


router = APIRouter(tags=["deployment"])


@router.get("/version")
def version(_session: UserSession = Depends(get_current_session)):
    return data_response(VersionInfo().to_dict())


@router.get("/deployment/status")
def deployment_status(session: UserSession = Depends(get_current_session)):
    require_management(session)
    return data_response(get_current_deployment_status())


@router.get("/deployment/installer")
def installer_information(session: UserSession = Depends(get_current_session)):
    require_user_management(session)
    return data_response(get_installer_information())


@router.get("/updates/status")
def update_status(session: UserSession = Depends(get_current_session)):
    require_management(session)
    return data_response(get_update_status())


@router.post("/deployment/verify")
def verify_deployment(session: UserSession = Depends(get_current_session)):
    require_user_management(session)
    return data_response(verify_installation(get_config().deployment.installation_directory))


@router.get("/deployment/compatibility")
def compatibility(
    application_version: str = Query(default=APP_VERSION),
    database_version: int = Query(default=DATABASE_SCHEMA_VERSION, ge=0),
    installer_version: str = Query(default=INSTALLER_VERSION),
    _session: UserSession = Depends(get_current_session),
):
    return data_response(compatibility_report(
        application_version, database_version, installer_version
    ))
