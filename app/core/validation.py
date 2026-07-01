"""Reusable, side-effect-free validation and normalization helpers."""

from datetime import date
from typing import Any, Iterable, Optional, Type

from app.core.exceptions import ValidationError


def required_text(
    value: Any,
    label: str,
    *,
    error_type: Type[ValidationError] = ValidationError,
) -> str:
    """Return stripped text or raise a stable validation exception."""
    normalized = str(value or "").strip()
    if not normalized:
        raise error_type(f"{label} is required.")
    return normalized


def optional_text(value: Any) -> Optional[str]:
    """Normalize optional text to either stripped text or ``None``."""
    normalized = str(value or "").strip()
    return normalized or None


def normalized_email(value: Any) -> Optional[str]:
    """Normalize an optional email address for case-insensitive comparisons."""
    normalized = optional_text(value)
    return normalized.lower() if normalized else None


def positive_int(
    value: Any,
    label: str = "Quantity",
    *,
    error_type: Type[ValidationError] = ValidationError,
) -> int:
    """Validate a positive whole number without accepting booleans/fractions."""
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise error_type(f"{label} must be a positive whole number.") from exc
    if isinstance(value, bool) or number <= 0 or float(value) != number:
        raise error_type(f"{label} must be a positive whole number.")
    return number


def non_negative_number(
    value: Any,
    label: str,
    *,
    error_type: Type[ValidationError] = ValidationError,
) -> float:
    """Validate and return a finite non-negative number."""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise error_type(f"{label} must be a non-negative number.") from exc
    if number < 0 or number != number or number in (float("inf"), float("-inf")):
        raise error_type(f"{label} must be a non-negative number.")
    return number


def choice(
    value: Any,
    choices: Iterable[str],
    label: str,
    *,
    error_type: Type[ValidationError] = ValidationError,
) -> str:
    """Validate that a value belongs to a finite set of strings."""
    allowed = set(choices)
    if value not in allowed:
        raise error_type(f"Invalid {label}.")
    return str(value)


def iso_date(
    value: Any,
    label: str,
    *,
    allow_none: bool = True,
    error_type: Type[ValidationError] = ValidationError,
) -> Optional[str]:
    """Validate an ISO ``YYYY-MM-DD`` date and return normalized text."""
    normalized = optional_text(value)
    if normalized is None and allow_none:
        return None
    try:
        return date.fromisoformat(normalized or "").isoformat()
    except ValueError as exc:
        raise error_type(f"{label} must use YYYY-MM-DD format.") from exc
