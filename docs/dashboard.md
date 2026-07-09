# Dashboard

The browser dashboard lives under `/dashboard` and is a management surface for
owners, managers, and administrators. It reuses domain services for sales,
documents, reports, inventory, and platform health rather than duplicating
business rules in route handlers.

## Sales Workspace

`GET /dashboard/sales` renders the Sales Workspace V1 management page. It is a
read-only review portal, not a cashier checkout screen.

The page includes:

- Summary cards for net sales, transactions, refunds, and discounts.
- A recent sales table with receipt number, date/time, customer fallback, store,
  cashier, tender type, gross amount, discount, refund total, net amount, and
  status.
- Filter controls that preserve selected query parameters.
- Empty-state handling when no sales match.
- Previous and next pagination links.
- A view action for the sale detail and receipt preview page.

Supported query parameters:

- `date_from`
- `date_to`
- `store_id`
- `cashier_id`
- `customer_id`
- `payment_method`
- `search`
- `refunded` with `all`, `refunded`, or `non-refunded`
- `page`
- `page_size`

`GET /dashboard/sales/{sale_id}` renders a read-only detail page with the sale
header, line items, customer information where available, payment breakdown,
refund summary, and a plain-text receipt preview generated through
`app.documents.document_service.generate_sales_receipt`.

## Sales JSON Endpoints

The dashboard exposes lightweight JSON endpoints for the browser workspace and
future dashboard widgets:

- `GET /dashboard/api/sales`
- `GET /dashboard/api/sales/{sale_id}`
- `GET /dashboard/api/sales-summary`

These endpoints call helpers in `app.dashboard.services.dashboard_service`.
They return schema-safe fallbacks for missing optional data and preserve the
existing dashboard API endpoints such as `/dashboard/api/summary`,
`/dashboard/api/sales-trend`, `/dashboard/api/top-products`, and
`/dashboard/api/insights`.

## Authorization Foundation

The current dashboard has a placeholder identity boundary in the dashboard
service. It defaults to an administrator-style view while keeping store-aware
filtering isolated for the future authenticated dashboard:

- Admin: company-wide visibility.
- Manager: store-scoped visibility.
- Cashier: limited store visibility when enabled.

Dashboard pages and JSON endpoints must not expose secrets, password hashes,
activation documents, bearer tokens, or payment credentials.

## Current Limitations

- Sales workspace actions are read-only.
- Full dashboard browser authentication is not enabled yet.
- Store, cashier, and customer filters currently accept IDs instead of lookup
  selectors.
- Receipt preview availability depends on the existing document service and the
  persisted sale schema.
