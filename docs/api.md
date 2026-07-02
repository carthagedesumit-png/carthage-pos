# Carthage POS REST API

## Start the API

Install dependencies and initialize at least one administrator as described in
the project README. Start the API from the repository root:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.api.app:app --host 127.0.0.1 --port 8000
```

Interactive OpenAPI documentation is available at `http://127.0.0.1:8000/docs`,
ReDoc at `/redoc`, and the machine-readable schema at `/openapi.json`. Production
deployments should terminate TLS at a trusted reverse proxy and must not expose
the development server directly to the public internet.

## Authentication

Log in with existing POS credentials. Roles and store scope are loaded from the
database; clients cannot supply or override them.

```http
POST /api/v1/auth/login
Content-Type: application/json

{"username":"manager1","password":"secret","store_id":1}
```

The response contains a bearer token. Only its SHA-256 hash is persisted.

```http
Authorization: Bearer <access_token>
```

Use `GET /api/v1/auth/me` to inspect the current identity,
`POST /api/v1/auth/switch-store` to select another authorized store, and
`POST /api/v1/auth/logout` to revoke the token. Sessions expire after
`POS_API_SESSION_HOURS` hours, which defaults to 12.

## Common Examples

Create a customer:

```http
POST /api/v1/customers
Authorization: Bearer <token>
Content-Type: application/json

{"first_name":"Ada","last_name":"Lovelace","phone_number":"+234800000001"}
```

Create a guest cash sale:

```http
POST /api/v1/sales
Authorization: Bearer <token>
Content-Type: application/json

{
  "items":[{"product_id":1,"quantity":2}],
  "payment_method":"CASH",
  "amount_paid":50
}
```

Generate an 80mm plain-text receipt:

```http
GET /api/v1/documents/receipts/1?format=text&width_mm=80
Authorization: Bearer <token>
```

List endpoints accept `page` and `per_page` where applicable. Store-aware
reports accept repeated filters such as `?store_id=1&store_id=2`.

## Endpoint Groups

- `authentication`, `users`: login, logout, identity, user administration.
- `stores`: store search, lifecycle, and active session store context.
- `products`, `inventory`: catalog search, product management, stock operations.
- `sales`, `returns`: checkout, history, partial returns, and full refunds.
- `suppliers`, `procurement`: suppliers, purchase orders, receiving, documents.
- `transfers`: request, approve, dispatch, receive, cancel, and audit documents.
- `customers`, `loyalty`, `wallet`, `credit`: CRM and financial ledgers.
- `reports`: sales, inventory, branch, cashier, customer, wallet, credit, loyalty.
- `documents`: receipt, invoice, credit note, PO, GRN, and transfer output.
- `hardware`: status, printer diagnostics/jobs, cash drawer, scanner, and display.

Document endpoints support `format=json`, `format=text`, and `format=html`.
Thermal receipts and credit notes support `width_mm=58` or `width_mm=80`.

## Error Model

Errors use one envelope and never include tracebacks or credentials:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": []
  }
}
```

- `400`: malformed or invalid input.
- `401`: missing, invalid, expired, or revoked bearer session.
- `403`: authenticated user lacks role or store access.
- `404`: requested business record does not exist.
- `409`: duplicate or conflicting data.
- `500`: unexpected failure with sanitized client output.

## Architecture

Routes are transport adapters. They validate request shapes, resolve bearer and
store context, invoke existing service functions, paginate returned collections,
and translate exceptions. Business rules and transaction management remain in
the domain services. API sessions are the only API-specific persisted model.
