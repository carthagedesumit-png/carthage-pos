"""FastAPI application factory for Carthage POS."""

from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.api.errors import install_exception_handlers
from app.api.licensing_middleware import enforce_api_license
from app.api.schemas import ErrorResponse
from app.api.routers import (
    backups, barcodes, core, customers, deployment, documents, hardware,
    licensing, operations, reports,
)
from app.core.logging_utils import get_logger, log_event
from app.core.version import APP_VERSION
from app.database.db_manager import initialize_database
from app.dashboard.router import router as dashboard_router
from app.dashboard.api.dashboard_api import router as dashboard_api_router


logger = get_logger("api.requests")


def create_app(*, initialize: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if initialize:
            initialize_database()
        yield

    application = FastAPI(
        title="Carthage POS API",
        description="Store-aware REST integration layer for Carthage POS services.",
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
    application.mount(
        "/dashboard/static",
        StaticFiles(directory="app/dashboard/static"),
        name="dashboard_static",
    )
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
        )
        return response

    @application.get("/health", tags=["system"])
    def health():
        return {"status": "ok"}

    return application


app = create_app()
