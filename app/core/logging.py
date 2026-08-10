"""Structured logging that keeps request metadata useful without recording credentials, PII, or full ticket text."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any


SENSITIVE_KEY_RE = re.compile(r"password|secret|token|authorization|cookie|api[_-]?key", re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
TEXT_KEY_RE = re.compile(r"body|excerpt|question|title|content|reason", re.IGNORECASE)


def redact_value(value: Any, key: str | None = None) -> Any:
    """Redact by key and clear PII pattern; callers should still avoid passing text fields in the first place."""

    if key and (SENSITIVE_KEY_RE.search(key) or TEXT_KEY_RE.search(key)):
        return "[redacted]"
    if isinstance(value, str):
        return EMAIL_RE.sub("[redacted-email]", PHONE_RE.sub("[redacted-phone]", value))
    if isinstance(value, Mapping):
        return {str(item_key): redact_value(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    return value


class JSONFormatter(logging.Formatter):
    """Serialize only safe record fields into one JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "event": record.getMessage(),
            "logger": record.name,
        }
        for key in ("request_id", "method", "path", "status_code", "duration_ms", "node", "run_id", "error_type"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(redact_value(payload), ensure_ascii=False, separators=(",", ":"))


def configure_logging() -> logging.Logger:
    """Configure the dedicated application logger once, without touching third-party loggers."""

    logger = logging.getLogger("ticketinsight")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
    return logger
