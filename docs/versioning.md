# CBOS Versioning

## Authoritative Source

Application, API, installer, migration, and database schema versions are defined
in `app/core/version.py`. Release scripts, installer metadata, startup logs,
health output, dashboard administration information, and release manifests must
read from this source.

## Semantic Versioning Policy

CBOS uses `MAJOR.MINOR.PATCH` for stable releases and
`MAJOR.MINOR.PATCH-rc.N` for release candidates.

- `MAJOR`: incompatible data, installer, API, or operational contract changes.
- `MINOR`: backward-compatible product capability or workflow additions.
- `PATCH`: backward-compatible fixes, hardening, documentation, or packaging
  updates.
- `rc.N`: release-candidate build number for acceptance testing before a stable
  release. RC versions sort before the matching stable release.

Database schema compatibility is tracked separately with
`DATABASE_SCHEMA_VERSION`, `MIN_SUPPORTED_DATABASE_VERSION`, and
`compatibility_report()`.

## Release Channels

- `stable`: production-ready public release.
- `pilot`: controlled customer pilot release.
- `beta`: broader external beta.
- `rc`: release-candidate build validation.
- `development`: internal development builds.

Every distributable build must include a machine-readable release manifest.
