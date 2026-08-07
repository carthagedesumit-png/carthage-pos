"""Resumable first-run onboarding and isolated optional demo provisioning."""
import json
from pathlib import Path
from datetime import datetime,timezone

from app.core.exceptions import InstallationError

STEPS=('company','store','administrator','tax_currency','receipt_printer','operations','accounts_license','complete')
def load_onboarding(path):
    path=Path(path)
    if not path.exists():return {'status':'NOT_STARTED','current_step':STEPS[0],'completed_steps':[],'values':{}}
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,json.JSONDecodeError) as exc:raise InstallationError('Saved onboarding state is unreadable; restore or remove the onboarding state file.') from exc
def save_onboarding(path,step,values):
    if step not in STEPS:raise InstallationError('Unknown onboarding step.')
    path=Path(path);state=load_onboarding(path);completed=list(dict.fromkeys([*state.get('completed_steps',[]),step]));index=min(STEPS.index(step)+1,len(STEPS)-1)
    state={'status':'COMPLETED' if step=='complete' else 'IN_PROGRESS','current_step':STEPS[index],'completed_steps':completed,'values':{**state.get('values',{}),**values},'updated_at':datetime.now(timezone.utc).isoformat()}
    path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(state,indent=2,sort_keys=True),encoding='utf-8');temporary.replace(path);return state
def onboarding_summary(path):
    state=load_onboarding(path);return {**state,'progress':round(len(state.get('completed_steps',[]))/len(STEPS)*100)}

def provision_demo_company(session):
    """Seed an explicitly selected demo tenant in the active isolated database."""
    if session.role!='admin':raise InstallationError('Only administrators can provision demo data.')
    from app.database.db_manager import get_connection
    with get_connection() as conn:
        if conn.execute("SELECT 1 FROM finance_audit WHERE event_type='DEMO_PROVISIONED'").fetchone():return {'created':False,'reason':'already_provisioned'}
    from app.inventory.category_service import create_category
    from app.inventory.inventory_service import create_product
    from app.procurement.supplier_service import create_supplier
    from app.customers.customer_service import create_customer
    from app.sales.sales_service import create_sale
    category=create_category(session,'Demo Beverages','Pilot demonstration products')
    product=create_product(session,sku='DEMO-COFFEE',barcode='629999000001',name='Demo Coffee',selling_price=5,cost_price=2,quantity_in_stock=40,reorder_level=5,category_id=category['id'])
    supplier=create_supplier(session,'Demo Supply Company',email='demo-supplier@example.invalid')
    customer=create_customer(session,'Demo','Customer',email='demo-customer@example.invalid')
    sale=create_sale(session,[{'product_id':product['id'],'quantity':2}],payment_method='CASH',amount_paid=10,customer_id=customer['id'])
    from app.finance.finance_service import record_income,create_expense,approve_expense
    with get_connection() as conn:expense_category=conn.execute('SELECT id FROM finance_categories ORDER BY id LIMIT 1').fetchone()[0]
    expense=create_expense(session,str(datetime.now().date()),expense_category,3,'Demo operating expense');approve_expense(session,expense);record_income(session,str(datetime.now().date()),'SERVICE',8,'Demo service income')
    with get_connection() as conn:conn.execute("INSERT INTO finance_audit(store_id,user_id,event_type,details) VALUES(?,?,?,?)",(session.store_id,session.user_id,'DEMO_PROVISIONED',json.dumps({'product_id':product['id'],'supplier_id':supplier['id'],'customer_id':customer['id']})))
    return {'created':True,'product_id':product['id'],'sale_id':sale['sale']['sale_id'],'supplier_id':supplier['id'],'customer_id':customer['id']}
