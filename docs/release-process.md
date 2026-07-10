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
