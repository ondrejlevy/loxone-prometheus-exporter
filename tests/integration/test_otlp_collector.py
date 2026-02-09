"""Integration tests for OTLP collector interaction.

Covers tasks T028, T029, T040, T041, T042.
Uses a mock OTLP collector (gRPC) to verify end-to-end export flow.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

# ── T028: Mock OTLP Collector Fixture ─────────────────────────────────


@pytest.fixture()
def mock_sdk_exporter() -> MagicMock:
    """Create a mock SDK MetricExporter that tracks calls."""
    from opentelemetry.sdk.metrics.export import MetricExportResult

    exporter = MagicMock()
    exporter.export.return_value = MetricExportResult.SUCCESS
    exporter.shutdown.return_value = None
    return exporter


@pytest.fixture()
def sample_registry() -> CollectorRegistry:
    """Create a registry with some sample metrics."""
    registry = CollectorRegistry()
    g = Gauge("test_temp", "Temperature", ["room"], registry=registry)
    g.labels(room="living").set(22.5)
    g.labels(room="bedroom").set(19.0)

    c = Counter("test_requests", "Total requests", registry=registry)
    c.inc(42)

    h = Histogram(
        "test_duration", "Duration", buckets=[0.1, 0.5, 1.0], registry=registry
    )
    h.observe(0.3)
    h.observe(0.7)
    return registry


def _make_otlp_config(**overrides):
    from loxone_exporter.config import AuthConfig, OTLPConfiguration, TLSConfig

    defaults = {
        "enabled": True,
        "endpoint": "http://localhost:4317",
        "protocol": "grpc",
        "interval_seconds": 10,
        "timeout_seconds": 5,
        "tls_config": TLSConfig(),
        "auth_config": AuthConfig(),
    }
    defaults.update(overrides)
    return OTLPConfiguration(**defaults)


# ── T029: Successful Export Flow ──────────────────────────────────────


class TestSuccessfulExportFlow:
    """Integration tests for successful OTLP export cycle."""

    @pytest.mark.asyncio()
    async def test_export_once_success(
        self, mock_sdk_exporter: MagicMock, sample_registry: CollectorRegistry
    ) -> None:
        from loxone_exporter.otlp_exporter import ExportState, OTLPExporter

        config = _make_otlp_config()
        with patch(
            "loxone_exporter.otlp_exporter.create_otlp_exporter",
            return_value=mock_sdk_exporter,
        ):
            exporter = OTLPExporter(config, sample_registry)

        exporter._status.state = ExportState.EXPORTING
        result = await exporter._export_once()

        assert result is True
        mock_sdk_exporter.export.assert_called_once()

        # Verify MetricsData was passed to SDK
        call_args = mock_sdk_exporter.export.call_args
        metrics_data = call_args[0][0]
        assert len(metrics_data.resource_metrics) == 1

    @pytest.mark.asyncio()
    async def test_export_updates_status_on_success(
        self, mock_sdk_exporter: MagicMock, sample_registry: CollectorRegistry
    ) -> None:
        from loxone_exporter.otlp_exporter import ExportState, OTLPExporter

        config = _make_otlp_config()
        with patch(
            "loxone_exporter.otlp_exporter.create_otlp_exporter",
            return_value=mock_sdk_exporter,
        ):
            exporter = OTLPExporter(config, sample_registry)

        exporter._status.state = ExportState.EXPORTING
        exporter._status.consecutive_failures = 3

        await exporter._export_once()
        exporter._handle_success()

        assert exporter._status.state == ExportState.IDLE
        assert exporter._status.consecutive_failures == 0
        assert exporter._status.last_success_timestamp is not None
        assert exporter._status.last_success_timestamp > 0

    @pytest.mark.asyncio()
    async def test_prometheus_metrics_still_available_during_export(
        self, mock_sdk_exporter: MagicMock, sample_registry: CollectorRegistry
    ) -> None:
        """T029: Verify Prometheus /metrics responds <500ms during OTLP export."""
        from prometheus_client import generate_latest

        from loxone_exporter.otlp_exporter import OTLPExporter as _OTLPExp

        config = _make_otlp_config()
        with patch(
            "loxone_exporter.otlp_exporter.create_otlp_exporter",
            return_value=mock_sdk_exporter,
        ):
            exporter = _OTLPExp(config, sample_registry)

        # Simulate slow OTLP export
        def slow_export(data):
            import time

            from opentelemetry.sdk.metrics.export import MetricExportResult
            time.sleep(0.1)
            return MetricExportResult.SUCCESS

        mock_sdk_exporter.export.side_effect = slow_export

        # Start export in background
        export_task = asyncio.create_task(exporter._export_once())

        # Meanwhile, verify Prometheus scrape is fast
        start = time.monotonic()
        output = generate_latest(sample_registry)
        duration = time.monotonic() - start

        assert output is not None
        assert duration < 0.5  # Must respond in <500ms

        await export_task


# ── T040: Collector Unreachable ───────────────────────────────────────


class TestCollectorUnreachable:
    """Integration tests for unreachable OTLP collector."""

    @pytest.mark.asyncio()
    async def test_export_failure_returns_false(
        self, sample_registry: CollectorRegistry
    ) -> None:
        from opentelemetry.sdk.metrics.export import MetricExportResult

        from loxone_exporter.otlp_exporter import OTLPExporter

        mock_exporter = MagicMock()
        mock_exporter.export.return_value = MetricExportResult.FAILURE

        config = _make_otlp_config()
        with patch(
            "loxone_exporter.otlp_exporter.create_otlp_exporter",
            return_value=mock_exporter,
        ):
            exporter = OTLPExporter(config, sample_registry)

        result = await exporter._export_once()
        assert result is False

    @pytest.mark.asyncio()
    async def test_export_exception_returns_false(
        self, sample_registry: CollectorRegistry
    ) -> None:
        from loxone_exporter.otlp_exporter import OTLPExporter

        mock_exporter = MagicMock()
        mock_exporter.export.side_effect = ConnectionError("refused")

        config = _make_otlp_config()
        with patch(
            "loxone_exporter.otlp_exporter.create_otlp_exporter",
            return_value=mock_exporter,
        ):
            exporter = OTLPExporter(config, sample_registry)

        result = await exporter._export_once()
        assert result is False


# ── T041: Timeout Handling ────────────────────────────────────────────


class TestTimeoutHandling:
    """Integration tests for export timeout scenarios."""

    @pytest.mark.asyncio()
    async def test_sdk_timeout_is_set(self) -> None:
        """Verify timeout is passed to SDK exporter constructor."""
        config = _make_otlp_config(timeout_seconds=10)

        with patch(
            "opentelemetry.exporter.otlp.proto.grpc.metric_exporter.OTLPMetricExporter"
        ) as mock_cls:
            mock_cls.return_value = MagicMock()
            from loxone_exporter.otlp_exporter import create_otlp_exporter

            create_otlp_exporter(config)
            assert mock_cls.call_args.kwargs["timeout"] == 10000  # ms


# ── T042: Authentication Failure ──────────────────────────────────────


class TestAuthenticationFailure:
    """Integration tests for authentication failure scenarios."""

    @pytest.mark.asyncio()
    async def test_auth_headers_included_in_request(self) -> None:
        from loxone_exporter.config import AuthConfig
        from loxone_exporter.otlp_exporter import create_otlp_exporter

        config = _make_otlp_config(
            auth_config=AuthConfig(headers={"Authorization": "Bearer secret123"}),
        )

        with patch(
            "opentelemetry.exporter.otlp.proto.grpc.metric_exporter.OTLPMetricExporter"
        ) as mock_cls:
            mock_cls.return_value = MagicMock()
            create_otlp_exporter(config)
            headers = mock_cls.call_args.kwargs["headers"]
            assert ("Authorization", "Bearer secret123") in headers

    @pytest.mark.asyncio()
    async def test_auth_failure_is_handled_gracefully(
        self, sample_registry: CollectorRegistry
    ) -> None:
        from loxone_exporter.config import AuthConfig
        from loxone_exporter.otlp_exporter import OTLPExporter

        mock_exporter = MagicMock()
        mock_exporter.export.side_effect = PermissionError("401 Unauthorized")

        config = _make_otlp_config(
            auth_config=AuthConfig(headers={"Authorization": "Bearer bad"}),
        )
        with patch(
            "loxone_exporter.otlp_exporter.create_otlp_exporter",
            return_value=mock_exporter,
        ):
            exporter = OTLPExporter(config, sample_registry)

        result = await exporter._export_once()
        assert result is False  # Graceful failure, no crash
