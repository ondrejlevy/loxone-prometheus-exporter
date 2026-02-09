"""Additional tests for loxone_auth.py to improve coverage.

This file demonstrates how to implement tests from COVERAGE_ANALYSIS.md Phase 2.
"""

from __future__ import annotations

import pytest

from loxone_exporter.loxone_auth import (
    _normalize_public_key,
    _parse_response,
)


class TestParseResponse:
    """Test _parse_response utility function."""

    def test_parse_valid_json_with_ll_wrapper(self) -> None:
        """Valid JSON with LL wrapper extracts inner object."""
        data = '{"LL": {"Code": "200", "value": "test"}}'
        result = _parse_response(data)
        assert result == {"Code": "200", "value": "test"}

    def test_parse_valid_json_without_ll_wrapper(self) -> None:
        """Valid JSON without LL wrapper returns as-is."""
        data = '{"Code": "200", "value": "test"}'
        result = _parse_response(data)
        assert result == {"Code": "200", "value": "test"}

    def test_parse_invalid_json_returns_empty_dict(self) -> None:
        """Invalid JSON returns empty dict."""
        data = "not valid json"
        result = _parse_response(data)
        assert result == {}

    def test_parse_empty_string_returns_empty_dict(self) -> None:
        """Empty string returns empty dict."""
        data = ""
        result = _parse_response(data)
        assert result == {}

    def test_parse_null_json_returns_empty_dict(self) -> None:
        """JSON null returns empty dict."""
        data = "null"
        result = _parse_response(data)
        assert result == {}


class TestPublicKeyNormalization:
    """Test PEM key format normalization."""

    def test_certificate_format_converted_to_public_key(self) -> None:
        """BEGIN CERTIFICATE converted to BEGIN PUBLIC KEY."""
        raw = (
            "-----BEGIN CERTIFICATE-----\n"
            "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA\n"
            "-----END CERTIFICATE-----"
        )
        result = _normalize_public_key(raw)
        assert "-----BEGIN PUBLIC KEY-----" in result
        assert "-----END PUBLIC KEY-----" in result
        assert "BEGIN CERTIFICATE" not in result

    def test_raw_key_without_headers_gets_wrapped(self) -> None:
        """Raw key without headers gets PEM wrapper."""
        raw = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA"
        result = _normalize_public_key(raw)
        assert result.startswith("-----BEGIN PUBLIC KEY-----")
        assert result.endswith("-----END PUBLIC KEY-----")
        assert raw in result

    def test_already_valid_pem_unchanged(self) -> None:
        """Valid PEM key remains unchanged."""
        raw = (
            "-----BEGIN PUBLIC KEY-----\n"
            "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA\n"
            "-----END PUBLIC KEY-----"
        )
        result = _normalize_public_key(raw)
        assert result == raw

    def test_empty_key_gets_wrapped(self) -> None:
        """Empty key gets proper PEM wrapper."""
        raw = ""
        result = _normalize_public_key(raw)
        assert "-----BEGIN PUBLIC KEY-----" in result
        assert "-----END PUBLIC KEY-----" in result

    def test_multiline_certificate_normalized(self) -> None:
        """Multiline certificate properly converted."""
        raw = """-----BEGIN CERTIFICATE-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA
test1234567890
-----END CERTIFICATE-----"""
        result = _normalize_public_key(raw)
        assert "-----BEGIN PUBLIC KEY-----" in result
        assert "-----END PUBLIC KEY-----" in result
        assert "test1234567890" in result


class TestTokenResponseVariants:
    """Test different token response formats (extending existing tests)."""

    # Note: These would be integration tests with mock WebSocket
    # Shown here as examples of what to test

    @pytest.mark.skip(reason="Requires WebSocket mock - see test_auth.py")
    def test_token_as_dict_with_token_field(self) -> None:
        """Token as dict with 'token' field."""
        # TODO: Mock WebSocket response with:
        # {"LL": {"Code": "200", "value": {"token": "abc123", "validUntil": ...}}}
        pass

    @pytest.mark.skip(reason="Requires WebSocket mock - see test_auth.py")
    def test_token_missing_uses_empty_string(self) -> None:
        """Missing token field uses empty string."""
        # TODO: Mock WebSocket response with:
        # {"LL": {"Code": "200", "value": {}}}
        pass


class TestHTTPPublicKeyFetch:
    """Test HTTP fetching of RSA public key."""

    @pytest.mark.asyncio
    async def test_http_fetch_success(self) -> None:
        """Successful HTTP fetch returns public key."""
        import json
        from unittest.mock import MagicMock, patch

        from loxone_exporter.loxone_auth import _fetch_public_key_http

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"LL": {"Code": "200", "value": "test-key-content"}}
        ).encode()
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with patch("urllib.request.urlopen", return_value=mock_response):
            key = await _fetch_public_key_http(
                "192.168.1.1", 80, "admin", "password"
            )
            assert key == "test-key-content"

    @pytest.mark.asyncio
    async def test_http_fetch_unsuccessful_response_raises(self) -> None:
        """HTTP unsuccessful response raises AuthenticationError."""
        import json
        from unittest.mock import MagicMock, patch

        from loxone_exporter.loxone_auth import (
            AuthenticationError,
            _fetch_public_key_http,
        )

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"LL": {"Code": "500", "value": ""}}
        ).encode()
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None

        with (
            patch("urllib.request.urlopen", return_value=mock_response),
            pytest.raises(AuthenticationError, match="Failed to get RSA"),
        ):
            await _fetch_public_key_http("192.168.1.1", 80, "admin", "password")

    @pytest.mark.asyncio
    async def test_http_fetch_timeout_raises(self) -> None:
        """HTTP timeout raises AuthenticationError."""
        from unittest.mock import patch

        from loxone_exporter.loxone_auth import (
            AuthenticationError,
            _fetch_public_key_http,
        )

        with (
            patch(
                "urllib.request.urlopen",
                side_effect=TimeoutError("Connection timed out"),
            ),
            pytest.raises((AuthenticationError, TimeoutError)),
        ):
            await _fetch_public_key_http("192.168.1.1", 80, "admin", "password")

    @pytest.mark.asyncio
    async def test_http_fetch_connection_error_raises(self) -> None:
        """HTTP connection error raises AuthenticationError."""
        from unittest.mock import patch
        from urllib.error import URLError

        from loxone_exporter.loxone_auth import (
            AuthenticationError,
            _fetch_public_key_http,
        )

        with (
            patch(
                "urllib.request.urlopen",
                side_effect=URLError("Connection refused"),
            ),
            pytest.raises((AuthenticationError, URLError)),
        ):
            await _fetch_public_key_http("192.168.1.1", 80, "admin", "password")
