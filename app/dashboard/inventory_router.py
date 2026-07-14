"""Thin server-rendered routes for inventory management."""

from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.api.session_service import issue_session, revoke_session
from app.core.exceptions import ApplicationError, AuthenticationError, AuthorizationError
from app.core.runtime_paths import resource_path
from app.dashboard.auth import (
    CSRF_COOKIE, SESSION_COOKIE, can_manage_inventory, csrf_token, dashboard_session,
)
from app.dashboard.services.inventory_management_service import (
    barcode_operation, category_context, product_form_context, product_operation_context,
    save_category, save_product, set_category_active, set_product_active,
    adjust_product_stock, receive_product_stock,
)


router = APIRouter(prefix="/dashboard")
templates = Jinja2Templates(directory=str(resource_path("app", "dashboard", "templates")))


async def _form(request):
    body = (await request.body()).decode("utf-8")
    return {key: values[-1] for key, values in parse_qs(body, keep_blank_values=True).items()}


def _render(request, template, context, status_code=200):
    token = csrf_token(request)
    session = dashboard_session(request)
    payload = {
        "request": request, "csrf_token": token, "session": session,
        "can_manage": can_manage_inventory(session),
        "header": {
            "user": session.full_name if session else "Dashboard Viewer",
            "store": f"Store #{session.store_id}" if session else "All Stores",
        },
        "active_page": "inventory", **context,
    }
    response = templates.TemplateResponse(request, template, payload, status_code=status_code)
    if not request.cookies.get(CSRF_COOKIE):
        response.set_cookie(CSRF_COOKIE, token, samesite="strict", secure=False)
    return response


def _redirect(path, message=None, error=None):
    separator = "&" if "?" in path else "?"
    if message:
        path += f"{separator}success={quote(message)}"
    elif error:
        path += f"{separator}error={quote(error)}"
    return RedirectResponse(path, status_code=303)


def _require(request):
    session = dashboard_session(request, required=True)
    if not can_manage_inventory(session):
        raise AuthorizationError("Your role has read-only inventory access.")
    return session


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    return _render(request, "dashboard_login.html", {"error": error, "title": "Dashboard Sign In"})


@router.post("/login")
async def login(request: Request):
    values = await _form(request)
    try:
        result = issue_session(values.get("username", ""), values.get("password", ""),
                               int(values["store_id"]) if values.get("store_id") else None)
    except (ApplicationError, ValueError) as exc:
        return _redirect("/dashboard/login", error=str(exc))
    response = _redirect("/dashboard/inventory", message="Signed in successfully.")
    response.set_cookie(SESSION_COOKIE, result["access_token"], httponly=True,
                        samesite="strict", secure=False, max_age=8 * 60 * 60)
    return response


@router.post("/logout")
def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        try:
            revoke_session(token)
        except AuthenticationError:
            pass
    response = _redirect("/dashboard/login", message="Signed out.")
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.get("/inventory/products/new", response_class=HTMLResponse)
def new_product(request: Request):
    try:
        session = _require(request)
    except (AuthenticationError, AuthorizationError) as exc:
        return _render(request, "dashboard_error.html", {"title": "Access denied", "error": str(exc)}, 403)
    return _render(request, "product_form.html", {
        **product_form_context(session), "title": "Add Product", "form_title": "Add Product",
        "action": "/dashboard/inventory/products", "errors": {},
    })


@router.post("/inventory/products")
async def create_product_route(request: Request):
    values = await _form(request)
    try:
        session = _require(request)
        product = save_product(session, values)
    except (ApplicationError, ValueError) as exc:
        context = product_form_context(dashboard_session(request, required=True), values=values)
        return _render(request, "product_form.html", {
            **context, "title": "Add Product", "form_title": "Add Product",
            "action": "/dashboard/inventory/products", "errors": {"form": str(exc)},
        }, 422 if not isinstance(exc, AuthorizationError) else 403)
    return _redirect(f"/dashboard/inventory/products/{product['id']}", "Product created.")


@router.get("/inventory/products/{product_id}/edit", response_class=HTMLResponse)
def edit_product_page(request: Request, product_id: int):
    try:
        session = _require(request)
        context = product_form_context(session, product_id)
    except (ApplicationError, ValueError) as exc:
        return _render(request, "dashboard_error.html", {"title": "Access denied", "error": str(exc)}, 403)
    if not context:
        return _render(request, "dashboard_error.html", {"title": "Not found", "error": "Product not found."}, 404)
    return _render(request, "product_form.html", {
        **context, "title": "Edit Product", "form_title": "Edit Product",
        "action": f"/dashboard/inventory/products/{product_id}", "errors": {},
    })


@router.post("/inventory/products/{product_id}")
async def edit_product_route(request: Request, product_id: int):
    values = await _form(request)
    try:
        session = _require(request)
        product = save_product(session, values, product_id)
    except (ApplicationError, ValueError) as exc:
        session = dashboard_session(request, required=True)
        context = product_form_context(session, product_id, values)
        return _render(request, "product_form.html", {
            **(context or {}), "title": "Edit Product", "form_title": "Edit Product",
            "action": f"/dashboard/inventory/products/{product_id}", "errors": {"form": str(exc)},
        }, 422 if not isinstance(exc, AuthorizationError) else 403)
    return _redirect(f"/dashboard/inventory/products/{product['id']}", "Product updated.")


@router.get("/inventory/products/{product_id}/lifecycle", response_class=HTMLResponse)
def lifecycle_page(request: Request, product_id: int, active: bool, store_id: int | None = None):
    try:
        session = _require(request)
        context = product_operation_context(session, product_id, store_id)
    except (ApplicationError, ValueError) as exc:
        return _render(request, "dashboard_error.html", {"title": "Access denied", "error": str(exc)}, 403)
    return _render(request, "product_confirm.html", {
        **(context or {}), "title": "Confirm Product Status", "active": active,
        "action": f"/dashboard/inventory/products/{product_id}/lifecycle",
    }, 200 if context else 404)


@router.post("/inventory/products/{product_id}/lifecycle")
async def lifecycle_route(request: Request, product_id: int):
    values = await _form(request)
    try:
        set_product_active(_require(request), product_id, values.get("active") == "true",
                           int(values.get("store_id")))
    except (ApplicationError, ValueError) as exc:
        return _redirect(f"/dashboard/inventory/products/{product_id}", error=str(exc))
    return _redirect(f"/dashboard/inventory/products/{product_id}", "Product status updated.")


def _operation_page(request, product_id, operation, store_id=None):
    try:
        session = _require(request)
        context = product_operation_context(session, product_id, store_id)
    except (ApplicationError, ValueError) as exc:
        return _render(request, "dashboard_error.html", {"title": "Access denied", "error": str(exc)}, 403)
    return _render(request, "stock_form.html", {
        **(context or {}), "operation": operation,
        "title": "Receive Stock" if operation == "receive" else "Adjust Stock",
        "action": f"/dashboard/inventory/products/{product_id}/{operation}", "errors": {},
    }, 200 if context else 404)


@router.get("/inventory/products/{product_id}/receive", response_class=HTMLResponse)
def receive_page(request: Request, product_id: int, store_id: int | None = None):
    return _operation_page(request, product_id, "receive", store_id)


@router.get("/inventory/products/{product_id}/adjust", response_class=HTMLResponse)
def adjust_page(request: Request, product_id: int, store_id: int | None = None):
    return _operation_page(request, product_id, "adjust", store_id)


async def _stock_write(request, product_id, operation):
    values = await _form(request)
    try:
        session = _require(request)
        if operation == "receive":
            receive_product_stock(session, product_id, values)
        else:
            current = product_operation_context(session, product_id, values.get("store_id"))
            new_quantity = int(values.get("new_quantity", -1))
            if new_quantity < current["product"]["quantity_in_stock"] and values.get("confirmed") != "true":
                raise ValueError("Negative adjustments require explicit confirmation.")
            adjust_product_stock(session, product_id, values)
    except (ApplicationError, ValueError) as exc:
        return _redirect(f"/dashboard/inventory/products/{product_id}/{operation}", error=str(exc))
    return _redirect(f"/dashboard/inventory/products/{product_id}",
                     "Stock received." if operation == "receive" else "Stock adjusted.")


@router.post("/inventory/products/{product_id}/receive")
async def receive_route(request: Request, product_id: int):
    return await _stock_write(request, product_id, "receive")


@router.post("/inventory/products/{product_id}/adjust")
async def adjust_route(request: Request, product_id: int):
    return await _stock_write(request, product_id, "adjust")


@router.get("/inventory/categories", response_class=HTMLResponse)
def categories_page(request: Request, edit: int | None = None, error: str = "", success: str = ""):
    session = dashboard_session(request)
    return _render(request, "categories.html", {
        **category_context(edit), "title": "Category Management", "error": error,
        "success": success, "read_only": not can_manage_inventory(session),
    })


@router.post("/inventory/categories")
async def category_create_route(request: Request):
    values = await _form(request)
    try:
        save_category(_require(request), values)
    except (ApplicationError, ValueError) as exc:
        return _redirect("/dashboard/inventory/categories", error=str(exc))
    return _redirect("/dashboard/inventory/categories", "Category created.")


@router.post("/inventory/categories/{category_id}")
async def category_update_route(request: Request, category_id: int):
    values = await _form(request)
    try:
        save_category(_require(request), values, category_id)
    except (ApplicationError, ValueError) as exc:
        return _redirect(f"/dashboard/inventory/categories?edit={category_id}", error=str(exc))
    return _redirect("/dashboard/inventory/categories", "Category updated.")


@router.post("/inventory/categories/{category_id}/lifecycle")
async def category_lifecycle_route(request: Request, category_id: int):
    values = await _form(request)
    try:
        set_category_active(_require(request), category_id, values.get("active") == "true")
    except (ApplicationError, ValueError) as exc:
        return _redirect("/dashboard/inventory/categories", error=str(exc))
    return _redirect("/dashboard/inventory/categories", "Category status updated.")


@router.post("/inventory/products/{product_id}/barcode")
async def barcode_route(request: Request, product_id: int):
    values = await _form(request)
    try:
        result = barcode_operation(_require(request), product_id, values)
    except (ApplicationError, ValueError) as exc:
        return _redirect(f"/dashboard/inventory/products/{product_id}", error=str(exc))
    operation = values.get("operation", "preview")
    if operation == "preview":
        return _render(request, "label_preview.html", {"title": "Label Preview", "preview": result,
                                                        "product_id": product_id})
    message = "Barcode updated." if operation in {"assign", "generate"} else (
        "Label sent to printer." if result.get("success") else f"Printer unavailable: {result.get('error')}")
    return _redirect(f"/dashboard/inventory/products/{product_id}", message)
