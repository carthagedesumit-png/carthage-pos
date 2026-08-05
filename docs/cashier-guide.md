# CBOS Cashier Guide

## Scanner and receipt recovery

Keyboard-emulating USB scanners use the checkout Barcode or SKU field and need no CBOS-specific driver. Keep that field focused, scan once per intended unit, and confirm cart quantity before payment. Repeated scans intentionally add quantity; they never submit the separate payment form. Unknown, inactive, and insufficient-stock items must be resolved by a manager.

A printer failure does not cancel a completed sale. Record the receipt number, fix or report the printer problem, and ask a manager or administrator for an audited historical reprint. Never repeat checkout merely to print another copy.

Sign in with your assigned cashier account and store. Scan barcodes or search products, confirm quantities, select a customer when required, and verify tender totals before checkout. CBOS records cash, card/POS terminal, bank transfer, wallet, credit, and mixed tenders. These are operator-recorded payments; CBOS does not contact or independently verify a bank, terminal, or gateway.

Cash must cover the balance and may produce change. Non-cash tenders cannot exceed the balance. Every split line must be positive; only cash in a split may account for change. Card and transfer references are optional operational identifiers, limited to safe short text. Never enter card numbers, CVVs, PINs, credentials, or other payment secrets.

The checkout screen shows amount due, remaining balance, and cash change. A completed persisted cart is retry-safe: a double-click or refresh returns the recorded sale rather than deducting stock again. Do not start a new cart merely because receipt printing fails.

Use Suspend when a customer needs to pause. Resume from the hold queue. Returns and discounts require manager authorization. Returns may be partial, preserve the original tender history, and cannot exceed sold quantities. At shift end, count the drawer and complete cash reconciliation. Expected cash is opening cash plus movements and recorded cash collections, less the cash share of refunds. A material variance (5.00 or more) requires an explanation. Report printer, drawer, or customer-display errors without retrying a completed sale.
