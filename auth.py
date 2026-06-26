import getpass
import hashlib
import hmac
import os

from app.database.db_manager import get_connection

HASH_NAME = "sha256"
HASH_ITERATIONS = 260000


class AuthenticationSystem:
    def __init__(self):
        self.current_user = None
        self.current_role = None

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
        configured_users = [
            ("admin", os.environ.get("CARTHAGE_POS_ADMIN_PASSWORD"), "admin"),
            ("cashier1", os.environ.get("CARTHAGE_POS_CASHIER_PASSWORD"), "cashier"),
        ]

        with get_connection() as conn:
            user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if user_count > 0:
                return

            created = 0
            for username, password, role in configured_users:
                if not password:
                    continue
                conn.execute(
                    """INSERT INTO users (username, password_hash, role)
                       VALUES (?, ?, ?)""",
                    (username, self.hash_password(password), role)
                )
                created += 1

        if created == 0:
            print("No POS users are configured yet.")
            print("Set CARTHAGE_POS_ADMIN_PASSWORD or CARTHAGE_POS_CASHIER_PASSWORD before first login.")

    def login(self):
        """Handles the cashier login loop."""
        self.ensure_default_users()

        while not self.current_user:
            self.display_login_header()
            print("\nPlease authenticate to access the terminal.")

            username = input("Username: ").strip()
            password = getpass.getpass("Password: ")

            user = self.fetch_user(username)
            if user and user["is_active"] and self.verify_password(password, user["password_hash"]):
                self.current_user = username
                self.current_role = user["role"]
                print(f"\n[SUCCESS] Welcome back, {username}!")
                input("\nPress Enter to launch the dashboard...")
                return True

            print("\n[ERROR] Invalid username or password.")
            input("Press Enter to try again...")

    def logout(self):
        """Logs out the current cashier."""
        if self.current_user:
            print(f"\nLogging out user: {self.current_user}...")
            self.current_user = None
            self.current_role = None
            input("Press Enter to return to login screen...")

    @staticmethod
    def hash_password(password):
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac(
            HASH_NAME,
            password.encode("utf-8"),
            salt,
            HASH_ITERATIONS
        )
        return f"pbkdf2_{HASH_NAME}${HASH_ITERATIONS}${salt.hex()}${digest.hex()}"

    @staticmethod
    def verify_password(password, stored_hash):
        try:
            algorithm, iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
            if algorithm != f"pbkdf2_{HASH_NAME}":
                return False
            candidate = hashlib.pbkdf2_hmac(
                HASH_NAME,
                password.encode("utf-8"),
                bytes.fromhex(salt_hex),
                int(iterations)
            )
            return hmac.compare_digest(candidate.hex(), digest_hex)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def fetch_user(username):
        with get_connection() as conn:
            row = conn.execute(
                "SELECT username, password_hash, role, is_active FROM users WHERE username = ?",
                (username,)
            ).fetchone()
            return dict(row) if row else None


if __name__ == "__main__":
    from app.database.db_manager import initialize_database

    initialize_database()
    auth = AuthenticationSystem()
    auth.login()