"""Structured logging helpers with sensitive-field redaction."""

import logging
from typing import Any


SENSITIVE_FIELDS = {"password", "password_hash", "secret", "token", "authorization"}


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced application logger without configuring global handlers."""
    logger = logging.getLogger(f"carthage_pos.{name}")
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger


def log_event(logger: logging.Logger, event: str, **context: Any) -> None:
    """Emit a structured event while excluding credentials and secrets."""
    safe_context = {
        key: value
        for key, value in context.items()
        if key.lower() not in SENSITIVE_FIELDS
    }
    logger.info(event, extra={"event": event, "context": safe_context})


def log_failure(logger: logging.Logger, event: str, **context: Any) -> None:
    """Emit a structured exception event from inside an exception handler."""
    safe_context = {
        key: value
        for key, value in context.items()
        if key.lower() not in SENSITIVE_FIELDS
    }
    logger.exception(event, extra={"event": event, "context": safe_context})
