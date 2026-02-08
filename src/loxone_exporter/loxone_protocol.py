"""Loxone WebSocket binary protocol parser.

Handles the 8-byte header format, VALUE_STATES (24-byte packed entries),
and TEXT_STATES (variable-length UUID + text pairs) as documented in the
Loxone WebSocket protocol specification.
"""

from __future__ import annotations

import struct
import uuid
from dataclasses import dataclass

# Message type constants
MSG_TEXT = 0
MSG_BINARY = 1
MSG_VALUE_STATES = 2
MSG_TEXT_STATES = 3
MSG_DAYTIMER_STATES = 4
MSG_OUT_OF_SERVICE = 5
MSG_KEEPALIVE = 6
MSG_WEATHER_STATES = 7

_HEADER_SIZE = 8
_VALUE_ENTRY_SIZE = 24  # 16 bytes UUID + 8 bytes double


@dataclass(frozen=True)
class MessageHeader:
    """Parsed Loxone binary message header."""

    msg_type: int
    exact_length: int
    estimated: bool


def parse_header(data: bytes) -> MessageHeader:
    """Parse an 8-byte Loxone binary message header.

    Format: ``<BBBxI`` — start byte (0x03), message type, info flags, reserved, payload length.

    Args:
        data: Exactly 8 bytes of header data.

    Returns:
        Parsed :class:`MessageHeader`.

    Raises:
        ValueError: If *data* is too short.
        struct.error: If *data* cannot be unpacked.
    """
    if len(data) < _HEADER_SIZE:
        msg = f"Header requires {_HEADER_SIZE} bytes, got {len(data)}"
        raise ValueError(msg)

    _start, msg_type, info, length = struct.unpack("<BBBxI", data[:_HEADER_SIZE])
    estimated = bool(info & 0x01)
    return MessageHeader(msg_type=msg_type, exact_length=length, estimated=estimated)


def _uuid_from_bytes_le(data: bytes) -> str:
    """Convert 16 little-endian UUID bytes to a canonical UUID string."""
    return str(uuid.UUID(bytes_le=data))


def parse_value_states(payload: bytes) -> list[tuple[str, float]]:
    """Parse a VALUE_STATES payload into (uuid_str, value) tuples.

    Each entry is 24 bytes: 16 bytes UUID (little-endian) + 8 bytes double (LE).
    Incomplete trailing entries are silently ignored.

    Args:
        payload: Raw VALUE_STATES binary payload.

    Returns:
        List of ``(uuid_string, float_value)`` tuples.
    """
    results: list[tuple[str, float]] = []
    offset = 0
    while offset + _VALUE_ENTRY_SIZE <= len(payload):
        uid = _uuid_from_bytes_le(payload[offset : offset + 16])
        (value,) = struct.unpack("<d", payload[offset + 16 : offset + 24])
        results.append((uid, value))
        offset += _VALUE_ENTRY_SIZE
    return results


def parse_text_states(payload: bytes) -> list[tuple[str, str]]:
    """Parse a TEXT_STATES payload into (uuid_str, text) tuples.

    Each entry: 16B UUID + 16B icon UUID + 4B text length + text + padding to 4-byte boundary.

    Args:
        payload: Raw TEXT_STATES binary payload.

    Returns:
        List of ``(uuid_string, text_value)`` tuples.
    """
    results: list[tuple[str, str]] = []
    offset = 0

    while offset + 36 <= len(payload):  # Minimum: 16 UUID + 16 icon + 4 length
        uid = _uuid_from_bytes_le(payload[offset : offset + 16])
        offset += 16
        # Skip icon UUID
        offset += 16
        # Text length (including null terminator)
        (text_len,) = struct.unpack("<I", payload[offset : offset + 4])
        offset += 4

        if offset + text_len > len(payload):
            break

        text_raw = payload[offset : offset + text_len]
        # Strip null terminator
        text = text_raw.rstrip(b"\x00").decode("utf-8", errors="replace")
        results.append((uid, text))

        # Advance past text + padding to 4-byte boundary
        padded = text_len + (4 - text_len % 4) % 4
        offset += padded

    return results
