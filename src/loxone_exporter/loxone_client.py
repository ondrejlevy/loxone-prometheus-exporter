"""Loxone Miniserver WebSocket client.

Manages the WebSocket connection lifecycle for a single Miniserver:
connect → authenticate → download structure → subscribe → receive loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import TYPE_CHECKING, Any

import websockets

from loxone_exporter.loxone_auth import AuthenticationError, authenticate
from loxone_exporter.loxone_protocol import (
    _HEADER_SIZE,
    MSG_KEEPALIVE,
    MSG_OUT_OF_SERVICE,
    MSG_TEXT_STATES,
    MSG_VALUE_STATES,
    parse_header,
    parse_text_states,
    parse_value_states,
)
from loxone_exporter.structure import MiniserverState, parse_structure

if TYPE_CHECKING:
    from loxone_exporter.config import MiniserverConfig

logger = logging.getLogger(__name__)


class LoxoneConnectionError(Exception):
    """Raised when connection to the Miniserver fails."""


class LoxoneClient:
    """WebSocket client for a single Loxone Miniserver.

    Manages the full lifecycle: connect, authenticate, discover structure,
    subscribe to binary status updates, and process incoming events.
    """

    def __init__(self, ms_config: MiniserverConfig) -> None:
        self._config = ms_config
        self._state = MiniserverState(name=ms_config.name)
        self._backoff = 1.0  # Initial backoff in seconds
        self._max_backoff = 30.0  # Max backoff per spec (FR-009 / SC-004)
        self._keepalive_interval = 30.0  # Send keepalive every 30s
        self._keepalive_timeout = 60.0  # Detect dead connection after 60s
        self._ws: Any = None
        self._keepalive_task: asyncio.Task[None] | None = None
        self._last_recv_time: float = 0.0

    def get_state(self) -> MiniserverState:
        """Return the current MiniserverState snapshot."""
        return self._state

    async def _connect_and_setup(self, ws: Any) -> None:
        """Authenticate, download structure, and subscribe on a new connection."""
        logger.info(
            "[%s] Connected to ws://%s:%d, authenticating...",
            self._config.name, self._config.host, self._config.port,
        )

        # Authenticate
        await authenticate(
            ws,
            self._config.username,
            self._config.password,
            host=self._config.host,
            port=self._config.port,
        )
        logger.info("[%s] Authentication successful", self._config.name)

        # Download structure file
        await ws.send("data/LoxAPP3.json")
        # Consume binary header frame(s): an estimated header is always
        # followed by an exact header before the actual payload.
        structure_data = await ws.recv()
        while isinstance(structure_data, bytes) and len(structure_data) == 8:
            hdr = parse_header(structure_data)
            logger.debug(
                "[%s] Structure header: type=%d estimated=%s len=%d",
                self._config.name, hdr.msg_type, hdr.estimated, hdr.exact_length,
            )
            structure_data = await ws.recv()

        if isinstance(structure_data, str):
            structure = json.loads(structure_data)
        else:
            structure = json.loads(structure_data.decode("utf-8"))

        # Parse structure
        controls, rooms, categories, state_map = parse_structure(structure)
        self._state.controls = controls
        self._state.rooms = rooms
        self._state.categories = categories
        self._state.state_map = state_map
        self._state.serial = structure.get("msInfo", {}).get("serialNr", "")
        self._state.firmware = str(structure.get("softwareVersion", ""))

        logger.info(
            "[%s] Structure loaded: %d controls, %d rooms, %d categories",
            self._config.name, len(controls), len(rooms), len(categories),
        )

        # Subscribe to binary status updates
        await ws.send("jdev/sps/enablebinstatusupdate")
        resp = await ws.recv()
        logger.info(
            "[%s] enablebinstatusupdate response (raw): type=%s len=%d",
            self._config.name, type(resp).__name__, len(resp)
        )
        # Consume binary header frame(s) if present
        consecutive_headers = 0
        while isinstance(resp, bytes) and len(resp) == 8:
            consecutive_headers += 1
            resp = await ws.recv()
            logger.debug(
                "[%s] Consumed header frame #%d, next: type=%s len=%d",
                self._config.name, consecutive_headers,
                type(resp).__name__, len(resp)
            )

        if isinstance(resp, str):
            logger.info(
                "[%s] enablebinstatusupdate JSON response: %s",
                self._config.name, resp[:500]
            )
        elif isinstance(resp, bytes):
            logger.info(
                "[%s] enablebinstatusupdate binary response: %d bytes",
                self._config.name, len(resp)
            )

        self._state.connected = True
        self._backoff = 1.0  # Reset backoff on success
        self._last_recv_time = time.monotonic()

    async def _keepalive_loop(self, ws: Any) -> None:
        """Send keepalive messages every 30 seconds."""
        try:
            while True:
                await asyncio.sleep(self._keepalive_interval)
                try:
                    await ws.send("keepalive")
                    logger.debug("[%s] Keepalive sent", self._config.name)
                except websockets.exceptions.ConnectionClosed:
                    break
        except asyncio.CancelledError:
            pass

    def _process_message(self, data: bytes) -> None:
        """Process a binary message from the Miniserver."""
        if len(data) < _HEADER_SIZE:
            logger.warning("[%s] Binary message too short: %d bytes", self._state.name, len(data))
            return

        header = parse_header(data[:_HEADER_SIZE])
        payload = data[_HEADER_SIZE:]

        if header.msg_type == MSG_VALUE_STATES:
            entries = parse_value_states(payload)
            logger.debug(
                "[%s] VALUE_STATES: %d entries, state_map has %d entries",
                self._state.name, len(entries), len(self._state.state_map)
            )
            if entries and len(self._state.state_map) > 0:
                # Log first few UUIDs for debugging
                sample_state_uuids = list(self._state.state_map.keys())[:3]
                sample_value_uuids = [uuid_str for uuid_str, _ in entries[:3]]
                logger.debug(
                    "[%s] Sample state_map UUIDs: %s",
                    self._state.name, sample_state_uuids
                )
                logger.debug(
                    "[%s] Sample VALUE_STATES UUIDs: %s",
                    self._state.name, sample_value_uuids
                )

            updated_count = 0
            for uuid_str, value in entries:
                ref = self._state.state_map.get(uuid_str)
                if ref:
                    ctrl = self._state.controls.get(ref.control_uuid)
                    if ctrl and ref.state_name in ctrl.states:
                        ctrl.states[ref.state_name].value = value
                        updated_count += 1
                    else:
                        # Check subcontrols
                        for parent in self._state.controls.values():
                            for sc in parent.sub_controls:
                                if sc.uuid == ref.control_uuid and ref.state_name in sc.states:
                                    sc.states[ref.state_name].value = value
                                    updated_count += 1
                                    break
                else:
                    logger.debug("[%s] Unknown state UUID: %s", self._state.name, uuid_str)
            if entries:
                self._state.last_update_ts = time.time()
                logger.debug(
                    "[%s] Updated %d/%d state values",
                    self._state.name, updated_count, len(entries)
                )

        elif header.msg_type == MSG_TEXT_STATES:
            text_entries = parse_text_states(payload)
            for uuid_str, text in text_entries:
                ref = self._state.state_map.get(uuid_str)
                if ref:
                    ctrl = self._state.controls.get(ref.control_uuid)
                    if ctrl and ref.state_name in ctrl.states:
                        ctrl.states[ref.state_name].text = text

        elif header.msg_type == MSG_KEEPALIVE:
            logger.debug("[%s] Keepalive response received", self._state.name)

        elif header.msg_type == MSG_OUT_OF_SERVICE:
            logger.warning("[%s] Miniserver going out of service", self._state.name)
            raise websockets.exceptions.ConnectionClosed(None, None)

    async def run(self) -> None:
        """Main client loop with auto-reconnect and exponential backoff.

        Runs until cancelled via ``asyncio.CancelledError``.
        """
        uri = f"ws://{self._config.host}:{self._config.port}/ws/rfc6455"

        while True:
            try:
                async with websockets.connect(uri) as ws:
                    self._ws = ws
                    try:
                        await self._connect_and_setup(ws)

                        # Start keepalive task
                        self._keepalive_task = asyncio.create_task(
                            self._keepalive_loop(ws)
                        )

                        # Receive loop
                        async for message in ws:
                            self._last_recv_time = time.monotonic()
                            if isinstance(message, bytes):
                                # Check if this is a header-only frame
                                if len(message) == _HEADER_SIZE:
                                    try:
                                        hdr = parse_header(message)
                                        logger.debug(
                                            "[%s] Received header: type=%d payload_len=%d",
                                            self._state.name, hdr.msg_type, hdr.exact_length,
                                        )
                                        # If there's a payload, receive it
                                        if hdr.exact_length > 0:
                                            payload = await ws.recv()
                                            if isinstance(payload, bytes):
                                                # Combine header + payload
                                                message = message + payload
                                                logger.debug(
                                                    "[%s] Received payload: %d bytes "
                                                    "(expected %d)",
                                                    self._state.name, len(payload),
                                                    hdr.exact_length,
                                                )
                                                self._process_message(message)
                                            else:
                                                logger.warning(
                                                    "[%s] Expected binary payload, got text: %s",
                                                    self._state.name, str(payload)[:100],
                                                )
                                        else:
                                            # Header with no payload (e.g., KEEPALIVE)
                                            self._process_message(message)
                                    except (
                                        websockets.exceptions.ConnectionClosed,
                                        websockets.exceptions.ConnectionClosedError,
                                        websockets.exceptions.ConnectionClosedOK,
                                    ):
                                        # Let connection closed exceptions propagate
                                        raise
                                    except Exception as e:
                                        logger.warning(
                                            "[%s] Error processing header frame: %s",
                                            self._state.name, e,
                                        )
                                elif len(message) > _HEADER_SIZE:
                                    # Complete message (header + payload in one frame)
                                    logger.debug(
                                        "[%s] Received complete message: %d bytes",
                                        self._state.name, len(message),
                                    )
                                    self._process_message(message)
                                else:
                                    logger.warning(
                                        "[%s] Received short binary frame: %d bytes",
                                        self._state.name, len(message),
                                    )
                            elif isinstance(message, str):
                                # Text messages (command responses during operation)
                                logger.debug(
                                    "[%s] Text message: %s",
                                    self._state.name,
                                    message[:200],
                                )

                    finally:
                        if self._keepalive_task:
                            self._keepalive_task.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await self._keepalive_task
                        self._state.connected = False
                        self._ws = None

            except asyncio.CancelledError:
                logger.info("[%s] Client shutting down", self._config.name)
                self._state.connected = False
                return

            except AuthenticationError as exc:
                logger.error(
                    "[%s] Authentication failed: %s. Retrying in %.0fs...",
                    self._config.name, exc, self._backoff,
                )

            except (
                websockets.exceptions.ConnectionClosed,
                websockets.exceptions.WebSocketException,
                OSError,
                ConnectionError,
            ) as exc:
                logger.warning(
                    "[%s] Connection lost: %s. Reconnecting in %.0fs...",
                    self._config.name, exc, self._backoff,
                )

            except Exception as exc:
                logger.exception(
                    "[%s] Unexpected error: %s. Reconnecting in %.0fs...",
                    self._config.name, exc, self._backoff,
                )

            # Exponential backoff
            self._state.connected = False
            await asyncio.sleep(self._backoff)
            self._backoff = min(self._backoff * 2, self._max_backoff)
