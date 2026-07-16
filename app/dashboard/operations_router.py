"""Thin administrator UI for diagnostics and maintenance services."""
from urllib.parse import parse_qs,quote
from fastapi import APIRouter,Request
from fastapi.responses import HTMLResponse,RedirectResponse,JSONResponse
from fastapi.templating import Jinja2Templates
from app.core.exceptions import ApplicationError
from app.core.runtime_paths import resource_path
from app.dashboard.auth import CSRF_COOKIE,csrf_token,dashboard_session
from app.operations.pilot_service import diagnostics,export_configuration,maintenance_history,run_maintenance
router=APIRouter(prefix='/dashboard/system');templates=Jinja2Templates(directory=str(resource_path('app','dashboard','templates')))
def _render(request,template,context):
    session=dashboard_session(request,True);token=csrf_token(request);response=templates.TemplateResponse(request,template,{'request':request,'title':'CBOS Operations','active_page':'system','session':session,'csrf_token':token,'header':{'user':session.full_name,'store':f'Store #{session.store_id}'},**context})
    if not request.cookies.get(CSRF_COOKIE):response.set_cookie(CSRF_COOKIE,token,samesite='strict',secure=False)
    return response
@router.get('/diagnostics',response_class=HTMLResponse)
def diagnostic_page(request:Request,success:str='',error:str=''):return _render(request,'diagnostics.html',{'diagnostics':diagnostics(dashboard_session(request,True)),'success':success,'error':error})
@router.get('/maintenance',response_class=HTMLResponse)
def maintenance_page(request:Request,success:str='',error:str=''):return _render(request,'maintenance.html',{'history':maintenance_history(dashboard_session(request,True)),'success':success,'error':error})
@router.post('/maintenance')
async def maintenance_action(request:Request):
    values=parse_qs((await request.body()).decode());operation=(values.get('operation') or [''])[-1]
    try:result=run_maintenance(dashboard_session(request,True),operation);return RedirectResponse('/dashboard/system/maintenance?success='+quote(result['operation']+' completed.'),303)
    except (ApplicationError,ValueError) as exc:return RedirectResponse('/dashboard/system/maintenance?error='+quote(str(exc)),303)
@router.get('/configuration/export')
def configuration_export(request:Request):return JSONResponse(export_configuration(dashboard_session(request,True)),headers={'Content-Disposition':'attachment; filename=cbos-configuration.json'})
