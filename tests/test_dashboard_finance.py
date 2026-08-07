import os,tempfile,unittest
from fastapi.testclient import TestClient
from app.api.app import app

class DashboardFinanceTestCase(unittest.TestCase):
 def setUp(self):
  self.db=tempfile.NamedTemporaryFile(delete=False);self.db.close();os.environ['CARTHAGE_POS_DB']=self.db.name;os.environ['POS_SECURE_COOKIES']='false';os.environ['POS_DASHBOARD_CSRF']='false'
  from app.core.config import reset_config_cache
  from app.database.db_manager import initialize_database
  from tests.support import bootstrap_staff
  reset_config_cache();initialize_database();bootstrap_staff();self.client=TestClient(app)
 def tearDown(self):
  self.client.close();os.environ.pop('CARTHAGE_POS_DB',None);os.environ.pop('POS_SECURE_COOKIES',None);os.environ.pop('POS_DASHBOARD_CSRF',None)
  from app.core.config import reset_config_cache
  reset_config_cache();os.unlink(self.db.name)
 def login(self,user='manager1',password='manager-password'):
  self.assertEqual(self.client.post('/dashboard/login',data={'username':user,'password':password},follow_redirects=False).status_code,303)
 def test_finance_pages_and_journal_route(self):
  self.login();page=self.client.get('/dashboard/finance');self.assertEqual(page.status_code,200);self.assertIn('Financial Management',page.text)
  for section in ('cash','expenses','income','journals','accounts','reports','tax'):
   self.assertEqual(self.client.get('/dashboard/finance/'+section).status_code,200)
  from app.finance.finance_service import list_accounts
  from auth import authenticate_user
  ids={a['code']:a['id'] for a in list_accounts(authenticate_user('manager1','manager-password'))}
  response=self.client.post('/dashboard/finance/journals',data={'entry_date':'2026-05-01','description':'Web journal','account_id':[ids['1000'],ids['4200']],'line_description':['Cash','Income'],'debit':['20',''],'credit':['','20'],'post':'true'},follow_redirects=False)
  self.assertEqual(response.status_code,303);self.assertIn('success=',response.headers['location'])
 def test_cashier_sees_read_only_workspace_and_cannot_post(self):
  self.login('cashier1','cashier-password');page=self.client.get('/dashboard/finance/journals');self.assertEqual(page.status_code,200);self.assertNotIn('New Journal Entry',page.text)
  denied=self.client.post('/dashboard/finance/accounts',data={'code':'9999','name':'Denied','account_type':'ASSET'},follow_redirects=False);self.assertIn('error=',denied.headers['location'])
 def test_csrf_rejection(self):
  os.environ['POS_DASHBOARD_CSRF']='true';from app.core.config import reset_config_cache;reset_config_cache()
  response=self.client.post('/dashboard/login',data={'username':'manager1','password':'manager-password'});self.assertEqual(response.status_code,403)

if __name__=='__main__':unittest.main()
