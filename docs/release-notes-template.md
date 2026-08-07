# CBOS Release Notes Template

## Release

- Version:
- Channel:
- Build timestamp:
- Source commit:
- Release manifest:

## Completed Capabilities

- Core POS, inventory, sales, CRM, procurement, reports, dashboard, backup,
  deployment, licensing foundation, health, and operational hardening.

## Pilot Limitations

- Dashboard browser authentication is not final.
- Dashboard write actions remain read-only where marked.
- CSV, Excel, PDF, and print actions in Reports are placeholders.
- Live commercial license server integration is deferred.

## Operational Prerequisites

- Verified backup directory.
- Strict startup validation for production.
- Healthy readiness endpoint.
- Signed installer/package when externally distributed.

## Dependency Warnings

- Python 3.14 currently emits a FastAPI dependency deprecation warning for
  `asyncio.iscoroutinefunction`; this is from installed framework code and is
  tracked as a dependency upgrade item.
