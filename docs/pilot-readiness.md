# Controlled pilot data, training, and go-live readiness

This RC is **not production ready**. Clean-PC installation and real scanner, receipt-printer, and cash-drawer acceptance remain physically unverified. Nothing in the software may substitute for signed evidence.

## Onboarding and roles

An administrator records each persisted onboarding step as completed, pending, warning, blocked, or physically unverified. Opening a page does not update it. Evidence references must be short register IDs, never credentials or filesystem paths. Required readiness checks include company/country/currency, active pilot store, active administrator, manager and cashier assignments, forced-password-change resolution, catalogue approval, reconciled opening stock, branding, backup and isolated restore rehearsal, licensing, training, peripherals, critical defects, and matching release evidence. Cashiers cannot import or establish opening stock. Use normal user creation and password policy; never plan or export passwords.

Danger checks: no active administrator; disabled store; inactive manager; cashier without an active home store; unexpected privilege/role; and unresolved forced password change. Existing authentication and session-revocation controls remain authoritative.

## CSV control

Templates in `docs/pilot-data/` are UTF-8 and fictional. Limits are 2 MiB, 5,000 data rows, 255 characters per field, strict CSV syntax, and UTF-8 encoding. Validation is write-free except for a short-lived normalized validation record and audit event; raw uploads are not retained. Errors identify row, field, code, and safe message. A separate confirmation token is required to atomically apply a validated batch and is single-use. Existing SKU/barcode records are never silently updated.

Product imports reference existing active categories and suppliers. Create categories and suppliers first through their existing authorized screens/services; supplier CSV is a preparation template, not an automatic importer. Decimal input is parsed exactly before conversion to the existing database representation. Spreadsheet formula prefixes are escaped in generated CSV. Never place passwords, keys, payment credentials, sessions, or customer data in these files.

Opening stock is store-specific and only applies to a zero balance. Zero is recorded in the immutable opening-stock evidence without creating a no-op stock movement. Positive quantities create an authoritative `ADJUSTMENT` movement labelled `OPENING_STOCK`, plus batch/line reconciliation evidence. The total quantity and decimal value must be reviewed before confirmation. Purchases, transfers, later adjustments, sales, and returns retain their existing distinct workflows. A failed row rolls back the entire batch.

## Isolated training plan

Use a disposable training database supplied by an explicit absolute `CARTHAGE_POS_DB` path under a newly created training directory, with licensing and authentication unchanged. Label screenshots and documents `TRAINING — NOT LIVE`. Never point training at an operational database, installed instance, ProgramData, or production backup directory. Training data cannot enter operational reports because it is a separate database process.

Exercises and evidence: administrator setup (active account/forced change); manager operations (allowed and denied actions); cashier login; search/barcode scan; cash, card/POS, transfer, and supported split sale; receipt/reprint; refund; cash-session open/close; stock receipt/adjustment; low-stock report; sales/payment/inventory/finance reports; backup and isolated restore; restart/cart recovery; and scanner/printer/drawer failure. For each, record expected result, actual result, timestamp, role/store, redacted screenshot or audit ID, and defect reference. Do not bypass authentication, roles, licensing, stock, or payment controls.

No automated training reset is provided: path ambiguity makes destructive reset inappropriate for this RC. Close CBOS, verify the absolute disposable training directory and evidence backup with two operators, then archive or delete that specifically identified directory using the operating system. Never use an environment variable or wildcard as a deletion target.

## Backup, rollback, support, and daily review

Before go-live: create a backup through the existing service, verify its metadata/integrity, restore only to a new temporary isolated directory, open and validate the restored copy, and record the evidence ID, responsible person, retention decision, and measured duration. Never overwrite the active database during rehearsal. No recovery-time guarantee is claimed.

Stop sale and consider rollback for database/migration failure, authentication or authorization failure, financial imbalance/duplicate transaction, stock corruption, payment-result uncertainty, or critical printing failure where a compliant receipt is mandatory. Restore the last verified pre-go-live backup only under the documented restore procedure. High severity materially blocks a core workflow; medium has a safe workaround; low is cosmetic. Critical defects block go-live.

Diagnostics must contain timestamps, app/schema version, redacted request/audit IDs, operator role, store code, reproduction steps, expected/actual, workaround, status, and owner. Never collect passwords, hashes, tokens, payment secrets, unrestricted paths, or unnecessary personal data. Escalate critical/high issues to pilot owner, technical owner, security/finance owner as applicable; only the pilot owner authorizes resumption.

Daily review: verify login/session controls, opening/closing cash reconciliation, payment/refund totals, stock exceptions, backup result, audit exceptions, peripheral status, unresolved defects, operator feedback, and next-day stop/go decision. The authoritative gate remains blocked until database compatibility, users/store, license policy, writable backup, successful restore rehearsal, catalogue, stock reconciliation, training, zero critical defects, physical clean-PC/peripherals, and build evidence are all accepted. Assessment records readiness only; it never deploys or activates a pilot.
