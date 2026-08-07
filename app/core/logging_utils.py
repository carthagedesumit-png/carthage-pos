"""Structured logging helpers with sensitive-field redaction."""

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any


SENSITIVE_FIELDS = {"password", "password_hash", "secret", "token", "authorization"}
_request_id: ContextVar[str] = ContextVar("request_id", default="")


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced application logger without configuring global handlers."""
    logger = logging.getLogger(f"carthage_pos.{name}")
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger


def set_request_id(request_id: str) -> None:
    _request_id.set(request_id or "")


class StructuredLogFormatter(logging.Formatter):
    """Format application log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "event": getattr(record, "event", record.getMessage()),
            "request_id": getattr(record, "request_id", _request_id.get()),
            "context": _redact(getattr(record, "context", {})),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info).splitlines()[-1]
        return json.dumps(payload, sort_keys=True, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Configure root CBOS application logging with a structured format."""
    root = logging.getLogger("carthage_pos")
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    formatter = StructuredLogFormatter()
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.handlers = [stream_handler]
    root.propagate = False


def log_event(logger: logging.Logger, event: str, **context: Any) -> None:
    """Emit a structured event while excluding credentials and secrets."""
    logger.info(event, extra={"event": event, "context": _redact(context), "request_id": _request_id.get()})


def log_failure(logger: logging.Logger, event: str, **context: Any) -> None:
    """Emit a structured exception event from inside an exception handler."""
    logger.exception(event, extra={"event": event, "context": _redact(context), "request_id": _request_id.get()})


def _redact(context: Any) -> Any:
    if isinstance(context, dict):
        return {
            key: _redact(value)
            for key, value in context.items()
            if key.lower() not in SENSITIVE_FIELDS
        }
    if isinstance(context, list):
        return [_redact(item) for item in context]
    return context
