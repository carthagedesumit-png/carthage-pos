# CBOS Security

## HTTP Security Headers

CBOS applies configurable headers to API and dashboard responses:

- `X-Content-Type-Options`: default `nosniff`
- `X-Frame-Options`: default `DENY`
- `Referrer-Policy`: default `same-origin`
- `Content-Security-Policy`: default self-hosted policy for scripts, styles,
  images, fonts, connections, frame ancestors, base URI, and form actions

Override with:

- `POS_CONTENT_TYPE_OPTIONS`
- `POS_FRAME_OPTIONS`
- `POS_REFERRER_POLICY`
- `POS_CONTENT_SECURITY_POLICY`

## Sessions

API bearer sessions are persisted as SHA-256 token hashes. Tokens have:

- absolute expiry from `POS_API_SESSION_HOURS`
- idle expiry from `POS_SESSION_IDLE_MINUTES`
- revocation through `POST /api/v1/auth/logout`

If responses set cookies, middleware adds `HttpOnly`, configured
`SameSite`, and `Secure` when `POS_SECURE_COOKIES=true`.

## CSRF

Dashboard CSRF protection is optional because current dashboard forms are
read-only GET filters. Enable it with:

```powershell
$env:POS_DASHBOARD_CSRF="true"
```

Mutating dashboard requests must then include an `X-CSRF-Token` header or
`csrf_token` query value matching the `cbos_csrf` cookie. Dashboard API routes
continue to use bearer/API protection.

## Authentication Rate Limiting

Failed login attempts are rate-limited by client address for
`POST /api/v1/auth/login`.

Configuration:

- `POS_AUTH_RATE_LIMIT_ENABLED`
- `POS_AUTH_RATE_LIMIT_ATTEMPTS`
- `POS_AUTH_RATE_LIMIT_WINDOW_SECONDS`

Successful logins do not consume the failed-attempt budget.

## Audit Logging

Authentication, user administration, store administration, backup activity,
deployment events, hardware operations, and sales/procurement mutations emit
structured application events. Sensitive fields such as passwords, password
hashes, secrets, tokens, and authorization values are redacted before logging.

Each HTTP response includes `X-Request-ID`. Supplying `X-Request-ID` on a
request preserves the operator-provided value and attaches it to request logs.

## Operator Checklist

- Keep `POS_LICENSE_ENFORCEMENT=true` in packaged production installs.
- Set `POS_STRICT_STARTUP_VALIDATION=true` for beta and production services.
- Keep API traffic behind TLS when accessed beyond localhost.
- Restrict backup, log, license, activation, and database directories to the
  CBOS service account and administrators.
- Rotate operator passwords before external beta deployment.
- Keep issuer private keys outside CBOS runtime systems.
