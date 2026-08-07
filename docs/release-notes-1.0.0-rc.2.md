# CBOS 1.0.0-rc.2 Release Notes

RC2 consolidates the work reviewed since RC1: installed authentication and application-access repairs; payment, tender, refund, and cash-reconciliation hardening; the peripheral and pilot-readiness foundation; controlled pilot-data setup and go-live preparation; migration/upgrade consolidation; and authoritative runtime-asset and build-preflight checks.

Supported upgrades are limited to the reviewed schema range in the release manifest. Automated rehearsals cover the reconstructable core/multi-store and payment-era fixtures and current schema-1 compatibility. RC1 remains the historical predecessor; the stable installer `AppId` is unchanged, so RC2 is an in-place upgrade rather than a separate product. No schema change is introduced by this version promotion.

Known warnings and limitations: external payment gateways and banking settlement are not verified; offline card/transfer reference formats may repeat and require operational review. Executables and the installer are not yet built. Local Windows, clean-PC, printer, scanner, cash-drawer, peripheral, and named human pilot go-live acceptance remain pending. This release candidate does not claim production deployment, customer use, hardware certification, or physical acceptance.

Source finalization and source validation are separate from the version-promotion commit and all artifact/physical gates. Until the promotion is committed, `source_commit` and installer checksum, size, build time, and acceptance results remain unresolved.
