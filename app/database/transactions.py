"""Explicit transaction boundaries for multi-step write operations."""

from contextlib import contextmanager
from typing import Iterator

from app.core.logging_utils import get_logger, log_failure
from app.database.db_manager import ClosingConnection, get_connection


logger = get_logger("database.transactions")


@contextmanager
def transaction(mode: str = "IMMEDIATE") -> Iterator[ClosingConnection]:
    """Run a write unit atomically and always close its database connection."""
    if mode not in {"DEFERRED", "IMMEDIATE", "EXCLUSIVE"}:
        raise ValueError("Unsupported transaction mode.")
    conn = get_connection()
    try:
        conn.execute(f"BEGIN {mode}")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        log_failure(logger, "database_transaction_rolled_back", mode=mode)
        raise
    finally:
        conn.close()
