# Backup, Restore and Disaster Recovery

## Strategy

Backups use SQLite's online backup API, producing a transactionally consistent
snapshot while the POS remains available. Each artifact has a separate JSON
manifest containing its ID, UTC timestamp, application/database versions,
size, SHA-256 checksum, initiating user, type, compression state, and storage
filename. A non-sensitive JSONL operational audit is stored beside manifests.

`FULL` creates a full snapshot. `INCREMENTAL` currently creates a full baseline
with a link to the previous backup; this establishes chain metadata without
claiming page-delta recovery. Future incremental engines can replace this
strategy while retaining manifests and verification contracts.

ZIP compression uses the Python standard library. Uncompressed SQLite files
remain supported. Local folders, external drives, and mounted network paths use
the same configured directory contract. API callers never submit filesystem
paths.

## Configuration

```powershell
$env:POS_BACKUP_DIRECTORY="D:\CarthagePOS\Backups"
$env:POS_BACKUP_RETENTION_DAYS="30"
$env:POS_BACKUP_MAX_COUNT="30"
$env:POS_BACKUP_COMPRESSION="true"
$env:POS_BACKUP_OVERWRITE="false"
$env:POS_BACKUP_AUTO_BEFORE_RESTORE="true"
$env:POS_BACKUP_VERIFY_AFTER_CREATE="true"
$env:POS_BACKUP_SCHEDULE="DAILY" # MANUAL, DAILY, WEEKLY, MONTHLY
```

Retention removes expired or excess artifacts only after a new backup verifies.
Named backup replacement is disabled by default. When enabled, the old named
artifact is retained until the replacement has been created and verified.

The scheduler is an in-process policy foundation, not an operating-system task.
Call `run_scheduled_backup()` from a future application timer or worker. It is
idempotent before the calculated due time and records its last/next run state.

## Restore Workflow

1. Select a backup or request the latest manifest.
2. Run dry-run restore validation.
3. Review checksum, SQLite integrity, required tables, and version checks.
4. Submit the exact `RESTORE:<backup-id>` confirmation as an administrator.
5. The service materializes and validates a staging database.
6. If configured, it creates a verified backup of the live database.
7. SQLite WAL is checkpointed and the database is replaced atomically.
8. Migrations run against the restored database.
9. Any replacement or migration failure restores the original database file.

Restore may invalidate API sessions created after the selected backup. Operators
should log in again and verify store, inventory, recent sales, and reports.

## Portable Export and Import

Products, customers, suppliers, stores, and store inventory support JSON and
CSV. Imports are admin-only and transactional. Inventory imports create audited
adjustment movements and synchronize compatibility totals. Configuration and
report metadata use JSON; imported configuration is staged for operator review
because environment/deployment settings must not be silently rewritten by an
API request.

Exports intentionally exclude passwords, authentication tokens, payment
credentials, and customer transaction/payment history. Full database backups
remain the authoritative disaster-recovery mechanism.

## Disaster Recovery Checklist

1. Keep at least one backup copy off the POS machine.
2. Restrict backup folder permissions to the POS service and administrators.
3. Verify backups after creation and test restore in an isolated environment.
4. Monitor free space, failed jobs, retention, and the JSONL audit.
5. Record application version and deployment configuration with release notes.
6. Before production restore, stop other POS/API processes using the database.
7. Perform a dry run and confirm the selected store/date/business state.
8. Restore, log in again, reconcile inventory and recent receipts, then reopen.
9. Preserve the automatic pre-restore backup until reconciliation completes.

## Permissions

- Cashier: no backup access.
- Manager: create, list, inspect, verify, export, and trigger due schedules.
- Admin: all manager operations plus restore, delete, import, and scheduler edits.

Run `python -m unittest tests.test_backup -v` without physical hardware or an
external scheduler. Tests use isolated temporary databases and backup folders.
