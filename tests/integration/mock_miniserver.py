"""Mock Loxone Miniserver WebSocket server for integration testing.

Simulates the Loxone WebSocket protocol:
- Accepts connections at /ws/rfc6455
- Responds to auth handshake commands
- Serves a sample LoxAPP3.json structure
- Sends VALUE_STATES binary frames
- Supports enablebinstatusupdate command
"""

from __future__ import annotations

import contextlib
import json
import struct
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import websockets

if TYPE_CHECKING:
    from websockets.asyncio.server import ServerConnection

# Binary message types
MSG_TEXT = 0
MSG_VALUE_STATES = 2
MSG_TEXT_STATES = 3
MSG_KEEPALIVE = 6


def _make_binary_header(msg_type: int, payload_length: int) -> bytes:
    """Build an 8-byte Loxone binary header."""
    return struct.pack("<BBBxI", 0x03, msg_type, 0x00, payload_length)


def _uuid_to_bytes_le(uuid_str: str) -> bytes:
    """Convert a UUID string to 16 little-endian bytes."""
    return uuid.UUID(uuid_str).bytes_le


def _make_value_entry(uuid_str: str, value: float) -> bytes:
    """Build a 24-byte VALUE_STATES entry."""
    return _uuid_to_bytes_le(uuid_str) + struct.pack("<d", value)


@dataclass
class MockMiniserverConfig:
    """Configuration for the mock miniserver."""

    host: str = "127.0.0.1"
    port: int = 0  # 0 = auto-assign
    structure: dict[str, Any] = field(default_factory=dict)
    value_entries: list[tuple[str, float]] = field(default_factory=list)
    auth_username: str = "admin"
    auth_password: str = "secret"
    fail_auth: bool = False
    rsa_pub_key: str = ""


class MockMiniserver:
    """A mock Loxone Miniserver that speaks the WS binary protocol."""

    def __init__(self, config: MockMiniserverConfig) -> None:
        self.config = config
        self._server: Any = None
        self._clients: list[ServerConnection] = []
        self._authenticated: set[ServerConnection] = set()
        self._subscribed: set[ServerConnection] = set()

    @property
    def port(self) -> int:
        """Return the actual port after server starts."""
        if self._server is None:
            return 0
        return self._server.sockets[0].getsockname()[1]

    async def start(self) -> None:
        """Start the mock WebSocket server."""
        self._server = await websockets.serve(
            self._handler,
            self.config.host,
            self.config.port,
        )

    async def stop(self) -> None:
        """Stop the mock server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def send_value_update(self, uuid_str: str, value: float) -> None:
        """Send a VALUE_STATES update to all subscribed clients."""
        entry = _make_value_entry(uuid_str, value)
        header = _make_binary_header(MSG_VALUE_STATES, len(entry))
        payload = header + entry
        for ws in list(self._subscribed):
            try:
                await ws.send(payload)
            except websockets.exceptions.ConnectionClosed:
                self._subscribed.discard(ws)

    async def send_out_of_service(self) -> None:
        """Send an OUT_OF_SERVICE message to all clients."""
        header = _make_binary_header(5, 0)
        for ws in list(self._clients):
            with contextlib.suppress(websockets.exceptions.ConnectionClosed):
                await ws.send(header)

    async def _handler(self, ws: ServerConnection) -> None:
        """Handle a single WebSocket connection."""
        self._clients.append(ws)
        try:
            async for message in ws:
                if isinstance(message, str):
                    await self._handle_text(ws, message)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.remove(ws)
            self._authenticated.discard(ws)
            self._subscribed.discard(ws)

    async def _handle_text(self, ws: ServerConnection, message: str) -> None:
        """Handle a text command from the client."""
        msg = message.strip()

        if "getPublicKey" in msg:
            if self.config.rsa_pub_key:
                await ws.send(json.dumps({
                    "LL": {
                        "control": "dev/sys/getPublicKey",
                        "value": self.config.rsa_pub_key,
                        "Code": "200",
                    }
                }))
            else:
                await ws.send(json.dumps({
                    "LL": {"control": "dev/sys/getPublicKey", "Code": "500"}
                }))

        elif "keyexchange" in msg:
            await ws.send(json.dumps({
                "LL": {"control": "dev/sys/keyexchange", "value": "ok", "Code": "200"}
            }))

        elif "getkey2" in msg:
            await ws.send(json.dumps({
                "LL": {
                    "control": f"dev/sys/getkey2/{self.config.auth_username}",
                    "value": {"key": "aa" * 32, "salt": "bb" * 16, "hashAlg": "SHA256"},
                    "Code": "200",
                }
            }))

        elif "gettoken" in msg:
            if self.config.fail_auth:
                await ws.send(json.dumps({
                    "LL": {"control": "dev/sys/gettoken", "Code": "401"}
                }))
            else:
                self._authenticated.add(ws)
                await ws.send(json.dumps({
                    "LL": {
                        "control": "dev/sys/gettoken",
                        "value": {
                            "token": "mock-token",
                            "key": "cc" * 16,
                            "validUntil": 9999999999,
                            "tokenRights": 2,
                            "unsecurePass": False,
                        },
                        "Code": "200",
                    }
                }))

        elif "getkey" in msg and "getkey2" not in msg:
            await ws.send(json.dumps({
                "LL": {"control": "dev/sys/getkey", "value": "aabbccdd" * 4, "Code": "200"}
            }))

        elif "authenticate/" in msg:
            if self.config.fail_auth:
                await ws.send(json.dumps({
                    "LL": {"control": "authenticate", "Code": "401"}
                }))
            else:
                self._authenticated.add(ws)
                await ws.send(json.dumps({
                    "LL": {"control": "authenticate", "value": "ok", "Code": "200"}
                }))

        elif "data/LoxAPP3.json" in msg or "LoxAPP3.json" in msg:
            await ws.send(json.dumps(self.config.structure))

        elif "enablebinstatusupdate" in msg:
            self._subscribed.add(ws)
            # Acknowledge
            await ws.send(json.dumps({
                "LL": {"control": "dev/sps/enablebinstatusupdate", "value": "1", "Code": "200"}
            }))
            # Send initial value states
            if self.config.value_entries:
                payload = b""
                for uid, val in self.config.value_entries:
                    payload += _make_value_entry(uid, val)
                header = _make_binary_header(MSG_VALUE_STATES, len(payload))
                await ws.send(header + payload)

        elif msg == "keepalive":
            header = _make_binary_header(MSG_KEEPALIVE, 0)
            await ws.send(header)

        else:
            # Generic OK response
            await ws.send(json.dumps({
                "LL": {"control": msg, "value": "ok", "Code": "200"}
            }))
