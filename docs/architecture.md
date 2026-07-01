# Carthage POS Architecture

## Overview

Carthage POS is a layered Python application backed by SQLite. Terminal and
future UI/API adapters call service functions; services enforce authorization
and business rules; database modules own connections, schema migration, and
transaction boundaries. Reporting and document generation are read-oriented
consumers of persisted business records.

Dependencies flow inward:

1. `app/ui` adapts user interaction to service calls.
2. Domain services in `app/sales`, `app/inventory`, `app/procurement`, and
   `app/stores` coordinate business operations.
3. Shared policy and infrastructure live in `app/core` and `app/database`.
4. `app/reports` and `app/documents` query completed records without owning
   sales, procurement, or inventory mutations.

## Module Responsibilities

- `auth.py`: authentication, session revalidation, roles, and store access.
- `app/core/config.py`: validated immutable process configuration.
- `app/core/exceptions.py`: stable application exception taxonomy.
- `app/core/validation.py`: reusable input normalization and validation.
- `app/core/logging_utils.py`: namespaced structured operational events.
- `app/database/db_manager.py`: connection creation and idempotent migrations.
- `app/database/transactions.py`: explicit atomic write transactions.
- `app/inventory`: catalog, branch inventory, and stock movement audit records.
- `app/sales`: totals, payment, sale, return, and stock coordination.
- `app/procurement`: suppliers, purchase orders, receipts, and costing.
- `app/stores`: stores, user assignment, and inter-store transfers.
- `app/reports`: refund-aware analytics and inventory valuation.
- `app/documents`: side-effect-free business document assembly and rendering.

## Service Interactions

Every public write service follows the same sequence:

1. Revalidate the caller session and store scope.
2. Normalize and validate input before mutation where possible.
3. Open one `transaction()` for the complete business operation.
4. Write the primary record, dependent records, inventory balances, and audit
   rows using the same connection.
5. Commit once, then emit a sanitized structured log event.
6. Return the established dictionary-based service contract.

Exceptions raised inside a transaction trigger rollback and propagate. Domain
validation exceptions inherit from `ValueError`, preserving legacy callers,
while also inheriting from `ApplicationError` for newer integrations.

## Migration Strategy

Schema changes are idempotent functions in `app/database/db_manager.py` and run
through `initialize_database()`. A migration must preserve historical records,
use additive changes where possible, backfill deterministic values, and be
covered by a legacy-schema test. Never perform schema migration from a domain
service. This hardening milestone requires no database migration.

## Configuration

Read settings through `get_config()` rather than accessing environment variables
inside domain services. Configuration is immutable and cached. Tests or process
bootstrap code that changes environment values must call `reset_config_cache()`.
Defaults preserve prior behavior when no variables are configured.

## Logging

Use a logger from `get_logger()` and emit stable event names with `log_event()`.
Do not log passwords, hashes, tokens, payment credentials, or full generated
documents. Applications configure handlers and serialization at their entry
point; library modules never call `basicConfig()`.

## Coding Conventions

- Keep SQL parameterized; interpolate only locally controlled column names.
- Use one transaction per multi-step write operation.
- Keep authorization at every public mutation boundary.
- Raise the narrowest application exception that describes the domain failure.
- Preserve public function inputs and dictionary return shapes unless a versioned
  API explicitly replaces them.
- Put reusable validation in `app/core/validation.py` and retain domain-specific
  state checks in their owning service.
- Add migrations only for persisted schema changes, never for code-only refactors.
- Add focused tests for success, validation, authorization, and rollback paths.
