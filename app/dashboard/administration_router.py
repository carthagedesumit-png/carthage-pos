"""Protected, thin Administration Workspace routes."""
from urllib.parse import parse_qs, quote
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.administration.user_service import (
    administration_form_options, create_managed_user, get_managed_user,
    require_administration_access, reset_user_password, set_user_active, set_user_locked,
    terminate_other_sessions, terminate_session, update_managed_user,
)
from app.core.exceptions import ApplicationError, AuthenticationError, AuthorizationError
from app.core.runtime_paths import resource_path
from app.dashboard.auth import CSRF_COOKIE, SESSION_COOKIE, csrf_token, dashboard_session
from app.dashboard.services.admin_service import (
    get_dashboard_system_summary, get_dashboard_system_user_detail, list_dashboard_system_users,
)

router = APIRouter(prefix="/dashboard")
templates = Jinja2Templates(directory=str(resource_path("app", "dashboard", "templates")))

async def _form(request):
    parsed = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    return {key: (values if key == "store_ids" else values[-1]) for key, values in parsed.items()}

def _session(request): return require_administration_access(dashboard_session(request, required=True))
def _read_session(request):
    session=dashboard_session(request)
    if session:return require_administration_access(session)
    if request.cookies.get(SESSION_COOKIE):raise AuthorizationError("Administration access is not available for this session.")
    return None

def _render(request, template, context, status=200):
    token=csrf_token(request); session=dashboard_session(request)
    payload={"request":request,"csrf_token":token,"session":session,"header":{"user":session.full_name if session else "Dashboard Viewer","store":f"Store #{session.store_id}" if session else "All Stores"},"active_page":"system",**context}
    response=templates.TemplateResponse(request,template,payload,status_code=status)
    if not request.cookies.get(CSRF_COOKIE): response.set_cookie(CSRF_COOKIE,token,samesite="strict",secure=False)
    return response

def _redirect(path, success=None, error=None):
    value=success or error; key="success" if success else "error"
    if value: path += ("&" if "?" in path else "?")+f"{key}={quote(str(value))}"
    return RedirectResponse(path,status_code=303)

def _denied(request, exc): return _render(request,"dashboard_error.html",{"title":"Administration access denied","page_title":"Administration access denied","page_subtitle":str(exc)},403)

@router.get("/system",response_class=HTMLResponse)
def system_home(request:Request):
    try: session=_read_session(request)
    except (AuthenticationError,AuthorizationError) as exc:return _denied(request,exc)
    return _render(request,"system.html",{"title":"Administration Workspace - Carthage Business Operating System","page_title":"Administration Workspace","page_subtitle":"CBOS system control for users, licensing, backups, deployment, hardware, and configuration.","summary":get_dashboard_system_summary(),"can_manage_users":True})

@router.get("/system/users",response_class=HTMLResponse)
def users(request:Request,search:str="",role:str="",active:str="all",page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100),success:str="",error:str=""):
    try: session=_read_session(request)
    except (AuthenticationError,AuthorizationError) as exc:return _denied(request,exc)
    result=list_dashboard_system_users({"search":search,"role":role,"active":active,"page":page,"page_size":page_size})
    return _render(request,"system_users.html",{"title":"Users - Carthage Business Operating System","users":result["items"],"filters":result["filters"],"pagination":result["pagination"],"roles":["","admin","manager","cashier","auditor","inventory_officer"],"active_filters":["active","inactive","locked","all"],"success":success,"error":error,"can_create":bool(session)})

@router.get("/system/users/new",response_class=HTMLResponse)
def user_new(request:Request):
    try: session=_session(request); options=administration_form_options(session)
    except (AuthenticationError,AuthorizationError) as exc:return _denied(request,exc)
    return _render(request,"system_user_form.html",{"title":"Create User","form_title":"Create User","action":"/dashboard/system/users","values":{},"user":None,"errors":{},**options})

@router.post("/system/users")
async def user_create(request:Request):
    values=await _form(request)
    try:
        session=_session(request); user=create_managed_user(session,username=values.get("username"),password=values.get("password"),full_name=values.get("full_name"),role=values.get("role"),email=values.get("email"),store_ids=values.get("store_ids",[]),home_store_id=values.get("home_store_id"),force_password_change=values.get("force_password_change")=="true")
    except (ApplicationError,ValueError) as exc:
        session=dashboard_session(request)
        if not session:return _denied(request,exc)
        return _render(request,"system_user_form.html",{"title":"Create User","form_title":"Create User","action":"/dashboard/system/users","values":values,"user":None,"errors":{"form":str(exc)},**administration_form_options(session)},422 if not isinstance(exc,AuthorizationError) else 403)
    return _redirect(f"/dashboard/system/users/{user['id']}",success="User created.")

@router.get("/system/users/{user_id}",response_class=HTMLResponse)
def user_detail(request:Request,user_id:int,success:str="",error:str=""):
    try:
        session=_read_session(request)
        if session:
            detail=get_managed_user(session,user_id)
            detail_payload={"user":detail,"activity":detail["audit"],"sessions":detail["sessions"],"permissions":detail["permissions"]}
        else:
            detail_payload=get_dashboard_system_user_detail(user_id); detail=detail_payload["user"] if detail_payload else None
    except (AuthenticationError,AuthorizationError) as exc:return _denied(request,exc)
    except (ApplicationError,ValueError) as exc:return _render(request,"dashboard_error.html",{"title":"User Not Found","page_title":"User Not Found","page_subtitle":str(exc)},404)
    if not detail:return _render(request,"dashboard_error.html",{"title":"User Not Found","page_title":"User Not Found","page_subtitle":"User does not exist."},404)
    return _render(request,"system_user_detail.html",{"title":f"{detail['username']} - Carthage Business Operating System","detail":detail_payload,"user_id":user_id,"success":success,"error":error,"can_edit":bool(session) and not(session.role=="manager" and detail["role"] in {"admin","manager"})})

@router.get("/system/users/{user_id}/edit",response_class=HTMLResponse)
def user_edit(request:Request,user_id:int):
    try: session=_session(request); user=get_managed_user(session,user_id); options=administration_form_options(session)
    except (AuthenticationError,AuthorizationError) as exc:return _denied(request,exc)
    return _render(request,"system_user_form.html",{"title":"Edit User","form_title":"Edit User","action":f"/dashboard/system/users/{user_id}","values":user,"user":user,"errors":{},**options})

@router.post("/system/users/{user_id}")
async def user_update(request:Request,user_id:int):
    values=await _form(request)
    try: user=update_managed_user(_session(request),user_id,full_name=values.get("full_name"),role=values.get("role"),email=values.get("email"),store_ids=values.get("store_ids",[]),home_store_id=values.get("home_store_id"))
    except (ApplicationError,ValueError) as exc:return _redirect(f"/dashboard/system/users/{user_id}/edit",error=str(exc))
    return _redirect(f"/dashboard/system/users/{user['id']}",success="User updated.")

@router.post("/system/users/{user_id}/lifecycle")
async def lifecycle(request:Request,user_id:int):
    values=await _form(request)
    try:set_user_active(_session(request),user_id,values.get("active")=="true")
    except (ApplicationError,ValueError) as exc:return _redirect(f"/dashboard/system/users/{user_id}",error=str(exc))
    return _redirect(f"/dashboard/system/users/{user_id}",success="Account status updated.")

@router.post("/system/users/{user_id}/lock")
async def lock(request:Request,user_id:int):
    values=await _form(request)
    try:set_user_locked(_session(request),user_id,values.get("locked")=="true")
    except (ApplicationError,ValueError) as exc:return _redirect(f"/dashboard/system/users/{user_id}",error=str(exc))
    return _redirect(f"/dashboard/system/users/{user_id}",success="Account lock status updated.")

@router.get("/system/users/{user_id}/password",response_class=HTMLResponse)
def password_page(request:Request,user_id:int):
    try:session=_session(request); user=get_managed_user(session,user_id)
    except (AuthenticationError,AuthorizationError) as exc:return _denied(request,exc)
    return _render(request,"system_password_reset.html",{"title":"Reset Password","user":user,"errors":{}})

@router.post("/system/users/{user_id}/password")
async def password_reset(request:Request,user_id:int):
    values=await _form(request)
    try:reset_user_password(_session(request),user_id,values.get("temporary_password"))
    except (ApplicationError,ValueError) as exc:return _render(request,"system_password_reset.html",{"title":"Reset Password","user":get_managed_user(dashboard_session(request),user_id),"errors":{"form":str(exc)}},422)
    return _redirect(f"/dashboard/system/users/{user_id}",success="Temporary password set; existing sessions revoked.")

@router.post("/system/users/{user_id}/sessions/{reference}/terminate")
def session_terminate(request:Request,user_id:int,reference:str):
    try:terminate_session(_session(request),user_id,reference)
    except (ApplicationError,ValueError) as exc:return _redirect(f"/dashboard/system/users/{user_id}",error=str(exc))
    return _redirect(f"/dashboard/system/users/{user_id}",success="Session terminated.")

@router.post("/system/sessions/terminate-others")
def sessions_terminate_others(request:Request):
    try:count=terminate_other_sessions(_session(request),request.cookies.get(SESSION_COOKIE,""))
    except (ApplicationError,ValueError) as exc:return _redirect("/dashboard/system/users",error=str(exc))
    return _redirect("/dashboard/system/users",success=f"Terminated {count} other sessions.")
