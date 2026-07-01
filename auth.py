import getpass
import os
from dataclasses import dataclass
from sqlite3 import IntegrityError
from typing import Optional

import bcrypt

from app.core.exceptions import AuthenticationError, AuthorizationError, ValidationError
from app.core.logging_utils import get_logger, log_event
from app.core.validation import required_text
from app.database.db_manager import get_connection
from app.database.transactions import transaction

ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_CASHIER = "cashier"
VALID_ROLES = {ROLE_ADMIN, ROLE_MANAGER, ROLE_CASHIER}
INVENTORY_ROLES = {ROLE_ADMIN, ROLE_MANAGER}
USER_MANAGEMENT_ROLES = {ROLE_ADMIN}


logger = get_logger("authentication")


@dataclass(frozen=True)
class UserSession:
    user_id: int
    username: str
    full_name: str
    role: str
    store_id: Optional[int] = None

    def can_manage_users(self):
        return self.role in USER_MANAGEMENT_ROLES

    def can_manage_inventory(self):
        return self.role in INVENTORY_ROLES


class AuthenticationSystem:
    def __init__(self):
        self.session = None

    @property
    def current_user(self):
        return self.session.username if self.session else None

    @property
    def current_role(self):
        return self.session.role if self.session else None

    def clear_screen(self):
        """Clears the terminal for a clean UI experience."""
        os.system('cls' if os.name == 'nt' else 'clear')

    def display_login_header(self):
        """Renders the top branding for the login screen."""
        self.clear_screen()
        print("=" * 40)
        print("       CARTHAGE SYSTEMS - POS       ")
        print("          SYSTEM LOCKBOX            ")
        print("=" * 40)

    def ensure_default_users(self):
        """Creates first-run users only from environment-provided passwords."""
        admin_password = os.environ.get("CARTHAGE_POS_ADMIN_PASSWORD")
        configured_staff = [
            ("manager1", os.environ.get("CARTHAGE_POS_MANAGER_PASSWORD"), "Store Manager", ROLE_MANAGER),
            ("cashier1", os.environ.get("CARTHAGE_POS_CASHIER_PASSWORD"), "Cashier One", ROLE_CASHIER),
        ]

        with get_connection() as conn:
            user_count = conn.execute("SELECT COUNT(*) FROM users WHERE username != 'system'").fetchone()[0]
            if user_count > 0:
                return

        if not admin_password:
            print("No POS users are configured yet.")
            print("Set CARTHAGE_POS_ADMIN_PASSWORD before first login.")
            return

        bootstrap_admin("admin", admin_password, "System Administrator")
        admin_session = authenticate_user("admin", admin_password)
        for username, password, full_name, role in configured_staff:
            if not password:
                continue
            create_user(username, password, full_name, role, acting_session=admin_session)

    def login(self):
        """Handles the cashier login loop and stores a user session."""
        self.ensure_default_users()

        while not self.session:
            self.display_login_header()
            print("\nPlease authenticate to access the terminal.")

            username = input("Username: ").strip()
            password = getpass.getpass("Password: ")

            session = authenticate_user(username, password)
            if session:
                self.session = session
                print(f"\n[SUCCESS] Welcome back, {session.full_name}!")
                input("\nPress Enter to launch the dashboard...")
                return True

            print("\n[ERROR] Invalid username or password.")
            input("Press Enter to try again...")

    def logout(self):
        """Logs out the current cashier."""
        if self.session:
            print(f"\nLogging out user: {self.session.username}...")
            self.session = None
            input("Press Enter to return to login screen...")


def hash_password(password):
    if not password:
        raise ValidationError("Password cannot be empty.")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password, password_hash):
    if not password or not password_hash or not password_hash.startswith("$2"):
        return False
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def row_to_session(row, store_id=None):
    active_store_id = store_id if store_id is not None else row["home_store_id"]
    return UserSession(
        user_id=row["id"],
        username=row["username"],
        full_name=row["full_name"],
        role=row["role"],
        store_id=active_store_id,
    )


def bootstrap_admin(username, password, full_name):
    """Creates the first administrator and is permanently disabled afterward."""
    username = normalize_username(username)
    full_name = required_text(full_name, "Full name")
    password_hash = hash_password(password)

    try:
        with transaction() as conn:
            user_count = conn.execute(
                "SELECT COUNT(*) FROM users WHERE username != 'system'"
            ).fetchone()[0]
            if user_count:
                raise AuthorizationError(
                    "Administrator bootstrap is only available before the first user is created."
                )
            cursor = conn.execute(
                """INSERT INTO users (
                       username, password_hash, full_name, role, is_active, home_store_id
                   ) VALUES (?, ?, ?, ?, 1, ?)""",
                (
                    username,
                    password_hash,
                    full_name,
                    ROLE_ADMIN,
                    _default_store_id(conn),
                ),
            )
            user_id = cursor.lastrowid
    except IntegrityError as exc:
        raise ValidationError(f"Username already exists: {username}") from exc

    log_event(logger, "admin_bootstrapped", user_id=user_id, username=username)
    return get_user_by_id(user_id)


def create_user(
    username,
    password,
    full_name,
    role=ROLE_CASHIER,
    acting_session=None,
    home_store_id=None,
):
    acting_session = require_user_management(acting_session)
    return _insert_user(
        username,
        password,
        full_name,
        role,
        home_store_id=home_store_id or acting_session.store_id,
    )


def _insert_user(username, password, full_name, role, home_store_id=None):
    username = normalize_username(username)
    validate_role(role)
    full_name = required_text(full_name, "Full name")

    try:
        with transaction() as conn:
            home_store_id = home_store_id or _default_store_id(conn)
            _require_active_store(conn, home_store_id)
            cursor = conn.execute(
                """INSERT INTO users (
                       username, password_hash, full_name, role, is_active, home_store_id
                   ) VALUES (?, ?, ?, ?, 1, ?)""",
                (username, hash_password(password), full_name, role, home_store_id)
            )
            user_id = cursor.lastrowid
            conn.execute(
                "INSERT OR IGNORE INTO user_store_access (user_id, store_id) VALUES (?, ?)",
                (user_id, home_store_id),
            )
    except IntegrityError as exc:
        raise ValidationError(f"Username already exists: {username}") from exc

    log_event(logger, "user_created", user_id=user_id, username=username, role=role)
    return get_user_by_id(user_id)


def authenticate_user(username, password, store_id=None):
    username = normalize_username(username)
    with get_connection() as conn:
        row = conn.execute(
            """SELECT id, username, password_hash, full_name, role, is_active, home_store_id
               FROM users WHERE username = ?""",
            (username,)
        ).fetchone()
        if not row or not row["is_active"] or not verify_password(password, row["password_hash"]):
            log_event(logger, "authentication_failed", username=username)
            return None
        conn.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (row["id"],))
        session = row_to_session(row, store_id=store_id)
        session = validate_session(session)
        log_event(logger, "authentication_succeeded", user_id=session.user_id, username=username)
        return session


def change_password(user_id, new_password, acting_session=None):
    acting_session = validate_session(acting_session)
    if acting_session.user_id != user_id:
        require_user_management(acting_session)
    if not get_user_by_id(user_id):
        raise ValidationError("User does not exist.")
    with transaction() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(new_password), user_id)
        )
    log_event(logger, "password_changed", user_id=user_id, acting_user_id=acting_session.user_id)


def deactivate_user(user_id, acting_session=None):
    acting_session = require_user_management(acting_session)
    if acting_session.user_id == user_id:
        raise AuthorizationError("Administrators cannot deactivate their own active session.")
    with transaction() as conn:
        cursor = conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
        if cursor.rowcount == 0:
            raise ValidationError("User does not exist.")
    log_event(logger, "user_deactivated", user_id=user_id, acting_user_id=acting_session.user_id)


def reactivate_user(user_id, acting_session=None):
    acting_session = require_user_management(acting_session)
    with transaction() as conn:
        cursor = conn.execute("UPDATE users SET is_active = 1 WHERE id = ?", (user_id,))
        if cursor.rowcount == 0:
            raise ValidationError("User does not exist.")
    log_event(logger, "user_reactivated", user_id=user_id, acting_user_id=acting_session.user_id)


def get_user_by_id(user_id):
    with get_connection() as conn:
        row = conn.execute(
            """SELECT id, username, full_name, role, is_active, created_at, last_login,
                      home_store_id
               FROM users WHERE id = ?""",
            (user_id,)
        ).fetchone()
        return dict(row) if row else None


def require_user_management(session):
    session = validate_session(session)
    if not session.can_manage_users():
        raise AuthorizationError("Only admin users can manage POS users.")
    return session


def require_inventory_management(session, store_id=None):
    session = validate_session(session)
    if not session.can_manage_inventory():
        raise AuthorizationError("Only admin and manager users can manage inventory.")
    if store_id is not None:
        require_store_access(session, store_id, manage=True)
    return session


def validate_session(session):
    """Revalidates identity, role, and active status against the current database."""
    if not isinstance(session, UserSession):
        raise AuthorizationError("A valid authenticated user session is required.")
    with get_connection() as conn:
        row = conn.execute(
            """SELECT id, username, full_name, role, is_active, home_store_id
               FROM users WHERE id = ?""",
            (session.user_id,),
        ).fetchone()
        if row:
            active_store_id = session.store_id or row["home_store_id"]
            store = conn.execute(
                "SELECT id, is_active FROM stores WHERE id = ?", (active_store_id,)
            ).fetchone()
            has_assignment = conn.execute(
                "SELECT 1 FROM user_store_access WHERE user_id = ? AND store_id = ?",
                (row["id"], active_store_id),
            ).fetchone()
        else:
            active_store_id = None
            store = None
            has_assignment = None
    if (
        not row
        or not row["is_active"]
        or row["username"] != session.username
        or row["role"] != session.role
    ):
        raise AuthorizationError("This user session is no longer valid.")
    if not store or not store["is_active"]:
        raise AuthorizationError("The selected store is inactive or unavailable.")
    if row["role"] == ROLE_CASHIER and active_store_id != row["home_store_id"]:
        raise AuthorizationError("Cashiers may only operate in their assigned home store.")
    if row["role"] == ROLE_MANAGER and not has_assignment:
        raise AuthorizationError("Manager is not assigned to the selected store.")
    return row_to_session(row, store_id=active_store_id)


def switch_store(session, store_id):
    """Return a revalidated session scoped to an authorized active store."""
    session = validate_session(session)
    candidate = UserSession(
        user_id=session.user_id,
        username=session.username,
        full_name=session.full_name,
        role=session.role,
        store_id=int(store_id),
    )
    return validate_session(candidate)


def require_store_access(session, store_id, manage=False):
    """Require access to one store, with manager/admin rights when requested."""
    scoped = switch_store(session, store_id)
    if manage and scoped.role not in INVENTORY_ROLES:
        raise AuthorizationError("Only admin and manager users can manage stores.")
    return scoped


def _default_store_id(conn):
    row = conn.execute("SELECT id FROM stores WHERE code = 'MAIN' COLLATE NOCASE").fetchone()
    if not row:
        raise ValueError("Default store is not configured.")
    return row["id"]


def _require_active_store(conn, store_id):
    row = conn.execute(
        "SELECT id FROM stores WHERE id = ? AND is_active = 1", (store_id,)
    ).fetchone()
    if not row:
        raise ValueError("Store not found or inactive.")


def normalize_username(username):
    username = (username or "").strip().lower()
    if not username:
        raise ValidationError("Username is required.")
    return username


def validate_role(role):
    if role not in VALID_ROLES:
        raise ValidationError(f"Role must be one of: {', '.join(sorted(VALID_ROLES))}.")


if __name__ == "__main__":
    from app.database.db_manager import initialize_database

    initialize_database()
    auth = AuthenticationSystem()
    auth.login()
