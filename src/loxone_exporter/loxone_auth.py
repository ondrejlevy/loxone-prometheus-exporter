"""Loxone Miniserver authentication — token-based and hash-based flows.

Implements the authentication protocol per Loxone "Communicating with
Miniserver" documentation and validated against PyLoxone / lxcommunicator:
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
import urllib.parse
from typing import Any

from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.Hash import HMAC as CryptoHMAC
from Crypto.Hash import SHA1 as CryptoSHA1
from Crypto.Hash import SHA256 as CryptoSHA256
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
    # Loxone may use 'Code' or 'code' depending on context (e.g. after key exchange)
    code = str(resp.get("Code", resp.get("code", "")))
    return code.startswith("2")


async def _recv_text(ws: Any) -> str:
    """Receive a Loxone text response, consuming the binary header frame first.

    The Miniserver sends every response as two WebSocket frames:
    1. A binary 8-byte header (start=0x03, msg_type, info, payload length)
    2. A text frame with the actual JSON payload

    This helper transparently consumes the binary header and returns only the
    text payload that callers can pass to ``_parse_response``.
    """
    msg = await ws.recv()
    # If first frame is the 8-byte binary header, read the next (text) frame
    if isinstance(msg, bytes):
        msg = await ws.recv()
    return msg if isinstance(msg, str) else msg.decode("utf-8", errors="replace")


async def _fetch_public_key_http(
    host: str,
    port: int,
    username: str,
    password: str,
) -> str:
    """Fetch RSA public key via HTTP (required on modern firmware)."""
    import urllib.request

    url = f"http://{host}:{port}/jdev/sys/getPublicKey"
    req = urllib.request.Request(url)
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    req.add_header("Authorization", f"Basic {credentials}")

    with urllib.request.urlopen(req, timeout=10) as response:
        data = json.loads(response.read())

    resp = data.get("LL", data)
    if not _is_success(resp):
        raise AuthenticationError("Failed to get RSA public key via HTTP")

    return str(resp.get("value", "")).strip()


def _normalize_public_key(raw_key: str) -> str:
    """Convert Loxone public key/certificate PEM to importable format.

    Loxone may return the key wrapped as ``BEGIN CERTIFICATE`` instead of
    ``BEGIN PUBLIC KEY``.  PyCryptodome's ``RSA.import_key`` only accepts
    the latter, so we rewrite the header/footer when necessary.
    """
    pem = raw_key.strip()
    pem = pem.replace(
        "-----BEGIN CERTIFICATE-----",
        "-----BEGIN PUBLIC KEY-----\n",
    ).replace(
        "-----END CERTIFICATE-----",
        "\n-----END PUBLIC KEY-----\n",
    )
    if not pem.startswith("-----BEGIN"):
        pem = f"-----BEGIN PUBLIC KEY-----\n{pem}\n-----END PUBLIC KEY-----"
    return pem


def _encrypt_ws_command(
    cmd: str,
    aes_key: bytes,
    aes_iv: bytes,
    salt: str,
) -> str:
    """Encrypt a WebSocket command for the Loxone Miniserver.

    The Loxone protocol requires:
    1. ``salt/{hex_salt}/{command}\\x00`` — null-terminated, salt-prefixed
    2. PKCS#7 padded to AES block size
    3. AES-256-CBC encrypted
    4. Base64 encoded
    5. **URL-encoded** — critical because base64 contains ``/`` and ``+``
       that are otherwise interpreted as path separators.

    Returns the URL-encoded base64 cipher ready for ``jdev/sys/enc/{cipher}``.
    """
    plaintext = f"salt/{salt}/{cmd}\x00"
    padded = pad(plaintext.encode("utf-8"), AES.block_size)
    cipher = AES.new(aes_key, AES.MODE_CBC, iv=aes_iv)
    encrypted = cipher.encrypt(padded)
    b64 = base64.b64encode(encrypted).decode("ascii")
    return urllib.parse.quote(b64)


async def _token_auth(
    ws: Any,
    username: str,
    password: str,
    *,
    public_key_pem: str | None = None,
) -> bool:
    """Attempt token-based authentication (firmware >= 9.x).

    Flow:
    1. Get RSA public key (from *public_key_pem* or via WebSocket)
    2. Generate AES session key + IV, encrypt with RSA, send key exchange
    3. Get key2 (salt + hash algorithm)
    4. Compute HMAC credentials
    5. Request JWT / token (encrypted)

    Returns True on success, raises AuthenticationError on failure.
    """
    # Step 1: Obtain RSA public key
    if public_key_pem is None:
        await ws.send("jdev/sys/getPublicKey")
        resp = _parse_response(await _recv_text(ws))
        if not _is_success(resp):
            raise AuthenticationError("Failed to get RSA public key")
        public_key_pem = str(resp.get("value", "")).strip()

    pub_key_pem = _normalize_public_key(public_key_pem)

    rsa_key = RSA.import_key(pub_key_pem)
    cipher_rsa = PKCS1_v1_5.new(rsa_key)

    # Step 2: Generate AES-256 session key + IV
    aes_key = secrets.token_bytes(32)  # 256-bit
    aes_iv = secrets.token_bytes(16)  # 128-bit
    # Loxone expects hex-encoded key:iv
    session_key = f"{aes_key.hex()}:{aes_iv.hex()}".encode("utf-8")

    # Encrypt session key with RSA
    encrypted_session = cipher_rsa.encrypt(session_key)
    b64_session = base64.b64encode(encrypted_session).decode("ascii")

    await ws.send(f"jdev/sys/keyexchange/{b64_session}")
    resp = _parse_response(await _recv_text(ws))
    if not _is_success(resp):
        raise AuthenticationError("Key exchange failed")

    # Step 3: Get key2 for the user
    await ws.send(f"jdev/sys/getkey2/{username}")
    resp = _parse_response(await _recv_text(ws))
    if not _is_success(resp):
        raise AuthenticationError(f"Failed to get key for user {username!r}")

    key_data = resp.get("value", {})
    # The Miniserver returns key/salt as hex-encoded strings; use them directly
    # per PyLoxone convention (bytes.fromhex gives the HMAC key bytes).
    key_hex = str(key_data.get("key", ""))
    user_salt = str(key_data.get("salt", ""))
    hash_alg = str(key_data.get("hashAlg", "SHA256")).upper()

    key_bytes = bytes.fromhex(key_hex)

    # Step 4: Compute HMAC credentials (per Loxone protocol / PyLoxone)
    if hash_alg == "SHA1":
        hash_func = hashlib.sha1
        crypto_hash_mod = CryptoSHA1
    else:  # SHA256 or unknown → default to SHA256
        hash_func = hashlib.sha256
        crypto_hash_mod = CryptoSHA256

    # pwd_hash = HASH("password:user_salt") → uppercase hex
    pwd_hash = hash_func(
        f"{password}:{user_salt}".encode("utf-8")
    ).hexdigest().upper()
    # final_hash = HMAC(key, "username:pwd_hash")
    digester = CryptoHMAC.new(
        key_bytes, f"{username}:{pwd_hash}".encode("utf-8"), crypto_hash_mod,
    )
    final_hash = digester.hexdigest()

    # Step 5: Request JWT (firmware >= 10.2) or token
    client_uuid = "edfc5f9a-df3f-4cad-9dffac30c150c33e"
    client_name = "loxone-exporter"
    permission = 2  # web access (short-lived)

    # Random encryption salt (16 bytes = 32 hex chars, per PyLoxone)
    enc_salt = secrets.token_bytes(16).hex()

    # Use getjwt for modern firmware, gettoken as fallback
    token_cmd = (
        f"jdev/sys/getjwt/{final_hash}"
        f"/{username}/{permission}/{client_uuid}/{client_name}"
    )

    enc_cmd = _encrypt_ws_command(token_cmd, aes_key, aes_iv, enc_salt)
    await ws.send(f"jdev/sys/enc/{enc_cmd}")
    resp = _parse_response(await _recv_text(ws))

    if not _is_success(resp):
        # Try gettoken for older firmware
        logger.debug("getjwt failed (code %s), trying gettoken",
                     resp.get("Code", resp.get("code")))
        token_cmd_legacy = (
            f"jdev/sys/gettoken/{final_hash}"
            f"/{username}/{permission}/{client_uuid}/{client_name}"
        )
        enc_cmd2 = _encrypt_ws_command(token_cmd_legacy, aes_key, aes_iv, enc_salt)
        await ws.send(f"jdev/sys/enc/{enc_cmd2}")
        resp = _parse_response(await _recv_text(ws))
        if not _is_success(resp):
            raise AuthenticationError("Token authentication failed")

    token_value = resp.get("value", {})
    if isinstance(token_value, dict):
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
    resp = _parse_response(await _recv_text(ws))
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
    resp = _parse_response(await _recv_text(ws))
    if not _is_success(resp):
        raise AuthenticationError("Hash-based authentication failed")

    logger.info("Hash-based auth successful")
    return True


async def authenticate(
    ws: Any,
    username: str,
    password: str,
    *,
    host: str = "",
    port: int = 80,
) -> bool:
    """Authenticate with a Loxone Miniserver over WebSocket.

    Attempts token-based authentication first (firmware >= 9.x).
    Falls back to hash-based authentication on failure.

    On modern firmware the RSA public key is not available over WebSocket;
    when *host* is provided the function will retry by fetching it via HTTP.

    Args:
        ws: An open WebSocket connection.
        username: Loxone username.
        password: Loxone password.
        host: Miniserver host (used for HTTP public-key fallback).
        port: Miniserver HTTP port.

    Returns:
        ``True`` on successful authentication.

    Raises:
        AuthenticationError: If both authentication methods fail.
    """
    # --- attempt 1: token auth with WS-provided public key ---
    try:
        return await _token_auth(ws, username, password)
    except AuthenticationError:
        logger.info("Token-based auth via WS unavailable")
    except Exception as exc:
        logger.debug("Token-based auth error (WS key): %s", exc)

    # --- attempt 2: token auth with HTTP-provided public key ---
    if host:
        try:
            pk = await _fetch_public_key_http(host, port, username, password)
            logger.info("Fetched RSA public key via HTTP, retrying token auth")
            return await _token_auth(ws, username, password, public_key_pem=pk)
        except AuthenticationError:
            logger.info("Token-based auth (HTTP key) also failed, trying hash fallback")
        except Exception as exc:
            logger.debug("Token-based auth error (HTTP key): %s", exc)

    # --- attempt 3: legacy hash-based auth ---
    try:
        return await _hash_auth(ws, username, password)
    except AuthenticationError:
        raise
    except Exception as exc:
        raise AuthenticationError(f"Authentication failed: {exc}") from exc
