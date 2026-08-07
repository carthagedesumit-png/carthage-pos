import os,tempfile,unittest

class FinanceIntegrationTestCase(unittest.TestCase):
 def setUp(self):
  self.db=tempfile.NamedTemporaryFile(delete=False);self.db.close();os.environ['CARTHAGE_POS_DB']=self.db.name
  from app.database.db_manager import initialize_database
  from tests.support import bootstrap_staff
  initialize_database();self.s=bootstrap_staff()
  from app.inventory.inventory_service import create_product
  self.product=create_product(self.s['manager'],sku='FIN-INT',barcode='FIN-INT',name='Finance Integration',selling_price=10,cost_price=4,quantity_in_stock=30,reorder_level=2)
 def tearDown(self):os.environ.pop('CARTHAGE_POS_DB',None);os.unlink(self.db.name)
 def test_mixed_tax_discount_cogs_and_duplicate_sale_posting(self):
  from app.sales.sales_service import create_sale
  sale=create_sale(self.s['manager'],[{'product_id':self.product['id'],'quantity':2}],payment_method='MIXED',payments=[{'payment_method':'CASH','amount':8},{'payment_method':'CARD','amount':11}],discount_type='FIXED',discount_value=2,tax_rate=.05)
  sid=sale['sale']['sale_id']
  from app.finance.posting_service import post_sale
  duplicate=post_sale(self.s['manager'],sid);self.assertTrue(duplicate['duplicate'])
  from app.database.db_manager import get_connection
  with get_connection() as conn:
   event=conn.execute("SELECT * FROM finance_posting_events WHERE idempotency_key=?",(f'sale:{sid}',)).fetchone();lines=conn.execute('SELECT a.code,l.debit,l.credit FROM finance_journal_lines l JOIN finance_accounts a ON a.id=l.account_id WHERE journal_id=?',(event['journal_id'],)).fetchall()
  self.assertEqual(event['status'],'POSTED');self.assertEqual(round(sum(r['debit'] for r in lines),2),round(sum(r['credit'] for r in lines),2));self.assertIn('5000',{r['code'] for r in lines});self.assertIn('1200',{r['code'] for r in lines})
 def test_partial_return_and_partial_goods_receipt_post_once(self):
  from app.sales.sales_service import create_sale,process_return
  sale=create_sale(self.s['cashier'],[{'product_id':self.product['id'],'quantity':2}],payment_method='CASH',amount_paid=20);item=sale['items'][0]
  returned=process_return(self.s['manager'],sale['sale']['sale_id'],[{'sale_item_id':item['id'],'quantity':1}],'Partial')
  from app.procurement.supplier_service import create_supplier
  from app.procurement.purchase_service import create_purchase_order,submit_purchase_order,receive_purchase_order
  supplier=create_supplier(self.s['manager'],'Finance Supplier');po=create_purchase_order(self.s['manager'],supplier['id'],'FIN-PO-1',[{'product_id':self.product['id'],'quantity':4,'unit_cost':5}]);po_id=po['purchase_order']['id'];submit_purchase_order(self.s['manager'],po_id);receipt=receive_purchase_order(self.s['manager'],po_id,[{'purchase_order_item_id':po['items'][0]['id'],'quantity':2}])
  from app.database.db_manager import get_connection
  with get_connection() as conn:
   keys={r[0] for r in conn.execute('SELECT idempotency_key FROM finance_posting_events')}
  self.assertIn(f"return:{returned['return']['id']}",keys);self.assertIn(f"goods-receipt:{receipt['receipt']['id']}",keys)
 def test_wallet_credit_and_inventory_adjustment_integration(self):
  from app.customers.customer_service import create_customer
  from app.customers.wallet_service import deposit_wallet
  from app.customers.credit_service import set_credit_terms
  customer=create_customer(self.s['manager'],'Finance','Customer');deposit=deposit_wallet(self.s['manager'],customer['id'],25);set_credit_terms(self.s['manager'],customer['id'],100)
  from app.sales.sales_service import create_sale
  create_sale(self.s['cashier'],[{'product_id':self.product['id'],'quantity':1}],payment_method='CREDIT',customer_id=customer['id'])
  from app.customers.credit_service import make_credit_payment
  payment=make_credit_payment(self.s['manager'],customer['id'],5)
  from app.inventory.inventory_service import adjust_stock
  adjust_stock(self.s['manager'],self.product['id'],25,notes='Shrinkage')
  from app.database.db_manager import get_connection
  with get_connection() as conn:keys={r[0] for r in conn.execute('SELECT idempotency_key FROM finance_posting_events')}
  self.assertIn(f"wallet:{deposit['transaction_id']}",keys);self.assertIn(f"credit:{payment['transaction_id']}",keys);self.assertTrue(any(k.startswith('inventory-adjustment:') for k in keys))
 def test_opening_balance_preview_post_lock_and_uniqueness(self):
  from app.finance.integration_service import opening_preview,create_opening_batch,post_opening_batch
  from app.finance.finance_service import list_accounts,lock_period
  accounts={a['code']:a['id'] for a in list_accounts(self.s['admin'])};lines=[{'account_id':accounts['1000'],'debit':500}]
  preview=opening_preview(self.s['admin'],'2025-12-31','Opening',lines,accounts['3000']);self.assertEqual(preview['total_debits'],preview['total_credits'])
  batch=create_opening_batch(self.s['admin'],'2025-12-31','Opening',lines,accounts['3000']);posted=post_opening_batch(self.s['admin'],batch['batch_id']);self.assertIsNotNone(posted['journal_id'])
  with self.assertRaises(Exception):create_opening_batch(self.s['admin'],'2025-12-31','Again',lines,accounts['3000'])
  lock_period(self.s['admin'],'Locked','2025-01-01','2025-01-31')
  blocked=create_opening_batch(self.s['admin'],'2025-01-15','Locked opening',lines,accounts['3000'])
  with self.assertRaises(Exception):post_opening_batch(self.s['admin'],blocked['batch_id'])
 def test_reconciliation_and_historical_dry_run_are_non_mutating(self):
  from app.sales.sales_service import create_sale
  create_sale(self.s['cashier'],[{'product_id':self.product['id'],'quantity':1}],payment_method='TRANSFER')
  from app.finance.integration_service import reconciliation_report,backfill
  report=reconciliation_report(self.s['admin']);self.assertEqual(report['checks'][0]['status'],'MATCHED')
  before=backfill(self.s['admin'],dry_run=True);self.assertEqual(before['posted'],0);self.assertEqual(before['eligible'],0)
 def test_finance_failure_rolls_back_originating_sale(self):
  from app.database.db_manager import get_connection
  with get_connection() as conn:conn.execute("DELETE FROM finance_account_mappings WHERE mapping_key='sales_revenue'")
  from app.sales.sales_service import create_sale
  with self.assertRaises(Exception):create_sale(self.s['cashier'],[{'product_id':self.product['id'],'quantity':1}],payment_method='CASH',amount_paid=10)
  with get_connection() as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM sales').fetchone()[0],0);self.assertEqual(conn.execute('SELECT quantity_on_hand FROM store_inventory WHERE product_id=? AND store_id=?',(self.product['id'],self.s['cashier'].store_id)).fetchone()[0],30)

if __name__=='__main__':unittest.main()
