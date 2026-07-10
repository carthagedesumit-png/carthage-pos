"""Central application-to-HTTP exception translation."""

from sqlite3 import IntegrityError

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from app.core.exceptions import (
    ApplicationError,
    AuthenticationError,
    AuthorizationError,
    ValidationError,
)
from app.core.logging_utils import get_logger, log_failure


logger = get_logger("api.errors")
dashboard_templates = Jinja2Templates(directory="app/dashboard/templates")


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthenticationError)
    async def authentication_error(_request: Request, exc: AuthenticationError):
        return _error(401, "authentication_error", str(exc))

    @app.exception_handler(AuthorizationError)
    async def authorization_error(_request: Request, exc: AuthorizationError):
        return _error(403, "authorization_error", str(exc))

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(request: Request, exc: RequestValidationError):
        if _is_dashboard_page(request):
            return _dashboard_error(
                request,
                400,
                "We could not read that dashboard request.",
                "Check the page address or filters and try again.",
            )
        details = [
            {"location": list(item["loc"]), "message": item["msg"], "type": item["type"]}
            for item in exc.errors()
        ]
        return _error(400, "validation_error", "Request validation failed.", details)

    @app.exception_handler(IntegrityError)
    async def integrity_error(_request: Request, _exc: IntegrityError):
        return _error(409, "conflict", "The request conflicts with existing data.")

    @app.exception_handler(ValidationError)
    @app.exception_handler(ValueError)
    async def validation_error(_request: Request, exc: ValueError):
        message = str(exc)
        lowered = message.lower()
        if any(marker in lowered for marker in ("not found", "does not exist", "unknown")):
            return _error(404, "not_found", message)
        if any(marker in lowered for marker in ("already exists", "duplicate", "unique")):
            return _error(409, "conflict", message)
        return _error(400, "validation_error", message)

    @app.exception_handler(ApplicationError)
    async def application_error(_request: Request, exc: ApplicationError):
        return _error(400, "application_error", str(exc))

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        if _is_dashboard_page(request):
            log_failure(
                logger,
                "dashboard_unexpected_failure",
                method=request.method,
                path=request.url.path,
                error_type=type(exc).__name__,
            )
            return _dashboard_error(
                request,
                500,
                "The dashboard could not load this page.",
                "The issue has been recorded. Please refresh or return to the dashboard.",
            )
        log_failure(
            logger,
            "api_unexpected_failure",
            method=request.method,
            path=request.url.path,
            error_type=type(exc).__name__,
        )
        return _error(500, "internal_error", "An unexpected server error occurred.")


def _error(status: int, code: str, message: str, details=None) -> JSONResponse:
    payload = {"error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    return JSONResponse(status_code=status, content=payload)


def _is_dashboard_page(request: Request) -> bool:
    path = request.url.path
    return path.startswith("/dashboard") and not path.startswith("/dashboard/api")


def _dashboard_error(request: Request, status: int, title: str, message: str):
    return dashboard_templates.TemplateResponse(
        request,
        "dashboard_error.html",
        {
            "title": f"{title} - Carthage Business Operating System",
            "header": {"user": "Administrator", "store": "Main Store"},
            "active_page": "dashboard",
            "page_title": title,
            "page_subtitle": message,
            "status_code": status,
        },
        status_code=status,
    )
