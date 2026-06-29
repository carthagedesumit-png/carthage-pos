import os
import tempfile
import unittest


class AuthTestCase(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False)
        self.db_file.close()
        os.environ["CARTHAGE_POS_DB"] = self.db_file.name

        from app.database.db_manager import initialize_database

        initialize_database()

    def tearDown(self):
        os.environ.pop("CARTHAGE_POS_DB", None)
        os.unlink(self.db_file.name)

    def test_password_hashing_uses_bcrypt(self):
        from auth import hash_password, verify_password

        password_hash = hash_password("strong-password")

        self.assertTrue(password_hash.startswith("$2"))
        self.assertNotIn("strong-password", password_hash)
        self.assertTrue(verify_password("strong-password", password_hash))

    def test_successful_login_returns_session_and_updates_last_login(self):
        from auth import authenticate_user, create_user, get_user_by_id

        created = create_user("manager1", "correct-password", "Manager One", "manager")
        session = authenticate_user("manager1", "correct-password")
        user = get_user_by_id(created["id"])

        self.assertIsNotNone(session)
        self.assertEqual(session.username, "manager1")
        self.assertEqual(session.role, "manager")
        self.assertIsNotNone(user["last_login"])

    def test_invalid_password_is_rejected(self):
        from auth import authenticate_user, create_user

        create_user("cashier1", "correct-password", "Cashier One", "cashier")

        self.assertIsNone(authenticate_user("cashier1", "wrong-password"))

    def test_duplicate_usernames_are_rejected(self):
        from auth import create_user

        create_user("admin1", "first-password", "Admin One", "admin")

        with self.assertRaises(ValueError):
            create_user("admin1", "second-password", "Admin Duplicate", "admin")

    def test_inactive_accounts_cannot_login(self):
        from auth import authenticate_user, create_user, deactivate_user

        user = create_user("cashier2", "correct-password", "Cashier Two", "cashier")
        deactivate_user(user["id"])

        self.assertIsNone(authenticate_user("cashier2", "correct-password"))

    def test_role_restrictions(self):
        from auth import AuthorizationError, create_user, require_inventory_management, require_user_management

        admin = create_user("admin1", "admin-password", "Admin One", "admin")
        manager = create_user("manager1", "manager-password", "Manager One", "manager")
        cashier = create_user("cashier1", "cashier-password", "Cashier One", "cashier")

        from auth import authenticate_user

        admin_session = authenticate_user(admin["username"], "admin-password")
        manager_session = authenticate_user(manager["username"], "manager-password")
        cashier_session = authenticate_user(cashier["username"], "cashier-password")

        require_user_management(admin_session)
        require_inventory_management(admin_session)
        require_inventory_management(manager_session)

        with self.assertRaises(AuthorizationError):
            require_user_management(manager_session)
        with self.assertRaises(AuthorizationError):
            require_inventory_management(cashier_session)

    def test_password_change_invalidates_old_password(self):
        from auth import authenticate_user, change_password, create_user

        user = create_user("cashier3", "old-password", "Cashier Three", "cashier")
        change_password(user["id"], "new-password")

        self.assertIsNone(authenticate_user("cashier3", "old-password"))
        self.assertIsNotNone(authenticate_user("cashier3", "new-password"))

    def test_reactivate_user_restores_login(self):
        from auth import authenticate_user, create_user, deactivate_user, reactivate_user

        user = create_user("cashier4", "correct-password", "Cashier Four", "cashier")
        deactivate_user(user["id"])
        reactivate_user(user["id"])

        self.assertIsNotNone(authenticate_user("cashier4", "correct-password"))


if __name__ == "__main__":
    unittest.main()