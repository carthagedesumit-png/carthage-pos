"""Thin dashboard transport for the finance service."""
from urllib.parse import parse_qs,quote
from fastapi import APIRouter,Request
from fastapi.responses import HTMLResponse,RedirectResponse
from fastapi.templating import Jinja2Templates
from app.core.exceptions import ApplicationError
from app.core.runtime_paths import resource_path
from app.dashboard.auth import CSRF_COOKIE,csrf_token,dashboard_session
from app.finance import finance_service as finance
from app.finance.integration_service import backfill,create_opening_batch,post_opening_batch,reconciliation_report
from app.finance.posting_service import integration_health,retry_event

router=APIRouter(prefix='/dashboard/finance');templates=Jinja2Templates(directory=str(resource_path('app','dashboard','templates')))
async def _form(r):
    values=parse_qs((await r.body()).decode(),keep_blank_values=True);return {k:(v if k in {'account_id','debit','credit','line_description'} else v[-1]) for k,v in values.items()}
def _go(section='',success=None,error=None):
    path='/dashboard/finance'+(f'/{section}' if section else '')
    if success or error:path+='?'+('success=' if success else 'error=')+quote(str(success or error))
    return RedirectResponse(path,status_code=303)
def _render(request,section,success='',error=''):
    session=dashboard_session(request,required=True);data=finance.overview(session);data['integration']=integration_health(session);data['reconciliation']=reconciliation_report(session);token=csrf_token(request)
    response=templates.TemplateResponse(request,'finance.html',{'request':request,'title':'Financial Management','active_page':'finance','section':section,'data':data,'session':session,'can_write':session.role in finance.WRITE_ROLES,'csrf_token':token,'success':success,'error':error,'header':{'user':session.full_name,'store':f'Store #{session.store_id}'}})
    if not request.cookies.get(CSRF_COOKIE):response.set_cookie(CSRF_COOKIE,token,samesite='strict',secure=False)
    return response
@router.get('',response_class=HTMLResponse)
@router.get('/{section}',response_class=HTMLResponse)
def page(request:Request,section:str='overview',success:str='',error:str=''):
    if section not in {'overview','cash','banking','expenses','income','journals','accounts','reports','tax','integration','opening'}:section='overview'
    return _render(request,section,success,error)
@router.post('/journals')
async def journal(request:Request):
    v=await _form(request)
    try:
        lines=[{'account_id':a,'debit':d or 0,'credit':c or 0,'description':x} for a,d,c,x in zip(v.get('account_id',[]),v.get('debit',[]),v.get('credit',[]),v.get('line_description',[])) if a]
        finance.create_journal(dashboard_session(request,True),v.get('entry_date'),v.get('description'),lines,v.get('reference'),post=v.get('post')=='true')
        return _go('journals','Journal saved.')
    except (ApplicationError,ValueError) as exc:return _go('journals',error=exc)
@router.post('/journals/{journal_id}/post')
def post(request:Request,journal_id:int):
    try:finance.post_journal(dashboard_session(request,True),journal_id);return _go('journals','Journal posted.')
    except ApplicationError as exc:return _go('journals',error=exc)
@router.post('/accounts')
async def account(request:Request):
    v=await _form(request)
    try:finance.create_account(dashboard_session(request,True),v.get('code'),v.get('name'),v.get('account_type'));return _go('accounts','Account created.')
    except (ApplicationError,ValueError) as exc:return _go('accounts',error=exc)
@router.post('/expenses')
async def expense(request:Request):
    v=await _form(request)
    try:finance.create_expense(dashboard_session(request,True),v.get('expense_date'),v.get('category_id'),v.get('amount'),v.get('description'),expense_type=v.get('expense_type'),tax_amount=v.get('tax_amount') or 0,attachment_name=v.get('attachment_name'),attachment_type=v.get('attachment_type'),recurring_rule=v.get('recurring_rule'));return _go('expenses','Expense submitted for approval.')
    except (ApplicationError,ValueError) as exc:return _go('expenses',error=exc)
@router.post('/expenses/{expense_id}/approve')
def approve(request:Request,expense_id:int):
    try:finance.approve_expense(dashboard_session(request,True),expense_id);return _go('expenses','Expense approved and posted.')
    except ApplicationError as exc:return _go('expenses',error=exc)
@router.post('/expense-categories')
async def category(request:Request):
    v=await _form(request)
    try:finance.create_expense_category(dashboard_session(request,True),v.get('name'),v.get('account_id'));return _go('expenses','Expense category created.')
    except (ApplicationError,ValueError) as exc:return _go('expenses',error=exc)
@router.post('/vendors')
async def vendor(request:Request):
    v=await _form(request)
    try:finance.create_vendor(dashboard_session(request,True),v.get('name'),v.get('email'),v.get('phone'));return _go('expenses','Vendor created.')
    except (ApplicationError,ValueError) as exc:return _go('expenses',error=exc)
@router.post('/income')
async def income(request:Request):
    v=await _form(request)
    try:finance.record_income(dashboard_session(request,True),v.get('income_date'),v.get('income_type'),v.get('amount'),v.get('description'),v.get('tax_amount') or 0);return _go('income','Income posted.')
    except (ApplicationError,ValueError) as exc:return _go('income',error=exc)
@router.post('/cash')
async def cash(request:Request):
    v=await _form(request);s=dashboard_session(request,True)
    try:
        action=v.get('action')
        if action=='open':finance.open_cash(s,v.get('amount'))
        elif action=='adjust':finance.cash_adjustment(s,int(v.get('cash_session_id')),v.get('amount'),v.get('reason'),v.get('movement_type'),v.get('destination_store_id') or None)
        elif action=='close':finance.close_cash(s,int(v.get('cash_session_id')),v.get('amount'))
        else:raise ValueError('Unknown cash action.')
        return _go('cash','Cash operation completed.')
    except (ApplicationError,ValueError) as exc:return _go('cash',error=exc)
@router.post('/tax')
async def tax(request:Request):
    v=await _form(request)
    try:finance.add_tax_rate(dashboard_session(request,True),v.get('name'),v.get('rate'),v.get('pricing_mode'));return _go('tax','Tax rate created.')
    except (ApplicationError,ValueError) as exc:return _go('tax',error=exc)
@router.post('/periods/lock')
async def period(request:Request):
    v=await _form(request)
    try:finance.lock_period(dashboard_session(request,True),v.get('name'),v.get('start_date'),v.get('end_date'));return _go('reports','Accounting period locked.')
    except (ApplicationError,ValueError) as exc:return _go('reports',error=exc)
@router.post('/opening')
async def opening(request:Request):
    v=await _form(request)
    try:
        lines=[{'account_id':a,'debit':d or 0,'credit':c or 0,'description':x} for a,d,c,x in zip(v.get('account_id',[]),v.get('debit',[]),v.get('credit',[]),v.get('line_description',[])) if a and (d or c)]
        batch=create_opening_batch(dashboard_session(request,True),v.get('effective_date'),v.get('description'),lines,v.get('equity_account_id'))
        if v.get('post')=='true':post_opening_batch(dashboard_session(request,True),batch['batch_id'])
        return _go('opening','Opening balance batch saved.')
    except (ApplicationError,ValueError) as exc:return _go('opening',error=exc)
@router.post('/integration/backfill')
async def run_backfill(request:Request):
    v=await _form(request)
    try:
        result=backfill(dashboard_session(request,True),dry_run=v.get('confirm')!='true',module=v.get('module') or None,date_from=v.get('date_from') or None,date_to=v.get('date_to') or None)
        return _go('integration',f"Backfill {'preview' if result['dry_run'] else 'completed'}: {result['eligible']} eligible, {result['posted']} posted.")
    except (ApplicationError,ValueError) as exc:return _go('integration',error=exc)
@router.post('/integration/{event_id}/retry')
def retry(request:Request,event_id:int):
    try:retry_event(dashboard_session(request,True),event_id);return _go('integration','Posting retried successfully.')
    except (ApplicationError,ValueError) as exc:return _go('integration',error=exc)
