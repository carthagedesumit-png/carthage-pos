"""FastAPI application factory for Carthage Business Operating System."""

from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.errors import install_exception_handlers
from app.api.licensing_middleware import enforce_api_license
from app.api.schemas import ErrorResponse
from app.api.security_middleware import (
    auth_rate_limit_middleware,
    csrf_middleware,
    request_id_middleware,
    reset_rate_limit_state,
    security_headers_middleware,
)
from app.api.routers import (
    backups, barcodes, core, customers, deployment, documents, hardware,
    licensing, operations, reports,
)
from app.core.config import get_config
from app.core.configuration_validation import validate_startup_configuration
from app.core.health_service import live_status, readiness_status
from app.core.logging_utils import get_logger, log_event
from app.core.runtime_paths import resource_path
from app.core.version import APP_VERSION
from app.database.db_manager import initialize_database
from app.dashboard.router import router as dashboard_router
from app.dashboard.inventory_router import router as inventory_dashboard_router
from app.dashboard.api.dashboard_api import router as dashboard_api_router


logger = get_logger("api.requests")


def create_app(*, initialize: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        config = get_config()
        reset_rate_limit_state()
        validate_startup_configuration()
        if initialize:
            initialize_database()
        log_event(
            logger,
            "api_startup_completed",
            version=APP_VERSION,
            host=config.api.host,
            port=config.api.port,
            environment="production" if config.licensing.enforcement_enabled else "development",
        )
        yield
        log_event(logger, "api_shutdown_completed", version=APP_VERSION)

    application = FastAPI(
        title="Carthage Business Operating System API",
        description="Store-aware REST integration layer for CBOS services.",
        version=APP_VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        responses={
            400: {"model": ErrorResponse, "description": "Validation error"},
            401: {"model": ErrorResponse, "description": "Authentication required"},
            403: {"model": ErrorResponse, "description": "Operation forbidden"},
            404: {"model": ErrorResponse, "description": "Resource not found"},
            409: {"model": ErrorResponse, "description": "Resource conflict"},
            500: {"model": ErrorResponse, "description": "Unexpected server failure"},
        },
    )
    install_exception_handlers(application)
    application.middleware("http")(security_headers_middleware)
    application.middleware("http")(csrf_middleware)
    application.middleware("http")(auth_rate_limit_middleware)
    application.middleware("http")(request_id_middleware)
    application.mount(
        "/dashboard/static",
        StaticFiles(directory=str(resource_path("app", "dashboard", "static"))),
        name="dashboard_static",
    )
    application.include_router(inventory_dashboard_router)
    application.include_router(dashboard_router)
    application.include_router(dashboard_api_router)
    application.include_router(core.router, prefix="/api/v1")
    application.include_router(operations.router, prefix="/api/v1")
    application.include_router(customers.router, prefix="/api/v1")
    application.include_router(reports.router, prefix="/api/v1")
    application.include_router(documents.router, prefix="/api/v1")
    application.include_router(hardware.router, prefix="/api/v1")
    application.include_router(barcodes.router, prefix="/api/v1")
    application.include_router(backups.router, prefix="/api/v1")
    application.include_router(deployment.router, prefix="/api/v1")
    application.include_router(licensing.router, prefix="/api/v1")
    application.middleware("http")(enforce_api_license)

    @application.middleware("http")
    async def request_logging(request: Request, call_next):
        started = perf_counter()
        response = await call_next(request)
        log_event(
            logger,
            "api_request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round((perf_counter() - started) * 1000, 2),
            request_id=getattr(request.state, "request_id", ""),
        )
        return response

    @application.get("/health", tags=["system"])
    def health():
        return {"status": "ok"}

    @application.get("/health/live", tags=["system"])
    def health_live():
        return live_status()

    @application.get("/health/ready", tags=["system"])
    def health_ready():
        payload = readiness_status()
        if not payload["ready"]:
            return JSONResponse(status_code=503, content=payload)
        return payload

    return application


app = create_app()
