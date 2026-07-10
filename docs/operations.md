# CBOS Operations

## Production Deployment

For external beta or production services:

1. Generate installer configuration with database, backup, log, license, and
   activation directories outside the application code directory.
2. Set `POS_STRICT_STARTUP_VALIDATION=true`.
3. Enable licensing enforcement for packaged installs when applicable.
4. Run database migrations with application startup or installer repair.
5. Confirm `/health/live` and `/health/ready` before exposing traffic.

## Health Endpoints

- `GET /health`: backward-compatible basic health response.
- `GET /health/live`: process liveness and version metadata.
- `GET /health/ready`: readiness checks for database connectivity, schema
  compatibility, startup configuration, writable paths, and deployment status.

Readiness returns `503` when a required check fails.

## Backup Procedure

Manual backups use the existing backup service and API:

```http
POST /api/v1/backups
Authorization: Bearer <admin-or-manager-token>

{"name":"end-of-day","backup_type":"FULL","compression":true}
```

Backups are timestamped, checksummed, and described by sidecar metadata. When
`POS_BACKUP_VERIFY_AFTER_CREATE=true`, CBOS verifies each new artifact before
retention removes older backups.

Retention settings:

- `POS_BACKUP_RETENTION_DAYS`
- `POS_BACKUP_MAX_COUNT`
- `POS_BACKUP_OVERWRITE`

## Restore Procedure

1. List backups with `GET /api/v1/backups`.
2. Verify the selected backup with `POST /api/v1/backups/verify`.
3. Dry-run restore with `POST /api/v1/backups/restore` and `dry_run=true`.
4. Confirm restore with `RESTORE:<backup-id>`.
5. Preserve the automatic pre-restore backup until reconciliation is complete.

Restore validation checks artifact existence, SHA-256 checksum, SQLite
integrity, required tables, schema compatibility, and application major-version
compatibility.

## Troubleshooting

- Readiness fails on `database_connectivity`: verify `CARTHAGE_POS_DB`, file
  permissions, and SQLite accessibility.
- Readiness fails on `schema_compatibility`: run installer repair or application
  startup migrations.
- Readiness reports configuration warnings in source runs: set explicit runtime
  directories or enable strict validation to reproduce production behavior.
- Backup verification fails: keep the failed artifact isolated, check disk
  health, and create a fresh backup before deleting older verified backups.
- Authentication is rate-limited: wait for
  `POS_AUTH_RATE_LIMIT_WINDOW_SECONDS` or verify credential automation is not
  retrying stale passwords.

## Operational Checklist

- `/health/live` returns `200`.
- `/health/ready` returns `200`.
- Backup directory is writable and protected.
- A manual backup can be created and verified.
- Restore dry run passes for the latest backup.
- Logs include request IDs and contain no secrets.
- Dashboard renders with security headers.
- API login, logout, idle timeout, and rate limiting behave as expected.
- Installer repair succeeds on a staging machine.
