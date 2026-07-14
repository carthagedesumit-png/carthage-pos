"""Store-scoped finance orchestration and double-entry reporting."""
import json
from datetime import date

from auth import ROLE_ADMIN, ROLE_CASHIER, ROLE_MANAGER, require_store_access, validate_session
from app.core.exceptions import AuthorizationError, ValidationError
from app.database.db_manager import get_connection
from app.database.transactions import transaction

WRITE_ROLES={ROLE_ADMIN,ROLE_MANAGER}; TYPES={'ASSET','LIABILITY','EQUITY','INCOME','EXPENSE'}

def _session(session,write=False,store_id=None):
    session=validate_session(session);store_id=int(store_id or session.store_id);require_store_access(session,store_id)
    if write and session.role not in WRITE_ROLES:raise AuthorizationError('Cashiers have read-only finance access.')
    return session,store_id
def _money(value,label='Amount'):
    try:value=round(float(value),2)
    except (TypeError,ValueError) as exc:raise ValidationError(f'{label} must be numeric.') from exc
    if value<0:raise ValidationError(f'{label} cannot be negative.')
    return value
def _audit(conn,s,store,event,kind=None,eid=None,details=None):
    conn.execute('INSERT INTO finance_audit(store_id,user_id,event_type,entity_type,entity_id,details) VALUES(?,?,?,?,?,?)',(store,s.user_id,event,kind,eid,json.dumps(details or {},sort_keys=True)))
def _period_open(conn,store,entry_date):
    locked=conn.execute('SELECT 1 FROM finance_periods WHERE store_id=? AND is_locked=1 AND DATE(?) BETWEEN start_date AND end_date',(store,entry_date)).fetchone()
    if locked:raise ValidationError('The accounting period is locked.')

def list_accounts(session,store_id=None):
    _session(session,store_id=store_id)
    with get_connection() as conn:return [dict(r) for r in conn.execute('SELECT * FROM finance_accounts ORDER BY code')]
def create_account(session,code,name,account_type,parent_id=None):
    s,store=_session(session,True);account_type=str(account_type).upper()
    if account_type not in TYPES:raise ValidationError('Invalid account type.')
    with transaction() as conn:
        cur=conn.execute('INSERT INTO finance_accounts(code,name,account_type,parent_id) VALUES(?,?,?,?)',(str(code).strip(),str(name).strip(),account_type,parent_id));_audit(conn,s,store,'ACCOUNT_CREATED','account',cur.lastrowid)
    return cur.lastrowid
def create_expense_category(session,name,account_id):
    s,store=_session(session,True)
    with transaction() as conn:cur=conn.execute('INSERT INTO finance_categories(name,account_id) VALUES(?,?)',(str(name).strip(),int(account_id)));_audit(conn,s,store,'EXPENSE_CATEGORY_CREATED','category',cur.lastrowid)
    return cur.lastrowid
def create_vendor(session,name,email=None,phone=None):
    s,store=_session(session,True)
    with transaction() as conn:cur=conn.execute('INSERT INTO finance_vendors(name,email,phone) VALUES(?,?,?)',(str(name).strip(),email or None,phone or None));_audit(conn,s,store,'VENDOR_CREATED','vendor',cur.lastrowid)
    return cur.lastrowid

def create_journal(session,entry_date,description,lines,reference=None,store_id=None,post=False,source_type=None,source_id=None):
    s,store=_session(session,True,store_id);entry_date=str(entry_date or date.today())
    if not str(description).strip() or len(lines)<2:raise ValidationError('A journal requires a description and at least two lines.')
    normalized=[]
    for line in lines:
        debit=_money(line.get('debit',0),'Debit');credit=_money(line.get('credit',0),'Credit')
        if (debit>0)==(credit>0):raise ValidationError('Each journal line must contain either a debit or a credit.')
        normalized.append((int(line['account_id']),str(line.get('description') or ''),debit,credit,line.get('tax_rate_id')))
    if round(sum(x[2] for x in normalized)-sum(x[3] for x in normalized),2)!=0:raise ValidationError('Journal debits and credits must balance.')
    with transaction() as conn:
        _period_open(conn,store,entry_date)
        ids={r[0] for r in conn.execute('SELECT id FROM finance_accounts WHERE is_active=1')}
        if any(x[0] not in ids for x in normalized):raise ValidationError('Journal account is inactive or unavailable.')
        cur=conn.execute("INSERT INTO finance_journals(store_id,entry_date,reference,description,source_type,source_id,created_by) VALUES(?,?,?,?,?,?,?)",(store,entry_date,reference,str(description).strip(),source_type,source_id,s.user_id));jid=cur.lastrowid
        conn.executemany('INSERT INTO finance_journal_lines(journal_id,account_id,description,debit,credit,tax_rate_id) VALUES(?,?,?,?,?,?)',[(jid,*x) for x in normalized]);_audit(conn,s,store,'JOURNAL_CREATED','journal',jid)
    return post_journal(s,jid) if post else journal_detail(s,jid)
def post_journal(session,journal_id):
    s,_=_session(session,True)
    with transaction() as conn:
        row=conn.execute('SELECT * FROM finance_journals WHERE id=?',(journal_id,)).fetchone()
        if not row:raise ValidationError('Journal not found.')
        require_store_access(s,row['store_id']);_period_open(conn,row['store_id'],row['entry_date'])
        if row['status']!='DRAFT':raise ValidationError('Only draft journals can be posted.')
        sums=conn.execute('SELECT ROUND(SUM(debit),2),ROUND(SUM(credit),2),COUNT(*) FROM finance_journal_lines WHERE journal_id=?',(journal_id,)).fetchone()
        if sums[2]<2 or sums[0]!=sums[1]:raise ValidationError('Journal is not balanced.')
        conn.execute("UPDATE finance_journals SET status='POSTED',posted_by=?,posted_at=CURRENT_TIMESTAMP WHERE id=?",(s.user_id,journal_id));_audit(conn,s,row['store_id'],'JOURNAL_POSTED','journal',journal_id)
    return journal_detail(s,journal_id)
def journal_detail(session,journal_id):
    s,_=_session(session)
    with get_connection() as conn:
        row=conn.execute('SELECT * FROM finance_journals WHERE id=?',(journal_id,)).fetchone()
        if not row:raise ValidationError('Journal not found.')
        require_store_access(s,row['store_id']);lines=[dict(r) for r in conn.execute('SELECT l.*,a.code,a.name account_name FROM finance_journal_lines l JOIN finance_accounts a ON a.id=l.account_id WHERE journal_id=? ORDER BY l.id',(journal_id,))]
    return {'journal':dict(row),'lines':lines}
def list_journals(session,store_id=None):
    s,store=_session(session,store_id=store_id)
    with get_connection() as conn:return [dict(r) for r in conn.execute('SELECT * FROM finance_journals WHERE store_id=? ORDER BY entry_date DESC,id DESC',(store,))]
def lock_period(session,name,start_date,end_date,store_id=None):
    s,store=_session(session,True,store_id)
    if s.role!=ROLE_ADMIN:raise AuthorizationError('Only administrators can lock accounting periods.')
    with transaction() as conn:
        cur=conn.execute('INSERT INTO finance_periods(store_id,name,start_date,end_date,is_locked,locked_by,locked_at) VALUES(?,?,?,?,1,?,CURRENT_TIMESTAMP)',(store,name,start_date,end_date,s.user_id));_audit(conn,s,store,'PERIOD_LOCKED','period',cur.lastrowid)
    return cur.lastrowid

def create_expense(session,expense_date,category_id,amount,description,vendor_id=None,expense_type='OPERATING',tax_amount=0,attachment_name=None,attachment_type=None,recurring_rule=None,store_id=None):
    s,store=_session(session,True,store_id);amount=_money(amount);tax=_money(tax_amount,'Tax')
    if amount<=0:raise ValidationError('Expense amount must be positive.')
    with transaction() as conn:
        _period_open(conn,store,expense_date);category=conn.execute('SELECT * FROM finance_categories WHERE id=? AND is_active=1',(category_id,)).fetchone()
        if not category:raise ValidationError('Expense category not found.')
        cur=conn.execute('INSERT INTO finance_expenses(store_id,expense_date,category_id,vendor_id,amount,tax_amount,description,expense_type,attachment_name,attachment_type,recurring_rule,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(store,expense_date,category_id,vendor_id,amount,tax,description,expense_type,attachment_name,attachment_type,recurring_rule,s.user_id));_audit(conn,s,store,'EXPENSE_CREATED','expense',cur.lastrowid)
    return cur.lastrowid
def approve_expense(session,expense_id):
    s,_=_session(session,True)
    with transaction() as conn:
        row=conn.execute('SELECT e.*,c.account_id FROM finance_expenses e JOIN finance_categories c ON c.id=e.category_id WHERE e.id=?',(expense_id,)).fetchone()
        if not row:raise ValidationError('Expense not found.')
        require_store_access(s,row['store_id'])
        if row['status']!='PENDING':raise ValidationError('Only pending expenses can be approved.')
    journal=create_journal(s,row['expense_date'],row['description'],[{'account_id':row['account_id'],'debit':row['amount']},{'account_id':_account('1000'),'credit':row['amount']}],reference=f'EXP-{expense_id}',store_id=row['store_id'],post=True,source_type='EXPENSE',source_id=expense_id)
    with transaction() as conn:conn.execute("UPDATE finance_expenses SET status='APPROVED',approved_by=?,approved_at=CURRENT_TIMESTAMP,journal_id=? WHERE id=?",(s.user_id,journal['journal']['id'],expense_id));_audit(conn,s,row['store_id'],'EXPENSE_APPROVED','expense',expense_id)
    return journal
def record_income(session,income_date,income_type,amount,description,tax_amount=0,store_id=None):
    s,store=_session(session,True,store_id);amount=_money(amount);tax=_money(tax_amount,'Tax')
    if amount<=0:raise ValidationError('Income amount must be positive.')
    income_account='4100' if str(income_type).upper()=='SERVICE' else '4200'
    journal=create_journal(s,income_date,description,[{'account_id':_account('1000'),'debit':amount},{'account_id':_account(income_account),'credit':amount}],reference='NON-SALES',store_id=store,post=True,source_type='INCOME')
    with transaction() as conn:
        cur=conn.execute('INSERT INTO finance_income(store_id,income_date,income_type,amount,tax_amount,description,created_by,journal_id) VALUES(?,?,?,?,?,?,?,?)',(store,income_date,income_type,amount,tax,description,s.user_id,journal['journal']['id']));_audit(conn,s,store,'INCOME_RECORDED','income',cur.lastrowid)
    return journal

def open_cash(session,amount,store_id=None):
    s,store=_session(session,True,store_id);amount=_money(amount)
    with transaction() as conn:
        if conn.execute("SELECT 1 FROM finance_cash_sessions WHERE store_id=? AND user_id=? AND status='OPEN'",(store,s.user_id)).fetchone():raise ValidationError('A cash session is already open.')
        cur=conn.execute('INSERT INTO finance_cash_sessions(store_id,user_id,opening_amount) VALUES(?,?,?)',(store,s.user_id,amount));_audit(conn,s,store,'CASH_OPENED','cash_session',cur.lastrowid)
    return cur.lastrowid
def cash_adjustment(session,cash_session_id,amount,reason,movement_type='ADJUSTMENT',destination_store_id=None):
    s,_=_session(session,True);amount=float(amount)
    if not reason.strip() or amount==0:raise ValidationError('A non-zero amount and reason are required.')
    with transaction() as conn:
        row=conn.execute("SELECT * FROM finance_cash_sessions WHERE id=? AND status='OPEN'",(cash_session_id,)).fetchone()
        if not row:raise ValidationError('Open cash session not found.')
        require_store_access(s,row['store_id'])
        if destination_store_id:require_store_access(s,int(destination_store_id))
        cur=conn.execute('INSERT INTO finance_cash_movements(store_id,cash_session_id,movement_type,amount,reason,destination_store_id,created_by) VALUES(?,?,?,?,?,?,?)',(row['store_id'],cash_session_id,movement_type,round(amount,2),reason,destination_store_id,s.user_id));_audit(conn,s,row['store_id'],'CASH_MOVEMENT','cash_movement',cur.lastrowid)
    return cur.lastrowid
def close_cash(session,cash_session_id,closing_amount):
    s,_=_session(session,True);closing=_money(closing_amount,'Closing cash')
    with transaction() as conn:
        row=conn.execute("SELECT * FROM finance_cash_sessions WHERE id=? AND status='OPEN'",(cash_session_id,)).fetchone()
        if not row:raise ValidationError('Open cash session not found.')
        require_store_access(s,row['store_id']);moves=conn.execute('SELECT COALESCE(SUM(amount),0) FROM finance_cash_movements WHERE cash_session_id=?',(cash_session_id,)).fetchone()[0]
        sales=conn.execute("SELECT COALESCE(SUM(sp.amount),0) FROM sale_payments sp JOIN sales s ON s.sale_id=sp.sale_id WHERE s.store_id=? AND s.user_id=? AND sp.payment_method='CASH' AND s.created_at>=?",(row['store_id'],row['user_id'],row['opened_at'])).fetchone()[0]
        expected=round(row['opening_amount']+moves+sales,2);variance=round(closing-expected,2)
        conn.execute("UPDATE finance_cash_sessions SET expected_amount=?,closing_amount=?,variance=?,status='CLOSED',closed_at=CURRENT_TIMESTAMP WHERE id=?",(expected,closing,variance,cash_session_id));_audit(conn,s,row['store_id'],'CASH_RECONCILED','cash_session',cash_session_id,{'expected':expected,'closing':closing,'variance':variance})
    return {'expected_amount':expected,'closing_amount':closing,'variance':variance}

def add_tax_rate(session,name,rate,pricing_mode='EXCLUSIVE',liability_account_id=None):
    s,store=_session(session,True);rate=float(rate);mode=str(pricing_mode).upper()
    if rate<0 or mode not in {'INCLUSIVE','EXCLUSIVE','EXEMPT'}:raise ValidationError('Invalid tax configuration.')
    with transaction() as conn:cur=conn.execute('INSERT INTO finance_tax_rates(name,rate,pricing_mode,liability_account_id) VALUES(?,?,?,?)',(name,rate,mode,liability_account_id or _account('2100')));_audit(conn,s,store,'TAX_RATE_CREATED','tax_rate',cur.lastrowid)
    return cur.lastrowid
def calculate_tax(amount,rate,pricing_mode='EXCLUSIVE',exempt=False):
    amount=_money(amount);rate=float(rate);mode=str(pricing_mode).upper()
    if exempt or mode=='EXEMPT':return {'net':amount,'tax':0.0,'gross':amount}
    if mode=='INCLUSIVE':tax=round(amount-(amount/(1+rate)),2);return {'net':round(amount-tax,2),'tax':tax,'gross':amount}
    tax=round(amount*rate,2);return {'net':amount,'tax':tax,'gross':round(amount+tax,2)}

def statements(session,date_from=None,date_to=None,store_id=None):
    s,store=_session(session,store_id=store_id);where=['j.store_id=?',"j.status='POSTED'"];params=[store]
    if date_from:where.append('j.entry_date>=?');params.append(date_from)
    if date_to:where.append('j.entry_date<=?');params.append(date_to)
    with get_connection() as conn:
        rows=[dict(r) for r in conn.execute(f'''SELECT a.id,a.code,a.name,a.account_type,ROUND(SUM(l.debit),2) debit,ROUND(SUM(l.credit),2) credit FROM finance_journal_lines l JOIN finance_journals j ON j.id=l.journal_id JOIN finance_accounts a ON a.id=l.account_id WHERE {' AND '.join(where)} GROUP BY a.id ORDER BY a.code''',params)]
        expenses=[dict(r) for r in conn.execute('SELECT * FROM finance_expenses WHERE store_id=? ORDER BY expense_date DESC',(store,))]
        cash=[dict(r) for r in conn.execute('SELECT * FROM finance_cash_sessions WHERE store_id=? ORDER BY id DESC',(store,))]
        ledger=[dict(r) for r in conn.execute(f'''SELECT j.entry_date,j.reference,j.description journal_description,a.code,a.name,l.description,l.debit,l.credit FROM finance_journal_lines l JOIN finance_journals j ON j.id=l.journal_id JOIN finance_accounts a ON a.id=l.account_id WHERE {' AND '.join(where)} ORDER BY j.entry_date,j.id,l.id''',params)]
        sales_tax=conn.execute('SELECT ROUND(COALESCE(SUM(tax_amount),0),2) FROM sales WHERE store_id=?',(store,)).fetchone()[0]
        movements=[dict(r) for r in conn.execute('SELECT * FROM finance_cash_movements WHERE store_id=? ORDER BY created_at DESC',(store,))]
    tb=[{**r,'balance':round(r['debit']-r['credit'],2)} for r in rows]
    income=sum(r['credit']-r['debit'] for r in rows if r['account_type']=='INCOME');expense=sum(r['debit']-r['credit'] for r in rows if r['account_type']=='EXPENSE')
    assets=sum(r['debit']-r['credit'] for r in rows if r['account_type']=='ASSET');liabilities=sum(r['credit']-r['debit'] for r in rows if r['account_type']=='LIABILITY');equity=sum(r['credit']-r['debit'] for r in rows if r['account_type']=='EQUITY')
    return {'trial_balance':tb,'general_ledger':ledger,'profit_loss':{'income':round(income,2),'expenses':round(expense,2),'net_profit':round(income-expense,2)},'balance_sheet':{'assets':round(assets,2),'liabilities':round(liabilities,2),'equity':round(equity+income-expense,2)},'cash_flow':{'net_cash_flow':round(sum((r['debit']-r['credit']) for r in rows if r['code'] in {'1000','1010'}),2)},'tax_report':{'sales_tax':sales_tax},'expenses':expenses,'cash_sessions':cash,'cash_movements':movements}
def overview(session,store_id=None):
    data=statements(session,store_id=store_id);data.update({'accounts':list_accounts(session,store_id),'journals':list_journals(session,store_id)})
    with get_connection() as conn:data['tax_rates']=[dict(r) for r in conn.execute('SELECT * FROM finance_tax_rates ORDER BY name')];data['categories']=[dict(r) for r in conn.execute('SELECT * FROM finance_categories WHERE is_active=1 ORDER BY name')];data['vendors']=[dict(r) for r in conn.execute('SELECT * FROM finance_vendors WHERE is_active=1 ORDER BY name')]
    return data
def _account(code):
    with get_connection() as conn:row=conn.execute('SELECT id FROM finance_accounts WHERE code=?',(code,)).fetchone()
    if not row:raise ValidationError(f'Required account {code} is unavailable.')
    return row['id']
