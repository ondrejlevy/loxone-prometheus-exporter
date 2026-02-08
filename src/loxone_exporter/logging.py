"""Structured logging setup for the Loxone Prometheus Exporter."""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

# Patterns to redact sensitive information from log output
_SENSITIVE_PATTERNS = [
    (re.compile(r'(password\s*[=:]\s*)[^\s,}\]"]+', re.IGNORECASE), r"\1****"),
    (re.compile(r'(token\s*[=:]\s*)[^\s,}\]"]+', re.IGNORECASE), r"\1****"),
    (re.compile(r'(authenticate/)[0-9a-fA-F]+', re.IGNORECASE), r"\1****"),
    (re.compile(r'(jdev/sys/enc/)[^\s"]+', re.IGNORECASE), r"\1****"),
    (re.compile(r'(keyexchange/)[^\s"]+', re.IGNORECASE), r"\1****"),
]


def _sanitize(message: str) -> str:
    """Redact passwords, tokens, and hashes from a log message."""
    for pattern, replacement in _SENSITIVE_PATTERNS:
        message = pattern.sub(replacement, message)
    return message


class _JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": _sanitize(record.getMessage()),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


class _SanitizingFormatter(logging.Formatter):
    """Text formatter that redacts sensitive data."""

    def format(self, record: logging.LogRecord) -> str:
        result = super().format(record)
        return _sanitize(result)


_TEXT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s — %(message)s"

_VALID_LEVELS = {"debug", "info", "warning", "error"}
_VALID_FORMATS = {"json", "text"}


def setup_logging(level: str = "info", fmt: str = "json") -> None:
    """Configure the root logger with the specified level and format.

    Args:
        level: Log level — one of ``debug``, ``info``, ``warning``, ``error``.
        fmt: Output format — ``json`` for structured JSON lines, ``text`` for
            human-readable plain text.

    Raises:
        ValueError: If *level* or *fmt* is not a recognised value.
    """
    level_lower = level.lower()
    fmt_lower = fmt.lower()

    if level_lower not in _VALID_LEVELS:
        msg = f"Invalid log level {level!r}. Must be one of {sorted(_VALID_LEVELS)}"
        raise ValueError(msg)
    if fmt_lower not in _VALID_FORMATS:
        msg = f"Invalid log format {fmt!r}. Must be one of {sorted(_VALID_FORMATS)}"
        raise ValueError(msg)

    root = logging.getLogger()
    root.setLevel(level_lower.upper())

    # Remove existing handlers to allow re-configuration
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)

    if fmt_lower == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(_SanitizingFormatter(_TEXT_FORMAT))

    root.addHandler(handler)
