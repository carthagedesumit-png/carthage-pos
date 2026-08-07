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

    def bootstrap(self):
        from auth import authenticate_user, bootstrap_admin

        user = bootstrap_admin("admin1", "admin-password", "Admin One")
        return user, authenticate_user("admin1", "admin-password")

    def test_password_hashing_uses_bcrypt(self):
        from auth import hash_password, verify_password

        password_hash = hash_password("strong-password")

        self.assertTrue(password_hash.startswith("$2"))
        self.assertNotIn("strong-password", password_hash)
        self.assertTrue(verify_password("strong-password", password_hash))

    def test_successful_login_returns_session_and_updates_last_login(self):
        from auth import authenticate_user, create_user, get_user_by_id

        _, admin_session = self.bootstrap()
        created = create_user(
            "manager1", "correct-password", "Manager One", "manager",
            acting_session=admin_session,
        )
        session = authenticate_user("manager1", "correct-password")
        user = get_user_by_id(created["id"])

        self.assertEqual(session.username, "manager1")
        self.assertEqual(session.role, "manager")
        self.assertIsNotNone(user["last_login"])

    def test_invalid_password_is_rejected(self):
        from auth import authenticate_user

        self.bootstrap()
        self.assertIsNone(authenticate_user("admin1", "wrong-password"))

    def test_duplicate_usernames_are_rejected(self):
        from auth import create_user

        _, admin_session = self.bootstrap()
        with self.assertRaises(ValueError):
            create_user(
                "admin1", "second-password", "Admin Duplicate", "admin",
                acting_session=admin_session,
            )

    def test_inactive_accounts_cannot_login(self):
        from auth import authenticate_user, create_user, deactivate_user

        _, admin_session = self.bootstrap()
        user = create_user(
            "cashier2", "correct-password", "Cashier Two", "cashier",
            acting_session=admin_session,
        )
        deactivate_user(user["id"], acting_session=admin_session)

        self.assertIsNone(authenticate_user("cashier2", "correct-password"))

    def test_role_restrictions(self):
        from auth import (
            AuthorizationError,
            authenticate_user,
            create_user,
            require_inventory_management,
            require_user_management,
        )

        _, admin_session = self.bootstrap()
        create_user("manager1", "manager-password", "Manager One", "manager", admin_session)
        create_user("cashier1", "cashier-password", "Cashier One", "cashier", admin_session)
        manager_session = authenticate_user("manager1", "manager-password")
        cashier_session = authenticate_user("cashier1", "cashier-password")

        require_user_management(admin_session)
        require_inventory_management(admin_session)
        require_inventory_management(manager_session)
        with self.assertRaises(AuthorizationError):
            require_user_management(manager_session)
        with self.assertRaises(AuthorizationError):
            require_inventory_management(cashier_session)

    def test_password_change_invalidates_old_password(self):
        from auth import authenticate_user, change_password, create_user

        _, admin_session = self.bootstrap()
        user = create_user("cashier3", "old-password", "Cashier Three", "cashier", admin_session)
        cashier_session = authenticate_user("cashier3", "old-password")
        change_password(user["id"], "new-password", acting_session=cashier_session)

        self.assertIsNone(authenticate_user("cashier3", "old-password"))
        self.assertIsNotNone(authenticate_user("cashier3", "new-password"))

    def test_reactivate_user_restores_login(self):
        from auth import authenticate_user, create_user, deactivate_user, reactivate_user

        _, admin_session = self.bootstrap()
        user = create_user("cashier4", "correct-password", "Cashier Four", "cashier", admin_session)
        deactivate_user(user["id"], acting_session=admin_session)
        reactivate_user(user["id"], acting_session=admin_session)

        self.assertIsNotNone(authenticate_user("cashier4", "correct-password"))

    def test_user_management_requires_an_admin_session(self):
        from auth import AuthorizationError, create_user

        self.bootstrap()
        with self.assertRaises(AuthorizationError):
            create_user("cashier", "password", "Cashier", "cashier")

    def test_bootstrap_admin_can_only_run_once(self):
        from auth import AuthorizationError, bootstrap_admin

        self.bootstrap()
        with self.assertRaises(AuthorizationError):
            bootstrap_admin("other-admin", "password", "Other Admin")

    def test_deactivated_session_is_rejected(self):
        from auth import AuthorizationError, create_user, deactivate_user, require_inventory_management

        _, admin_session = self.bootstrap()
        manager = create_user("manager1", "password", "Manager", "manager", admin_session)
        from auth import authenticate_user

        manager_session = authenticate_user("manager1", "password")
        deactivate_user(manager["id"], acting_session=admin_session)
        with self.assertRaises(AuthorizationError):
            require_inventory_management(manager_session)


if __name__ == "__main__":
    unittest.main()
