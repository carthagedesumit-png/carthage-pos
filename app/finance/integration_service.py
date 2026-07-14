"""Opening balances, reconciliation, and safe historical posting orchestration."""
from datetime import date

from auth import validate_session
from app.core.exceptions import AuthorizationError, ValidationError
from app.database.db_manager import get_connection
from app.database.transactions import transaction
from app.finance.posting_service import account_mappings, post_event, post_goods_receipt, post_return, post_sale

def opening_preview(session,effective_date,description,lines,equity_account_id,store_id=None):
    session=validate_session(session)
    if session.role!='admin':raise AuthorizationError('Opening balances are administrator-only.')
    store=int(store_id or session.store_id);normalized=[]
    for item in lines:
        debit=round(float(item.get('debit') or 0),2);credit=round(float(item.get('credit') or 0),2)
        if debit<0 or credit<0 or (debit>0 and credit>0):raise ValidationError('Opening balance lines are invalid.')
        if debit or credit:normalized.append({'account_id':int(item['account_id']),'debit':debit,'credit':credit,'description':item.get('description') or ''})
    debit=sum(x['debit'] for x in normalized);credit=sum(x['credit'] for x in normalized);difference=round(debit-credit,2)
    if difference<0:normalized.append({'account_id':int(equity_account_id),'debit':abs(difference),'credit':0,'description':'Opening balance equity'})
    elif difference>0:normalized.append({'account_id':int(equity_account_id),'debit':0,'credit':difference,'description':'Opening balance equity'})
    return {'store_id':store,'effective_date':str(effective_date),'description':description,'equity_account_id':int(equity_account_id),'lines':normalized,'total_debits':round(sum(x['debit'] for x in normalized),2),'total_credits':round(sum(x['credit'] for x in normalized),2)}
def create_opening_batch(session,effective_date,description,lines,equity_account_id,store_id=None):
    preview=opening_preview(session,effective_date,description,lines,equity_account_id,store_id);session=validate_session(session)
    with transaction() as conn:
        try:batch=conn.execute('INSERT INTO finance_opening_batches(store_id,effective_date,description,equity_account_id,created_by) VALUES(?,?,?,?,?)',(preview['store_id'],preview['effective_date'],description,equity_account_id,session.user_id)).lastrowid
        except Exception as exc:raise ValidationError('An opening balance batch already exists for this store and date; use a reversing journal for corrections.') from exc
        conn.executemany('INSERT INTO finance_opening_lines(batch_id,account_id,debit,credit,description) VALUES(?,?,?,?,?)',[(batch,x['account_id'],x['debit'],x['credit'],x['description']) for x in preview['lines']])
    return {**preview,'batch_id':batch,'status':'DRAFT'}
def post_opening_batch(session,batch_id):
    session=validate_session(session)
    if session.role!='admin':raise AuthorizationError('Opening balances are administrator-only.')
    with transaction() as conn:
        batch=conn.execute("SELECT * FROM finance_opening_batches WHERE id=? AND status='DRAFT'",(batch_id,)).fetchone()
        if not batch:raise ValidationError('Draft opening balance batch not found.')
        lines=[dict(r) for r in conn.execute('SELECT account_id,debit,credit,description FROM finance_opening_lines WHERE batch_id=?',(batch_id,))]
        result=post_event(session,'OPENING_BALANCE','finance_opening',batch_id,batch['store_id'],batch['effective_date'],batch['description'],f'OPENING-{batch_id}',lines,f'opening:{batch["store_id"]}:{batch["effective_date"]}',conn)
        conn.execute("UPDATE finance_opening_batches SET status='POSTED',journal_id=?,posted_at=CURRENT_TIMESTAMP WHERE id=?",(result['journal_id'],batch_id))
    return result

def reconciliation_report(session,store_id=None,date_from=None,date_to=None):
    session=validate_session(session);store=int(store_id or session.store_id)
    from auth import require_store_access
    require_store_access(session,store)
    dates='';params=[store]
    if date_from:dates+=' AND DATE(s.created_at)>=?';params.append(date_from)
    if date_to:dates+=' AND DATE(s.created_at)<=?';params.append(date_to)
    with get_connection() as conn:
        m=account_mappings(conn)
        sales=round(conn.execute(f'SELECT COALESCE(SUM(subtotal),0) FROM sales s WHERE store_id=?{dates}',params).fetchone()[0],2)
        revenue=_account_balance(conn,m['sales_revenue'],store,credit_normal=True,date_from=date_from,date_to=date_to)
        inventory=round(conn.execute('SELECT COALESCE(SUM(quantity_on_hand*average_cost),0) FROM store_inventory WHERE store_id=?',(store,)).fetchone()[0],2)
        inventory_gl=_account_balance(conn,m['inventory_asset'],store,date_from=date_from,date_to=date_to)
        wallet=round(conn.execute('SELECT COALESCE(SUM(amount_delta),0) FROM wallet_transactions WHERE store_id=?',(store,)).fetchone()[0],2)
        wallet_gl=_account_balance(conn,m['wallet_liability'],store,credit_normal=True,date_from=date_from,date_to=date_to)
        credit=round(conn.execute('SELECT COALESCE(SUM(amount_delta),0) FROM credit_transactions WHERE store_id=?',(store,)).fetchone()[0],2)
        ar=_account_balance(conn,m['accounts_receivable'],store,date_from=date_from,date_to=date_to)
        sales_tax=round(conn.execute(f'SELECT COALESCE(SUM(tax_amount),0) FROM sales s WHERE store_id=?{dates}',params).fetchone()[0],2)
        tax_gl=_account_balance(conn,m['tax_payable'],store,credit_normal=True,date_from=date_from,date_to=date_to)
        unposted=[dict(r) for r in conn.execute("SELECT s.sale_id source_id,s.receipt_number reference FROM sales s LEFT JOIN finance_posting_events e ON e.idempotency_key='sale:'||s.sale_id WHERE s.store_id=? AND e.id IS NULL",(store,))]
    checks=[_check('sales_revenue',sales,revenue),_check('inventory_asset',inventory,inventory_gl),_check('wallet_liability',wallet,wallet_gl),_check('accounts_receivable',credit,ar),_check('tax_liability',sales_tax,tax_gl)]
    return {'store_id':store,'date_from':date_from,'date_to':date_to,'checks':checks,'balanced':all(x['difference']==0 for x in checks),'unposted_sources':unposted}
def _account_balance(conn,account,store,credit_normal=False,date_from=None,date_to=None):
    where=['j.store_id=?',"j.status='POSTED'",'l.account_id=?'];params=[store,account]
    if date_from:where.append('j.entry_date>=?');params.append(date_from)
    if date_to:where.append('j.entry_date<=?');params.append(date_to)
    row=conn.execute(f"SELECT COALESCE(SUM(l.debit),0),COALESCE(SUM(l.credit),0) FROM finance_journal_lines l JOIN finance_journals j ON j.id=l.journal_id WHERE {' AND '.join(where)}",params).fetchone();return round((row[1]-row[0]) if credit_normal else (row[0]-row[1]),2)
def _check(name,source,ledger):return {'name':name,'source_total':source,'ledger_total':ledger,'difference':round(source-ledger,2),'status':'MATCHED' if round(source-ledger,2)==0 else 'OUT_OF_BALANCE'}

def backfill(session,dry_run=True,store_id=None,module=None,date_from=None,date_to=None):
    session=validate_session(session)
    if session.role!='admin':raise AuthorizationError('Historical backfill is administrator-only.')
    store=int(store_id or session.store_id);candidates=[]
    with get_connection() as conn:
        specs=[('sales','SALE_COMPLETED','sales','sale_id','created_at','sale:'),('sales_returns','SALE_RETURNED','sales','id','created_at','return:'),('purchase_receipts','GOODS_RECEIVED','procurement','id','received_at','goods-receipt:')]
        for table,event,source,idcol,datecol,prefix in specs:
            if module and source!=module:continue
            join='JOIN sales parent ON parent.sale_id=t.sale_id' if table=='sales_returns' else ('JOIN purchase_orders po ON po.id=t.purchase_order_id' if table=='purchase_receipts' else '')
            storecol='parent.store_id' if table=='sales_returns' else ('po.store_id' if table=='purchase_receipts' else 't.store_id')
            where=[f'{storecol}=?'];params=[store]
            if date_from:where.append(f'DATE(t.{datecol})>=?');params.append(date_from)
            if date_to:where.append(f'DATE(t.{datecol})<=?');params.append(date_to)
            rows=conn.execute(f"SELECT t.{idcol} source_id,t.{datecol} transaction_date FROM {table} t {join} LEFT JOIN finance_posting_events e ON e.idempotency_key=?||t.{idcol} WHERE {' AND '.join(where)} AND e.id IS NULL",[prefix,*params]).fetchall()
            candidates.extend({'event_type':event,'source_module':source,'source_record_id':r['source_id'],'transaction_date':r['transaction_date']} for r in rows)
    if dry_run:return {'dry_run':True,'eligible':len(candidates),'candidates':candidates,'posted':0,'failed':[]}
    from app.backup.backup_service import create_backup
    backup=create_backup(session,name=f'pre-finance-backfill-{date.today().isoformat()}')
    handlers={'SALE_COMPLETED':post_sale,'SALE_RETURNED':post_return,'GOODS_RECEIVED':post_goods_receipt};posted=0;failed=[]
    for item in candidates:
        try:handlers[item['event_type']](session,item['source_record_id']);posted+=1
        except Exception as exc:failed.append({**item,'error':str(exc)})
    return {'dry_run':False,'eligible':len(candidates),'posted':posted,'failed':failed,'backup_id':backup['backup_id']}
