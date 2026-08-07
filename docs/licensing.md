# Licensing and Product Editions

## Architecture

Licensing is offline first. The installed application creates an activation
request containing the human-readable license key, customer metadata, a nonce,
and only hashed machine identifiers. A separate issuer signs the activation
response with RSA-SHA256 PKCS#1 v1.5. The POS verifies that response using a
2048-bit-or-stronger public key and never needs the private key.

Production issuer private keys must live in an access-controlled signing service
or hardware security module. They must never be copied into this repository,
installer, application configuration, logs, backups, or customer machines. The
private key under `tests/fixtures` is explicitly test-only and cannot be used for
production licenses.

Signed license files are installed atomically under `POS_LICENSE_DIRECTORY`.
Replacement archives the previous document; deactivation archives the active
document and emits a portable deactivation request. Licensing audits contain
event metadata but omit license keys, signatures, machine identifiers, tokens,
and passwords.

## Product Editions

| Edition | Capabilities | Limits |
| --- | --- | --- |
| Community | Core POS and reporting | 1 store, 3 users |
| Professional | Multi-store, API, CRM, hardware, backup, barcode, documents, reports, transfers | 10 stores, 50 users |
| Enterprise | All production features, including procurement and cloud-sync foundation | Unlimited stores/users |
| Developer | All features and development tools | Unlimited; explicit non-production mode only |

Feature names and limits are defined centrally in `app/licensing/editions.py`.
API middleware enforces API/feature access, while user and store services enforce
resource limits. Expired licenses enter a configurable grace period and then
read-only mode. Authentication and licensing recovery endpoints remain usable.

## Offline Activation

1. An administrator calls `POST /api/v1/licensing/export-request` or
   `export_activation_request()` and transfers the generated request file to the
   vendor using an approved channel.
2. The vendor validates entitlement and activation count, then uses the isolated
   issuer workflow to create a signed response bound to the request identifiers.
3. The administrator transfers the response to the POS and calls
   `POST /api/v1/licensing/activate` or `import_activation_response()`.
4. The POS verifies the signature, edition, type, application compatibility,
   activation count, expiration, and machine binding before atomic installation.
5. Replacement, renewal, and deactivation use the same administration boundary
   and preserve local audit history.

Multiple hashed identifiers allow a configurable match threshold so a minor
hardware change does not immediately invalidate a legitimate installation.
Lower thresholds improve tolerance; higher thresholds strengthen binding.

## License Types and Lifecycle

Supported types are Trial, Professional, Enterprise, Developer,
Offline Perpetual, and Subscription. Trial and subscription documents require
an expiration. Local evaluation state detects significant clock rollback.
`POS_LICENSE_EVALUATION_DAYS` and `POS_LICENSE_GRACE_PERIOD_DAYS` control the
evaluation and grace windows. Subscription renewal currently exports a request;
future online activation implements the existing `ActivationProvider` contract.

## Configuration

- `POS_LICENSE_DIRECTORY`: private runtime license state directory.
- `POS_LICENSE_FILE`: active signed license document.
- `POS_ACTIVATION_DIRECTORY`: portable request/response working directory.
- `POS_LICENSE_PUBLIC_KEY_FILE`: vendor public verification key.
- `POS_LICENSE_GRACE_PERIOD_DAYS`: post-expiration grace window.
- `POS_LICENSE_EVALUATION_DAYS`: local evaluation duration.
- `POS_LICENSE_DEFAULT_EDITION`: restricted fallback edition.
- `POS_LICENSE_TRIAL_EDITION`: capabilities during evaluation.
- `POS_LICENSE_DEVELOPER_MODE`: explicit non-production override.
- `POS_LICENSE_ENFORCEMENT`: centralized enforcement switch.
- `POS_LICENSE_FINGERPRINT_MIN_MATCHES`: stable identifier match threshold.

Installer deployments enable enforcement. Source checkouts default it off to
preserve existing development and test workflows. Release engineering must
provision the production public key at the configured path before distributing
commercial activation responses.

## Upgrade and Deployment

Licensing adds no database tables or migration. Upgrades preserve the license
directory and active signed document. A normal uninstall should preserve
business and license state; customer-approved clean removal may delete it
according to deployment policy. Never place license state in a publicly served
folder.

For edition upgrades, issue a newly signed response and import it as a
replacement. The application validates the new document before archiving the
old one, providing rollback-safe local replacement without rewriting business
records.

## Provider Interface

`app/licensing/providers.py` defines a replaceable license status provider
interface and a local development/test provider. Future commercial providers
should implement the same sanitized status contract and feed status into the
existing licensing service layer. Authentication and authorization remain
separate from licensing.
