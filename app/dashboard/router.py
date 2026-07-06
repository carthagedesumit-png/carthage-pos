from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.dashboard.services.dashboard_service import get_dashboard_summary

templates = Jinja2Templates(directory="app/dashboard/templates")

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/", response_class=HTMLResponse)
def dashboard_home(request: Request):
    return templates.TemplateResponse(
        request,
        "overview.html",
        {
            "title": "Carthage POS Executive Dashboard",
            "metrics": get_dashboard_summary(),
        },
    )


@router.get("/api/summary")
def dashboard_summary():
    return get_dashboard_summary()


@router.get("/health")
def dashboard_health():
    return {
        "status": "ok",
        "module": "dashboard",
    }


@router.get("/login", response_class=HTMLResponse)
def dashboard_login(request: Request):
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "title": "Dashboard Login",
        },
    )
