# Barcode and Label Platform

## Architecture

`barcode_service.py` owns validation, generation, manual assignment, lifecycle
audit, and identifier lookup. `label_service.py` composes catalog/store data,
renders previews, submits text through the hardware printer contract, and
records immutable job/item history. Templates and renderers are independent
adapters, so a production barcode library does not affect business services.

The legacy `products.barcode` value mirrors the active primary identifier.
Secondary, supplier, and QR values live in `product_identifiers`. Scanner and
sales lookup resolve SKU, all active identifier types, and legacy product IDs
through one service.

## Formats and Templates

- Code 39: uppercase Code 39 character set.
- Code 128: printable ASCII, up to 128 characters.
- EAN-8, EAN-13, and UPC-A: exact length and checksum validation.
- QR: future-ready payload storage and preview abstraction.

Templates are `SHELF`, `SMALL_PRODUCT`, `LARGE_PRODUCT`, `WAREHOUSE`,
`BARCODE_ONLY`, and `QR`. Dimensions can be overridden per preview. Output
includes structured data, plain text, SVG preview, and a PNG placeholder. The
dependency-free SVG is a preview, not guaranteed scanner-ready.

Generated identifiers use the company prefix, product ID, and a deterministic
per-product sequence. Values are unique case-insensitively, including retired
values, so historical identifiers cannot be accidentally reused.

## Printing Workflow

1. Preview validates store access and composes current catalog/store metadata.
2. A manager or admin submits products and positive label counts.
3. The service creates a pending numbered job and immutable item selection.
4. Text is sent through the configured printer adapter/profile.
5. The job becomes `PRINTED` or `FAILED`; device errors return a safe result.
6. Reprint creates a new linked job and preserves the original audit record.

Procurement receipts, low-stock products, and inventory counts have batch
helpers. Cashiers may preview and look up identifiers. Managers may generate,
print, and reprint; manual assignment is admin-only.

## Configuration

```powershell
$env:POS_DEFAULT_BARCODE_FORMAT="CODE128"
$env:POS_DEFAULT_LABEL_TEMPLATE="SMALL_PRODUCT"
$env:POS_LABEL_PRINTER_PROFILE="generic"
$env:POS_LABEL_WIDTH_MM="50"
$env:POS_LABEL_HEIGHT_MM="30"
$env:POS_BARCODE_COMPANY_PREFIX="POS"
$env:POS_AUTO_GENERATE_BARCODES="false"
$env:POS_QR_ENABLED="true"
```

When `POS_AUTO_GENERATE_BARCODES` is enabled, product creation atomically assigns
a primary identifier in the configured format. Otherwise products may remain
without a barcode; SKU lookup remains available for backward compatibility.

## Testing and Future Drivers

Run `python -m unittest tests.test_barcodes -v`. Tests use `MockPrinter`, so no
physical hardware or graphics package is required. Real SVG/PNG renderers
implement `BarcodeRenderer`; printer drivers continue to implement the existing
hardware interface and translate vendor failures to hardware exceptions.
