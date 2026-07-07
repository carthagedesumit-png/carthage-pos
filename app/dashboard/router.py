from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.dashboard.services.dashboard_service import get_dashboard_summary

templates = Jinja2Templates(directory="app/dashboard/templates")

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def get_header():
    """
    Temporary header information.
    Later this will come from the authenticated user session.
    """
    return {
        "user": "Administrator",
        "store": "Main Store",
    }


@router.get("/", response_class=HTMLResponse)
def dashboard_home(request: Request):
    return templates.TemplateResponse(
        "overview.html",
        {
            "request": request,
            "title": "Carthage POS Executive Dashboard",
            "metrics": get_dashboard_summary(),
            "header": get_header(),
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
        "login.html",
        {
            "request": request,
            "title": "Dashboard Login",
            "header": {
                "user": "Guest",
                "store": "",
            },
        },
    )
