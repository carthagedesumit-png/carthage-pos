"""Thin routes for persisted retail checkout."""
from urllib.parse import parse_qs,quote
from fastapi import APIRouter,Request
from fastapi.responses import HTMLResponse,RedirectResponse
from fastapi.templating import Jinja2Templates
from app.checkout.checkout_service import *
from app.core.exceptions import ApplicationError,AuthenticationError,AuthorizationError
from app.core.runtime_paths import resource_path
from app.dashboard.auth import CSRF_COOKIE,csrf_token,dashboard_session

router=APIRouter(prefix="/dashboard");templates=Jinja2Templates(directory=str(resource_path("app","dashboard","templates")))
async def _form(r):
 p=parse_qs((await r.body()).decode(),keep_blank_values=True);return {k:(v if k in {"payment_method","payment_amount","allocation_reference","sale_item_id","return_quantity"} else v[-1]) for k,v in p.items()}
def _session(r):return dashboard_session(r,required=True)
def _render(r,t,c,status=200):
 token=csrf_token(r);s=dashboard_session(r);resp=templates.TemplateResponse(r,t,{"request":r,"csrf_token":token,"session":s,"header":{"user":s.full_name if s else "Viewer","store":f"Store #{s.store_id}" if s else ""},"active_page":"sales",**c},status_code=status)
 if not r.cookies.get(CSRF_COOKIE):resp.set_cookie(CSRF_COOKIE,token,samesite="strict",secure=False)
 return resp
def _redirect(path,success=None,error=None):
 if success or error:path+=("&" if "?" in path else "?")+f"{'success' if success else 'error'}={quote(str(success or error))}"
 return RedirectResponse(path,status_code=303)

@router.get("/sales/checkout",response_class=HTMLResponse)
def checkout_page(request:Request,cart_id:int|None=None,q:str="",customer_q:str="",success:str="",error:str=""):
 try:
  s=_session(request);cart=get_cart(s,cart_id) if cart_id else active_cart(s)
  products=product_search(s,q) if q else [];customers=customer_search(s,customer_q) if customer_q else []
  return _render(request,"sales_checkout.html",{"title":"Retail Checkout","checkout":cart,"holds":list_holds(s),"products":products,"customers":customers,"q":q,"customer_q":customer_q,"success":success,"error":error})
 except (ApplicationError,ValueError) as exc:return _render(request,"dashboard_error.html",{"title":"Checkout unavailable","page_title":"Checkout unavailable","page_subtitle":str(exc)},403)

@router.post("/sales/carts/{cart_id}/items")
async def item_add(request:Request,cart_id:int):
 v=await _form(request)
 try:add_identifier(_session(request),cart_id,v.get("identifier"),int(v.get("quantity") or 1))
 except (ApplicationError,ValueError) as exc:return _redirect(f"/dashboard/sales/checkout?cart_id={cart_id}",error=str(exc))
 return _redirect(f"/dashboard/sales/checkout?cart_id={cart_id}")
@router.post("/sales/carts/{cart_id}/items/{product_id}")
async def item_set(request:Request,cart_id:int,product_id:int):
 v=await _form(request)
 try:set_item(_session(request),cart_id,product_id,int(v.get("quantity") or 0))
 except (ApplicationError,ValueError) as exc:return _redirect(f"/dashboard/sales/checkout?cart_id={cart_id}",error=str(exc))
 return _redirect(f"/dashboard/sales/checkout?cart_id={cart_id}")
@router.post("/sales/carts/{cart_id}/customer")
async def customer_set(request:Request,cart_id:int):
 v=await _form(request)
 try:set_customer(_session(request),cart_id,v.get("customer_id"))
 except (ApplicationError,ValueError) as exc:return _redirect(f"/dashboard/sales/checkout?cart_id={cart_id}",error=str(exc))
 return _redirect(f"/dashboard/sales/checkout?cart_id={cart_id}")
@router.post("/sales/carts/{cart_id}/discount")
async def discount(request:Request,cart_id:int):
 v=await _form(request)
 try:apply_discount(_session(request),cart_id,v.get("discount_type"),float(v.get("discount_value") or 0),v.get("discount_reason"))
 except (ApplicationError,ValueError) as exc:return _redirect(f"/dashboard/sales/checkout?cart_id={cart_id}",error=str(exc))
 return _redirect(f"/dashboard/sales/checkout?cart_id={cart_id}",success="Discount approved.")
@router.post("/sales/carts/{cart_id}/status")
async def cart_status(request:Request,cart_id:int):
 v=await _form(request);action=v.get("action")
 try:
  s=_session(request);{"suspend":suspend_cart,"resume":resume_cart,"void":void_cart}[action](s,cart_id)
 except (ApplicationError,ValueError,KeyError) as exc:return _redirect("/dashboard/sales/checkout",error=str(exc))
 return _redirect("/dashboard/sales/checkout",success=f"Cart {action}d.")
@router.post("/sales/carts/{cart_id}/checkout")
async def cart_checkout(request:Request,cart_id:int):
 v=await _form(request)
 try:
  methods=v.get("payment_method",[]);amounts=v.get("payment_amount",[]);refs=v.get("allocation_reference",[]) or ([""]*len(methods));payments=[{"payment_method":m,"amount":a,"reference":r or None} for m,a,r in zip(methods,amounts,refs) if m and a]
  method=v.get("tender_type") or "CASH";result=checkout(_session(request),cart_id,payment_method=method,amount_paid=v.get("amount_paid") or None,payments=payments or None,redeem_points=v.get("redeem_points") or 0,print_after=v.get("print_after")=="true",payment_reference=v.get("payment_reference") or None)
 except (ApplicationError,ValueError) as exc:return _redirect(f"/dashboard/sales/checkout?cart_id={cart_id}",error=str(exc))
 return _redirect(f"/dashboard/sales/{result['receipt']['sale']['sale_id']}/receipt",success="Sale completed.")
@router.get("/sales/{sale_id}/receipt",response_class=HTMLResponse)
def receipt(request:Request,sale_id:int,success:str="",error:str=""):
 try:s=_session(request);data=print_receipt_data(sale_id);doc=receipt_actions(s,sale_id,"preview")
 except (ApplicationError,ValueError) as exc:return _render(request,"dashboard_error.html",{"title":"Receipt unavailable","page_title":"Receipt unavailable","page_subtitle":str(exc)},404)
 return _render(request,"sales_receipt.html",{"title":"Receipt Preview","detail":data,"document":doc,"sale_id":sale_id,"success":success,"error":error})
@router.post("/sales/{sale_id}/receipt")
async def receipt_action(request:Request,sale_id:int):
 v=await _form(request)
 try:result=receipt_actions(_session(request),sale_id,v.get("action"),v.get("reason") or "")
 except (ApplicationError,ValueError) as exc:return _redirect(f"/dashboard/sales/{sale_id}/receipt",error=str(exc))
 return _redirect(f"/dashboard/sales/{sale_id}/receipt",success="Action completed." if result.get("success",True) else result.get("error"))
@router.post("/sales/{sale_id}/returns")
async def return_route(request:Request,sale_id:int):
 v=await _form(request)
 try:
  items=[{"sale_item_id":int(i),"quantity":int(q)} for i,q in zip(v.get("sale_item_id",[]),v.get("return_quantity",[])) if q and int(q)>0]
  result=return_sale(_session(request),sale_id,items,v.get("reason"))
 except (ApplicationError,ValueError) as exc:return _redirect(f"/dashboard/sales/{sale_id}/receipt",error=str(exc))
 return _redirect(f"/dashboard/sales/{sale_id}/receipt",success=f"Return #{result['return']['id']} completed.")
