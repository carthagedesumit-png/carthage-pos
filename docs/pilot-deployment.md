# CBOS Pilot Deployment

## Pilot Scope

The v1.0 pilot validates installation, store setup, inventory setup, checkout,
receipts, reports, backup, restore readiness, and support handoff. It does not
promise unfinished commercial workflows or live licensing-server integration.

## Deployment Flow

1. Complete site assessment.
2. Confirm hardware, operating system, printer, scanner, and network readiness.
3. Choose database, backup, log, license, and activation directories.
4. Run clean installation.
5. Create the administrator account.
6. Confirm `/health/live` and `/health/ready`.
7. Confirm dashboard and API startup.
8. Import or create initial products and stock.
9. Complete a test sale and receipt.
10. Create and verify a backup.
11. Record pilot feedback and incidents.

## Customer Handoff

Provide the customer with:

- administrator credentials handoff procedure
- backup location and retention settings
- support contact and escalation details
- known issues and pilot limitations
- go-live checklist result
- post-deployment verification result

Checklists live under `docs/pilot-checklists/`.
