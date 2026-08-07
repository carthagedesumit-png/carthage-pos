import os, tempfile, unittest
from fastapi.testclient import TestClient
from app.api.app import app

class DashboardAdministrationManagementTestCase(unittest.TestCase):
    def setUp(self):
        self.db=tempfile.NamedTemporaryFile(delete=False); self.db.close()
        os.environ["CARTHAGE_POS_DB"]=self.db.name; os.environ["POS_SECURE_COOKIES"]="false"; os.environ["POS_DASHBOARD_CSRF"]="false"
        from app.core.config import reset_config_cache
        from app.database.db_manager import initialize_database
        from tests.support import bootstrap_staff
        reset_config_cache(); initialize_database(); self.sessions=bootstrap_staff(); self.client=TestClient(app)
    def tearDown(self):
        self.client.close()
        for key in ("CARTHAGE_POS_DB","POS_SECURE_COOKIES","POS_DASHBOARD_CSRF"):os.environ.pop(key,None)
        from app.core.config import reset_config_cache
        reset_config_cache(); os.unlink(self.db.name)
    def login(self,user="test-admin",password="admin-password"):
        response=self.client.post("/dashboard/login",data={"username":user,"password":password},follow_redirects=False)
        self.assertEqual(response.status_code,303); return response
    def create(self,username="admin-created",role="cashier",email="created@example.test"):
        return self.client.post("/dashboard/system/users",data={"username":username,"full_name":"Created User","email":email,"role":role,"password":"Strong-Temp9!","store_ids":"1","home_store_id":"1","force_password_change":"true"},follow_redirects=False)
    def created_id(self,response):return int(response.headers["location"].split("/")[-1].split("?")[0])

    def test_create_edit_and_unique_fields(self):
        self.login(); response=self.create(); self.assertEqual(response.status_code,303); uid=self.created_id(response)
        page=self.client.get(f"/dashboard/system/users/{uid}"); self.assertIn("created@example.test",page.text); self.assertIn("Force password change",page.text)
        edit=self.client.post(f"/dashboard/system/users/{uid}",data={"full_name":"Edited User","email":"edited@example.test","role":"inventory_officer","store_ids":"1","home_store_id":"1"},follow_redirects=False)
        self.assertEqual(edit.status_code,303); self.assertIn("Edited User",self.client.get(f"/dashboard/system/users/{uid}").text)
        self.assertEqual(self.create(username="admin-created",email="other@example.test").status_code,422)
        self.assertEqual(self.create(username="other-user",email="edited@example.test").status_code,422)

    def test_activate_deactivate_lock_unlock_and_audit(self):
        self.login(); uid=self.created_id(self.create())
        for path,data in [("lifecycle",{"active":"false"}),("lifecycle",{"active":"true"}),("lock",{"locked":"true"}),("lock",{"locked":"false"})]:
            self.assertEqual(self.client.post(f"/dashboard/system/users/{uid}/{path}",data=data,follow_redirects=False).status_code,303)
        from app.database.db_manager import get_connection
        with get_connection() as conn: events={r[0] for r in conn.execute("SELECT event_type FROM user_audit_events WHERE user_id=?",(uid,)).fetchall()}
        self.assertTrue({"USER_DEACTIVATED","USER_ACTIVATED","USER_LOCKED","USER_UNLOCKED"}.issubset(events))

    def test_password_reset_strength_history_and_no_plaintext(self):
        self.login(); uid=self.created_id(self.create()); weak=self.client.post(f"/dashboard/system/users/{uid}/password",data={"temporary_password":"weak"})
        self.assertEqual(weak.status_code,422)
        strong="Another-Strong9!"; result=self.client.post(f"/dashboard/system/users/{uid}/password",data={"temporary_password":strong},follow_redirects=False)
        self.assertEqual(result.status_code,303)
        from app.database.db_manager import get_connection
        with get_connection() as conn:
            row=conn.execute("SELECT password_hash,force_password_change FROM users WHERE id=?",(uid,)).fetchone(); history=conn.execute("SELECT password_hash FROM user_password_history WHERE user_id=?",(uid,)).fetchall()
        self.assertNotIn(strong,row[0]); self.assertEqual(row[1],1); self.assertTrue(history)
        self.assertEqual(self.client.post(f"/dashboard/system/users/{uid}/password",data={"temporary_password":strong}).status_code,422)

    def test_forced_password_change_flow(self):
        self.login(); self.assertEqual(self.create(username="forced-user",email="forced@example.test").status_code,303)
        self.client.cookies.clear(); login=self.client.post("/dashboard/login",data={"username":"forced-user","password":"Strong-Temp9!"},follow_redirects=False)
        self.assertIn("/dashboard/change-password",login.headers["location"])
        self.assertEqual(self.client.get("/dashboard/inventory/products/new").status_code,403)
        changed=self.client.post("/dashboard/change-password",data={"current_password":"Strong-Temp9!","new_password":"New-Secure-Pass9!"},follow_redirects=False)
        self.assertEqual(changed.status_code,303); self.assertIn("/dashboard/inventory",changed.headers["location"])
        from auth import authenticate_user
        self.assertIsNotNone(authenticate_user("forced-user","New-Secure-Pass9!"))

    def test_session_revoke_selected_and_others(self):
        self.login(); uid=self.sessions["admin"].user_id
        self.client.post("/api/v1/auth/login",json={"username":"test-admin","password":"admin-password"})
        detail=self.client.get(f"/dashboard/system/users/{uid}"); self.assertIn("Active Sessions",detail.text)
        from app.database.db_manager import get_connection
        with get_connection() as conn: ref=conn.execute("SELECT session_reference FROM api_sessions WHERE user_id=? AND revoked_at IS NULL ORDER BY created_at DESC",(uid,)).fetchone()[0]
        self.assertEqual(self.client.post(f"/dashboard/system/users/{uid}/sessions/{ref}/terminate",follow_redirects=False).status_code,303)
        self.assertEqual(self.client.post("/dashboard/system/sessions/terminate-others",follow_redirects=False).status_code,303)

    def test_manager_privilege_escalation_and_cashier_access_denied(self):
        self.login("manager1","manager-password")
        self.assertEqual(self.create(username="manager-cashier").status_code,303)
        denied=self.create(username="manager-admin",role="admin",email="manager-admin@example.test"); self.assertEqual(denied.status_code,403)
        self.client.cookies.clear(); self.login("cashier1","cashier-password")
        self.assertEqual(self.client.get("/dashboard/system").status_code,403)
        self.assertEqual(self.create(username="cashier-bypass").status_code,403)

    def test_cashier_exact_store_and_role_permissions(self):
        self.login(); bad=self.client.post("/dashboard/system/users",data={"username":"nostore","full_name":"No Store","role":"cashier","password":"Strong-Temp9!"})
        self.assertEqual(bad.status_code,422)
        uid=self.created_id(self.create(role="auditor")); page=self.client.get(f"/dashboard/system/users/{uid}")
        self.assertIn("audit.view",page.text)

    def test_csrf_rejection(self):
        os.environ["POS_DASHBOARD_CSRF"]="true"
        from app.core.config import reset_config_cache
        reset_config_cache(); response=self.client.post("/dashboard/login",data={"username":"test-admin","password":"admin-password"})
        self.assertEqual(response.status_code,403); self.assertIn("csrf_rejected",response.text)

if __name__=="__main__":unittest.main()
