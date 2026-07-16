"""Cached, store-aware executive KPI, forecast, insight, export, and schedule service."""
import csv,io,json,math,time
from datetime import date,datetime,timedelta
from html import escape
from threading import RLock

from auth import ROLE_ADMIN,ROLE_MANAGER,require_store_access,validate_session
from app.core.exceptions import AuthorizationError,ValidationError
from app.database.db_manager import get_connection,get_database_path
from app.database.transactions import transaction
from app.finance.finance_service import statements
from app.reports.reporting_service import (get_branch_comparison_report,get_cashier_performance_report,get_customer_lifetime_value,get_date_range_sales_report,get_inventory_valuation,get_low_stock_products,get_payment_method_report,get_product_performance_report,get_stock_value_by_category,get_top_customers)

_CACHE={};_LOCK=RLock();CACHE_TTL_SECONDS=60
def require_executive(session):
    session=validate_session(session)
    if session.role not in {ROLE_ADMIN,ROLE_MANAGER}:raise AuthorizationError('Executive analytics is restricted to administrators and managers.')
    return session
def _scope(session):return None if session.role==ROLE_ADMIN else [session.store_id]
def clear_cache(session=None):
    if session:require_executive(session)
    with _LOCK:_CACHE.clear()
def executive_dashboard(session,refresh=False,as_of=None):
    session=require_executive(session);today=as_of or date.today();key=(get_database_path(),session.user_id,session.role,session.store_id,str(today))
    with _LOCK:
        cached=_CACHE.get(key)
        if cached and not refresh and time.monotonic()-cached[0]<CACHE_TTL_SECONDS:return {**cached[1],'cache':{'hit':True,'generated_at':cached[2]}}
    payload=_build(session,today);generated=datetime.now().isoformat(timespec='seconds')
    with _LOCK:_CACHE[key]=(time.monotonic(),payload,generated)
    return {**payload,'cache':{'hit':False,'generated_at':generated}}
def _build(session,today):
    stores=_scope(session);yesterday=today-timedelta(days=1);week=today-timedelta(days=today.weekday());month=today.replace(day=1);year=today.replace(month=1,day=1)
    periods={'today':_period(session,today,today,stores),'yesterday':_period(session,yesterday,yesterday,stores),'week':_period(session,week,today,stores),'month':_period(session,month,today,stores),'year':_period(session,year,today,stores)}
    lifetime=get_product_performance_report(limit=10,store_ids=stores,session=session);inventory=get_inventory_valuation(store_ids=stores,session=session);low=get_low_stock_products(store_ids=stores,session=session);branches=get_branch_comparison_report(store_ids=stores,session=session);employees=get_cashier_performance_report(store_ids=stores,session=session);categories=get_stock_value_by_category(store_ids=stores,session=session);payments=get_payment_method_report(store_ids=stores,session=session);customers=get_top_customers(limit=10,store_ids=stores,session=session);extra=_extra_metrics(session,stores,today);finance=_finance_totals(session,branches)
    gross_profit=periods['year'].get('estimated_profit',0);revenue=periods['year']['total_sales'];margin=round(gross_profit/revenue*100,2) if revenue else 0
    kpis={'revenue_today':periods['today']['total_sales'],'revenue_yesterday':periods['yesterday']['total_sales'],'revenue_week':periods['week']['total_sales'],'revenue_month':periods['month']['total_sales'],'revenue_year':revenue,'gross_profit':gross_profit,'net_profit':finance['net_profit'],'gross_margin_percent':margin,'cash_position':finance['cash'],'bank_balances':finance['bank'],'outstanding_receivables':extra['receivables'],'outstanding_payables':finance['payables'],'inventory_valuation':inventory['inventory_cost'],'inventory_turnover':round((periods['year'].get('cost_of_goods_sold',0) or 0)/inventory['inventory_cost'],2) if inventory['inventory_cost'] else 0,'average_basket_value':periods['year']['average_sale'],'tax_collected':periods['year']['tax_total']}
    forecasts=_forecasts(extra,today);charts={'revenue_trend':extra['daily'],'profit_trend':extra['daily_profit'],'cash_flow_trend':extra['cash_flow'],'sales_heatmap':extra['heatmap'],'product_performance':lifetime['best_selling_products'],'category_performance':extra['category_profitability'],'branch_comparison':branches,'inventory_movement':extra['inventory_movement'],'expense_breakdown':extra['expenses'],'revenue_composition':payments}
    payload={'as_of':str(today),'scope':'ALL_STORES' if stores is None else f'STORE_{session.store_id}','kpis':kpis,'periods':periods,'inventory':{'stock_ageing':extra['stock_ageing'],'dead_stock':extra['dead_stock'],'low_stock_alerts':low,'fast_moving':lifetime['best_selling_products'],'slow_moving':lifetime['slow_moving_products'],'top_selling':lifetime['highest_revenue_products']},'performance':{'top_customers':customers,'top_suppliers':extra['suppliers'],'employees':employees,'branches':branches,'categories':extra['category_profitability'],'supplier_performance':extra['suppliers'],'customer_lifetime_value':extra['customer_ltv'],'sales_by_hour':extra['by_hour'],'sales_by_weekday':extra['by_weekday'],'refund_trends':extra['refunds'],'discount_trends':extra['discounts']},'charts':charts,'forecasts':forecasts}
    payload['insights']=_insights(payload,extra);return payload
def _period(session,start,end,stores):return get_date_range_sales_report(start,end,top_limit=10,store_ids=stores,session=session)
def _finance_totals(session,branches):
    ids=[b['store_id'] for b in branches] or [session.store_id];result={'cash':0,'bank':0,'payables':0,'net_profit':0}
    for store in ids:
        data=statements(session,store_id=store);result['net_profit']+=data['profit_loss']['net_profit']
        for row in data['trial_balance']:
            if row['code']=='1000':result['cash']+=row['balance']
            elif row['code']=='1010':result['bank']+=row['balance']
            elif row['code']=='2000':result['payables']+=round(row['credit']-row['debit'],2)
    return {k:round(v,2) for k,v in result.items()}
def _extra_metrics(session,stores,today):
    clause,params=_store_filter(stores,'s');inv_clause,inv_params=_store_filter(stores,'si');start=today-timedelta(days=89)
    with get_connection() as conn:
        daily=[dict(r) for r in conn.execute(f"SELECT DATE(s.created_at) label,ROUND(SUM(s.total_amount-COALESCE((SELECT SUM(total_refunded) FROM sales_returns WHERE sale_id=s.sale_id),0)),2) value FROM sales s WHERE DATE(s.created_at)>=? {clause} GROUP BY DATE(s.created_at) ORDER BY label",[str(start),*params])]
        daily_profit=[dict(r) for r in conn.execute(f"SELECT DATE(s.created_at) label,ROUND(SUM(s.subtotal-s.discount_amount-COALESCE((SELECT SUM(total_refunded) FROM sales_returns WHERE sale_id=s.sale_id),0)-COALESCE((SELECT SUM(quantity*unit_cost_at_sale) FROM sale_items WHERE sale_id=s.sale_id),0)),2) value FROM sales s WHERE DATE(s.created_at)>=? {clause} GROUP BY DATE(s.created_at) ORDER BY label",[str(start),*params])]
        by_hour=[dict(r) for r in conn.execute(f"SELECT CAST(STRFTIME('%H',s.created_at) AS INTEGER) hour,COUNT(*) transactions,ROUND(SUM(s.total_amount),2) revenue FROM sales s WHERE 1=1 {clause} GROUP BY hour ORDER BY hour",params)];by_weekday=[dict(r) for r in conn.execute(f"SELECT STRFTIME('%w',s.created_at) weekday,COUNT(*) transactions,ROUND(SUM(s.total_amount),2) revenue FROM sales s WHERE 1=1 {clause} GROUP BY weekday ORDER BY weekday",params)]
        category=[dict(r) for r in conn.execute(f"SELECT COALESCE(c.name,'Uncategorized') name,ROUND(SUM(si.quantity*(si.price_at_sale-si.unit_cost_at_sale)),2) profit,ROUND(SUM(si.quantity*si.price_at_sale),2) revenue FROM sale_items si JOIN sales s ON s.sale_id=si.sale_id LEFT JOIN products p ON p.id=CAST(si.product_id AS INTEGER) LEFT JOIN categories c ON c.id=p.category_id WHERE 1=1 {clause} GROUP BY c.id,c.name ORDER BY profit DESC",params)]
        suppliers=[dict(r) for r in conn.execute(f"SELECT sup.id,sup.name,COUNT(DISTINCT pr.id) receipts,ROUND(COALESCE(SUM(pri.subtotal),0),2) received_value,ROUND(AVG(JULIANDAY(pr.received_at)-JULIANDAY(po.created_at)),1) average_delivery_days FROM suppliers sup LEFT JOIN purchase_orders po ON po.supplier_id=sup.id LEFT JOIN purchase_receipts pr ON pr.purchase_order_id=po.id LEFT JOIN purchase_receipt_items pri ON pri.receipt_id=pr.id GROUP BY sup.id,sup.name ORDER BY received_value DESC LIMIT 10")]
        ltv=[dict(r) for r in conn.execute(f"SELECT c.id,c.customer_code,c.first_name,c.last_name,ROUND(COALESCE(SUM(s.total_amount),0),2) lifetime_value,COUNT(s.sale_id) transactions FROM customers c LEFT JOIN sales s ON s.customer_id=c.id {('AND '+clause[5:]) if clause else ''} GROUP BY c.id ORDER BY lifetime_value DESC LIMIT 10",params)]
        stock=[dict(r) for r in conn.execute(f"SELECT p.id,p.sku,p.name,si.store_id,si.quantity_on_hand,si.average_cost,MAX(DATE(s.created_at)) last_sold_at,COALESCE(SUM(CASE WHEN DATE(s.created_at)>=DATE(?,'-30 days') THEN sold.quantity ELSE 0 END),0) sold_30 FROM store_inventory si JOIN products p ON p.id=si.product_id LEFT JOIN sale_items sold ON CAST(sold.product_id AS INTEGER)=p.id LEFT JOIN sales s ON s.sale_id=sold.sale_id AND s.store_id=si.store_id WHERE p.is_active=1 {inv_clause} GROUP BY p.id,si.store_id",[str(today),*inv_params])]
        refunds=[dict(r) for r in conn.execute(f"SELECT DATE(sr.created_at) label,ROUND(SUM(sr.total_refunded),2) value FROM sales_returns sr JOIN sales s ON s.sale_id=sr.sale_id WHERE DATE(sr.created_at)>=? {clause} GROUP BY DATE(sr.created_at) ORDER BY label",[str(start),*params])];discounts=[dict(r) for r in conn.execute(f"SELECT DATE(s.created_at) label,ROUND(SUM(s.discount_amount),2) value FROM sales s WHERE DATE(s.created_at)>=? {clause} GROUP BY DATE(s.created_at) ORDER BY label",[str(start),*params])]
        receivables=conn.execute(f"SELECT ROUND(COALESCE(SUM(amount_delta),0),2) FROM credit_transactions ct WHERE 1=1 {clause.replace('s.store_id','ct.store_id')}",params).fetchone()[0]
        movements=[dict(r) for r in conn.execute(f"SELECT DATE(sm.created_at) label,sm.movement_type,COALESCE(SUM(sm.quantity),0) quantity FROM stock_movements sm WHERE DATE(sm.created_at)>=? {clause.replace('s.store_id','sm.store_id')} GROUP BY label,sm.movement_type ORDER BY label",[str(start),*params])]
        expenses=[dict(r) for r in conn.execute(f"SELECT COALESCE(fc.name,e.expense_type) name,ROUND(SUM(e.amount),2) value FROM finance_expenses e LEFT JOIN finance_categories fc ON fc.id=e.category_id WHERE e.status='APPROVED' {clause.replace('s.store_id','e.store_id')} GROUP BY name ORDER BY value DESC",params)]
        cash_flow=[dict(r) for r in conn.execute(f"SELECT j.entry_date label,ROUND(SUM(l.debit-l.credit),2) value FROM finance_journal_lines l JOIN finance_journals j ON j.id=l.journal_id JOIN finance_accounts a ON a.id=l.account_id WHERE j.status='POSTED' AND a.code IN ('1000','1010') {clause.replace('s.store_id','j.store_id')} GROUP BY j.entry_date ORDER BY j.entry_date",params)]
    for item in stock:item['days_cover']=round(item['quantity_on_hand']/(item['sold_30']/30),1) if item['sold_30'] else None
    return {'daily':daily,'daily_profit':daily_profit,'by_hour':by_hour,'by_weekday':by_weekday,'heatmap':by_weekday,'category_profitability':category,'suppliers':suppliers,'customer_ltv':ltv,'stock_ageing':sorted(stock,key=lambda x:x['last_sold_at'] or '')[:20],'dead_stock':[x for x in stock if not x['last_sold_at'] and x['quantity_on_hand']>0],'refunds':refunds,'discounts':discounts,'receivables':round(receivables or 0,2),'inventory_movement':movements,'expenses':expenses,'cash_flow':cash_flow,'stock':stock}
def _store_filter(stores,alias):
    if stores is None:return '',[]
    marks=','.join('?' for _ in stores);return f' AND {alias}.store_id IN ({marks})',list(stores)
def _forecasts(extra,today):
    values=[float(x['value']) for x in extra['daily']];recent=values[-30:];prior=values[-60:-30];average=round(sum(recent)/len(recent),2) if recent else 0;growth=(sum(recent)/sum(prior)-1) if prior and sum(prior) else 0;growth=max(-.5,min(.5,growth));revenue=[{'date':str(today+timedelta(days=i)),'value':round(average*((1+growth)**(i/30)),2)} for i in range(1,31)]
    depletion=[]
    for item in extra['stock']:
        rate=item['sold_30']/30
        days=math.floor(item['quantity_on_hand']/rate) if rate else None
        depletion.append({'product_id':item['id'],'sku':item['sku'],'name':item['name'],'daily_rate':round(rate,2),'days_remaining':days,'expected_stockout':str(today+timedelta(days=days)) if days is not None else None,'suggested_reorder_date':str(today+timedelta(days=max(0,days-7))) if days is not None else None,'slow_moving_prediction':rate<.1})
    weekdays={str(x['weekday']):x['revenue'] for x in extra['by_weekday']};return {'revenue':revenue,'cash_flow':[{'date':x['date'],'value':x['value']} for x in revenue],'inventory_depletion':depletion,'expected_stockouts':[x for x in depletion if x['days_remaining'] is not None and x['days_remaining']<=14],'slow_moving_prediction':[x for x in depletion if x['slow_moving_prediction']],'seasonal_weekday_pattern':weekdays,'method':'deterministic trailing-average with bounded growth'}
def _insights(payload,extra):
    k=payload['kpis'];cards=[];change=k['revenue_today']-k['revenue_yesterday'];cards.append({'severity':'positive' if change>=0 else 'warning','title':'Revenue movement','message':f"Revenue {'increased' if change>=0 else 'decreased'} by {abs(change):.2f} versus yesterday."})
    if k['gross_margin_percent']<20:cards.append({'severity':'warning','title':'Profit margin declining','message':f"Gross margin is {k['gross_margin_percent']:.2f}%; review pricing, discounts, and costs."})
    if extra['category_profitability']:cards.append({'severity':'info','title':'Leading category','message':extra['category_profitability'][0]['name']+' has the highest measured category profit.'})
    branches=payload['performance']['branches']
    if branches:cards.append({'severity':'warning','title':'Slowest-performing branch','message':min(branches,key=lambda x:x['net_sales'])['store_name']+' has the lowest net sales.'})
    if payload['inventory']['low_stock_alerts']:cards.append({'severity':'warning','title':'Inventory attention','message':f"{len(payload['inventory']['low_stock_alerts'])} store-product balances are at or below reorder level."})
    return cards

def export_executive_report(session,format_name,refresh=False):
    data=executive_dashboard(session,refresh);fmt=str(format_name).lower();rows=[{'metric':k,'value':v} for k,v in data['kpis'].items()]
    if fmt=='csv':
        stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=['metric','value']);writer.writeheader();writer.writerows(rows);content=stream.getvalue().encode('utf-8-sig');mime='text/csv';ext='csv'
    elif fmt in {'excel','xls'}:
        body=''.join(f'<Row><Cell><Data ss:Type="String">{escape(str(r["metric"]))}</Data></Cell><Cell><Data ss:Type="String">{escape(str(r["value"]))}</Data></Cell></Row>' for r in rows);content=('<?xml version="1.0"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Worksheet ss:Name="Executive KPIs"><Table>'+body+'</Table></Worksheet></Workbook>').encode();mime='application/vnd.ms-excel';ext='xls'
    elif fmt=='pdf':content=_pdf(rows);mime='application/pdf';ext='pdf'
    else:raise ValidationError('Executive exports support CSV, Excel, or PDF.')
    _audit(session,'EXECUTIVE_REPORT_EXPORTED',{'format':fmt});return {'content':content,'media_type':mime,'filename':f'executive-report-{data["as_of"]}.{ext}'}
def _pdf(rows):
    text=['CBOS Executive Report',* [f'{r["metric"]}: {r["value"]}' for r in rows]];commands='BT /F1 10 Tf 40 760 Td '+''.join(f'({str(line).replace("(","[").replace(")","]")}) Tj 0 -14 Td ' for line in text)+'ET';objects=['<< /Type /Catalog /Pages 2 0 R >>','<< /Type /Pages /Kids [3 0 R] /Count 1 >>','<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',f'<< /Length {len(commands)} >>\nstream\n{commands}\nendstream','<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];out='%PDF-1.4\n';offset=[]
    for i,obj in enumerate(objects,1):offset.append(len(out));out+=f'{i} 0 obj\n{obj}\nendobj\n'
    xref=len(out);out+='xref\n0 6\n0000000000 65535 f \n'+''.join(f'{x:010d} 00000 n \n' for x in offset)+f'trailer << /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF';return out.encode('latin-1','replace')
def create_schedule(session,name,frequency,format_name='PDF',store_id=None,recipients=None):
    session=require_executive(session);frequency=str(frequency).upper();fmt=str(format_name).upper()
    if frequency not in {'DAILY','WEEKLY','MONTHLY','QUARTERLY'} or fmt not in {'PDF','CSV','EXCEL'}:raise ValidationError('Invalid executive report schedule.')
    target=int(store_id or session.store_id) if session.role==ROLE_MANAGER or store_id else None
    if target:require_store_access(session,target)
    with transaction() as conn:identifier=conn.execute('INSERT INTO executive_report_schedules(name,frequency,store_id,format,recipients,created_by) VALUES(?,?,?,?,?,?)',(name,frequency,target,fmt,recipients,session.user_id)).lastrowid
    _audit(session,'EXECUTIVE_SCHEDULE_CREATED',{'schedule_id':identifier});return identifier
def list_schedules(session):
    session=require_executive(session)
    with get_connection() as conn:return [dict(r) for r in conn.execute('SELECT * FROM executive_report_schedules WHERE (?="admin" OR store_id=?) ORDER BY id DESC',(session.role,session.store_id))]
def _audit(session,event,details):
    with transaction() as conn:conn.execute('INSERT INTO executive_analytics_audit(user_id,store_id,event_type,details) VALUES(?,?,?,?)',(session.user_id,session.store_id,event,json.dumps(details,sort_keys=True)))
