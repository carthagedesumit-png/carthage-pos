# CBOS Release Process

## Release Manifest

Generate release metadata with `app.deployment.release_manifest`.

The manifest includes:

- application version
- release channel
- build timestamp
- source commit identifier when available
- supported database schema range
- supported upgrade path
- installer/package checksum metadata
- compatibility report

The manifest is suitable for deployment verification and future update checks.

## RC Build

Build v1.0 release candidates with:

```powershell
.\scripts\build_rc.ps1
```

The command derives `1.0.0-rc.2` from `app.core.version`, generates
PyInstaller version metadata, validates whitespace, runs the unit suite,
packages required dashboard assets, writes checksums, creates
`release-manifest.json`, and emits a release evidence bundle. The Inno Setup
installer is only considered complete when the compiler runs successfully.

Detailed build and validation instructions are in `docs/rc-build.md`.

## Release Checklist

Each release must carry an auditable checklist with explicit status values:

- `pending`
- `passed`
- `failed`
- `waived`

Required checks:

- code and tests
- security configuration
- database migrations
- backup and restore
- installer build
- clean install
- upgrade install
- rollback
- documentation
- licensing readiness
- known issues
- release notes
- pilot approval
- final sign-off

## V1.0 Pilot Gate

GitHub Actions provides the automatic pre-merge source gate for pull requests
to `main` and `feature/reporting-engine`. It runs the full automated suite,
tracked-file hygiene checks, source-only release manifest/checksum validation,
and whitespace validation on Windows with Python 3.14. CI uses read-only
repository permissions and does not build, sign, upload, publish, or deploy a
release. Installer production and clean second-PC Windows acceptance remain
manual release gates.

Before pilot deployment:

1. Full test suite passes.
2. `git diff --check` passes.
3. Release manifest validates against `app.core.version`.
4. Upgrade rehearsal succeeds on a copied database.
5. Failed-upgrade rehearsal proves original data is unchanged.
6. Clean-machine installation acceptance checklist is complete.
7. Backup create, verify, dry-run restore, and rollback checks pass.
8. Known issues and pilot limitations are published.
9. Customer pilot owner signs the go-live checklist.

Windows clean-install, business smoke, upgrade, and rollback acceptance are
documented in `docs/windows-acceptance.md`.
