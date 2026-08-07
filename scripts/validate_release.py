"""Validate CBOS release artifacts and generate acceptance evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.version import APP_VERSION, DATABASE_SCHEMA_VERSION, INSTALLER_VERSION, parse_version
from app.deployment.release_manifest import (
    load_release_manifest,
    validate_release_manifest,
    write_release_manifest,
)
from app.deployment.runtime_assets import (
    REQUIRED_RUNTIME_FILES,
    REQUIRED_RUNTIME_MODULES,
    RUNTIME_DATA_DIRECTORIES,
)


PRODUCT_NAME = "Carthage Business Operating System"
REQUIRED_SOURCE_ASSETS = REQUIRED_RUNTIME_FILES + tuple(
    Path(module.replace(".", "/") + ".py") for module in REQUIRED_RUNTIME_MODULES
)
PACKAGED_DATA_DIRECTORIES = RUNTIME_DATA_DIRECTORIES
PROHIBITED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".env", ".pyc", ".log"}
PROHIBITED_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".coverage", ".env"}
EVIDENCE_FILES = {
    "artifact-inventory.json",
    "build-validation.json",
    "checksums.txt",
    "release-manifest.json",
    "release-evidence.json",
}


def expected_release_directory(version: str = APP_VERSION) -> str:
    return f"CBOS-{version}"


def expected_installer_filename(version: str = APP_VERSION) -> str:
    return f"CBOS-Setup-{version}.exe"


def authoritative_version() -> str:
    return APP_VERSION


FULL_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")


def normalize_full_commit(value: object) -> str | None:
    """Return a normalized full object ID; abbreviated and malformed IDs fail closed."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    return normalized if FULL_COMMIT_PATTERN.fullmatch(normalized) else None


def resolve_commit_reference(
    reference: str,
    root: str | Path = REPO_ROOT,
    *,
    runner: Callable[[tuple[str, ...], Path], subprocess.CompletedProcess] | None = None,
) -> str | None:
    """Resolve a ref to one exact commit without invoking a command shell."""
    if not isinstance(reference, str) or not reference.strip():
        return None
    arguments = ("rev-parse", "--verify", "--end-of-options", f"{reference.strip()}^{{commit}}")
    try:
        if runner is None:
            completed = subprocess.run(
                ["git", *arguments], cwd=Path(root), check=False,
                capture_output=True, text=True, timeout=10,
            )
        else:
            completed = runner(arguments, Path(root))
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return normalize_full_commit(completed.stdout)


def source_commit(root: str | Path = REPO_ROOT) -> str | None:
    return resolve_commit_reference("HEAD", root)


def commits_match(left: str | None, right: str | None) -> bool:
    """Compare normalized full commit IDs without repository-dependent abbreviation rules."""
    normalized_left = normalize_full_commit(left)
    normalized_right = normalize_full_commit(right)
    return bool(normalized_left and normalized_left == normalized_right)


def working_tree_clean(root: str | Path = REPO_ROOT) -> bool:
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"], cwd=Path(root), check=True,
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return not completed.stdout.strip()


def validate_evidence_identity(evidence: dict, *, expected_commit: str | None = None,
                               installer_path: str | Path | None = None) -> dict:
    checks = [
        {"name": "evidence_version", "passed": evidence.get("version") == APP_VERSION},
        {"name": "evidence_source_commit", "passed": commits_match(
            evidence.get("source_commit"), expected_commit
        )},
    ]
    if installer_path is not None:
        installer = Path(installer_path)
        recorded = evidence.get("installer") or {}
        checks.extend([
            {"name": "evidence_installer_filename", "passed": installer.name == expected_installer_filename() and recorded.get("filename") == installer.name},
            {"name": "evidence_installer_checksum", "passed": installer.is_file() and bool(recorded.get("sha256")) and recorded.get("sha256") == sha256_file(installer)},
        ])
    return {"valid": all(item["passed"] for item in checks), "checks": checks}


def numeric_windows_version(version: str = APP_VERSION) -> tuple[int, int, int, int]:
    major, minor, patch, _rank, prerelease = parse_version(version)
    return major, minor, patch, prerelease


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact_inventory(release_dir: str | Path) -> list[dict]:
    root = Path(release_dir)
    if not root.exists():
        return []
    entries = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        entries.append(
            {
                "path": relative,
                "name": path.name,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return entries


def prohibited_release_files(release_dir: str | Path) -> list[str]:
    root = Path(release_dir)
    if not root.exists():
        return []
    prohibited = []
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if any(part in PROHIBITED_NAMES for part in path.parts):
            prohibited.append(relative)
        elif path.is_file() and path.suffix.lower() in PROHIBITED_SUFFIXES:
            prohibited.append(relative)
        elif path.is_file() and path.name.lower().startswith("test_"):
            prohibited.append(relative)
    return sorted(set(prohibited))


def source_asset_checks(root: str | Path = REPO_ROOT) -> list[dict]:
    base = Path(root)
    checks = []
    for relative in REQUIRED_SOURCE_ASSETS:
        path = base / relative
        checks.append(
            {
                "name": relative.as_posix(),
                "exists": path.exists(),
                "contains_files": path.is_file() or (
                    any(item.is_file() for item in path.rglob("*")) if path.exists() else False
                ),
            }
        )
    return checks


def packaged_asset_checks(release_dir: str | Path) -> list[dict]:
    root = Path(release_dir)
    candidates = [
        root,
        root / "_internal",
        root / "CarthagePOS",
        root / "CarthagePOS" / "_internal",
    ]
    checks = []
    for relative in PACKAGED_DATA_DIRECTORIES:
        matches = [candidate / relative for candidate in candidates if (candidate / relative).exists()]
        checks.append(
            {
                "name": relative.as_posix(),
                "exists": bool(matches),
                "contains_files": any(any(item.is_file() for item in match.rglob("*")) for match in matches),
                "locations": [str(match.relative_to(root)) for match in matches],
            }
        )
    return checks


def validate_checksums(release_dir: str | Path, checksums_file: str | Path | None = None) -> dict:
    root = Path(release_dir)
    checksum_path = Path(checksums_file) if checksums_file else root / "checksums.txt"
    if not checksum_path.is_file():
        return {"valid": False, "checks": [{"name": "checksums_file", "passed": False}]}
    checks = []
    for raw in checksum_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        digest, filename = line.split(maxsplit=1)
        artifact = root / filename
        checks.append(
            {
                "name": filename,
                "passed": artifact.is_file() and sha256_file(artifact) == digest.lower(),
            }
        )
    return {"valid": bool(checks) and all(item["passed"] for item in checks), "checks": checks}


def validate_release_artifacts(
    release_dir: str | Path,
    *,
    require_executables: bool = True,
    require_installer: bool = False,
) -> dict:
    root = Path(release_dir)
    inventory = artifact_inventory(root)
    names = {item["name"] for item in inventory}
    manifest_path = root / "release-manifest.json"
    manifest = load_release_manifest(manifest_path) if manifest_path.is_file() else {}
    manifest_validation = validate_release_manifest(manifest) if manifest else {"valid": False, "checks": []}
    checkout_commit = source_commit()
    source_assets = source_asset_checks()
    packaged_assets = packaged_asset_checks(root)
    checks = [
        {"name": "release_directory_exists", "passed": root.is_dir()},
        {"name": "release_directory_name", "passed": root.name == expected_release_directory()},
        {"name": "authoritative_application_version", "passed": APP_VERSION == INSTALLER_VERSION},
        {"name": "manifest_exists", "passed": manifest_path.is_file()},
        {"name": "manifest_valid", "passed": bool(manifest_validation["valid"])},
        {"name": "source_commit_matches", "passed": (
            bool(checkout_commit) and commits_match(manifest.get("source_commit"), checkout_commit)
        )},
        {"name": "source_assets_available", "passed": all(item["exists"] and item["contains_files"] for item in source_assets)},
        {"name": "no_prohibited_files", "passed": not prohibited_release_files(root)},
    ]
    if require_executables:
        checks.append({"name": "application_executable_exists", "passed": "CarthagePOS.exe" in names})
        checks.append({"name": "deployment_executable_exists", "passed": "CarthagePOSDeployment.exe" in names})
        checks.append(
            {
                "name": "packaged_assets_available",
                "passed": all(item["exists"] and item["contains_files"] for item in packaged_assets),
            }
        )
    if require_installer:
        installers = [
            item for item in inventory
            if item["name"].endswith(".exe") and "Setup" in item["name"]
        ]
        checks.append({
            "name": "installer_exists",
            "passed": any(item["name"] == expected_installer_filename() and
                          (root / item["path"]).is_file() and item.get("size", 0) > 0
                          for item in installers),
        })
    checksum_result = validate_checksums(root)
    checksum_applicable = require_executables or any(
        item["name"] not in EVIDENCE_FILES for item in inventory
    )
    if not checksum_applicable:
        checksum_result = {"valid": True, "status": "not-run", "checks": []}
    checks.append({
        "name": "checksums_valid",
        "passed": checksum_result["valid"],
    })
    return {
        "valid": all(item["passed"] for item in checks),
        "version": APP_VERSION,
        "database_schema_version": DATABASE_SCHEMA_VERSION,
        "checks": checks,
        "manifest_validation": manifest_validation,
        "checksum_validation": checksum_result,
        "inventory": inventory,
        "prohibited_files": prohibited_release_files(root),
        "source_assets": source_assets,
        "packaged_assets": packaged_assets,
    }


def write_checksums(release_dir: str | Path, files: list[Path] | None = None) -> Path:
    root = Path(release_dir)
    selected = files or [Path(item["path"]) for item in artifact_inventory(root) if item["name"] not in EVIDENCE_FILES]
    lines = []
    for relative in sorted(selected, key=lambda item: item.as_posix()):
        artifact = root / relative
        if artifact.is_file():
            lines.append(f"{sha256_file(artifact)}  {relative.as_posix()}")
    destination = root / "checksums.txt"
    destination.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return destination


def generate_release_evidence(
    release_dir: str | Path,
    evidence_dir: str | Path | None = None,
    *,
    source_commit: str | None = None,
    require_executables: bool = False,
    require_installer: bool = False,
) -> dict:
    root = Path(release_dir)
    evidence_root = Path(evidence_dir) if evidence_dir else root
    root.mkdir(parents=True, exist_ok=True)
    evidence_root.mkdir(parents=True, exist_ok=True)
    package_paths = [root / item["path"] for item in artifact_inventory(root) if item["name"] not in EVIDENCE_FILES]
    checkout_commit = globals()["source_commit"]()
    clean = working_tree_clean()
    artifact_evidence = require_executables or require_installer
    requested_commit = None
    if source_commit is not None:
        requested_commit = resolve_commit_reference(source_commit)
    elif clean:
        requested_commit = checkout_commit
    if not clean or not checkout_commit or not requested_commit:
        raise ValueError("Persisted release evidence requires an exact clean current checkout commit.")
    if artifact_evidence and (not clean or not checkout_commit or not commits_match(requested_commit, checkout_commit)):
        raise ValueError("Artifact evidence requires the exact clean current checkout commit.")
    if source_commit is not None and (
        not clean or not checkout_commit or not commits_match(requested_commit, checkout_commit)
    ):
        raise ValueError("Finalized evidence source commit must match the clean current checkout exactly.")
    manifest = write_release_manifest(
        root / "release-manifest.json",
        channel="rc",
        source_commit=requested_commit,
        resolve_source_commit=requested_commit is not None,
        package_paths=package_paths,
    )
    write_checksums(root)
    validation = validate_release_artifacts(
        root,
        require_executables=require_executables,
        require_installer=require_installer,
    )
    inventory = artifact_inventory(root)
    evidence = {
        "product": PRODUCT_NAME,
        "version": APP_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "build_type": "installer" if require_installer else (
            "package" if require_executables else "source-only"
        ),
        "source_commit": requested_commit,
        "schema_version": DATABASE_SCHEMA_VERSION,
        "gate_status": {
            "source_finalized": "passed",
            "source_validation": "passed" if validation["valid"] else "failed",
            "version_promotion_commit": "created" if requested_commit else "pending",
            "package_validation": "passed" if require_executables and validation["valid"] else "not-run",
            "installer_validation": "passed" if require_installer and validation["valid"] else "not-run",
            "executable_build": "complete" if require_executables and validation["valid"] else "pending",
            "installer_build": "complete" if require_installer and validation["valid"] else "pending",
            "local_windows_acceptance": "physically-unverified",
            "clean_pc_acceptance": "physically-unverified",
            "peripheral_acceptance": "physically-unverified",
            "pilot_go_live_approval": "not-run",
        },
        "installer": None,
        "release_directory": "<isolated-release-directory>",
        "release_manifest": manifest,
        "validation": validation,
    }
    _write_json(evidence_root / "artifact-inventory.json", inventory)
    _write_json(evidence_root / "build-validation.json", validation)
    _write_json(evidence_root / "release-evidence.json", evidence)
    if evidence_root != root:
        (evidence_root / "checksums.txt").write_text((root / "checksums.txt").read_text(encoding="utf-8"), encoding="utf-8")
        _write_json(evidence_root / "release-manifest.json", manifest)
    return evidence


def write_pyinstaller_version_file(destination: str | Path, version: str = APP_VERSION) -> Path:
    major, minor, patch, prerelease = numeric_windows_version(version)
    content = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, {prerelease}),
    prodvers=({major}, {minor}, {patch}, {prerelease}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'Carthage Systems'),
         StringStruct(u'FileDescription', u'Carthage Business Operating System'),
         StringStruct(u'FileVersion', u'{version}'),
         StringStruct(u'InternalName', u'CarthagePOS'),
         StringStruct(u'LegalCopyright', u'Copyright Carthage Systems'),
         StringStruct(u'OriginalFilename', u'CarthagePOS.exe'),
         StringStruct(u'ProductName', u'Carthage Business Operating System'),
         StringStruct(u'ProductVersion', u'{version}')])
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate CBOS release artifacts.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("version")
    version_file = subparsers.add_parser("pyinstaller-version-file")
    version_file.add_argument("destination")
    validate = subparsers.add_parser("validate")
    validate.add_argument("--release-dir", required=True)
    validate.add_argument("--require-executables", action="store_true")
    validate.add_argument("--require-installer", action="store_true")
    evidence = subparsers.add_parser("evidence")
    evidence.add_argument("--release-dir", required=True)
    evidence.add_argument("--evidence-dir")
    evidence.add_argument("--source-commit")
    evidence.add_argument("--require-executables", action="store_true")
    evidence.add_argument("--require-installer", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "version":
        print(authoritative_version())
        return 0
    if args.command == "pyinstaller-version-file":
        print(write_pyinstaller_version_file(args.destination))
        return 0
    if args.command == "validate":
        result = validate_release_artifacts(
            args.release_dir,
            require_executables=args.require_executables,
            require_installer=args.require_installer,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["valid"] else 1
    if args.command == "evidence":
        result = generate_release_evidence(
            args.release_dir,
            args.evidence_dir,
            source_commit=args.source_commit,
            require_executables=args.require_executables,
            require_installer=args.require_installer,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["validation"]["valid"] else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
