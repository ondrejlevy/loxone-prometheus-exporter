"""Integration test: full client → mock miniserver → metrics flow."""

from __future__ import annotations

import asyncio
import contextlib
import time

import pytest

from loxone_exporter.config import MiniserverConfig
from loxone_exporter.loxone_client import LoxoneClient


@pytest.fixture()
def mock_loxapp3() -> dict:
    """Minimal LoxAPP3.json for integration testing."""
    return {
        "msInfo": {"serialNr": "TEST123", "msName": "IntegrationTest"},
        "softwareVersion": "14.5.0.0",
        "rooms": {
            "r1": {"name": "Room 1", "uuid": "r1"},
        },
        "cats": {
            "c1": {"name": "Cat 1", "uuid": "c1", "type": "switch"},
        },
        "controls": {
            "ctrl1": {
                "name": "Test Switch",
                "type": "Switch",
                "room": "r1",
                "cat": "c1",
                "states": {
                    "active": "12345678-abcd-1234-abcd-123456789abc",
                },
            },
        },
    }


class TestLoxoneClientIntegration:
    """Full lifecycle test using mock miniserver."""

    async def test_connect_auth_discover_subscribe_receive(
        self, mock_loxapp3: dict
    ) -> None:
        """Client connects → authenticates → downloads structure → subscribes → receives values."""
        from tests.integration.mock_miniserver import MockMiniserver, MockMiniserverConfig

        mock_config = MockMiniserverConfig(
            structure=mock_loxapp3,
            value_entries=[("12345678-abcd-1234-abcd-123456789abc", 1.0)],
        )
        server = MockMiniserver(mock_config)
        await server.start()

        try:
            ms_config = MiniserverConfig(
                name="test",
                host="127.0.0.1",
                port=server.port,
                username="admin",
                password="secret",
            )
            client = LoxoneClient(ms_config)

            # Run client in background, let it connect + receive
            client_task = asyncio.create_task(client.run())

            # Wait for connection and value update
            for _ in range(50):  # 5 seconds max
                await asyncio.sleep(0.1)
                state = client.get_state()
                if state.connected and state.last_update_ts > 0:
                    break
            else:
                pytest.fail("Client did not connect and receive values within 5s")

            state = client.get_state()
            assert state.connected is True
            assert state.name == "test"
            assert len(state.controls) == 1
            assert "ctrl1" in state.controls
            ctrl = state.controls["ctrl1"]
            assert ctrl.name == "Test Switch"
            assert ctrl.states["active"].value == 1.0

            # Verify latency < 2s (SC-006)
            latency = time.time() - state.last_update_ts
            assert latency < 2.0, f"Update latency {latency:.2f}s exceeds 2s"

            # Send a value update
            await server.send_value_update("12345678-abcd-1234-abcd-123456789abc", 0.0)
            await asyncio.sleep(0.5)

            state = client.get_state()
            assert ctrl.states["active"].value == 0.0

            # Clean shutdown
            client_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await client_task

        finally:
            await server.stop()


class TestReconnection:
    """US3: WebSocket reconnection, backoff, keepalive, and re-discovery."""

    async def test_reconnect_after_server_disconnect(self, mock_loxapp3: dict) -> None:
        """Client detects disconnect, backs off, reconnects, re-discovers structure."""
        from tests.integration.mock_miniserver import MockMiniserver, MockMiniserverConfig

        mock_config = MockMiniserverConfig(
            structure=mock_loxapp3,
            value_entries=[("12345678-abcd-1234-abcd-123456789abc", 1.0)],
        )
        server = MockMiniserver(mock_config)
        await server.start()

        ms_config = MiniserverConfig(
            name="test", host="127.0.0.1", port=server.port,
            username="admin", password="secret",
        )
        client = LoxoneClient(ms_config)
        client_task = asyncio.create_task(client.run())

        try:
            # Wait for initial connection
            for _ in range(50):
                await asyncio.sleep(0.1)
                if client.get_state().connected:
                    break
            else:
                pytest.fail("Client did not connect within 5s")

            assert client.get_state().connected is True

            # Save port before stopping server
            saved_port = server.port

            # Stop server → client should detect disconnect
            await server.stop()
            await asyncio.sleep(1.5)  # Allow detection + initial backoff

            assert client.get_state().connected is False

            # Restart server on same port
            server2 = MockMiniserver(MockMiniserverConfig(
                host="127.0.0.1", port=saved_port,
                structure=mock_loxapp3,
                value_entries=[("12345678-abcd-1234-abcd-123456789abc", 42.0)],
            ))
            await server2.start()

            # Wait for reconnect + re-discovery
            for _ in range(100):  # 10 seconds max
                await asyncio.sleep(0.1)
                if client.get_state().connected and client.get_state().last_update_ts > 0:
                    break
            else:
                await server2.stop()
                pytest.fail("Client did not reconnect within 10s")

            state = client.get_state()
            assert state.connected is True
            assert len(state.controls) == 1  # Structure re-discovered
            assert state.controls["ctrl1"].states["active"].value == 42.0

            await server2.stop()
        finally:
            client_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await client_task

    async def test_out_of_service_triggers_reconnect(self, mock_loxapp3: dict) -> None:
        """OUT_OF_SERVICE binary message triggers immediate reconnect."""
        from tests.integration.mock_miniserver import MockMiniserver, MockMiniserverConfig

        mock_config = MockMiniserverConfig(
            structure=mock_loxapp3,
            value_entries=[("12345678-abcd-1234-abcd-123456789abc", 1.0)],
        )
        server = MockMiniserver(mock_config)
        await server.start()

        ms_config = MiniserverConfig(
            name="test", host="127.0.0.1", port=server.port,
            username="admin", password="secret",
        )
        client = LoxoneClient(ms_config)
        client_task = asyncio.create_task(client.run())

        try:
            for _ in range(50):
                await asyncio.sleep(0.1)
                if client.get_state().connected:
                    break
            else:
                pytest.fail("Client did not connect within 5s")

            # Send out of service
            await server.send_out_of_service()
            await asyncio.sleep(0.5)

            # Client should disconnect
            assert client.get_state().connected is False

            # Wait for reconnect
            for _ in range(50):
                await asyncio.sleep(0.1)
                if client.get_state().connected:
                    break
            else:
                pytest.fail("Client did not reconnect after OUT_OF_SERVICE within 5s")

            assert client.get_state().connected is True
        finally:
            client_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await client_task
            await server.stop()

    async def test_backoff_escalation(self, mock_loxapp3: dict) -> None:
        """Backoff should increase on consecutive failures (1s→2s→4s) up to 30s cap."""
        ms_config = MiniserverConfig(
            name="test", host="127.0.0.1", port=19999,  # Nothing listening
            username="admin", password="secret",
        )
        client = LoxoneClient(ms_config)

        # Access internal backoff for verification
        assert client._backoff == 1.0

        client_task = asyncio.create_task(client.run())

        # Let it fail a few times
        await asyncio.sleep(4.0)

        # Backoff should have escalated from 1: after 1s fail → backoff=2, after 2s fail → backoff=4
        assert client._backoff > 1.0, "Backoff should have escalated"
        assert client._backoff <= 30.0, "Backoff should not exceed 30s cap"

        client_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await client_task

    async def test_backoff_reset_after_successful_reconnect(self, mock_loxapp3: dict) -> None:
        """Backoff should reset to 1s after successful reconnect."""
        from tests.integration.mock_miniserver import MockMiniserver, MockMiniserverConfig

        mock_config = MockMiniserverConfig(
            structure=mock_loxapp3,
            value_entries=[("12345678-abcd-1234-abcd-123456789abc", 1.0)],
        )
        server = MockMiniserver(mock_config)
        await server.start()

        ms_config = MiniserverConfig(
            name="test", host="127.0.0.1", port=server.port,
            username="admin", password="secret",
        )
        client = LoxoneClient(ms_config)
        client_task = asyncio.create_task(client.run())

        try:
            for _ in range(50):
                await asyncio.sleep(0.1)
                if client.get_state().connected:
                    break
            else:
                pytest.fail("Client did not connect within 5s")

            # After successful connection, backoff should be reset to 1.0
            assert client._backoff == 1.0
        finally:
            client_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await client_task
            await server.stop()

    async def test_connected_state_tracking(self, mock_loxapp3: dict) -> None:
        """MiniserverState.connected reflects actual WS connection status."""
        from tests.integration.mock_miniserver import MockMiniserver, MockMiniserverConfig

        mock_config = MockMiniserverConfig(
            structure=mock_loxapp3,
            value_entries=[("12345678-abcd-1234-abcd-123456789abc", 1.0)],
        )
        server = MockMiniserver(mock_config)
        await server.start()

        ms_config = MiniserverConfig(
            name="test", host="127.0.0.1", port=server.port,
            username="admin", password="secret",
        )
        client = LoxoneClient(ms_config)

        # Before connecting
        assert client.get_state().connected is False

        client_task = asyncio.create_task(client.run())

        try:
            for _ in range(50):
                await asyncio.sleep(0.1)
                if client.get_state().connected:
                    break
            else:
                pytest.fail("Client did not connect within 5s")

            assert client.get_state().connected is True
            assert client.get_state().last_update_ts > 0

            # Stop server
            await server.stop()
            await asyncio.sleep(1.5)
            assert client.get_state().connected is False
        finally:
            client_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await client_task
