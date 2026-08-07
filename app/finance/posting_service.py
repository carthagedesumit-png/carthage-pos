"""Idempotent accounting integration for authoritative CBOS business events."""
import json
from datetime import date

from auth import require_store_access, validate_session
from app.core.exceptions import ValidationError
from app.database.db_manager import get_connection
from app.database.transactions import transaction

EVENTS={'SALE_COMPLETED','SALE_RETURNED','GOODS_RECEIVED','INVENTORY_ADJUSTED','WALLET_ADJUSTED','CREDIT_ADJUSTED','CASH_MOVEMENT','OPENING_BALANCE'}

def account_mappings(conn):
    return {r['mapping_key']:r['account_id'] for r in conn.execute('SELECT * FROM finance_account_mappings')}
def configure_mapping(session,key,account_id):
    session=validate_session(session)
    if session.role!='admin':raise ValidationError('Only administrators can configure finance mappings.')
    with transaction() as conn:
        if not conn.execute('SELECT 1 FROM finance_accounts WHERE id=? AND is_active=1',(account_id,)).fetchone():raise ValidationError('Mapped account is unavailable.')
        conn.execute('INSERT INTO finance_account_mappings(mapping_key,account_id,updated_by) VALUES(?,?,?) ON CONFLICT(mapping_key) DO UPDATE SET account_id=excluded.account_id,updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP',(key,account_id,session.user_id))
def validate_mappings(conn,keys):
    mappings=account_mappings(conn);missing=sorted(set(keys)-set(mappings))
    if missing:raise ValidationError('Missing finance account mappings: '+', '.join(missing))
    return mappings

def post_event(session,event_type,source_module,source_record_id,store_id,transaction_date,description,reference,lines,idempotency_key,conn=None):
    if event_type not in EVENTS:raise ValidationError(f'Unsupported finance event: {event_type}')
    session=validate_session(session);require_store_access(session,store_id)
    if conn is None:
        with transaction() as owned:return post_event(session,event_type,source_module,source_record_id,store_id,transaction_date,description,reference,lines,idempotency_key,owned)
    existing=conn.execute('SELECT * FROM finance_posting_events WHERE idempotency_key=?',(idempotency_key,)).fetchone()
    if existing:
        if existing['status']=='POSTED':return {'event':dict(existing),'duplicate':True}
        conn.execute("UPDATE finance_posting_events SET status='PENDING',error_message=NULL,attempts=attempts+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",(existing['id'],));event_id=existing['id']
    else:
        event_id=conn.execute('INSERT INTO finance_posting_events(event_type,source_module,source_record_id,store_id,transaction_date,description,reference,idempotency_key,attempts) VALUES(?,?,?,?,?,?,?,?,1)',(event_type,source_module,int(source_record_id),int(store_id),str(transaction_date),description,reference,idempotency_key)).lastrowid
    try:
        journal_id=_post_journal(conn,session,store_id,transaction_date,description,reference,lines,event_type,source_record_id)
        conn.execute("UPDATE finance_posting_events SET status='POSTED',journal_id=?,posted_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?",(journal_id,event_id))
        return {'event_id':event_id,'journal_id':journal_id,'duplicate':False}
    except Exception as exc:
        # In externally owned transactions the exception deliberately rolls back source and event.
        if not conn.in_transaction:raise
        raise ValidationError(f'Finance posting failed for {idempotency_key}: {exc}') from exc

def _post_journal(conn,session,store,entry_date,description,reference,lines,source_type,source_id):
    locked=conn.execute('SELECT 1 FROM finance_periods WHERE store_id=? AND is_locked=1 AND DATE(?) BETWEEN start_date AND end_date',(store,entry_date)).fetchone()
    if locked:raise ValidationError('The accounting period is locked.')
    normalized=[]
    for line in lines:
        debit=round(float(line.get('debit') or 0),2);credit=round(float(line.get('credit') or 0),2)
        if debit<0 or credit<0 or (debit>0)==(credit>0):raise ValidationError('Posting lines require exactly one positive debit or credit.')
        normalized.append((int(line['account_id']),line.get('description') or '',debit,credit))
    if len(normalized)<2 or round(sum(x[2] for x in normalized)-sum(x[3] for x in normalized),2):raise ValidationError('Finance posting is not balanced.')
    ids={r[0] for r in conn.execute('SELECT id FROM finance_accounts WHERE is_active=1')}
    if any(x[0] not in ids for x in normalized):raise ValidationError('Finance mapping references an inactive account.')
    jid=conn.execute("INSERT INTO finance_journals(store_id,entry_date,reference,description,status,source_type,source_id,created_by,posted_by,posted_at) VALUES(?,?,?,?, 'POSTED',?,?,?,?,CURRENT_TIMESTAMP)",(store,str(entry_date),reference,description,source_type,int(source_id),session.user_id,session.user_id)).lastrowid
    conn.executemany('INSERT INTO finance_journal_lines(journal_id,account_id,description,debit,credit) VALUES(?,?,?,?,?)',[(jid,*x) for x in normalized])
    conn.execute('INSERT INTO finance_audit(store_id,user_id,event_type,entity_type,entity_id,details) VALUES(?,?,?,?,?,?)',(store,session.user_id,'BUSINESS_EVENT_POSTED','journal',jid,json.dumps({'source_type':source_type,'source_id':source_id},sort_keys=True)))
    return jid

def post_sale(session,sale_id,conn=None):
    if conn is None:
        with transaction() as owned:return post_sale(session,sale_id,owned)
    sale=conn.execute('SELECT * FROM sales WHERE sale_id=?',(sale_id,)).fetchone()
    if not sale or sale['payment_status']!='PAID':raise ValidationError('Only completed paid sales can be posted.')
    m=validate_mappings(conn,{'cash','card_clearing','transfer_clearing','wallet_liability','accounts_receivable','sales_revenue','tax_payable','discounts','cost_of_goods_sold','inventory_asset'})
    payments=conn.execute('SELECT payment_method,amount FROM sale_payments WHERE sale_id=?',(sale_id,)).fetchall();lines=[];tender_total=0
    payment_map={'CASH':'cash','CARD':'card_clearing','TRANSFER':'transfer_clearing','WALLET':'wallet_liability','CREDIT':'accounts_receivable'}
    for p in payments:
        key=payment_map[p['payment_method']];amount=round(float(p['amount']),2);tender_total+=amount;lines.append({'account_id':m[key],'debit':amount,'description':p['payment_method']})
    loyalty=round(float(sale['loyalty_redemption_amount'] or 0),2)
    if loyalty:lines.append({'account_id':m['wallet_liability'],'debit':loyalty,'description':'Loyalty redemption'});tender_total+=loyalty
    discount=round(float(sale['discount_amount'] or 0),2);tax=round(float(sale['tax_amount'] or 0),2);subtotal=round(float(sale['subtotal']),2)
    if discount:lines.append({'account_id':m['discounts'],'debit':discount,'description':'Sales discount'})
    lines.append({'account_id':m['sales_revenue'],'credit':subtotal,'description':'Sales revenue'})
    if tax:lines.append({'account_id':m['tax_payable'],'credit':tax,'description':'Output tax'})
    cogs=round(conn.execute('SELECT COALESCE(SUM(quantity*unit_cost_at_sale),0) FROM sale_items WHERE sale_id=?',(sale_id,)).fetchone()[0],2)
    if cogs:lines.extend([{'account_id':m['cost_of_goods_sold'],'debit':cogs,'description':'Cost of goods sold'},{'account_id':m['inventory_asset'],'credit':cogs,'description':'Inventory reduction'}])
    return post_event(session,'SALE_COMPLETED','sales',sale_id,sale['store_id'],str(sale['created_at'])[:10],f"Sale {sale['receipt_number']}",sale['receipt_number'],lines,f'sale:{sale_id}',conn)

def post_return(session,return_id,conn=None):
    if conn is None:
        with transaction() as owned:return post_return(session,return_id,owned)
    row=conn.execute('SELECT sr.*,s.store_id,s.receipt_number,s.total_amount,s.tax_amount,s.subtotal FROM sales_returns sr JOIN sales s ON s.sale_id=sr.sale_id WHERE sr.id=?',(return_id,)).fetchone()
    if not row:raise ValidationError('Return not found.')
    m=validate_mappings(conn,{'cash','card_clearing','transfer_clearing','wallet_liability','accounts_receivable','sales_revenue','cost_of_goods_sold','inventory_asset'});refund=round(float(row['total_refunded']),2)
    cogs=round(conn.execute('SELECT COALESCE(SUM(sri.quantity*si.unit_cost_at_sale),0) FROM sales_return_items sri JOIN sale_items si ON si.id=sri.sale_item_id WHERE sri.return_id=?',(return_id,)).fetchone()[0],2)
    lines=[{'account_id':m['sales_revenue'],'debit':refund,'description':'Sales return'}]
    payments=conn.execute('SELECT payment_method,amount FROM sale_payments WHERE sale_id=? ORDER BY id',(row['sale_id'],)).fetchall();payment_map={'CASH':'cash','CARD':'card_clearing','TRANSFER':'transfer_clearing','WALLET':'wallet_liability','CREDIT':'accounts_receivable'}
    total=sum(float(p['amount']) for p in payments) or refund;allocated=0
    for index,payment in enumerate(payments):
        amount=round(refund-allocated,2) if index==len(payments)-1 else round(refund*float(payment['amount'])/total,2);allocated+=amount
        if amount:lines.append({'account_id':m[payment_map[payment['payment_method']]],'credit':amount,'description':f"{payment['payment_method']} refund"})
    if cogs:lines.extend([{'account_id':m['inventory_asset'],'debit':cogs,'description':'Returned inventory'},{'account_id':m['cost_of_goods_sold'],'credit':cogs,'description':'COGS reversal'}])
    return post_event(session,'SALE_RETURNED','sales',return_id,row['store_id'],str(row['created_at'])[:10],f"Return #{return_id} for {row['receipt_number']}",f"RETURN-{return_id}",lines,f'return:{return_id}',conn)

def post_goods_receipt(session,receipt_id,conn=None):
    if conn is None:
        with transaction() as owned:return post_goods_receipt(session,receipt_id,owned)
    row=conn.execute('SELECT pr.*,po.store_id,po.reference_number FROM purchase_receipts pr JOIN purchase_orders po ON po.id=pr.purchase_order_id WHERE pr.id=?',(receipt_id,)).fetchone()
    if not row:raise ValidationError('Goods receipt not found.')
    amount=round(conn.execute('SELECT COALESCE(SUM(subtotal),0) FROM purchase_receipt_items WHERE receipt_id=?',(receipt_id,)).fetchone()[0],2);m=validate_mappings(conn,{'inventory_asset','accounts_payable'})
    lines=[{'account_id':m['inventory_asset'],'debit':amount,'description':'Received inventory'},{'account_id':m['accounts_payable'],'credit':amount,'description':'Supplier payable'}]
    return post_event(session,'GOODS_RECEIVED','procurement',receipt_id,row['store_id'],str(row['received_at'])[:10],f"Goods receipt {row['receipt_number']}",row['reference_number'],lines,f'goods-receipt:{receipt_id}',conn)

def post_wallet_change(session,transaction_id,conn=None):
    if conn is None:
        with transaction() as owned:return post_wallet_change(session,transaction_id,owned)
    row=conn.execute('SELECT * FROM wallet_transactions WHERE id=?',(transaction_id,)).fetchone()
    if not row:raise ValidationError('Wallet transaction not found.')
    m=validate_mappings(conn,{'cash','wallet_liability'});amount=abs(round(float(row['amount_delta']),2));positive=row['amount_delta']>0
    lines=[{'account_id':m['cash'],'debit':amount if positive else 0,'credit':0 if positive else amount,'description':'Wallet cash movement'},{'account_id':m['wallet_liability'],'credit':amount if positive else 0,'debit':0 if positive else amount,'description':'Wallet liability'}]
    return post_event(session,'WALLET_ADJUSTED','customers',transaction_id,row['store_id'],str(row['created_at'])[:10],f"Wallet {row['transaction_type']}",f"WALLET-{transaction_id}",lines,f'wallet:{transaction_id}',conn)
def post_credit_payment(session,transaction_id,conn=None):
    if conn is None:
        with transaction() as owned:return post_credit_payment(session,transaction_id,owned)
    row=conn.execute('SELECT * FROM credit_transactions WHERE id=?',(transaction_id,)).fetchone()
    if not row:raise ValidationError('Credit transaction not found.')
    m=validate_mappings(conn,{'cash','accounts_receivable'});amount=abs(round(float(row['amount_delta']),2))
    lines=[{'account_id':m['cash'],'debit':amount,'description':'Customer payment'},{'account_id':m['accounts_receivable'],'credit':amount,'description':'Receivable settlement'}]
    return post_event(session,'CREDIT_ADJUSTED','customers',transaction_id,row['store_id'],str(row['created_at'])[:10],f"Credit {row['transaction_type']}",f"CREDIT-{transaction_id}",lines,f'credit:{transaction_id}',conn)
def post_inventory_adjustment(session,movement_id,conn=None):
    if conn is None:
        with transaction() as owned:return post_inventory_adjustment(session,movement_id,owned)
    row=conn.execute('SELECT sm.*,si.average_cost FROM stock_movements sm JOIN store_inventory si ON si.store_id=sm.store_id AND si.product_id=sm.product_id WHERE sm.id=?',(movement_id,)).fetchone()
    if not row or row['movement_type']!='ADJUSTMENT':raise ValidationError('Inventory adjustment not found.')
    delta=int(row['quantity']);amount=round(abs(delta)*float(row['average_cost'] or 0),2)
    if not amount:return None
    m=validate_mappings(conn,{'inventory_asset','stock_gain','stock_loss'});positive=delta>0
    lines=[{'account_id':m['inventory_asset'],'debit':amount if positive else 0,'credit':0 if positive else amount,'description':'Inventory adjustment'},{'account_id':m['stock_gain'] if positive else m['stock_loss'],'credit':amount if positive else 0,'debit':0 if positive else amount,'description':'Stock gain/loss'}]
    return post_event(session,'INVENTORY_ADJUSTED','inventory',movement_id,row['store_id'],str(row['created_at'])[:10],'Inventory adjustment',f"STOCK-{movement_id}",lines,f'inventory-adjustment:{movement_id}',conn)
def post_cash_movement(session,movement_id,conn=None):
    if conn is None:
        with transaction() as owned:return post_cash_movement(session,movement_id,owned)
    row=conn.execute('SELECT * FROM finance_cash_movements WHERE id=?',(movement_id,)).fetchone()
    if not row:raise ValidationError('Cash movement not found.')
    m=validate_mappings(conn,{'cash','bank','cash_variance','stock_gain'});amount=abs(round(float(row['amount']),2));positive=row['amount']>0
    if row['movement_type']=='SAFE_TRANSFER':lines=[{'account_id':m['bank'],'debit':amount,'description':'Safe/bank transfer'},{'account_id':m['cash'],'credit':amount,'description':'Drawer transfer'}]
    else:lines=[{'account_id':m['cash'],'debit':amount if positive else 0,'credit':0 if positive else amount,'description':'Cash adjustment'},{'account_id':m['stock_gain'] if positive else m['cash_variance'],'credit':amount if positive else 0,'debit':0 if positive else amount,'description':'Cash variance'}]
    return post_event(session,'CASH_MOVEMENT','finance_cash',movement_id,row['store_id'],str(row['created_at'])[:10],row['reason'],f"CASH-{movement_id}",lines,f'cash-movement:{movement_id}',conn)

def retry_event(session,event_id):
    session=validate_session(session)
    if session.role!='admin':raise ValidationError('Only administrators can retry postings.')
    with get_connection() as conn:event=conn.execute('SELECT * FROM finance_posting_events WHERE id=?',(event_id,)).fetchone()
    if not event:raise ValidationError('Posting event not found.')
    dispatch={('sales','SALE_COMPLETED'):post_sale,('sales','SALE_RETURNED'):post_return,('procurement','GOODS_RECEIVED'):post_goods_receipt}
    handler=dispatch.get((event['source_module'],event['event_type']))
    if not handler:raise ValidationError('This event cannot be retried automatically.')
    return handler(session,event['source_record_id'])

def integration_health(session,store_id=None):
    session=validate_session(session);store=int(store_id or session.store_id);require_store_access(session,store)
    with get_connection() as conn:
        counts={r['status']:r['count'] for r in conn.execute('SELECT status,COUNT(*) count FROM finance_posting_events WHERE store_id=? GROUP BY status',(store,))}
        recent=[dict(r) for r in conn.execute('SELECT * FROM finance_posting_events WHERE store_id=? ORDER BY id DESC LIMIT 50',(store,))]
    return {'counts':counts,'events':recent,'healthy':not counts.get('FAILED',0)}
