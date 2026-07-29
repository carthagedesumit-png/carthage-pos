"""Self-contained, read-only installer upgrade credential preflight."""

import argparse
import json
import os
import sys
from pathlib import Path


EXIT_CODES = {
    "ok": 0, "username_missing": 10, "password_missing": 11,
    "configuration_missing": 12, "database_missing": 13,
    "user_not_found": 14, "inactive": 15, "locked": 16,
    "bcrypt_mismatch": 17, "not_administrator": 18,
    "runtime_failure": 19,
}


def _load_installed_environment():
    runtime = Path(os.environ.get("PROGRAMDATA", "")) / "Carthage POS"
    state_path = runtime / "config" / "deployment.json"
    if not state_path.is_file():
        raise FileNotFoundError("configuration_missing")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    config_path = Path(state.get("configuration_file") or runtime / "config" / "carthage-pos.env")
    from app.core.config import parse_environment_file
    environment = parse_environment_file(str(config_path))
    os.environ.update(environment)
    return state_path


def _consume(path):
    password_path = Path(path)
    try:
        password = password_path.read_bytes().decode("utf-8-sig").rstrip("\r\n")
    finally:
        password_path.unlink(missing_ok=True)
    if not password or "\x00" in password:
        raise ValueError("password_missing")
    return password


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("verify-upgrade-credentials", nargs="?")
    parser.add_argument("--install-dir", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password-file", required=True)
    args = parser.parse_args(argv)
    result = {"status": "runtime_failure"}
    try:
        _load_installed_environment()
        password = _consume(args.password_file)
        from app.deployment.installer_service import classify_upgrade_credentials
        result = classify_upgrade_credentials(args.install_dir, args.username, password)
    except FileNotFoundError:
        result = {"status": "configuration_missing"}
    except ValueError:
        result = {"status": "password_missing"}
    except Exception:
        result = {"status": "runtime_failure"}
    print(json.dumps(result, sort_keys=True))
    return EXIT_CODES.get(result["status"], EXIT_CODES["runtime_failure"])


if __name__ == "__main__":
    raise SystemExit(main())
