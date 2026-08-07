# CBOS Upgrade Guide

## Supported Upgrade Path

CBOS v1.0 supports upgrades from databases whose schema version is within the
range reported by `compatibility_report()` and the release manifest.

## Rehearsal

Run upgrade rehearsal against a copy before changing a live installation:

1. Copy the customer database to a staging location.
2. Validate current `PRAGMA user_version`.
3. Create a pre-upgrade backup copy.
4. Run the existing `initialize_database()` migrations against the copy.
5. Validate schema version and SQLite integrity.
6. Simulate failure and confirm the source database remains unchanged.

The helper `app.deployment.upgrade_rehearsal.rehearse_database_upgrade()` is the
deterministic implementation used by tests.

## Live Upgrade

Use the installer/deployment lifecycle rather than direct database scripts:

1. Confirm latest verified backup.
2. Confirm release manifest compatibility.
3. Run installer upgrade.
4. Confirm deployment health.
5. Confirm `/health/ready`.
6. Confirm dashboard and API startup.
7. Retain rollback backup until customer acceptance is complete.

## Repair

Use repair when configuration files or Windows integration metadata are missing
but the business database is intact. Repair recreates missing runtime files,
runs idempotent migrations, and keeps a rollback snapshot.

## Supported generated rehearsal states

The canonical test fixtures are built by `tests/upgrade_fixture_builder.py`; no
business database or binary fixture is stored. Operational rehearsal support is
limited to two reconstructable repository milestones: `core_multistore_68db2de`,
whose explicit DDL follows commit `68db2de`, and `payments_fd5c947`, whose payment,
refund, tender, and hardware DDL follows commit `fd5c947`. The builder records the
evidence beside the SQL and never creates today's schema and deletes tables.
`pre_deployment_settings` is a bootstrap/configuration compatibility case, not an
advertised historical business-database upgrade path. Earlier database shapes are
unsupported unless their DDL can be reconstructed and reviewed reliably.

Each operational fixture is fictional, minimal, deterministic, generated during
tests, and has `PRAGMA user_version=0`; the target remains schema 1. A database
newer than schema 1 fails closed and must be opened by a compatible newer CBOS
release. Do not change `PRAGMA user_version` to bypass this guard.

Upgrade rehearsal uses the backup service to create and verify a pre-upgrade
snapshot, migrates a copied working database twice, and uses
`restore_backup_copy()` to restore the verified pre-upgrade bytes to a new,
non-active destination without migration or overwrite. Tests compare independent
pre-upgrade/restored invariants and upgraded invariants, run `integrity_check`,
and reject corrupt backups and existing restore destinations. Never rehearse on
the installed active database. Recovery-time and recovery-point guarantees
require separate measurement and are not implied by this procedure.

## Rollback

If upgrade validation fails, restore the rollback snapshot or verified backup.
Never overwrite the only copy of a customer database.
