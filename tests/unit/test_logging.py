"""Tests for the logging module — setup and credential sanitization."""

from __future__ import annotations

import json
import logging

import pytest

from loxone_exporter.logging import _sanitize, setup_logging


class TestSetupLogging:
    """Test logging configuration."""

    def test_json_format(self) -> None:
        """JSON format should produce valid JSON lines."""
        setup_logging(level="info", fmt="json")
        root = logging.getLogger()
        assert len(root.handlers) == 1
        handler = root.handlers[0]
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        output = handler.formatter.format(record)
        parsed = json.loads(output)
        assert parsed["message"] == "hello"
        assert parsed["level"] == "INFO"

    def test_text_format(self) -> None:
        """Text format should produce human-readable output."""
        setup_logging(level="debug", fmt="text")
        root = logging.getLogger()
        assert len(root.handlers) == 1
        record = logging.LogRecord(
            name="test", level=logging.DEBUG, pathname="", lineno=0,
            msg="hello world", args=(), exc_info=None,
        )
        output = root.handlers[0].formatter.format(record)
        assert "hello world" in output
        assert "DEBUG" in output

    def test_invalid_level_raises(self) -> None:
        """Invalid log level should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid log level"):
            setup_logging(level="FATAL", fmt="json")

    def test_invalid_format_raises(self) -> None:
        """Invalid log format should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid log format"):
            setup_logging(level="info", fmt="xml")

    def test_handlers_replaced_on_reconfig(self) -> None:
        """Calling setup_logging twice shouldn't stack handlers."""
        setup_logging(level="info", fmt="json")
        setup_logging(level="debug", fmt="text")
        root = logging.getLogger()
        assert len(root.handlers) == 1


class TestCredentialSanitization:
    """Verify sensitive data is redacted from log output."""

    def test_password_redacted(self) -> None:
        assert "****" in _sanitize("password=secret123")
        assert "secret123" not in _sanitize("password=secret123")

    def test_password_colon_redacted(self) -> None:
        assert "****" in _sanitize("password: mysecret")
        assert "mysecret" not in _sanitize("password: mysecret")

    def test_token_redacted(self) -> None:
        assert "****" in _sanitize("token=abc123def")
        assert "abc123def" not in _sanitize("token=abc123def")

    def test_authenticate_hash_redacted(self) -> None:
        result = _sanitize("authenticate/a1b2c3d4e5f6")
        assert "****" in result
        assert "a1b2c3d4e5f6" not in result

    def test_encrypted_command_redacted(self) -> None:
        result = _sanitize('jdev/sys/enc/dGVzdGRhdGE=')
        assert "****" in result
        assert "dGVzdGRhdGE=" not in result

    def test_keyexchange_redacted(self) -> None:
        result = _sanitize("keyexchange/base64encodedkey==")
        assert "****" in result
        assert "base64encodedkey==" not in result

    def test_non_sensitive_unchanged(self) -> None:
        msg = "Connected to 192.168.1.100 on port 80"
        assert _sanitize(msg) == msg

    def test_json_formatter_sanitizes(self) -> None:
        """JSON formatter should sanitize messages."""
        setup_logging(level="info", fmt="json")
        root = logging.getLogger()
        handler = root.handlers[0]
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="authenticate/a1b2c3d4e5f6", args=(), exc_info=None,
        )
        output = handler.formatter.format(record)
        parsed = json.loads(output)
        assert "a1b2c3d4e5f6" not in parsed["message"]
        assert "****" in parsed["message"]

    def test_text_formatter_sanitizes(self) -> None:
        """Text formatter should sanitize messages."""
        setup_logging(level="info", fmt="text")
        root = logging.getLogger()
        handler = root.handlers[0]
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="password=secret123", args=(), exc_info=None,
        )
        output = handler.formatter.format(record)
        assert "secret123" not in output
        assert "****" in output
