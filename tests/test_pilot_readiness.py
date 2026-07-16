import os,socket,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

class PilotReadinessTestCase(unittest.TestCase):
 def setUp(self):
  self.root=Path(tempfile.mkdtemp());self.db=self.root/'pilot.db';os.environ['CARTHAGE_POS_DB']=str(self.db);os.environ['POS_BACKUP_DIRECTORY']=str(self.root/'backups');os.environ['POS_LOG_DIRECTORY']=str(self.root/'logs')
  from app.core.config import reset_config_cache
  from app.database.db_manager import initialize_database
  from tests.support import bootstrap_staff
  reset_config_cache();initialize_database();self.sessions=bootstrap_staff()
 def tearDown(self):
  import shutil
  for key in ('CARTHAGE_POS_DB','POS_BACKUP_DIRECTORY','POS_LOG_DIRECTORY'):os.environ.pop(key,None)
  from app.core.config import reset_config_cache
  reset_config_cache();shutil.rmtree(self.root,ignore_errors=True)
 def test_startup_browser_port_conflict_and_single_instance(self):
  from app.deployment.startup_service import acquire_instance,choose_port,release_instance,schedule_browser
  with socket.socket() as occupied:
   occupied.bind(('127.0.0.1',0));busy=occupied.getsockname()[1]
   with socket.socket() as candidate:candidate.bind(('127.0.0.1',0));fallback=candidate.getsockname()[1]
   self.assertEqual(choose_port('127.0.0.1',busy,fallback),fallback)
  lock=self.root/'instance.json';first=acquire_instance(lock,'http://127.0.0.1:65530');self.assertTrue(first['acquired']);release_instance(lock)
  opened=[];timer=schedule_browser('http://127.0.0.1:8000',True,0,opened.append);timer.join(1);self.assertEqual(opened,['http://127.0.0.1:8000/dashboard/'])
 def test_resumable_onboarding_and_installer_preflight(self):
  from app.deployment.onboarding_service import save_onboarding,onboarding_summary
  state=self.root/'onboarding.json';save_onboarding(state,'company',{'business_name':'Pilot Co'});resumed=onboarding_summary(state);self.assertEqual(resumed['current_step'],'store');self.assertGreater(resumed['progress'],0)
  from app.deployment.installer_service import validate_installation_request
  from app.deployment.models import SetupRequest
  request=SetupRequest('Pilot Co','Main Store','pilot-admin','StrongPilot123','Pilot Admin',str(self.root/'app'),str(self.root/'data'/'cbos.db'),str(self.root/'backup'))
  self.assertTrue(validate_installation_request(request,minimum_free_bytes=1)['valid'])
 def test_demo_company_is_explicit_idempotent_and_financially_live(self):
  from app.deployment.onboarding_service import provision_demo_company
  result=provision_demo_company(self.sessions['admin']);self.assertTrue(result['created']);self.assertFalse(provision_demo_company(self.sessions['admin'])['created'])
  from app.database.db_manager import get_connection
  with get_connection() as conn:
   self.assertGreater(conn.execute('SELECT COUNT(*) FROM products').fetchone()[0],0);self.assertGreater(conn.execute('SELECT COUNT(*) FROM sales').fetchone()[0],0);self.assertGreater(conn.execute("SELECT COUNT(*) FROM finance_journals WHERE status='POSTED'").fetchone()[0],0)
 def test_diagnostics_recovery_maintenance_and_preferences(self):
  from app.operations.pilot_service import diagnostics,run_maintenance,maintenance_history,save_preferences,get_preferences
  report=diagnostics(self.sessions['admin']);self.assertEqual(report['storage']['integrity'],'ok');self.assertIn('api',report);self.assertIn('recovery',report)
  result=run_maintenance(self.sessions['admin'],'OPTIMIZE_DATABASE');self.assertEqual(result['status'],'COMPLETED');self.assertEqual(len(maintenance_history(self.sessions['admin'])),1)
  save_preferences(self.sessions['manager'],{'favorites':['sales','inventory'],'secret':'ignored'});prefs=get_preferences(self.sessions['manager']);self.assertNotIn('secret',prefs);self.assertEqual(prefs['favorites'],['sales','inventory'])

class PilotDashboardAcceptanceTestCase(unittest.TestCase):
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
 def test_admin_diagnostics_and_maintenance_pages(self):
  self.assertEqual(self.client.post('/dashboard/login',data={'username':'test-admin','password':'admin-password'},follow_redirects=False).status_code,303)
  page=self.client.get('/dashboard/system/diagnostics');self.assertEqual(page.status_code,200);self.assertIn('Operational Diagnostics',page.text)
  maintenance=self.client.post('/dashboard/system/maintenance',data={'operation':'OPTIMIZE_DATABASE'},follow_redirects=False);self.assertEqual(maintenance.status_code,303)
  export=self.client.get('/dashboard/system/configuration/export');self.assertEqual(export.status_code,200);self.assertIn('company',export.json())
 def test_non_admin_is_denied_diagnostics(self):
  self.client.post('/dashboard/login',data={'username':'cashier1','password':'cashier-password'});self.assertEqual(self.client.get('/dashboard/system/diagnostics').status_code,403)

if __name__=='__main__':unittest.main()
