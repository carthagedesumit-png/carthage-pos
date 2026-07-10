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

## Rollback

If upgrade validation fails, restore the rollback snapshot or verified backup.
Never overwrite the only copy of a customer database.
