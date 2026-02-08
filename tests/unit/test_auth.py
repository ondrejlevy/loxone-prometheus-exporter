"""Tests for Loxone authentication — token-based and hash-based flows."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest


class TestTokenBasedAuth:
    """Token-based authentication flow (firmware >= 9.x)."""

    async def test_requests_rsa_public_key(self) -> None:
        """Auth should request the Miniserver's RSA public key first."""
        from loxone_exporter.loxone_auth import authenticate

        ws = AsyncMock()
        # Simulate: getPublicKey response → key exchange → getkey2 → gettoken
        ws.recv = AsyncMock(
            side_effect=[
                # Response to getPublicKey
                json.dumps({
                    "LL": {
                        "control": "dev/sys/getPublicKey",
                        "value": _SAMPLE_RSA_PUB_PEM,
                        "Code": "200",
                    }
                }),
                # Response to key exchange
                json.dumps({
                    "LL": {
                        "control": "dev/sys/keyexchange",
                        "value": "ok",
                        "Code": "200",
                    }
                }),
                # Response to getkey2
                json.dumps({
                    "LL": {
                        "control": "dev/sys/getkey2/admin",
                        "value": {
                            "key": "aa" * 32,
                            "salt": "bb" * 16,
                            "hashAlg": "SHA256",
                        },
                        "Code": "200",
                    }
                }),
                # Response to gettoken
                json.dumps({
                    "LL": {
                        "control": "dev/sys/gettoken",
                        "value": {
                            "token": "test-token-value",
                            "key": "cc" * 16,
                            "validUntil": 9999999999,
                            "tokenRights": 2,
                            "unsecurePass": False,
                        },
                        "Code": "200",
                    }
                }),
            ]
        )

        result = await authenticate(ws, "admin", "secret")
        assert result is True
        # First send should be getPublicKey request
        first_send = ws.send.call_args_list[0][0][0]
        assert "getPublicKey" in first_send

    async def test_key_exchange_sends_encrypted_session_key(self) -> None:
        """After getting RSA key, should send encrypted AES session key."""
        from loxone_exporter.loxone_auth import authenticate

        ws = AsyncMock()
        ws.recv = AsyncMock(
            side_effect=[
                json.dumps({
                    "LL": {
                        "control": "dev/sys/getPublicKey",
                        "value": _SAMPLE_RSA_PUB_PEM,
                        "Code": "200",
                    }
                }),
                json.dumps({
                    "LL": {
                        "control": "dev/sys/keyexchange",
                        "value": "ok",
                        "Code": "200",
                    }
                }),
                json.dumps({
                    "LL": {
                        "control": "dev/sys/getkey2/admin",
                        "value": {
                            "key": "aa" * 32,
                            "salt": "bb" * 16,
                            "hashAlg": "SHA256",
                        },
                        "Code": "200",
                    }
                }),
                json.dumps({
                    "LL": {
                        "control": "dev/sys/gettoken",
                        "value": {
                            "token": "tok",
                            "key": "cc" * 16,
                            "validUntil": 9999999999,
                            "tokenRights": 2,
                            "unsecurePass": False,
                        },
                        "Code": "200",
                    }
                }),
            ]
        )

        await authenticate(ws, "admin", "secret")
        # Second send should be keyexchange with base64 data
        second_send = ws.send.call_args_list[1][0][0]
        assert "keyexchange" in second_send

    async def test_hmac_credentials_computed(self) -> None:
        """Auth should compute HMAC of credentials with key from getkey2."""
        from loxone_exporter.loxone_auth import authenticate

        ws = AsyncMock()
        ws.recv = AsyncMock(
            side_effect=[
                json.dumps({
                    "LL": {
                        "control": "dev/sys/getPublicKey",
                        "value": _SAMPLE_RSA_PUB_PEM,
                        "Code": "200",
                    }
                }),
                json.dumps({
                    "LL": {
                        "control": "dev/sys/keyexchange",
                        "value": "ok",
                        "Code": "200",
                    }
                }),
                json.dumps({
                    "LL": {
                        "control": "dev/sys/getkey2/admin",
                        "value": {
                            "key": "aa" * 32,
                            "salt": "bb" * 16,
                            "hashAlg": "SHA256",
                        },
                        "Code": "200",
                    }
                }),
                json.dumps({
                    "LL": {
                        "control": "dev/sys/gettoken",
                        "value": {
                            "token": "tok",
                            "key": "cc" * 16,
                            "validUntil": 9999999999,
                            "tokenRights": 2,
                            "unsecurePass": False,
                        },
                        "Code": "200",
                    }
                }),
            ]
        )

        result = await authenticate(ws, "admin", "secret")
        assert result is True
        # The gettoken call is the 4th send — encrypted via AES
        token_send = ws.send.call_args_list[3][0][0]
        assert "jdev/sys/enc/" in token_send


class TestHashBasedAuth:
    """Hash-based fallback authentication (firmware 8.x)."""

    async def test_hash_based_fallback_on_token_failure(self) -> None:
        """If token-based auth fails, fall back to hash-based."""
        from loxone_exporter.loxone_auth import authenticate

        ws = AsyncMock()
        ws.recv = AsyncMock(
            side_effect=[
                # getPublicKey fails (old firmware)
                json.dumps({"LL": {"control": "dev/sys/getPublicKey", "Code": "500"}}),
                # Fallback: getkey response
                json.dumps({
                    "LL": {
                        "control": "dev/sys/getkey",
                        "value": "aabbccdd" * 4,
                        "Code": "200",
                    }
                }),
                # authenticate response
                json.dumps({
                    "LL": {
                        "control": "authenticate",
                        "value": "ok",
                        "Code": "200",
                    }
                }),
            ]
        )

        result = await authenticate(ws, "admin", "secret")
        assert result is True

    async def test_hash_based_uses_hmac_sha1(self) -> None:
        """Hash-based auth computes HMAC-SHA1 of user:password."""
        from loxone_exporter.loxone_auth import authenticate

        key_hex = "aabbccdd" * 4
        ws = AsyncMock()
        ws.recv = AsyncMock(
            side_effect=[
                json.dumps({"LL": {"control": "dev/sys/getPublicKey", "Code": "500"}}),
                json.dumps({"LL": {"control": "dev/sys/getkey", "value": key_hex, "Code": "200"}}),
                json.dumps({"LL": {"control": "authenticate", "value": "ok", "Code": "200"}}),
            ]
        )

        await authenticate(ws, "admin", "secret")
        # Verify authenticate command was sent
        auth_send = ws.send.call_args_list[-1][0][0]
        assert "authenticate/" in auth_send


class TestAuthenticationFailure:
    """Error handling during authentication."""

    async def test_auth_failure_raises_error(self) -> None:
        """Authentication failure should raise AuthenticationError."""
        from loxone_exporter.loxone_auth import AuthenticationError, authenticate

        ws = AsyncMock()
        ws.recv = AsyncMock(
            side_effect=[
                json.dumps({"LL": {"control": "dev/sys/getPublicKey", "Code": "500"}}),
                json.dumps({
                    "LL": {
                        "control": "dev/sys/getkey",
                        "value": "aabbccdd" * 4,
                        "Code": "200",
                    }
                }),
                # authenticate fails
                json.dumps({
                    "LL": {"control": "authenticate", "Code": "401"}
                }),
            ]
        )

        with pytest.raises(AuthenticationError):
            await authenticate(ws, "admin", "wrong")

    async def test_connection_error_during_auth(self) -> None:
        """Network error during auth should raise AuthenticationError."""
        from loxone_exporter.loxone_auth import AuthenticationError, authenticate

        ws = AsyncMock()
        ws.recv = AsyncMock(side_effect=ConnectionError("Connection lost"))

        with pytest.raises((AuthenticationError, ConnectionError)):
            await authenticate(ws, "admin", "secret")


# A real RSA-2048 public key for testing (not a secret — test-only)
_SAMPLE_RSA_PUB_PEM = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA0BMkI2+qRAzIdvxJtJH1\n"
    "+cYEuaDnzIQkBlZ4a8nbNUkf8yDAnl+js8GM8ui78DaLNdhibJXqqILuegNPT7jB\n"
    "x9Bjvap5CEC/ZnNTWAoj4GVuK1oZ+OAc6OhPQwlsuPmO6LsvDRdKJkm43pujbrsK\n"
    "VmBoQiP3p4IeV0tqQEEDlfvWK4kfJf8tvwXK4dUcgonjn/zDY/LbobbIWVIuzFvc\n"
    "oCH/gdvcRa+XtGAwpUk0iYjbwxfrk2NBuLF0yl8ETHcNOPOkmn3x4OePWK74HoWM\n"
    "/ryc698xhJz2Wv2DEA7xx1PBXXypwNAPqvavtFyAnsafi08remJ/KRsg6SDL7x3O\n"
    "9QIDAQAB\n"
    "-----END PUBLIC KEY-----"
)
