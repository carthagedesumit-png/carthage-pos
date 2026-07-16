"""Thin transport for the executive analytics workspace."""
from urllib.parse import parse_qs,quote
from fastapi import APIRouter,Request
from fastapi.responses import HTMLResponse,RedirectResponse,Response
from fastapi.templating import Jinja2Templates
from app.core.exceptions import ApplicationError
from app.core.runtime_paths import resource_path
from app.dashboard.auth import CSRF_COOKIE,csrf_token,dashboard_session
from app.executive.analytics_service import create_schedule,executive_dashboard,export_executive_report,list_schedules
router=APIRouter(prefix='/dashboard/executive');templates=Jinja2Templates(directory=str(resource_path('app','dashboard','templates')))
def _render(request,data,success='',error=''):
    session=dashboard_session(request,True);token=csrf_token(request);response=templates.TemplateResponse(request,'executive.html',{'request':request,'title':'Executive Intelligence','active_page':'executive','session':session,'csrf_token':token,'data':data,'schedules':list_schedules(session),'success':success,'error':error,'header':{'user':session.full_name,'store':'All Stores' if session.role=='admin' else f'Store #{session.store_id}'}})
    if not request.cookies.get(CSRF_COOKIE):response.set_cookie(CSRF_COOKIE,token,samesite='strict',secure=False)
    return response
@router.get('',response_class=HTMLResponse)
def workspace(request:Request,refresh:bool=False,success:str='',error:str=''):return _render(request,executive_dashboard(dashboard_session(request,True),refresh=refresh),success,error)
@router.get('/export/{format_name}')
def export(request:Request,format_name:str):
    result=export_executive_report(dashboard_session(request,True),format_name);return Response(result['content'],media_type=result['media_type'],headers={'Content-Disposition':f'attachment; filename="{result["filename"]}"'})
@router.post('/schedules')
async def schedule(request:Request):
    values={k:v[-1] for k,v in parse_qs((await request.body()).decode(),keep_blank_values=True).items()}
    try:create_schedule(dashboard_session(request,True),values.get('name'),values.get('frequency'),values.get('format'),recipients=values.get('recipients'));return RedirectResponse('/dashboard/executive?success='+quote('Executive report schedule created.'),303)
    except (ApplicationError,ValueError) as exc:return RedirectResponse('/dashboard/executive?error='+quote(str(exc)),303)
