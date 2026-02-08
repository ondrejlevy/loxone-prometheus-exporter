"""Tests for the Loxone WebSocket binary protocol parser."""

from __future__ import annotations

import struct
import uuid

import pytest


def _make_header(msg_type: int, length: int, estimated: bool = False) -> bytes:
    """Build an 8-byte Loxone binary message header."""
    info = 0x01 if estimated else 0x00
    return struct.pack("<BBBxI", 0x03, msg_type, info, length)


def _uuid_to_loxone_bytes(uuid_str: str) -> bytes:
    """Convert a UUID string to Loxone little-endian bytes (16 bytes)."""
    return uuid.UUID(uuid_str).bytes_le


def _make_value_entry(uuid_str: str, value: float) -> bytes:
    """Build a single 24-byte VALUE_STATES entry."""
    return _uuid_to_loxone_bytes(uuid_str) + struct.pack("<d", value)


class TestParseHeader:
    def test_text_message_header(self) -> None:
        from loxone_exporter.loxone_protocol import parse_header

        header = _make_header(msg_type=0, length=256)
        result = parse_header(header)
        assert result.msg_type == 0
        assert result.exact_length == 256
        assert result.estimated is False

    def test_value_states_header(self) -> None:
        from loxone_exporter.loxone_protocol import parse_header

        header = _make_header(msg_type=2, length=480)
        result = parse_header(header)
        assert result.msg_type == 2
        assert result.exact_length == 480
        assert result.estimated is False

    def test_estimated_length_flag(self) -> None:
        from loxone_exporter.loxone_protocol import parse_header

        header = _make_header(msg_type=2, length=1000, estimated=True)
        result = parse_header(header)
        assert result.msg_type == 2
        assert result.estimated is True

    def test_keepalive_header(self) -> None:
        from loxone_exporter.loxone_protocol import parse_header

        header = _make_header(msg_type=6, length=0)
        result = parse_header(header)
        assert result.msg_type == 6
        assert result.exact_length == 0

    def test_out_of_service_header(self) -> None:
        from loxone_exporter.loxone_protocol import parse_header

        header = _make_header(msg_type=5, length=0)
        result = parse_header(header)
        assert result.msg_type == 5

    def test_too_short_data_raises(self) -> None:
        from loxone_exporter.loxone_protocol import parse_header

        with pytest.raises((ValueError, struct.error)):
            parse_header(b"\x03\x02")


class TestParseValueStates:
    UUID1 = "15beed5b-01ab-d81f-ffff-403fb0c34b9e"
    UUID2 = "0b47c5b3-002f-0f3e-ffff-403fb0c34b9e"

    def test_single_entry(self) -> None:
        from loxone_exporter.loxone_protocol import parse_value_states

        payload = _make_value_entry(self.UUID1, 22.5)
        result = parse_value_states(payload)
        assert len(result) == 1
        uid, val = result[0]
        assert uid == self.UUID1
        assert val == pytest.approx(22.5)

    def test_multiple_entries(self) -> None:
        from loxone_exporter.loxone_protocol import parse_value_states

        payload = _make_value_entry(self.UUID1, 22.5) + _make_value_entry(
            self.UUID2, 1.0
        )
        result = parse_value_states(payload)
        assert len(result) == 2
        assert result[0] == (self.UUID1, pytest.approx(22.5))
        assert result[1] == (self.UUID2, pytest.approx(1.0))

    def test_empty_payload(self) -> None:
        from loxone_exporter.loxone_protocol import parse_value_states

        result = parse_value_states(b"")
        assert result == []

    def test_zero_value(self) -> None:
        from loxone_exporter.loxone_protocol import parse_value_states

        payload = _make_value_entry(self.UUID1, 0.0)
        result = parse_value_states(payload)
        assert result[0][1] == pytest.approx(0.0)

    def test_negative_value(self) -> None:
        from loxone_exporter.loxone_protocol import parse_value_states

        payload = _make_value_entry(self.UUID1, -5.3)
        result = parse_value_states(payload)
        assert result[0][1] == pytest.approx(-5.3)

    def test_digital_value(self) -> None:
        from loxone_exporter.loxone_protocol import parse_value_states

        payload = _make_value_entry(self.UUID1, 1.0)
        result = parse_value_states(payload)
        assert result[0][1] == pytest.approx(1.0)

    def test_malformed_payload_partial_entry(self) -> None:
        """Partial entries at the end should be skipped gracefully."""
        from loxone_exporter.loxone_protocol import parse_value_states

        payload = _make_value_entry(self.UUID1, 22.5) + b"\x00" * 10
        result = parse_value_states(payload)
        # Should parse at least the first complete entry
        assert len(result) >= 1
        assert result[0][1] == pytest.approx(22.5)


class TestParseTextStates:
    UUID1 = "15beed5b-01ab-d81f-ffff-403fb0c34b9e"

    def _make_text_entry(self, uuid_str: str, text: str) -> bytes:
        """Build a single TEXT_STATES entry with UUID + icon UUID + text."""
        uuid_bytes = _uuid_to_loxone_bytes(uuid_str)
        icon_uuid_bytes = b"\x00" * 16  # placeholder icon UUID
        text_bytes = text.encode("utf-8") + b"\x00"  # null-terminated
        text_len = len(text_bytes)
        # Pad to 4-byte alignment
        padded_len = text_len + (4 - text_len % 4) % 4
        text_padded = text_bytes.ljust(padded_len, b"\x00")
        return uuid_bytes + icon_uuid_bytes + struct.pack("<I", text_len) + text_padded

    def test_single_text_entry(self) -> None:
        from loxone_exporter.loxone_protocol import parse_text_states

        payload = self._make_text_entry(self.UUID1, "Hello World")
        result = parse_text_states(payload)
        assert len(result) == 1
        uid, text = result[0]
        assert uid == self.UUID1
        assert text == "Hello World"

    def test_empty_text(self) -> None:
        from loxone_exporter.loxone_protocol import parse_text_states

        payload = self._make_text_entry(self.UUID1, "")
        result = parse_text_states(payload)
        assert len(result) == 1
        assert result[0][1] == ""

    def test_empty_payload(self) -> None:
        from loxone_exporter.loxone_protocol import parse_text_states

        result = parse_text_states(b"")
        assert result == []

    def test_utf8_text(self) -> None:
        from loxone_exporter.loxone_protocol import parse_text_states

        payload = self._make_text_entry(self.UUID1, "Teplota: 22.5°C")
        result = parse_text_states(payload)
        assert result[0][1] == "Teplota: 22.5°C"
