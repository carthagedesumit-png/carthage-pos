from html import escape
from typing import Any


THERMAL_WIDTHS = {58: 32, 80: 48}
INTERNAL_KEYS = {"id", "product_id", "sale_item_id", "purchase_order_item_id"}


def render_plain_text(document: dict[str, Any], width_mm: int = 80) -> str:
    """Render a structured business document for terminal or thermal output."""
    if width_mm not in THERMAL_WIDTHS:
        raise ValueError("Thermal width must be either 58mm or 80mm.")
    width = THERMAL_WIDTHS[width_mm]
    lines: list[str] = []
    business = document.get("business", {})
    store = document.get("store", {})

    _center(lines, business.get("business_name") or "Business", width)
    if business.get("tax_id"):
        _center(lines, f"Tax ID: {business['tax_id']}", width)
    _center(lines, store.get("name") or store.get("code") or "", width)
    for value in _contact_lines(store, business):
        _center(lines, value, width)
    lines.append("=" * width)
    _center(lines, document.get("title", "DOCUMENT"), width)
    _center(lines, document["document_number"], width)
    lines.append("-" * width)

    for label, value in document.get("metadata", {}).items():
        if value not in (None, ""):
            lines.extend(_label_value(label, value, width))
    for section_name in ("customer", "supplier"):
        section = document.get(section_name) or {}
        if section:
            lines.append("-" * width)
            lines.append(section_name.upper())
            for label, value in section.items():
                if value not in (None, ""):
                    lines.extend(_label_value(label, value, width))

    lines.append("-" * width)
    for item in document.get("line_items", []):
        description = str(
            item.get("description") or item.get("product_name") or "Item"
        )
        lines.extend(_wrap(description, width))
        details = [
            f"{_label(key)}: {_format_value(key, value)}"
            for key, value in item.items()
            if key not in INTERNAL_KEYS
            and key not in {"description", "product_name"}
            and value not in (None, "")
        ]
        for detail in details:
            lines.extend(_wrap(f"  {detail}", width))

    event_history = document.get("event_history") or []
    if event_history:
        lines.append("-" * width)
        lines.append("EVENT HISTORY")
        for event in event_history:
            summary = (
                f"{event.get('from_status') or 'START'} -> {event.get('to_status')} | "
                f"{event.get('user')} | {event.get('timestamp')}"
            )
            lines.extend(_wrap(summary, width))
            if event.get("notes"):
                lines.extend(_wrap(f"  {event['notes']}", width))

    totals = document.get("totals") or {}
    if totals:
        lines.append("-" * width)
        for label, value in totals.items():
            lines.extend(_label_value(label, _format_value(label, value), width))
    lines.append("=" * width)
    footer = document.get("footer") or ""
    for line in _wrap(str(footer), width):
        _center(lines, line, width)
    return "\n".join(lines).rstrip() + "\n"


def render_html(document: dict[str, Any]) -> str:
    """Render dependency-free semantic HTML suitable for browser printing."""
    business = document.get("business", {})
    store = document.get("store", {})
    items = document.get("line_items", [])
    columns = _item_columns(items)
    header_cells = "".join(f"<th>{escape(_label(column))}</th>" for column in columns)
    body_rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{escape(str(_format_value(column, item.get(column, ''))))}</td>"
            for column in columns
        )
        + "</tr>"
        for item in items
    )
    metadata = "".join(
        f"<dt>{escape(_label(label))}</dt><dd>{escape(str(value))}</dd>"
        for label, value in document.get("metadata", {}).items()
        if value not in (None, "")
    )
    customer = "".join(
        f"<dt>{escape(_label(label))}</dt><dd>{escape(str(value))}</dd>"
        for label, value in (document.get("customer") or {}).items()
        if value not in (None, "")
    )
    supplier = "".join(
        f"<dt>{escape(_label(label))}</dt><dd>{escape(str(value))}</dd>"
        for label, value in (document.get("supplier") or {}).items()
        if value not in (None, "")
    )
    event_history = "".join(
        "<li>"
        + escape(
            f"{event.get('from_status') or 'START'} -> {event.get('to_status')} | "
            f"{event.get('user')} | {event.get('timestamp')}"
        )
        + (f" - {escape(str(event['notes']))}" if event.get("notes") else "")
        + "</li>"
        for event in (document.get("event_history") or [])
    )
    totals = "".join(
        f"<dt>{escape(_label(label))}</dt>"
        f"<dd>{escape(str(_format_value(label, value)))}</dd>"
        for label, value in (document.get("totals") or {}).items()
    )
    contact = " | ".join(_contact_lines(store, business))
    logo = (
        f'<img class="logo" src="{escape(business["logo_path"])}" alt="Logo">'
        if business.get("logo_path")
        else ""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{escape(document['document_number'])}</title>
<style>
body{{font-family:Arial,sans-serif;color:#111;margin:32px;line-height:1.35}}
header{{text-align:center;margin-bottom:24px}} .logo{{max-height:72px;max-width:180px}}
h1{{font-size:22px;margin:8px 0}} h2{{font-size:16px;margin:4px 0}}
dl{{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px}}
dt{{font-weight:700}} dd{{margin:0}} table{{width:100%;border-collapse:collapse;margin:20px 0}}
th,td{{border:1px solid #bbb;padding:7px;text-align:left}} th{{background:#f2f2f2}}
.totals{{margin-left:auto;max-width:360px}} footer{{margin-top:28px;text-align:center;color:#444}}
</style></head><body><header>{logo}<h1>{escape(business.get('business_name') or 'Business')}</h1>
<h2>{escape(document.get('title', 'Document'))}</h2><strong>{escape(document['document_number'])}</strong>
<div>{escape(store.get('name') or '')}</div><div>{escape(contact)}</div></header>
<dl>{metadata}</dl>{f'<h2>Customer</h2><dl>{customer}</dl>' if customer else ''}
{f'<h2>Supplier</h2><dl>{supplier}</dl>' if supplier else ''}
<table><thead><tr>{header_cells}</tr></thead><tbody>{body_rows}</tbody></table>
{f'<h2>Event History</h2><ol>{event_history}</ol>' if event_history else ''}
<dl class="totals">{totals}</dl><footer>{escape(str(document.get('footer') or ''))}</footer>
</body></html>"""


def attach_outputs(document: dict[str, Any], width_mm: int = 80) -> dict[str, Any]:
    """Attach text and HTML representations without mutating the source mapping."""
    result = dict(document)
    result["layout_width_mm"] = width_mm
    result["text"] = render_plain_text(result, width_mm=width_mm)
    result["html"] = render_html(result)
    return result


def _contact_lines(store: dict[str, Any], business: dict[str, Any]) -> list[str]:
    address = store.get("address") or business.get("address")
    phone = store.get("phone") or business.get("phone")
    email = store.get("email") or business.get("email")
    return [str(value) for value in (address, phone, email) if value]


def _center(lines: list[str], value: Any, width: int) -> None:
    for line in _wrap(str(value or ""), width):
        lines.append(line.center(width))


def _label_value(label: Any, value: Any, width: int) -> list[str]:
    text = f"{_label(str(label))}: {value}"
    return _wrap(text, width)


def _wrap(value: str, width: int) -> list[str]:
    if not value:
        return []
    words = value.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if len(word) > width:
            if current:
                lines.append(current)
                current = ""
            lines.extend(word[index:index + width] for index in range(0, len(word), width))
        elif not current:
            current = word
        elif len(current) + len(word) + 1 <= width:
            current += f" {word}"
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _item_columns(items: list[dict[str, Any]]) -> list[str]:
    preferred = [
        "description", "sku", "quantity", "unit_price", "unit_cost", "discount",
        "tax", "subtotal", "line_total", "ordered_quantity", "received_quantity",
        "pending_quantity", "dispatched_quantity",
    ]
    available = {
        key for item in items for key in item if key not in INTERNAL_KEYS
    }
    columns = [column for column in preferred if column in available]
    columns.extend(sorted(available - set(columns)))
    return columns or ["description"]


def _label(value: str) -> str:
    return value.replace("_", " ").strip().title()


def _format_value(key: str, value: Any) -> Any:
    if isinstance(value, float) and any(
        token in key for token in ("price", "cost", "amount", "total", "tax", "discount", "value")
    ):
        return f"{value:.2f}"
    return value
