def bootstrap_staff(include_manager=True, include_cashier=True):
    import bcrypt
    from unittest.mock import patch

    from auth import authenticate_user, bootstrap_admin, create_user

    # Keep isolated test fixtures fast while production retains bcrypt defaults.
    with patch("auth.bcrypt.gensalt", return_value=bcrypt.gensalt(rounds=4)):
        bootstrap_admin("test-admin", "admin-password", "Test Administrator")
        admin_session = authenticate_user("test-admin", "admin-password")
        sessions = {"admin": admin_session}

        if include_manager:
            create_user(
                "manager1", "manager-password", "Test Manager", "manager",
                acting_session=admin_session,
            )
            sessions["manager"] = authenticate_user("manager1", "manager-password")
        if include_cashier:
            create_user(
                "cashier1", "cashier-password", "Test Cashier", "cashier",
                acting_session=admin_session,
            )
            sessions["cashier"] = authenticate_user("cashier1", "cashier-password")

    return sessions
