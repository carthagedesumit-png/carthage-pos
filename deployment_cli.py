"""Command-line entry point packaged as the Windows deployment executable."""

import argparse
import json
from dataclasses import replace
from pathlib import Path

from app.deployment.installer_service import (
    fresh_install, repair_installation, uninstall_installation, upgrade_installation,
)
from app.deployment.verification_service import verify_installation
from app.deployment.wizard import SetupWizard


def main(argv=None):
    parser = argparse.ArgumentParser(description="Carthage POS deployment manager")
    subparsers = parser.add_subparsers(dest="command", required=True)
    install = subparsers.add_parser("install", help="Run the interactive setup wizard")
    install.add_argument("--install-dir")
    configure = subparsers.add_parser("configure", help="Install fresh or upgrade an existing deployment")
    configure.add_argument("--install-dir", required=True)
    for command in ("upgrade", "repair", "verify"):
        child = subparsers.add_parser(command)
        child.add_argument("--install-dir", required=True)
    uninstall = subparsers.add_parser("uninstall")
    uninstall.add_argument("--install-dir", required=True)
    uninstall.add_argument("--remove-data", action="store_true")
    uninstall.add_argument("--confirmation")
    args = parser.parse_args(argv)
    if args.command == "install":
        request = SetupWizard().collect()
        if args.install_dir:
            request = replace(request, installation_directory=args.install_dir).validated()
        result = fresh_install(request)
    elif args.command == "configure":
        state_path = Path(args.install_dir) / "config" / "deployment.json"
        if state_path.is_file():
            result = upgrade_installation(args.install_dir)
        else:
            request = replace(
                SetupWizard().collect(), installation_directory=args.install_dir
            ).validated()
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
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
