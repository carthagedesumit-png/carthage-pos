from app.database.db_manager import initialize_database, seed_initial_data
from app.ui.terminal_ui import run_pos_terminal
from auth import AuthenticationSystem


def bootstrap():
    initialize_database()
    seed_initial_data()

    auth = AuthenticationSystem()
    if auth.login():
        print("Booting Carthage Systems POS Terminal Engine...")
        print("\n--- System Status: Online & Secure ---")
        run_pos_terminal(session=auth.session)
    else:
        print("\n[CRITICAL] System access denied. Shutting down.")


if __name__ == "__main__":
    bootstrap()