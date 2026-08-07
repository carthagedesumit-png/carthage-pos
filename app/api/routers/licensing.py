"""Offline-first licensing and product-edition API endpoints."""

from fastapi import APIRouter, Depends

from auth import UserSession, require_user_management
from app.api.dependencies import get_current_session
from app.api.pagination import data_response
from app.api.schemas import ActivationExportRequest, LicenseImportRequest
from app.licensing.activation_service import (
    activate_license, deactivate_installation, export_activation_request,
    import_activation_response,
)
from app.licensing.feature_service import enabled_features
from app.licensing.license_service import get_current_license, get_license_status


router = APIRouter(prefix="/licensing", tags=["licensing"])


@router.get("/current")
def current_license(session: UserSession = Depends(get_current_session)):
    require_user_management(session)
    return data_response(get_current_license())


@router.get("/edition")
def current_edition(_session: UserSession = Depends(get_current_session)):
    status = get_license_status()
    return data_response({"edition": status["edition"], "limits": status["limits"]})


@router.get("/features")
def current_features(_session: UserSession = Depends(get_current_session)):
    status = get_license_status()
    return data_response({"edition": status["edition"], "features": enabled_features(status)})


@router.get("/status")
def license_status(_session: UserSession = Depends(get_current_session)):
    return data_response(get_license_status())


@router.post("/export-request")
def export_request(payload: ActivationExportRequest,
                   session: UserSession = Depends(get_current_session)):
    result = export_activation_request(
        session, payload.license_key, payload.customer_name, payload.company_name
    )
    # The portable request remains on disk; the API returns only safe metadata.
    return data_response({key: value for key, value in result.items() if key != "document"})


@router.post("/activate")
def activate(payload: LicenseImportRequest,
             session: UserSession = Depends(get_current_session)):
    return data_response(activate_license(session, payload.document))


@router.post("/import")
def import_license(payload: LicenseImportRequest,
                   session: UserSession = Depends(get_current_session)):
    return data_response(import_activation_response(session, payload.document))


@router.post("/deactivate")
def deactivate(session: UserSession = Depends(get_current_session)):
    return data_response(deactivate_installation(session))
