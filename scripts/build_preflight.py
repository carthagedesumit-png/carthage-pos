"""Read-only CBOS source preflight. This command never builds release artifacts."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.version import APP_VERSION, DATABASE_SCHEMA_VERSION, INSTALLER_VERSION
from app.deployment.runtime_assets import validate_runtime_assets
from scripts.validate_release import commits_match, resolve_commit_reference


PROHIBITED_TRACKED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pyc", ".log", ".env"}
SECRET_PATTERN = re.compile(
    r"(?i)(password|secret|token|private[_-]?key)\s*[:=]\s*['\"]([^'\"]{8,})['\"]"
)


def discover_iscc(explicit_path: str | Path | None = None) -> Path | None:
    """Locate Inno Setup without compiling an installer or searching the disk."""
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path).expanduser())
    on_path = shutil.which("ISCC.exe") or shutil.which("iscc")
    if on_path:
        candidates.append(Path(on_path))
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        program_files = os.environ.get(variable)
        if program_files:
            candidates.append(Path(program_files) / "Inno Setup 6" / "ISCC.exe")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _git(*args: str, root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=15)


def run_preflight(root: str | Path = ROOT, *, release_dir: str | Path | None = None,
                  test_evidence: str | Path | None = None, expected_branch: str | None = None,
                  expected_commit: str | None = None,
                  iscc_path: str | Path | None = None) -> dict:
    base = Path(root).resolve()
    checks, warnings = [], []
    head = _git("rev-parse", "--short=12", "HEAD", root=base)
    def resolve(reference: str) -> str | None:
        return resolve_commit_reference(
            reference, base, runner=lambda args, git_root: _git(*args, root=git_root)
        )

    full_commit = resolve("HEAD")
    branch = _git("branch", "--show-current", root=base)
    status = _git("status", "--porcelain", "--untracked-files=all", root=base)
    commit = head.stdout.strip() if head.returncode == 0 else None
    checks.append(_check("git_checkout", (
        head.returncode == branch.returncode == status.returncode == 0 and bool(full_commit)
    ),
                         commit=commit, branch=branch.stdout.strip()))
    if expected_branch:
        checks.append(_check("expected_branch", branch.stdout.strip() == expected_branch))
    if expected_commit:
        resolved_expected = resolve(expected_commit)
        checks.append(_check("expected_commit", commits_match(resolved_expected, full_commit),
                             commit=full_commit))
    checkout_clean = status.returncode == 0 and not status.stdout.strip()
    checks.append(_check("clean_working_tree", checkout_clean))
    checks.append(_check("version_consistency", APP_VERSION == INSTALLER_VERSION,
                         application_version=APP_VERSION, schema_version=DATABASE_SCHEMA_VERSION))
    if checkout_clean and full_commit:
        warnings.append({"name": "source_commit", "status": "resolved", "commit": full_commit,
                         "display_commit": commit})
    else:
        warnings.append({"name": "source_commit", "status": "pending-version-promotion-commit"})
    assets = validate_runtime_assets(base)
    checks.append(_check("runtime_asset_manifest", assets["valid"], details=assets["checks"]))

    compilation_errors = []
    for path in sorted([*base.glob("*.py"), *base.glob("app/**/*.py"), *base.glob("tests/**/*.py")]):
        try:
            compile(path.read_text(encoding="utf-8-sig"), path.as_posix(), "exec")
        except (OSError, SyntaxError, UnicodeError) as exc:
            compilation_errors.append({"path": path.relative_to(base).as_posix(), "error": type(exc).__name__})
    checks.append(_check("source_compilation", not compilation_errors, errors=compilation_errors))

    tracked = _git("ls-files", root=base)
    tracked_paths = tracked.stdout.splitlines() if tracked.returncode == 0 else []
    prohibited = [path for path in tracked_paths if Path(path).suffix.lower() in PROHIBITED_TRACKED_SUFFIXES]
    checks.append(_check("prohibited_tracked_artifacts", tracked.returncode == 0 and not prohibited,
                         paths=prohibited))
    secret_hits = []
    for relative in tracked_paths:
        path = base / relative
        if Path(relative).parts[0] in {"tests", "docs"} or relative in {
            "README.md", "scripts/verify_packaged_upgrade.py",
        }:
            continue
        if not path.is_file() or path.suffix.lower() not in {".py", ".ps1", ".iss", ".md", ".json", ".txt"}:
            continue
        try:
            for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
                match = SECRET_PATTERN.search(line)
                if match and not any(marker in match.group(2).casefold() for marker in (
                    "placeholder", "example", "change-me", "not-a-secret",
                )):
                    secret_hits.append(f"{relative}:{number}")
        except (OSError, UnicodeError):
            pass
    checks.append(_check("secret_scan", not secret_hits, matches=secret_hits))

    git_version = _git("--version", root=base)
    checks.append(_check("required_build_tools", git_version.returncode == 0,
                         python=sys.version.split()[0], git=git_version.stdout.strip()))
    pyinstaller = importlib.util.find_spec("PyInstaller")
    if pyinstaller is None:
        warnings.append({"name": "pyinstaller", "status": "optional-tool-missing"})
    else:
        version = subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--version"], cwd=base,
            capture_output=True, text=True, timeout=15,
        )
        warnings.append({"name": "pyinstaller", "status": "available",
                         "version": version.stdout.strip() or "unknown"})
    iscc = discover_iscc(iscc_path)
    warnings.append({"name": "inno_setup", "status": "available" if iscc else "optional-tool-missing",
                     **({"path": str(iscc)} if iscc else {})})

    if release_dir:
        destination = Path(release_dir).resolve()
        safe = destination != base and base in destination.parents and not destination.exists()
        checks.append(_check("release_directory_safe", safe, path="<release-directory>"))

    evidence_valid = False
    if test_evidence:
        try:
            evidence = json.loads(Path(test_evidence).read_text(encoding="utf-8"))
            evidence_valid = (
                commits_match(evidence.get("source_commit"), full_commit)
                and evidence.get("application_version") == APP_VERSION
                and evidence.get("status") == "passed"
                and int(evidence.get("test_total", 0)) > 0
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            evidence_valid = False
    checks.append(_check("canonical_tests_same_commit", evidence_valid))
    warnings.extend([
        {"name": "executable_build", "status": "pending"},
        {"name": "installer_build", "status": "pending"},
        {"name": "local_windows_acceptance", "status": "physically-unverified"},
        {"name": "clean_pc_acceptance", "status": "physically-unverified"},
        {"name": "peripheral_acceptance", "status": "physically-unverified"},
        {"name": "pilot_go_live_approval", "status": "not-run"},
    ])
    return {"valid": all(item["passed"] for item in checks), "build_performed": False,
            "checks": checks, "warnings": warnings}


def _check(name: str, passed: bool, **details) -> dict:
    return {"name": name, "passed": bool(passed), **details}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--release-dir")
    parser.add_argument("--test-evidence")
    parser.add_argument("--expected-branch")
    parser.add_argument("--expected-commit")
    parser.add_argument("--iscc")
    args = parser.parse_args(argv)
    result = run_preflight(
        args.root, release_dir=args.release_dir, test_evidence=args.test_evidence,
        expected_branch=args.expected_branch, expected_commit=args.expected_commit,
        iscc_path=args.iscc,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
