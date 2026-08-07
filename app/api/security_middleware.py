"""HTTP security middleware for production deployments."""

from collections import defaultdict, deque
from time import monotonic
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.core.config import get_config
from app.core.logging_utils import get_logger, log_event, set_request_id


logger = get_logger("api.security")
_auth_attempts: dict[str, deque[float]] = defaultdict(deque)


async def canonical_local_host_middleware(request: Request, call_next):
    """Keep installed browser sessions on the configured loopback host."""
    config = get_config()
    hostname = (request.url.hostname or "").lower()
    if config.api.host == "127.0.0.1" and hostname == "localhost":
        port = request.url.port or config.api.port
        target = f"{request.url.scheme}://127.0.0.1:{port}{request.url.path}"
        query = request.scope.get("query_string", b"").decode("latin-1")
        if query:
            target += "?" + query
        return RedirectResponse(target, status_code=307)
    return await call_next(request)


async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid4().hex
    request.state.request_id = request_id
    set_request_id(request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    settings = get_config().security
    response.headers.setdefault("X-Content-Type-Options", settings.content_type_options)
    response.headers.setdefault("X-Frame-Options", settings.frame_options)
    response.headers.setdefault("Referrer-Policy", settings.referrer_policy)
    response.headers.setdefault("Content-Security-Policy", settings.content_security_policy)
    _harden_cookie_headers(response, secure=settings.secure_cookies, same_site=settings.cookie_same_site)
    return response


async def csrf_middleware(request: Request, call_next):
    settings = get_config().security
    if (
        settings.csrf_enabled
        and request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and request.url.path.startswith("/dashboard")
        and not request.url.path.startswith("/dashboard/api")
    ):
        cookie_token = request.cookies.get("cbos_csrf")
        submitted = request.headers.get("X-CSRF-Token") or request.query_params.get("csrf_token")
        if not cookie_token or submitted != cookie_token:
            log_event(
                logger,
                "csrf_request_rejected",
                method=request.method,
                path=request.url.path,
                request_id=getattr(request.state, "request_id", ""),
            )
            return JSONResponse(
                status_code=403,
                content={"error": {"code": "csrf_rejected", "message": "CSRF validation failed."}},
            )
    return await call_next(request)


async def auth_rate_limit_middleware(request: Request, call_next):
    settings = get_config().security
    if (
        settings.rate_limit_enabled
        and request.method == "POST"
        and request.url.path.endswith("/auth/login")
    ):
        client = request.client.host if request.client else "unknown"
        now = monotonic()
        attempts = _auth_attempts[client]
        while attempts and now - attempts[0] > settings.auth_rate_limit_window_seconds:
            attempts.popleft()
        if len(attempts) >= settings.auth_rate_limit_attempts:
            log_event(
                logger,
                "auth_rate_limited",
                client=client,
                path=request.url.path,
                request_id=getattr(request.state, "request_id", ""),
            )
            return JSONResponse(
                status_code=429,
                content={"error": {"code": "rate_limited", "message": "Too many authentication attempts."}},
            )
        response = await call_next(request)
        if response.status_code in {400, 401, 403, 422}:
            attempts.append(now)
        return response
    return await call_next(request)


def reset_rate_limit_state() -> None:
    _auth_attempts.clear()


def _harden_cookie_headers(response, *, secure: bool, same_site: str) -> None:
    values = response.headers.getlist("set-cookie")
    if not values:
        return
    del response.headers["set-cookie"]
    for value in values:
        lowered = value.lower()
        hardened = value
        if secure and "secure" not in lowered:
            hardened += "; Secure"
        if "httponly" not in lowered:
            hardened += "; HttpOnly"
        if "samesite=" not in lowered:
            hardened += f"; SameSite={same_site.capitalize()}"
        response.headers.append("set-cookie", hardened)
