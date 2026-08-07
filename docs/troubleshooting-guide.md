# CBOS Troubleshooting Guide

## Peripheral failures after checkout

First confirm whether a receipt number was issued. If so, the sale committed: do not submit payment again. Check the configured profile and adapter state, restore paper/connectivity, then have a manager perform an authorized reprint. Disabled or unavailable devices are non-destructive.

Offline, paper-out, cancellation, Windows queue, timeout, scanner timing, and drawer-pulse behavior remains a physical acceptance requirement. Mock tests prove orchestration safety, not device compatibility.

1. If CBOS is already running, the launcher opens the existing dashboard.
2. For a port conflict, configure `POS_API_FALLBACK_PORT` or free the configured port.
3. If startup configuration is invalid, run installer Repair and review Diagnostics.
4. If database integrity is not `ok`, stop writes and restore the latest verified backup.
5. Resume or void unfinished carts from Sales Checkout.
6. Retry failed finance events only after correcting account mappings or period locks.
7. If printing fails after checkout, reprint the existing receipt; do not repeat the sale.

Preserve logs, timestamps, receipt numbers, and diagnostic output when escalating an incident. Never include passwords, tokens, or license secrets.
