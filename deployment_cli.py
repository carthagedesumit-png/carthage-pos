"""Command-line entry point packaged as the Windows deployment executable."""

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from app.core.exceptions import InstallationError
from app.deployment.installer_service import (
    fresh_install, repair_installation, uninstall_installation, upgrade_installation,
)
from app.deployment.models import SetupRequest
from app.deployment.verification_service import verify_installation
from app.deployment.wizard import SetupWizard


NONINTERACTIVE_SETUP_FIELDS = {
    "business_name": "Business name",
    "store_name": "Store name",
    "administrator_username": "Administrator username",
    "administrator_password": "Administrator password",
    "administrator_full_name": "Administrator full name",
    "database_path": "Database path",
    "backup_directory": "Backup path",
    "currency": "Currency",
    "tax_rate": "Tax rate",
    "timezone": "Timezone",
    "deployment_type": "Deployment type",
    "printer_preference": "Receipt printer",
}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Carthage POS deployment manager")
    subparsers = parser.add_subparsers(dest="command", required=True)
    install = subparsers.add_parser("install", help="Run the interactive setup wizard")
    install.add_argument("--install-dir")
    configure = subparsers.add_parser("configure", help="Install fresh or upgrade an existing deployment")
    configure.add_argument("--install-dir", required=True)
    _add_noninteractive_setup_arguments(configure)
    for command in ("upgrade", "repair", "verify"):
        child = subparsers.add_parser(command)
        child.add_argument("--install-dir", required=True)
    uninstall = subparsers.add_parser("uninstall")
    uninstall.add_argument("--install-dir", required=True)
    uninstall.add_argument("--remove-data", action="store_true")
    uninstall.add_argument("--confirmation")
    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            request = SetupWizard().collect()
            if args.install_dir:
                request = replace(request, installation_directory=args.install_dir).validated()
            result = fresh_install(request)
        elif args.command == "configure":
            state_path = _deployment_state_path(args)
            if state_path.is_file():
                result = upgrade_installation(args.install_dir)
            else:
                request = _setup_request_from_args(args)
                result = fresh_install(request)
        elif args.command == "upgrade":
            result = upgrade_installation(args.install_dir)
        elif args.command == "repair":
            result = repair_installation(args.install_dir)
        elif args.command == "verify":
            result = verify_installation(args.install_dir)
        else:
            result = uninstall_installation(
                args.install_dir, remove_data=args.remove_data, confirmation=args.confirmation
            )
    except Exception as exc:
        _report_failure(exc)
        return 1
    print(json.dumps(result, indent=2, default=str))
    print("CBOS deployment completed successfully.")
    return 0


def _add_noninteractive_setup_arguments(parser):
    parser.add_argument("--business-name")
    parser.add_argument("--store-name")
    parser.add_argument("--admin-username", dest="administrator_username")
    password = parser.add_mutually_exclusive_group()
    password.add_argument("--admin-password", dest="administrator_password")
    password.add_argument("--admin-password-file", dest="administrator_password_file")
    parser.add_argument("--admin-full-name", dest="administrator_full_name")
    parser.add_argument("--config-dir", dest="configuration_directory")
    parser.add_argument("--database-path")
    parser.add_argument("--backup-path", dest="backup_directory")
    parser.add_argument("--currency")
    parser.add_argument("--tax-rate", type=float)
    parser.add_argument("--timezone")
    parser.add_argument("--deployment-type")
    parser.add_argument("--receipt-printer", dest="printer_preference")


def _setup_request_from_args(args):
    if getattr(args, "administrator_password_file", None):
        args.administrator_password = _consume_password_file(args.administrator_password_file)
    provided = {
        name for name in NONINTERACTIVE_SETUP_FIELDS
        if getattr(args, name, None) not in (None, "")
    }
    if provided:
        missing = [
            label for name, label in NONINTERACTIVE_SETUP_FIELDS.items()
            if getattr(args, name, None) in (None, "")
        ]
        if missing:
            raise InstallationError(
                "Noninteractive deployment is missing required values: "
                + ", ".join(missing)
            )
        return SetupRequest(
            business_name=args.business_name,
            store_name=args.store_name,
            administrator_username=args.administrator_username,
            administrator_password=args.administrator_password,
            administrator_full_name=args.administrator_full_name,
            installation_directory=args.install_dir,
            configuration_directory=args.configuration_directory,
            database_path=args.database_path,
            backup_directory=args.backup_directory,
            printer_preference=args.printer_preference,
            currency=args.currency,
            tax_rate=args.tax_rate,
            timezone=args.timezone,
            deployment_type=args.deployment_type,
        ).validated()
    if not sys.stdin.isatty():
        raise InstallationError(
            "Noninteractive deployment requires explicit setup arguments. "
            "Run install for interactive setup or pass all configure options."
        )
    return replace(SetupWizard().collect(), installation_directory=args.install_dir).validated()


def _consume_password_file(path):
    password_path = Path(path)
    try:
        password = password_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InstallationError("Administrator password input could not be read.") from exc
    finally:
        try:
            password_path.unlink(missing_ok=True)
        except OSError:
            pass
    if not password.strip():
        raise InstallationError("Administrator password input is empty.")
    return password


def _deployment_state_path(args):
    if getattr(args, "configuration_directory", None):
        return Path(args.configuration_directory) / "deployment.json"
    program_data = os.environ.get("PROGRAMDATA")
    if program_data:
        candidate = Path(program_data) / "Carthage POS" / "config" / "deployment.json"
        if candidate.is_file():
            return candidate
    return Path(args.install_dir) / "config" / "deployment.json"


def _report_failure(exc):
    message = f"CBOS deployment failed: {exc}"
    print(message, file=sys.stderr)
    if getattr(sys, "frozen", False) and os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "CBOS Deployment Failed", 0x10)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
