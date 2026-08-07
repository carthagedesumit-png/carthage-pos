# Hardware Integration

## Architecture

Hardware support is an adapter layer under `app/hardware`. Sales, inventory,
documents, and other business services do not import peripheral drivers.

- `interfaces.py` defines printer, drawer, scanner, and display contracts.
- `profiles.py` defines 58mm, 80mm, and generic text printer layouts.
- `adapters.py` provides null, file-spool, keyboard, and mock adapters.
- `manager.py` composes configured adapters and supports dependency injection.
- `hardware_service.py` applies authorization, document generation, fallback,
  structured logging, and the persistent `hardware_events` audit trail.

Hardware failures return a result such as `{"success": false, "error": "..."}`
for checkout-facing operations. A completed sale is never rolled back because a
printer, drawer, or customer display is unavailable. Invalid input and
unauthorized manual drawer operations still raise normal application errors.

Completed sales and peripheral delivery are separate operations. A failed receipt
returns a retryable result and never reverses or repeats the sale. Historical
reprints require manager or administrator authorization, are headed `REPRINT`,
and are recorded against the sale in `hardware_events`. Manual drawer opens also
require manager/administrator authority and a 3-200 character operational reason.

## Supported Strategy

- Thermal printers: existing document text rendered for 58mm or 80mm paper.
- Generic printers: wider plain-text output.
- File spool printer: appends jobs to a configured UTF-8 path for integration.
- Cash drawers: printer-pulse abstraction or an independently injected adapter.
- Barcode scanners: keyboard-wedge input with trailing Enter/CR normalization.
- Label printers: label text uses the same injectable printer contract and
  58mm, 80mm, or generic printer profiles.
- Customer displays: welcome, item, totals, payment, and clear operations.

No vendor SDK or machine-specific device name is required by the core project.

## Configuration

All hardware is configured through environment variables:

```powershell
$env:POS_PRINTER_ENABLED="true"
$env:POS_PRINTER_PROFILE="80mm"       # 58mm, 80mm, or generic
$env:POS_RECEIPT_PRINTER_NAME="Front Register"
$env:POS_RECEIPT_PRINTER_PATH="C:\pos-spool\receipt-jobs.txt"
$env:POS_RECEIPT_COPIES="1"          # 1, 2, or 3
$env:POS_AUTOMATIC_RECEIPT_PRINTING="false"
$env:POS_CASH_DRAWER_ENABLED="true"
$env:POS_OPEN_DRAWER_AFTER_CASH_SALE="true"
$env:POS_SCANNER_ENABLED="true"
$env:POS_CUSTOMER_DISPLAY_ENABLED="false"
```

An enabled printer without a supported adapter/path reports unavailable and
falls back safely. Device names are descriptive placeholders for future drivers.
`available` reflects adapter-level availability only; `verified` remains false
until a real communication test is performed. Configuration must never contain
credentials. Machine-specific values belong in deployment environment storage,
not source control.

Keyboard-emulating scanners need no CBOS driver. They submit up to 128 printable
characters through the checkout barcode field. Unknown, inactive, unavailable,
and insufficient-stock products are rejected by the existing store-scoped cart
rules. Each completed scan adds one unit, so deliberate repeated scans remain
supported. The checkout submit control is independently disabled after submit,
preventing scan keystrokes from completing a sale.

## Testing Without Hardware

Run the mock integration suite:

```powershell
python -m unittest tests.test_hardware -v
```

`MockPrinter`, `MockCashDrawer`, `MockBarcodeScanner`, and
`MockCustomerDisplay` retain jobs and state for assertions. Build a
`HardwareManager` with those adapters and install it through
`configure_hardware_manager()`.

Managers can use terminal options 7 and 8 for printer and drawer diagnostics.
API diagnostics are available under `/api/v1/hardware`; OpenAPI lists the exact
request and response contracts.

## Implementing a Real Driver

1. Implement the relevant abstract class from `interfaces.py`.
2. Translate driver/SDK errors into `HardwareError` subclasses.
3. Return accurate enabled/available status without opening the device.
4. Never log receipt contents, payment data, or customer details.
5. Compose the adapter into `HardwareManager` at application startup.
6. Add contract tests using a fake transport before testing physical hardware.

ESC/POS, USB, serial, network-print, and vendor display SDK adapters can be
added independently without changing checkout or document-generation logic.
Production barcode engines implement `BarcodeRenderer`; the default renderer
intentionally produces dependency-free preview placeholders.

## RC limitations and recovery

CBOS does not claim universal printer, drawer, USB, ESC/POS, or Windows-driver
compatibility. The included production composition supports disabled devices and
the file-spool integration contract; real Windows printer integration requires an
approved adapter. Paper-out, offline, timeout, and cancellation behavior depends
on that adapter and must be exercised with the actual pilot devices. After a
failure, verify the completed receipt number, correct the device problem, and use
the authorized reprint action. Never repeat checkout to obtain a receipt.
