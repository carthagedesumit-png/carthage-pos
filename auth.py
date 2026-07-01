import getpass
import os
from dataclasses import dataclass
from sqlite3 import IntegrityError

import bcrypt

from app.database.db_manager import get_connection

ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_CASHIER = "cashier"
VALID_ROLES = {ROLE_ADMIN, ROLE_MANAGER, ROLE_CASHIER}
INVENTORY_ROLES = {ROLE_ADMIN, ROLE_MANAGER}
USER_MANAGEMENT_ROLES = {ROLE_ADMIN}


class AuthenticationError(Exception):
    pass


class AuthorizationError(Exception):
    pass


@dataclass(frozen=True)
class UserSession:
    user_id: int
    username: str
    full_name: str
    role: str

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
        raise ValueError("Password cannot be empty.")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password, password_hash):
    if not password or not password_hash or not password_hash.startswith("$2"):
        return False
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def row_to_session(row):
    return UserSession(
        user_id=row["id"],
        username=row["username"],
        full_name=row["full_name"],
        role=row["role"]
    )


def bootstrap_admin(username, password, full_name):
    """Creates the first administrator and is permanently disabled afterward."""
    username = normalize_username(username)
    if not full_name or not full_name.strip():
        raise ValueError("Full name is required.")
    password_hash = hash_password(password)

    try:
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            user_count = conn.execute(
                "SELECT COUNT(*) FROM users WHERE username != 'system'"
            ).fetchone()[0]
            if user_count:
                raise AuthorizationError(
                    "Administrator bootstrap is only available before the first user is created."
                )
            cursor = conn.execute(
                """INSERT INTO users (username, password_hash, full_name, role, is_active)
                   VALUES (?, ?, ?, ?, 1)""",
                (username, password_hash, full_name.strip(), ROLE_ADMIN),
            )
            user_id = cursor.lastrowid
    except IntegrityError as exc:
        raise ValueError(f"Username already exists: {username}") from exc

    return get_user_by_id(user_id)


def create_user(username, password, full_name, role=ROLE_CASHIER, acting_session=None):
    require_user_management(acting_session)
    return _insert_user(username, password, full_name, role)


def _insert_user(username, password, full_name, role):
    username = normalize_username(username)
    validate_role(role)
    if not full_name or not full_name.strip():
        raise ValueError("Full name is required.")

    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO users (username, password_hash, full_name, role, is_active)
                   VALUES (?, ?, ?, ?, 1)""",
                (username, hash_password(password), full_name.strip(), role)
            )
            user_id = cursor.lastrowid
    except IntegrityError as exc:
        raise ValueError(f"Username already exists: {username}") from exc

    return get_user_by_id(user_id)


def authenticate_user(username, password):
    username = normalize_username(username)
    with get_connection() as conn:
        row = conn.execute(
            """SELECT id, username, password_hash, full_name, role, is_active
               FROM users WHERE username = ?""",
            (username,)
        ).fetchone()
        if not row or not row["is_active"] or not verify_password(password, row["password_hash"]):
            return None
        conn.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (row["id"],))
        return row_to_session(row)


def change_password(user_id, new_password, acting_session=None):
    acting_session = validate_session(acting_session)
    if acting_session.user_id != user_id:
        require_user_management(acting_session)
    if not get_user_by_id(user_id):
        raise ValueError("User does not exist.")
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(new_password), user_id)
        )


def deactivate_user(user_id, acting_session=None):
    acting_session = require_user_management(acting_session)
    if acting_session.user_id == user_id:
        raise AuthorizationError("Administrators cannot deactivate their own active session.")
    with get_connection() as conn:
        cursor = conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
        if cursor.rowcount == 0:
            raise ValueError("User does not exist.")


def reactivate_user(user_id, acting_session=None):
    require_user_management(acting_session)
    with get_connection() as conn:
        cursor = conn.execute("UPDATE users SET is_active = 1 WHERE id = ?", (user_id,))
        if cursor.rowcount == 0:
            raise ValueError("User does not exist.")


def get_user_by_id(user_id):
    with get_connection() as conn:
        row = conn.execute(
            """SELECT id, username, full_name, role, is_active, created_at, last_login
               FROM users WHERE id = ?""",
            (user_id,)
        ).fetchone()
        return dict(row) if row else None


def require_user_management(session):
    session = validate_session(session)
    if not session.can_manage_users():
        raise AuthorizationError("Only admin users can manage POS users.")
    return session


def require_inventory_management(session):
    session = validate_session(session)
    if not session.can_manage_inventory():
        raise AuthorizationError("Only admin and manager users can manage inventory.")
    return session


def validate_session(session):
    """Revalidates identity, role, and active status against the current database."""
    if not isinstance(session, UserSession):
        raise AuthorizationError("A valid authenticated user session is required.")
    with get_connection() as conn:
        row = conn.execute(
            """SELECT id, username, full_name, role, is_active
               FROM users WHERE id = ?""",
            (session.user_id,),
        ).fetchone()
    if (
        not row
        or not row["is_active"]
        or row["username"] != session.username
        or row["role"] != session.role
    ):
        raise AuthorizationError("This user session is no longer valid.")
    return row_to_session(row)


def normalize_username(username):
    username = (username or "").strip().lower()
    if not username:
        raise ValueError("Username is required.")
    return username


def validate_role(role):
    if role not in VALID_ROLES:
        raise ValueError(f"Role must be one of: {', '.join(sorted(VALID_ROLES))}.")


if __name__ == "__main__":
    from app.database.db_manager import initialize_database

    initialize_database()
    auth = AuthenticationSystem()
    auth.login()
