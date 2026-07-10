# Carthage Business Operating System

Carthage Business Operating System (CBOS) with an enterprise-grade supermarket
POS module for inventory management and sales tracking.

## Release Candidate Preparation

CBOS is in the Release Candidate Preparation phase for external beta
deployment. The current hardening pass focuses on stability, dashboard
consistency, framework compatibility, friendly error handling, masked
configuration exposure, and regression-free quality checks rather than new
business modules.

## Version 1.0 Production Foundation

The production-readiness foundation adds operational controls without changing
business workflows: security headers, request IDs, optional dashboard CSRF
validation, failed-login rate limiting, API session idle timeout, startup
configuration diagnostics, liveness/readiness endpoints, and documented backup
and restore procedures.

## Features

- Terminal-based cashier login and checkout flow
- SQLite inventory, sales, and sale item storage
- bcrypt password hashing for POS users
- Database-backed admin, manager, and cashier authorization
- Cashier-aware sales records
- Refund-aware sales, payment, product, and inventory reports
- Foreign-key enforcement for database integrity
- Stock validation before cart add and checkout commit
- Unit tests backed by isolated temporary databases
- Versioned FastAPI integration layer with OpenAPI documentation
- Adapter-based receipt printer, cash drawer, scanner, and customer display support
- Multi-format product identifiers, reusable labels, previews, and audited label printing
- Verified database backups, rollback-safe restore, retention, scheduling, and portable exports
- Windows setup, upgrade, repair, deployment verification, and offline update staging
- Offline-first signed licensing, activation, product editions, and feature policy

## First-run setup

Create at least one POS user by setting an environment variable before the first login:

```powershell
$env:CARTHAGE_POS_ADMIN_PASSWORD="choose-a-strong-password"
python main.py
```

Optional cashier account:

```powershell
$env:CARTHAGE_POS_CASHIER_PASSWORD="choose-a-strong-password"
python main.py
```

The application stores password hashes in the SQLite database. Do not commit `.env` files, runtime databases, or local IDE settings.

Only the first administrator can be created through the bootstrap environment variable. After bootstrap, user management requires an active administrator session. Inventory changes and returns require an administrator or manager; cashier checkout always uses the catalog price.

## Run tests

```powershell
python -m unittest discover -s tests
```

## Run the API

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.api.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for the interactive API reference. See
[`docs/api.md`](docs/api.md) for authentication, endpoint groups, examples, and
the error contract.

Operational endpoints:

- `GET /health`
- `GET /health/live`
- `GET /health/ready`

The browser dashboard is available under `/dashboard` when the API app is
running. Dashboard, Sales, Inventory, CRM, Procurement, Reports, and
Administration workspaces provide read-only management filters, pagination,
detail pages, lightweight JSON endpoints, consistent navigation highlighting,
and safe empty-state behavior. Settings and Logout are present as placeholders
for the beta navigation shell. See [`docs/dashboard.md`](docs/dashboard.md).

Hardware configuration and mock-device testing are documented in
[`docs/hardware.md`](docs/hardware.md).
Barcode formats, label templates, configuration, and printing workflows are in
[`docs/barcodes.md`](docs/barcodes.md).
Backup operations and the disaster recovery checklist are documented in
[`docs/backup.md`](docs/backup.md).
Windows installation, upgrade, repair, uninstall, and release-build instructions
are documented in [`docs/installation.md`](docs/installation.md).
Commercial licensing, offline activation, edition capabilities, and secure key
deployment are documented in [`docs/licensing.md`](docs/licensing.md).
Production security controls are documented in [`docs/security.md`](docs/security.md).
Deployment, health checks, backup, restore, troubleshooting, and the operator
checklist are documented in [`docs/operations.md`](docs/operations.md).

## Build the Windows installer

Install `requirements-build.txt` and Inno Setup 6, then run:

```powershell
python -m pip install -r requirements-build.txt
.\installer\build.ps1
```

The build produces packaged application/deployment executables and an Inno
Setup installer. Release signing is performed outside this repository.
