"""Structured JSON logging with a central PII redaction filter.

Every log record's `extra` dict is passed through `mask_pii` so sensitive
fields (SSN, DOB, member_id, raw_text, …) are never emitted in the clear
(docs/DATA_HANDLING.md, code-quality rule).
"""

from __future__ import annotations

import logging
from typing import Any

from pythonjsonlogger.json import JsonFormatter

from app.core.config import settings
from app.core.constants import SENSITIVE_FIELDS
from app.core.security import mask_value

_RESERVED = frozenset(logging.makeLogRecord({}).__dict__.keys()) | {"message", "asctime"}


class RedactionFilter(logging.Filter):
    """Masks sensitive keys attached to a record via `extra=`."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in list(record.__dict__.items()):
            if key in _RESERVED:
                continue
            if key.lower() in SENSITIVE_FIELDS:
                record.__dict__[key] = mask_value(key, value)
        return True


def configure_logging() -> None:
    """Install a JSON handler with redaction on the root logger (idempotent)."""
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"levelname": "level", "asctime": "ts"},
        )
    )
    handler.addFilter(RedactionFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())


def get_logger(name: str, **context: Any) -> logging.LoggerAdapter[logging.Logger]:
    """Return a logger pre-bound with (already-safe) context fields."""
    return logging.LoggerAdapter(logging.getLogger(name), context)
