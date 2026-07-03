import os
import sys
from pathlib import Path

from app.database.db_manager import initialize_database, seed_initial_data
from app.ui.terminal_ui import run_pos_terminal
from app.core.config import get_config, load_environment_file
from auth import AuthenticationSystem


def bootstrap():
    load_deployment_environment()
    initialize_database()
    if get_config().deployment.seed_sample_data:
        seed_initial_data()

    auth = AuthenticationSystem()
    if auth.login():
        print("Booting Carthage Systems POS Terminal Engine...")
        print("\n--- System Status: Online & Secure ---")
        run_pos_terminal(session=auth.session)
    else:
        print("\n[CRITICAL] System access denied. Shutting down.")


def load_deployment_environment():
    """Load installer-generated settings before opening the production database."""
    explicit = os.environ.get("CARTHAGE_POS_ENV_FILE")
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    candidate = Path(explicit).expanduser() if explicit else base / "config" / "carthage-pos.env"
    if candidate.is_file():
        load_environment_file(str(candidate), override=False)


if __name__ == "__main__":
    bootstrap()
