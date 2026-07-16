import os,tempfile,unittest
from datetime import date,timedelta
from auth import UserSession
from app.core.exceptions import AuthorizationError

class ExecutiveAnalyticsTestCase(unittest.TestCase):
 def setUp(self):
  self.file=tempfile.NamedTemporaryFile(delete=False);self.file.close();os.environ['CARTHAGE_POS_DB']=self.file.name
  from app.database.db_manager import initialize_database
  from tests.support import bootstrap_staff
  initialize_database();self.sessions=bootstrap_staff()
  from app.inventory.inventory_service import create_product
  self.product=create_product(self.sessions['manager'],sku='EXEC-1',barcode='EXEC-1',name='Executive Product',selling_price=20,cost_price=8,quantity_in_stock=200,reorder_level=5)
  from app.executive.analytics_service import clear_cache
  clear_cache()
 def tearDown(self):os.environ.pop('CARTHAGE_POS_DB',None);os.unlink(self.file.name)
 def test_empty_database_and_permissions(self):
  from app.executive.analytics_service import executive_dashboard
  data=executive_dashboard(self.sessions['manager']);self.assertEqual(data['kpis']['revenue_today'],0);self.assertEqual(data['kpis']['gross_margin_percent'],0);self.assertEqual(data['forecasts']['method'],'deterministic trailing-average with bounded growth')
  with self.assertRaises(AuthorizationError):executive_dashboard(self.sessions['cashier'])
 def test_kpis_forecasts_and_cached_refresh(self):
  from app.sales.sales_service import create_sale
  create_sale(self.sessions['manager'],[{'product_id':self.product['id'],'quantity':2}],payment_method='CASH',amount_paid=42,tax_rate=.05)
  from app.executive.analytics_service import executive_dashboard
  first=executive_dashboard(self.sessions['manager']);second=executive_dashboard(self.sessions['manager']);fresh=executive_dashboard(self.sessions['manager'],refresh=True)
  self.assertEqual(first['kpis']['revenue_today'],42);self.assertGreater(first['kpis']['gross_profit'],0);self.assertFalse(first['cache']['hit']);self.assertTrue(second['cache']['hit']);self.assertFalse(fresh['cache']['hit']);self.assertTrue(first['forecasts']['inventory_depletion'])
 def test_multi_store_admin_aggregation_and_manager_scope(self):
  from app.database.db_manager import get_connection
  with get_connection() as conn:
   store2=conn.execute("INSERT INTO stores(code,name,is_active) VALUES('EXEC2','Executive Two',1)").lastrowid;conn.execute('INSERT INTO user_store_access(user_id,store_id) VALUES(?,?)',(self.sessions['manager'].user_id,store2));conn.execute('INSERT INTO store_inventory(store_id,product_id,quantity_on_hand,reorder_level,average_cost) VALUES(?,?,?,?,?)',(store2,self.product['id'],50,5,8))
  admin2=UserSession(self.sessions['admin'].user_id,self.sessions['admin'].username,self.sessions['admin'].full_name,'admin',store2);manager2=UserSession(self.sessions['manager'].user_id,self.sessions['manager'].username,self.sessions['manager'].full_name,'manager',store2)
  from app.sales.sales_service import create_sale
  create_sale(self.sessions['manager'],[{'product_id':self.product['id'],'quantity':1}],payment_method='CARD');create_sale(manager2,[{'product_id':self.product['id'],'quantity':2}],payment_method='CARD')
  from app.executive.analytics_service import clear_cache,executive_dashboard
  clear_cache();global_data=executive_dashboard(self.sessions['admin']);store_data=executive_dashboard(self.sessions['manager']);self.assertEqual(global_data['kpis']['revenue_today'],60);self.assertEqual(store_data['kpis']['revenue_today'],20);self.assertEqual(len(global_data['performance']['branches']),2)
 def test_exports_schedules_and_large_dataset(self):
  from app.sales.sales_service import create_sale
  for _ in range(40):create_sale(self.sessions['manager'],[{'product_id':self.product['id'],'quantity':1}],payment_method='TRANSFER')
  from app.executive.analytics_service import create_schedule,executive_dashboard,export_executive_report,list_schedules
  data=executive_dashboard(self.sessions['manager'],refresh=True);self.assertEqual(data['periods']['today']['transaction_count'],40)
  for fmt,magic in [('csv',b'\xef\xbb\xbf'),('excel',b'<?xml'),('pdf',b'%PDF')]:self.assertTrue(export_executive_report(self.sessions['manager'],fmt)['content'].startswith(magic))
  create_schedule(self.sessions['manager'],'Daily Store','DAILY','PDF');create_schedule(self.sessions['admin'],'Quarterly Company','QUARTERLY','EXCEL');self.assertEqual(len(list_schedules(self.sessions['manager'])),1);self.assertEqual(len(list_schedules(self.sessions['admin'])),2)

class ExecutiveDashboardTestCase(unittest.TestCase):
 def setUp(self):
  self.file=tempfile.NamedTemporaryFile(delete=False);self.file.close();os.environ['CARTHAGE_POS_DB']=self.file.name;os.environ['POS_SECURE_COOKIES']='false';os.environ['POS_DASHBOARD_CSRF']='false'
  from app.core.config import reset_config_cache
  from app.database.db_manager import initialize_database
  from tests.support import bootstrap_staff
  reset_config_cache();initialize_database();bootstrap_staff();from fastapi.testclient import TestClient;from app.api.app import app;self.client=TestClient(app)
 def tearDown(self):
  self.client.close();os.unlink(self.file.name)
  for key in ('CARTHAGE_POS_DB','POS_SECURE_COOKIES','POS_DASHBOARD_CSRF'):os.environ.pop(key,None)
  from app.core.config import reset_config_cache
  reset_config_cache()
 def login(self,user,password):self.assertEqual(self.client.post('/dashboard/login',data={'username':user,'password':password},follow_redirects=False).status_code,303)
 def test_workspace_exports_schedule_and_cashier_denial(self):
  self.login('manager1','manager-password');page=self.client.get('/dashboard/executive');self.assertEqual(page.status_code,200);self.assertIn('Executive Intelligence',page.text);self.assertIn('Revenue Trend',page.text)
  self.assertEqual(self.client.get('/dashboard/executive/export/pdf').content[:4],b'%PDF');created=self.client.post('/dashboard/executive/schedules',data={'name':'Weekly','frequency':'WEEKLY','format':'CSV'},follow_redirects=False);self.assertEqual(created.status_code,303)
  self.client.cookies.clear();self.login('cashier1','cashier-password');self.assertEqual(self.client.get('/dashboard/executive').status_code,403)

if __name__=='__main__':unittest.main()
