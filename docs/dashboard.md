# Dashboard

The browser dashboard lives under `/dashboard` and is a management surface for
owners, managers, and administrators inside the Carthage Business Operating
System (CBOS). The POS remains a core operating module. Dashboard pages reuse domain
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

## CRM Workspace

`GET /dashboard/customers` renders the CRM Workspace V1 management page. It is
a read-first customer relationship portal for customer profiles, customer
groups, wallet balances, loyalty activity, credit exposure, and purchase
history.

The page includes:

- Summary cards for customer count, lifetime value, loyalty points, and
  outstanding credit.
- A responsive customer table with customer code, name, phone/email, group,
  wallet balance, loyalty points, outstanding credit, lifetime value, last
  purchase date, and active status.
- Credit, wallet, and loyalty badges.
- Filter controls that preserve selected query parameters.
- Empty-state handling and previous/next pagination.

Supported query parameters:

- `search`
- `customer_group` as a group ID or group name fragment
- `active` with `active`, `inactive`, or `all`
- `has_credit`
- `has_wallet_balance`
- `loyalty_customer`
- `joined_from`
- `joined_to`
- `page`
- `page_size`

`GET /dashboard/customers/{customer_id}` renders a read-only customer detail
page with profile, contact information, customer group, lifetime sales, recent
sales, wallet history, loyalty history, credit history, and statement/print/
export action placeholders.

## CRM JSON Endpoints

The dashboard exposes lightweight JSON endpoints for CRM workspace data:

- `GET /dashboard/api/customers`
- `GET /dashboard/api/customers/summary`
- `GET /dashboard/api/customers/top`
- `GET /dashboard/api/customers/{customer_id}`
- `GET /dashboard/api/customers/{customer_id}/activity`

These endpoints use dashboard read helpers and return safe empty structures when
customer, sales, wallet, loyalty, or credit tables are unavailable.

## Procurement Workspace

`GET /dashboard/procurement` renders the Procurement Workspace V1 management
page. It is a read-only supplier and purchase management portal for reviewing
purchase orders, receiving progress, supplier exposure, and replenishment
activity.

The page includes:

- Summary cards for purchase orders, estimated purchase value, pending receipt
  count, and supplier count.
- A responsive purchase order table with reference number, supplier, store,
  status, expected delivery date, created/submitted date, ordered quantity,
  received quantity, remaining quantity, estimated value, creator, and
  outstanding/partial/complete/cancelled badges.
- Filter controls that preserve selected query parameters.
- Empty-state handling and previous/next pagination.
- Detail actions for purchase order and supplier drill-down pages.

Supported query parameters:

- `search`
- `supplier_id`
- `store_id`
- `status` with `DRAFT`, `SUBMITTED`, `PARTIALLY_RECEIVED`,
  `FULLY_RECEIVED`, or `CANCELLED`
- `date_from`
- `date_to`
- `pending_only`
- `partially_received`
- `completed`
- `cancelled`
- `page`
- `page_size`

`GET /dashboard/procurement/purchase-orders/{purchase_order_id}` renders a
read-only purchase order detail page with header fields, supplier contact
details, ordered items, received quantities, remaining quantities, unit costs,
line values, receipt history, goods received note references where available,
and purchase order/GRN/print action placeholders.

`GET /dashboard/procurement/suppliers/{supplier_id}` renders a read-only
supplier detail page with supplier profile, contact information, active state,
total purchase orders, outstanding purchase orders, total purchase value, last
purchase date, recent purchase orders, and statement/export/print action
placeholders.

## Procurement JSON Endpoints

The dashboard exposes lightweight JSON endpoints for the procurement workspace:

- `GET /dashboard/api/procurement`
- `GET /dashboard/api/procurement/summary`
- `GET /dashboard/api/procurement/activity`
- `GET /dashboard/api/procurement/purchase-orders/{purchase_order_id}`
- `GET /dashboard/api/procurement/suppliers`
- `GET /dashboard/api/procurement/suppliers/{supplier_id}`

These endpoints use dashboard-specific read helpers and return safe empty
structures when supplier, purchase order, purchase order item, receipt, product,
store, or user tables are unavailable.

## Reports & Analytics Workspace

`GET /dashboard/reports` renders the Reports & Analytics Workspace V1
executive intelligence page. It is a read-only portal that composes existing
reporting, dashboard, sales, inventory, customer, procurement, and store read
models without owning business mutations.

The page includes:

- Summary cards for net sales, estimated profit, inventory value, and refunds.
- Report filter controls that preserve selected query parameters.
- Overview sections for Sales Summary, Product Performance, Cashier
  Performance, Store Performance, Customer Performance, Inventory Valuation,
  Procurement Summary, and Refund Summary.
- Route-ready CSV, Excel, PDF, and print report placeholders marked as coming
  soon.
- Empty-state handling when analytics rows are unavailable.

Supported query parameters:

- `date_from`
- `date_to`
- `store_id`
- `cashier_id`
- `customer_id`
- `product_id`
- `category_id`
- `supplier_id`
- `report_type` with `overview`, `sales`, `products`, `cashiers`, `stores`,
  `customers`, `inventory`, `procurement`, or `refunds`

Report detail foundation pages are available at:

- `GET /dashboard/reports/sales`
- `GET /dashboard/reports/inventory`
- `GET /dashboard/reports/customers`
- `GET /dashboard/reports/procurement`
- `GET /dashboard/reports/stores`

Each detail page extends the shared dashboard layout, shows summary cards, uses
basic filters, displays a table foundation, and keeps export/print actions
read-only placeholders.

## Reports JSON Endpoints

The dashboard exposes lightweight JSON endpoints for report workspace data:

- `GET /dashboard/api/reports/summary`
- `GET /dashboard/api/reports/sales`
- `GET /dashboard/api/reports/products`
- `GET /dashboard/api/reports/cashiers`
- `GET /dashboard/api/reports/stores`
- `GET /dashboard/api/reports/customers`
- `GET /dashboard/api/reports/inventory`
- `GET /dashboard/api/reports/procurement`
- `GET /dashboard/api/reports/refunds`
- `GET /dashboard/api/reports/export/{export_format}`

The export endpoint currently returns a `coming_soon` placeholder for `csv`,
`excel`, `pdf`, and `print` formats. Full export generation remains outside
Reports Workspace V1.

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
- CRM workspace actions are read-only.
- Procurement workspace actions are read-only.
- Reports workspace actions are read-only.
- Full dashboard browser authentication is not enabled yet.
- Store, cashier, and customer filters currently accept IDs instead of lookup
  selectors.
- Store, category, and supplier inventory filters currently accept IDs instead
  of lookup selectors.
- Store and supplier procurement filters currently accept IDs instead of lookup
  selectors.
- Label print actions are placeholders; full label workflow remains in barcode
  and hardware services.
- Statement, print, and export actions in CRM are placeholders.
- Purchase order, goods received note, supplier statement, export, and print
  actions in Procurement are placeholders.
- CSV, Excel, PDF, and print actions in Reports are placeholders.
- Receipt preview availability depends on the existing document service and the
  persisted sale schema.
