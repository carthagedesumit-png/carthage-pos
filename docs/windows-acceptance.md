# Windows Acceptance

## Scope

Windows acceptance proves the CBOS v1.0 RC can be installed, started,
validated, upgraded, backed up, restored, and rolled back without losing
business data. It is a release gate for controlled pilot deployment.

## Preflight

Run artifact validation before installing:

```powershell
.\scripts\windows_acceptance.ps1 -ReleaseDir .\release\CBOS-1.0.0-rc.2 -SkipHttpChecks
```

After CBOS is running locally, repeat without `-SkipHttpChecks` to validate
`/health/live` and `/health/ready`.

## Clean Install

1. Install from the signed setup artifact, or run the packaged executable set
   in a clean test directory when installer tooling is unavailable.
2. Confirm application, config, log, backup, license, and activation
   directories exist.
3. Confirm generated configuration does not contain a default administrator
   password.
4. Bootstrap an administrator with a strong operator-provided password.
5. Start CBOS and confirm `/health/live`, `/health/ready`, dashboard, and API
   access.
6. Confirm displayed version, release manifest version, and artifact manifest
   version all match `app.core.version.APP_VERSION`.
7. Stop and restart CBOS, then confirm readiness again.

## Pilot Business Smoke

Use supported services, API routes, or dashboard workflows:

1. Create or confirm a store.
2. Create a product.
3. Receive stock into inventory.
4. Complete a sale.
5. Save or print a receipt through the configured output path.
6. Run a sales or inventory report.
7. Create and verify a backup.
8. Restart CBOS.
9. Confirm product, stock, sale, receipt/report evidence, and backup metadata
   persisted.

## Upgrade Acceptance

1. Start from a supported previous-version database fixture or generated
   baseline.
2. Copy the database before upgrade rehearsal.
3. Create a pre-upgrade backup and verify its checksum.
4. Run the upgrade rehearsal against the copy.
5. Install or stage the RC build over the previous application files.
6. Confirm schema compatibility, data integrity, preserved configuration, and
   preserved backup directory.
7. Confirm app version, installer version, and release manifest version match.
8. Confirm `/health/ready` after the upgrade.

## Failed Upgrade And Rollback

1. Rehearse a simulated failed upgrade on a database copy.
2. Verify the original database bytes are unchanged.
3. Verify rollback backup integrity before restore.
4. Restore from the rollback backup.
5. Start CBOS and confirm readiness, dashboard access, and representative data.
6. Attach diagnostic logs to the release evidence bundle without exposing
   secrets, license keys, tokens, passwords, or local absolute paths.

## Evidence Bundle

Each RC acceptance run should retain:

- full test summary
- `git diff --check` result
- artifact inventory
- SHA-256 checksums
- release manifest
- build validation summary
- clean-install checklist
- pilot smoke checklist
- upgrade checklist
- rollback checklist
- known issues
- release notes
- signoff checklist
