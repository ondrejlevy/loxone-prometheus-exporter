"""Loxone Miniserver authentication — token-based and hash-based flows.

Implements the authentication protocol per research.md R4:
- Token-based auth (firmware >= 9.x): RSA key exchange → AES session → HMAC credentials
- Hash-based fallback (firmware 8.x): HMAC-SHA1 of user:password
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
from typing import Any

from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication with the Miniserver fails."""


def _parse_response(data: str) -> dict[str, Any]:
    """Parse a Loxone JSON response, extracting the LL wrapper."""
    try:
        parsed = json.loads(data)
        result: dict[str, Any] = parsed.get("LL", parsed)
        return result
    except (json.JSONDecodeError, AttributeError):
        return {}


def _is_success(resp: dict[str, Any]) -> bool:
    """Check if a Loxone response indicates success."""
    code = str(resp.get("Code", ""))
    return code.startswith("2")


async def _token_auth(
    ws: Any,
    username: str,
    password: str,
) -> bool:
    """Attempt token-based authentication (firmware >= 9.x).

    Flow:
    1. Get RSA public key
    2. Generate AES session key + IV, encrypt with RSA, send key exchange
    3. Get key2 (salt + hash algorithm)
    4. Compute HMAC credentials
    5. Request token

    Returns True on success, raises AuthenticationError on failure.
    """
    # Step 1: Request RSA public key
    await ws.send("jdev/sys/getPublicKey")
    resp = _parse_response(await ws.recv())
    if not _is_success(resp):
        raise AuthenticationError("Failed to get RSA public key")

    pub_key_pem = str(resp.get("value", "")).strip()
    # Handle Loxone's key format (sometimes missing headers)
    if not pub_key_pem.startswith("-----BEGIN"):
        pub_key_pem = f"-----BEGIN PUBLIC KEY-----\n{pub_key_pem}\n-----END PUBLIC KEY-----"

    rsa_key = RSA.import_key(pub_key_pem)
    cipher_rsa = PKCS1_v1_5.new(rsa_key)

    # Step 2: Generate AES-256 session key + IV
    aes_key = secrets.token_bytes(32)  # 256-bit
    aes_iv = secrets.token_bytes(16)  # 128-bit
    session_key = aes_key + b":" + aes_iv

    # Encrypt session key with RSA
    encrypted_session = cipher_rsa.encrypt(session_key)
    b64_session = base64.b64encode(encrypted_session).decode("ascii")

    await ws.send(f"jdev/sys/keyexchange/{b64_session}")
    resp = _parse_response(await ws.recv())
    if not _is_success(resp):
        raise AuthenticationError("Key exchange failed")

    # Step 3: Get key2 for the user
    await ws.send(f"jdev/sys/getkey2/{username}")
    resp = _parse_response(await ws.recv())
    if not _is_success(resp):
        raise AuthenticationError(f"Failed to get key for user {username!r}")

    key_data = resp.get("value", {})
    key_hex = str(key_data.get("key", ""))
    salt_hex = str(key_data.get("salt", ""))
    hash_alg = str(key_data.get("hashAlg", "SHA256")).upper()

    key_bytes = bytes.fromhex(key_hex)
    salt_bytes = bytes.fromhex(salt_hex)

    # Step 4: Compute HMAC credentials
    if hash_alg == "SHA256":
        hash_func = hashlib.sha256
    elif hash_alg == "SHA1":
        hash_func = hashlib.sha1
    else:
        hash_func = hashlib.sha256

    # pw_hash = HMAC(user:password, key)
    pw_hash = hmac.new(key_bytes, f"{username}:{password}".encode(), hash_func).hexdigest()
    # final_hash = HMAC(user:pw_hash, salt)
    final_hash = hmac.new(salt_bytes, f"{username}:{pw_hash}".encode(), hash_func).hexdigest()

    # Step 5: Request token
    # Generate a unique UUID for this client session
    client_uuid = str(__import__("uuid").uuid4())
    client_name = "loxone-exporter"
    permission = 2  # web access

    # Encrypt the command with AES session key
    token_cmd = (
        f"salt/{salt_hex}/jdev/sys/gettoken/{final_hash}"
        f"/{username}/{permission}/{client_uuid}/{client_name}"
    )

    # For token-based, commands should be AES-encrypted after key exchange
    cipher_aes = AES.new(aes_key, AES.MODE_CBC, aes_iv)
    padded_cmd = pad(token_cmd.encode("utf-8"), AES.block_size)
    encrypted_cmd = cipher_aes.encrypt(padded_cmd)
    b64_cmd = base64.b64encode(encrypted_cmd).decode("ascii")

    await ws.send(f"jdev/sys/enc/{b64_cmd}")
    resp = _parse_response(await ws.recv())
    if not _is_success(resp):
        raise AuthenticationError("Token authentication failed")

    token_value = resp.get("value", {})
    if isinstance(token_value, dict):
        token_value.get("token", "")
        logger.info(
            "Token-based auth successful, token valid until %s",
            token_value.get("validUntil"),
        )
    else:
        logger.info("Token-based auth successful")

    return True


async def _hash_auth(
    ws: Any,
    username: str,
    password: str,
) -> bool:
    """Hash-based authentication fallback (firmware 8.x).

    Flow:
    1. Request one-time key
    2. Compute HMAC-SHA1(user:password, key)
    3. Send authenticate/{hash}

    Returns True on success, raises AuthenticationError on failure.
    """
    await ws.send("jdev/sys/getkey")
    resp = _parse_response(await ws.recv())
    if not _is_success(resp):
        raise AuthenticationError("Failed to get authentication key")

    key_hex = str(resp.get("value", ""))
    key_bytes = bytes.fromhex(key_hex)

    # HMAC-SHA1 of "user:password"
    hash_val = hmac.new(
        key_bytes,
        f"{username}:{password}".encode(),
        hashlib.sha1,
    ).hexdigest()

    await ws.send(f"authenticate/{hash_val}")
    resp = _parse_response(await ws.recv())
    if not _is_success(resp):
        raise AuthenticationError("Hash-based authentication failed")

    logger.info("Hash-based auth successful")
    return True


async def authenticate(
    ws: Any,
    username: str,
    password: str,
) -> bool:
    """Authenticate with a Loxone Miniserver over WebSocket.

    Attempts token-based authentication first (firmware >= 9.x).
    Falls back to hash-based authentication on failure.

    Args:
        ws: An open WebSocket connection.
        username: Loxone username.
        password: Loxone password.

    Returns:
        ``True`` on successful authentication.

    Raises:
        AuthenticationError: If both authentication methods fail.
    """
    try:
        return await _token_auth(ws, username, password)
    except AuthenticationError:
        logger.info("Token-based auth unavailable, falling back to hash-based auth")
    except Exception as exc:
        logger.debug("Token-based auth error: %s, trying hash-based fallback", exc)

    try:
        return await _hash_auth(ws, username, password)
    except AuthenticationError:
        raise
    except Exception as exc:
        raise AuthenticationError(f"Authentication failed: {exc}") from exc
