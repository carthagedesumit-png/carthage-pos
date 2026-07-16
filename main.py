import os
import sys
from pathlib import Path

import uvicorn

from app.database.db_manager import initialize_database, seed_initial_data
from app.ui.terminal_ui import run_pos_terminal
from app.core.config import get_config, load_environment_file
from auth import AuthenticationSystem


def bootstrap():
    try:
        load_deployment_environment()
    except RuntimeError as exc:
        print(f"[CRITICAL] {exc}", file=sys.stderr)
        if getattr(sys, "frozen", False) and os.name == "nt":
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, str(exc), "CBOS Startup Failed", 0x10)
            except Exception:
                pass
        raise SystemExit(1) from exc
    initialize_database()
    if get_config().deployment.seed_sample_data:
        seed_initial_data()

    if getattr(sys, "frozen", False):
        run_packaged_server()
        return

    auth = AuthenticationSystem()
    if auth.login():
        print("Booting Carthage Systems POS Terminal Engine...")
        print("\n--- System Status: Online & Secure ---")
        run_pos_terminal(session=auth.session)
    else:
        print("\n[CRITICAL] System access denied. Shutting down.")


def run_packaged_server():
    """Run the installed API and dashboard without console interaction."""
    from app.api.app import create_app

    from app.deployment.startup_service import release_instance,schedule_browser,startup_plan
    config = get_config();runtime=os.environ.get('POS_RUNTIME_DIRECTORY') or Path(config.deployment.log_directory).parent
    fallback=int(os.environ.get('POS_API_FALLBACK_PORT','0') or 0) or None
    plan=startup_plan(config.api.host,config.api.port,fallback_port=fallback,runtime_directory=runtime)
    browser=os.environ.get('POS_BROWSER_AUTO_LAUNCH','true').lower() in {'1','true','yes','on'}
    delay=float(os.environ.get('POS_BROWSER_STARTUP_DELAY','1.5'));timeout=float(os.environ.get('POS_STARTUP_TIMEOUT','30'))
    print(f"[STARTUP] CBOS endpoint: {plan['url']} (timeout {timeout:.0f}s)")
    if not plan['start']:
        schedule_browser(plan['url'],browser,0);return
    schedule_browser(plan['url'],browser,delay)
    try:uvicorn.run(create_app(initialize=False),host=config.api.host,port=plan['port'],log_level=config.deployment.log_level.lower())
    except Exception as exc:
        print(f"[CRITICAL] CBOS startup failed: {exc}",file=sys.stderr);raise
    finally:release_instance(plan['lock_path'])


def load_deployment_environment():
    """Load installer-generated settings before opening the production database."""
    explicit = os.environ.get("CARTHAGE_POS_ENV_FILE")
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    candidates = [Path(explicit).expanduser()] if explicit else [base / "config" / "carthage-pos.env"]
    program_data = os.environ.get("PROGRAMDATA")
    if program_data:
        candidates.append(Path(program_data) / "Carthage POS" / "config" / "carthage-pos.env")
    for candidate in candidates:
        if candidate.is_file():
            load_environment_file(str(candidate), override=getattr(sys, "frozen", False))
            return candidate
    if getattr(sys, "frozen", False):
        searched = ", ".join(str(path) for path in candidates)
        raise RuntimeError(f"Installer configuration was not found. Searched: {searched}")
    return None


if __name__ == "__main__":
    bootstrap()
