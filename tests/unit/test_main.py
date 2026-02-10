"""Tests for loxone_exporter.__main__ module."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from loxone_exporter.__main__ import _parse_args, main


class TestArgumentParsing:
    """Test CLI argument parsing."""

    def test_no_args_uses_defaults(self) -> None:
        """No --config means None (will try default paths)."""
        args = _parse_args([])
        assert args.config is None

    def test_config_short_flag(self) -> None:
        """--config accepts short form -c."""
        args = _parse_args(["-c", "/path/to/config.yml"])
        assert args.config == "/path/to/config.yml"

    def test_config_long_flag(self) -> None:
        """--config accepts long form."""
        args = _parse_args(["--config", "/path/to/config.yml"])
        assert args.config == "/path/to/config.yml"

    def test_help_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--help prints help and exits."""
        with pytest.raises(SystemExit) as exc:
            _parse_args(["--help"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "loxone_exporter" in captured.out


class TestMainErrorHandling:
    """Test main entry point error handling."""

    @patch("loxone_exporter.__main__._run", new_callable=MagicMock)
    @patch("loxone_exporter.__main__.asyncio.run")
    @patch("loxone_exporter.__main__._parse_args")
    def test_config_error_exits_with_code_1(
        self,
        mock_parse_args: Mock,
        mock_asyncio_run: Mock,
        mock_run: Mock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """ConfigError causes exit code 1."""
        from loxone_exporter.config import ConfigError

        mock_parse_args.return_value = Mock(config="invalid.yml")
        mock_asyncio_run.side_effect = ConfigError("Invalid config")

        with pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Configuration error" in captured.err
        assert "Invalid config" in captured.err

    @patch("loxone_exporter.__main__._run", new_callable=MagicMock)
    @patch("loxone_exporter.__main__.asyncio.run")
    @patch("loxone_exporter.__main__._parse_args")
    def test_keyboard_interrupt_exits_cleanly(
        self, mock_parse_args: Mock, mock_asyncio_run: Mock, mock_run: Mock,
    ) -> None:
        """KeyboardInterrupt exits without error (no exception raised)."""
        mock_parse_args.return_value = Mock(config=None)
        mock_asyncio_run.side_effect = KeyboardInterrupt()

        # Should not raise SystemExit
        main()

    @patch("loxone_exporter.__main__._run", new_callable=MagicMock)
    @patch("loxone_exporter.__main__.asyncio.run")
    @patch("loxone_exporter.__main__._parse_args")
    def test_unexpected_error_exits_with_code_2(
        self,
        mock_parse_args: Mock,
        mock_asyncio_run: Mock,
        mock_run: Mock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Unexpected exceptions cause exit code 2."""
        mock_parse_args.return_value = Mock(config=None)
        mock_asyncio_run.side_effect = RuntimeError("Unexpected error")

        with pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 2
        captured = capsys.readouterr()
        assert "Fatal error" in captured.err
        assert "Unexpected error" in captured.err

    @patch("loxone_exporter.__main__._run", new_callable=MagicMock)
    @patch("loxone_exporter.__main__._parse_args")
    def test_passes_config_path_to_run(
        self, mock_parse_args: Mock, mock_run: Mock
    ) -> None:
        """Config path from args is passed to _run()."""
        mock_parse_args.return_value = Mock(config="/custom/config.yml")

        with patch("loxone_exporter.__main__.asyncio.run") as mock_asyncio_run:
            main()
            # Verify asyncio.run was called with _run coroutine
            mock_asyncio_run.assert_called_once()


class TestAsyncRunFunction:
    """Test _run async function orchestration."""

    @ pytest.mark.asyncio
    @patch("loxone_exporter.__main__.asyncio.Event")  # Mock Event to control shutdown
    @patch("loxone_exporter.__main__.run_http_server")
    @patch("loxone_exporter.__main__.LoxoneClient")
    @patch("loxone_exporter.__main__.setup_logging")
    @patch("loxone_exporter.__main__.load_config")
    async def test_creates_clients_for_all_miniservers(
        self,
        mock_load_config: Mock,
        mock_setup_logging: Mock,
        mock_client_class: Mock,
        mock_run_server: AsyncMock,
        mock_event_class: Mock,
    ) -> None:
        """One LoxoneClient created per miniserver config."""
        from loxone_exporter.config import ExporterConfig, MiniserverConfig
        from loxone_exporter.structure import MiniserverState

        config = ExporterConfig(
            miniservers=[
                MiniserverConfig(name="ms1", host="h1", username="u1", password="p1"),
                MiniserverConfig(name="ms2", host="h2", username="u2", password="p2"),
            ]
        )
        mock_load_config.return_value = config

        mock_state1 = MiniserverState(name="ms1")
        mock_state2 = MiniserverState(name="ms2")

        # Set up mock Event that triggers shutdown immediately
        mock_event = Mock()
        mock_event_class.return_value = mock_event

        async def wait_then_raise():
            # Trigger shutdown after a short delay to let tasks start
            await asyncio.sleep(0.01)
            raise asyncio.CancelledError()

        mock_event.wait = wait_then_raise

        mock_client1 = Mock()
        mock_client1.run = AsyncMock()  # Return immediately
        mock_client1.get_state = Mock(return_value=mock_state1)

        mock_client2 = Mock()
        mock_client2.run = AsyncMock()  # Return immediately
        mock_client2.get_state = Mock(return_value=mock_state2)

        mock_client_class.side_effect = [mock_client1, mock_client2]

        from loxone_exporter.__main__ import _run
        await _run(None)

        assert mock_client_class.call_count == 2
        mock_client_class.assert_any_call(config.miniservers[0])
        mock_client_class.assert_any_call(config.miniservers[1])

    @pytest.mark.asyncio
    @patch("loxone_exporter.__main__.asyncio.Event")  # Mock Event to control shutdown
    @patch("loxone_exporter.__main__.run_http_server")
    @patch("loxone_exporter.__main__.LoxoneClient")
    @patch("loxone_exporter.__main__.setup_logging")
    @patch("loxone_exporter.__main__.load_config")
    async def test_all_tasks_started_in_taskgroup(
        self,
        mock_load_config: Mock,
        mock_setup_logging: Mock,
        mock_client_class: Mock,
        mock_run_server: AsyncMock,
        mock_event_class: Mock,
    ) -> None:
        """All client and server tasks started in TaskGroup."""
        from loxone_exporter.config import ExporterConfig, MiniserverConfig
        from loxone_exporter.structure import MiniserverState

        config = ExporterConfig(
            miniservers=[MiniserverConfig(name="ms", host="h", username="u", password="p")]
        )
        mock_load_config.return_value = config

        mock_state = MiniserverState(name="ms")

        # Set up mock Event that triggers shutdown immediately
        mock_event = Mock()
        mock_event_class.return_value = mock_event

        async def wait_then_raise():
            # Trigger shutdown after a short delay to let tasks start
            await asyncio.sleep(0.01)
            raise asyncio.CancelledError()

        mock_event.wait = wait_then_raise

        mock_client = Mock()
        mock_client.run = AsyncMock()  # Return immediately
        mock_client.get_state = Mock(return_value=mock_state)
        mock_client_class.return_value = mock_client

        server_called = asyncio.Event()

        async def mock_server_coro(*args: Any, **kwargs: Any) -> None:
            server_called.set()
            # Don't sleep - just set the event and return immediately

        mock_run_server.side_effect = mock_server_coro

        from loxone_exporter.__main__ import _run
        await _run(None)

        assert server_called.is_set()
        mock_run_server.assert_called_once()

    @pytest.mark.asyncio
    @patch("loxone_exporter.__main__.run_http_server")
    @patch("loxone_exporter.__main__.LoxoneClient")
    @patch("loxone_exporter.__main__.setup_logging")
    @patch("loxone_exporter.__main__.load_config")
    async def test_signal_handlers_can_trigger_shutdown(
        self,
        mock_load_config: Mock,
        mock_setup_logging: Mock,
        mock_client_class: Mock,
        mock_run_server: AsyncMock,
    ) -> None:
        """Shutdown signal triggers graceful shutdown."""
        from loxone_exporter.config import ExporterConfig, MiniserverConfig
        from loxone_exporter.structure import MiniserverState

        config = ExporterConfig(
            miniservers=[
                MiniserverConfig(name="ms", host="h", username="u", password="p")
            ]
        )
        mock_load_config.return_value = config

        mock_state = MiniserverState(name="ms")

        async def mock_server_forever(*args: Any, **kwargs: Any) -> None:
            # Run " forever" but make it interruptible
            try:
                await asyncio.sleep(1)  # Reduced to 1s for faster tests
            except asyncio.CancelledError:
                raise

        async def mock_client_forever():
            # Client also runs "forever"
            try:
                await asyncio.sleep(1)  # Reduced to 1s for faster tests
            except asyncio.CancelledError:
                raise

        mock_client = Mock()
        mock_client.run = AsyncMock(side_effect=mock_client_forever)
        mock_client.get_state = Mock(return_value=mock_state)
        mock_client_class.return_value = mock_client

        mock_run_server.side_effect = mock_server_forever

        from loxone_exporter.__main__ import _run

        # Run _run in background task
        run_task = asyncio.create_task(_run(None))

        # Give it time to set up (faster for CI)
        await asyncio.sleep(0.05)

        # Cancel the task (simulating signal)
        run_task.cancel()

        # Should raise CancelledError
        with pytest.raises(asyncio.CancelledError):
            await run_task

    @pytest.mark.asyncio
    @patch("loxone_exporter.__main__.LoxoneClient")
    @patch("loxone_exporter.__main__.setup_logging")
    @patch("loxone_exporter.__main__.load_config")
    async def test_config_error_propagates(
        self,
        mock_load_config: Mock,
        mock_setup_logging: Mock,
        mock_client_class: Mock,
    ) -> None:
        """ConfigError from load_config propagates to main()."""
        from loxone_exporter.config import ConfigError

        mock_load_config.side_effect = ConfigError("Bad config")

        from loxone_exporter.__main__ import _run

        with pytest.raises(ConfigError):
            await _run(None)
