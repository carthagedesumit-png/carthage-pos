"""Central API feature and read-only license enforcement."""

from fastapi.responses import JSONResponse

from app.core.config import get_config
from app.core.exceptions import LicenseError, LicenseFeatureError
from app.licensing.editions import (
    API_ACCESS, BACKUP, BARCODE, CRM, DOCUMENTS, HARDWARE, PROCUREMENT, TRANSFERS,
)
from app.licensing.feature_service import require_feature, require_write_access
from app.licensing.license_service import get_license_status


EXEMPT_PREFIXES = (
    "/health", "/docs", "/redoc", "/openapi.json",
    "/api/v1/auth", "/api/v1/licensing", "/api/v1/version",
    "/api/v1/deployment", "/api/v1/updates",
)
FEATURE_PREFIXES = {
    "/api/v1/customers": CRM,
    "/api/v1/customer-groups": CRM,
    "/api/v1/loyalty": CRM,
    "/api/v1/wallet": CRM,
    "/api/v1/credit": CRM,
    "/api/v1/suppliers": PROCUREMENT,
    "/api/v1/purchase-orders": PROCUREMENT,
    "/api/v1/procurement": PROCUREMENT,
    "/api/v1/hardware": HARDWARE,
    "/api/v1/backups": BACKUP,
    "/api/v1/barcodes": BARCODE,
    "/api/v1/documents": DOCUMENTS,
    "/api/v1/transfers": TRANSFERS,
}


async def enforce_api_license(request, call_next):
    if not get_config().licensing.enforcement_enabled:
        return await call_next(request)
    path = request.url.path
    if path.startswith(EXEMPT_PREFIXES):
        return await call_next(request)
    try:
        status = get_license_status()
        require_feature(API_ACCESS, status=status)
        for prefix, feature in FEATURE_PREFIXES.items():
            if path.startswith(prefix):
                require_feature(feature, status=status)
                break
        if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            require_write_access(status=status)
    except (LicenseError, LicenseFeatureError) as exc:
        return JSONResponse(
            status_code=403,
            content={"error": {"code": "license_restriction", "message": str(exc)}},
        )
    return await call_next(request)
