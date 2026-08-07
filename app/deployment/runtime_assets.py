"""Authoritative runtime assets and deterministic PyInstaller arguments."""

import argparse
import json
from pathlib import Path


RUNTIME_DATA_DIRECTORIES = (
    Path("app/dashboard/templates"),
    Path("app/dashboard/static"),
)
REQUIRED_RUNTIME_FILES = (
    Path("app/dashboard/templates/pilot_readiness.html"),
    Path("app/dashboard/static/css/dashboard.css"),
    Path("app/dashboard/static/js/dashboard.js"),
)
REQUIRED_RUNTIME_MODULES = (
    "app.operations.pilot_data_service",
)


def validate_runtime_assets(root: str | Path) -> dict:
    base = Path(root)
    checks = [
        {"path": path.as_posix(), "exists": (base / path).is_file()}
        for path in REQUIRED_RUNTIME_FILES
    ]
    checks.extend(
        {
            "path": module.replace(".", "/") + ".py",
            "exists": (base / (module.replace(".", "/") + ".py")).is_file(),
        }
        for module in REQUIRED_RUNTIME_MODULES
    )
    return {"valid": all(item["exists"] for item in checks), "checks": checks}


def pyinstaller_arguments(root: str | Path) -> list[str]:
    """Return build arguments only after every authoritative asset is present."""
    base = Path(root).resolve()
    validation = validate_runtime_assets(base)
    if not validation["valid"]:
        missing = ", ".join(item["path"] for item in validation["checks"] if not item["exists"])
        raise FileNotFoundError(f"Required runtime assets are missing: {missing}")
    arguments: list[str] = []
    for relative in RUNTIME_DATA_DIRECTORIES:
        arguments.extend(("--add-data", f"{(base / relative).resolve()};{relative.as_posix()}"))
    for module in REQUIRED_RUNTIME_MODULES:
        arguments.extend(("--hidden-import", module))
    return arguments


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--format", choices=("json",), default="json")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(pyinstaller_arguments(args.root)))
    except FileNotFoundError as exc:
        print(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
