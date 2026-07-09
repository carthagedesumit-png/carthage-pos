# Dashboard

The browser dashboard lives under `/dashboard` and is a management surface for
owners, managers, and administrators inside the Carthage Business Operating
System. The POS remains a core operating module. Dashboard pages reuse domain
services for sales, documents, reports, inventory, and platform health rather
than duplicating business rules in route handlers.

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

## Inventory Workspace

`GET /dashboard/inventory` renders the Inventory Workspace V1 management page.
It is a read-only portal for product, store stock, valuation, barcode readiness,
and label workflow review.

The page includes:

- Summary cards for inventory value, product rows, low stock, and out of stock.
- A responsive product table with product name, SKU, barcode, category,
  supplier, store, quantity on hand, reorder level, average cost, selling price,
  inventory value, active status, and stock badges.
- Missing-barcode indicators and a detail action for each product.
- Filter controls that preserve selected query parameters.
- Empty-state handling and previous/next pagination.

Supported query parameters:

- `search`
- `store_id`
- `category_id`
- `supplier_id`
- `low_stock`
- `out_of_stock`
- `active` with `active`, `inactive`, or `all`
- `has_barcode` with `all`, `has`, or `missing`
- `page`
- `page_size`

`GET /dashboard/inventory/products/{product_id}` renders a read-only product
detail page with profile, pricing, barcode identifiers, stock by store, stock
movement history, procurement history where available, and label/print action
placeholders.

## Inventory JSON Endpoints

The dashboard exposes lightweight JSON endpoints for the inventory workspace:

- `GET /dashboard/api/inventory`
- `GET /dashboard/api/inventory/summary`
- `GET /dashboard/api/inventory/low-stock`
- `GET /dashboard/api/inventory/products/{product_id}`
- `GET /dashboard/api/inventory/valuation`

These endpoints use dashboard read helpers that are schema-safe and
migration-safe. They return empty lists or zeroed summaries when product,
barcode, store inventory, procurement, or movement tables are unavailable.

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
- Inventory workspace actions are read-only.
- Full dashboard browser authentication is not enabled yet.
- Store, cashier, and customer filters currently accept IDs instead of lookup
  selectors.
- Store, category, and supplier inventory filters currently accept IDs instead
  of lookup selectors.
- Label print actions are placeholders; full label workflow remains in barcode
  and hardware services.
- Receipt preview availability depends on the existing document service and the
  persisted sale schema.
