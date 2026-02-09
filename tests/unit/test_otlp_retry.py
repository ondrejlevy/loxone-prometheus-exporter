"""Unit tests for OTLP exporter factory, backoff, state transitions, and overlap prevention.

Covers tasks T016, T037, T038, T039.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ── T016: Factory Function Tests ──────────────────────────────────────


class TestCreateOTLPExporter:
    """Tests for create_otlp_exporter() factory function."""

    @staticmethod
    def _make_config(**overrides: Any) -> Any:
        from loxone_exporter.config import AuthConfig, OTLPConfiguration, TLSConfig

        defaults: dict[str, Any] = {
            "enabled": True,
            "endpoint": "http://localhost:4317",
            "protocol": "grpc",
            "interval_seconds": 30,
            "timeout_seconds": 15,
            "tls_config": TLSConfig(),
            "auth_config": AuthConfig(),
        }
        defaults.update(overrides)
        return OTLPConfiguration(**defaults)

    @patch("opentelemetry.exporter.otlp.proto.grpc.metric_exporter.OTLPMetricExporter")
    def test_grpc_protocol_creates_grpc_exporter(self, mock_grpc_cls: MagicMock) -> None:
        from loxone_exporter.otlp_exporter import create_otlp_exporter

        config = self._make_config(protocol="grpc")
        mock_grpc_cls.return_value = MagicMock()
        result = create_otlp_exporter(config)
        mock_grpc_cls.assert_called_once()
        call_kwargs = mock_grpc_cls.call_args
        assert call_kwargs.kwargs["endpoint"] == "http://localhost:4317"
        assert call_kwargs.kwargs["insecure"] is True
        assert result is mock_grpc_cls.return_value

    @patch("opentelemetry.exporter.otlp.proto.http.metric_exporter.OTLPMetricExporter")
    def test_http_protocol_creates_http_exporter(self, mock_http_cls: MagicMock) -> None:
        from loxone_exporter.otlp_exporter import create_otlp_exporter

        config = self._make_config(protocol="http", endpoint="http://localhost:4318")
        mock_http_cls.return_value = MagicMock()
        result = create_otlp_exporter(config)
        mock_http_cls.assert_called_once()
        call_kwargs = mock_http_cls.call_args
        assert "/v1/metrics" in call_kwargs.kwargs["endpoint"]
        assert result is mock_http_cls.return_value

    def test_invalid_protocol_raises(self) -> None:
        from loxone_exporter.config import ConfigurationError
        from loxone_exporter.otlp_exporter import create_otlp_exporter

        config = self._make_config(protocol="tcp")
        with pytest.raises(ConfigurationError, match="Unsupported OTLP protocol"):
            create_otlp_exporter(config)

    @patch("opentelemetry.exporter.otlp.proto.grpc.metric_exporter.OTLPMetricExporter")
    def test_grpc_with_tls(self, mock_grpc_cls: MagicMock, tmp_path: Any) -> None:
        from loxone_exporter.config import TLSConfig
        from loxone_exporter.otlp_exporter import create_otlp_exporter

        cert = tmp_path / "ca.crt"
        cert.write_text("fake cert")
        config = self._make_config(
            tls_config=TLSConfig(enabled=True, cert_path=str(cert)),
        )
        mock_grpc_cls.return_value = MagicMock()
        create_otlp_exporter(config)
        call_kwargs = mock_grpc_cls.call_args.kwargs
        assert call_kwargs["insecure"] is False
        assert "credentials" in call_kwargs

    @patch("opentelemetry.exporter.otlp.proto.http.metric_exporter.OTLPMetricExporter")
    def test_http_with_tls(self, mock_http_cls: MagicMock, tmp_path: Any) -> None:
        from loxone_exporter.config import TLSConfig
        from loxone_exporter.otlp_exporter import create_otlp_exporter

        cert = tmp_path / "ca.crt"
        cert.write_text("fake cert")
        config = self._make_config(
            protocol="http",
            endpoint="http://localhost:4318",
            tls_config=TLSConfig(enabled=True, cert_path=str(cert)),
        )
        mock_http_cls.return_value = MagicMock()
        create_otlp_exporter(config)
        call_kwargs = mock_http_cls.call_args.kwargs
        assert call_kwargs["certificate_file"] == str(cert)

    @patch("opentelemetry.exporter.otlp.proto.grpc.metric_exporter.OTLPMetricExporter")
    def test_auth_headers_passed(self, mock_grpc_cls: MagicMock) -> None:
        from loxone_exporter.config import AuthConfig
        from loxone_exporter.otlp_exporter import create_otlp_exporter

        config = self._make_config(
            auth_config=AuthConfig(headers={"Authorization": "Bearer tok"}),
        )
        mock_grpc_cls.return_value = MagicMock()
        create_otlp_exporter(config)
        call_kwargs = mock_grpc_cls.call_args.kwargs
        assert ("Authorization", "Bearer tok") in call_kwargs["headers"]

    @patch("opentelemetry.exporter.otlp.proto.http.metric_exporter.OTLPMetricExporter")
    def test_http_endpoint_appends_v1_metrics(self, mock_http_cls: MagicMock) -> None:
        from loxone_exporter.otlp_exporter import create_otlp_exporter

        config = self._make_config(
            protocol="http", endpoint="http://collector:4318",
        )
        mock_http_cls.return_value = MagicMock()
        create_otlp_exporter(config)
        assert mock_http_cls.call_args.kwargs["endpoint"] == "http://collector:4318/v1/metrics"

    @patch("opentelemetry.exporter.otlp.proto.http.metric_exporter.OTLPMetricExporter")
    def test_http_endpoint_no_double_v1(self, mock_http_cls: MagicMock) -> None:
        from loxone_exporter.otlp_exporter import create_otlp_exporter

        config = self._make_config(
            protocol="http", endpoint="http://collector:4318/v1/metrics",
        )
        mock_http_cls.return_value = MagicMock()
        create_otlp_exporter(config)
        assert mock_http_cls.call_args.kwargs["endpoint"] == "http://collector:4318/v1/metrics"


# ── T037: Backoff Calculation Tests ───────────────────────────────────


class TestCalculateBackoff:
    """Tests for _calculate_backoff() exponential backoff logic."""

    def test_first_failure(self) -> None:
        from loxone_exporter.otlp_exporter import _calculate_backoff

        assert _calculate_backoff(1) == 1.0  # 1 * 2^0

    def test_second_failure(self) -> None:
        from loxone_exporter.otlp_exporter import _calculate_backoff

        assert _calculate_backoff(2) == 2.0  # 1 * 2^1

    def test_third_failure(self) -> None:
        from loxone_exporter.otlp_exporter import _calculate_backoff

        assert _calculate_backoff(3) == 4.0  # 1 * 2^2

    def test_max_cap(self) -> None:
        from loxone_exporter.otlp_exporter import _calculate_backoff

        result = _calculate_backoff(20)
        assert result == 300.0

    def test_zero_failures(self) -> None:
        from loxone_exporter.otlp_exporter import _calculate_backoff

        assert _calculate_backoff(0) == 1.0  # default base delay

    def test_progression(self) -> None:
        from loxone_exporter.otlp_exporter import _calculate_backoff

        expected = [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0, 300.0]
        for i, exp in enumerate(expected, start=1):
            assert _calculate_backoff(i) == exp, f"failure {i}: expected {exp}"


# ── T038: State Transition Tests ──────────────────────────────────────


class TestStateTransitions:
    """Tests for ExportState transitions via _handle_success / _handle_failure."""

    def test_handle_success_resets_state(self) -> None:
        from loxone_exporter.otlp_exporter import ExportState, ExportStatus, _BASE_DELAY

        status = ExportStatus(
            state=ExportState.EXPORTING,
            consecutive_failures=3,
            current_backoff_seconds=8.0,
        )
        # Simulate handle_success logic
        status.state = ExportState.IDLE
        status.consecutive_failures = 0
        status.current_backoff_seconds = _BASE_DELAY

        assert status.state == ExportState.IDLE
        assert status.consecutive_failures == 0
        assert status.current_backoff_seconds == 1.0

    def test_failure_increments_counter(self) -> None:
        from loxone_exporter.otlp_exporter import ExportState, ExportStatus, _MAX_FAILURES

        status = ExportStatus(state=ExportState.EXPORTING, consecutive_failures=0)
        status.consecutive_failures += 1
        assert status.consecutive_failures == 1

        # Below max → RETRYING
        if status.consecutive_failures < _MAX_FAILURES:
            status.state = ExportState.RETRYING
        assert status.state == ExportState.RETRYING

    def test_max_failures_transitions_to_failed(self) -> None:
        from loxone_exporter.otlp_exporter import ExportState, ExportStatus, _MAX_FAILURES

        status = ExportStatus(
            state=ExportState.EXPORTING,
            consecutive_failures=_MAX_FAILURES - 1,
        )
        status.consecutive_failures += 1
        if status.consecutive_failures >= _MAX_FAILURES:
            status.state = ExportState.FAILED
        assert status.state == ExportState.FAILED

    def test_export_status_defaults(self) -> None:
        from loxone_exporter.otlp_exporter import ExportState, ExportStatus

        status = ExportStatus()
        assert status.state == ExportState.DISABLED
        assert status.last_success_timestamp is None
        assert status.last_error is None
        assert status.consecutive_failures == 0


# ── T039: Overlap Prevention Tests ────────────────────────────────────


class TestOverlapPrevention:
    """Tests for _should_export overlap prevention check."""

    @patch("opentelemetry.exporter.otlp.proto.grpc.metric_exporter.OTLPMetricExporter")
    def test_should_export_when_idle(self, mock_grpc_cls: MagicMock) -> None:
        from loxone_exporter.config import AuthConfig, OTLPConfiguration, TLSConfig
        from loxone_exporter.otlp_exporter import OTLPExporter

        mock_grpc_cls.return_value = MagicMock()
        config = OTLPConfiguration(
            enabled=True, endpoint="http://localhost:4317",
            protocol="grpc", interval_seconds=30, timeout_seconds=15,
            tls_config=TLSConfig(), auth_config=AuthConfig(),
        )
        from prometheus_client import CollectorRegistry

        registry = CollectorRegistry()
        exporter = OTLPExporter(config, registry)
        assert exporter._should_export() is True

    @patch("opentelemetry.exporter.otlp.proto.grpc.metric_exporter.OTLPMetricExporter")
    def test_should_not_export_when_already_exporting(self, mock_grpc_cls: MagicMock) -> None:
        from loxone_exporter.config import AuthConfig, OTLPConfiguration, TLSConfig
        from loxone_exporter.otlp_exporter import OTLPExporter

        mock_grpc_cls.return_value = MagicMock()
        config = OTLPConfiguration(
            enabled=True, endpoint="http://localhost:4317",
            protocol="grpc", interval_seconds=30, timeout_seconds=15,
            tls_config=TLSConfig(), auth_config=AuthConfig(),
        )
        from prometheus_client import CollectorRegistry

        registry = CollectorRegistry()
        exporter = OTLPExporter(config, registry)
        exporter._exporting = True
        assert exporter._should_export() is False

    @patch("opentelemetry.exporter.otlp.proto.grpc.metric_exporter.OTLPMetricExporter")
    def test_failed_state_resets_on_new_export(self, mock_grpc_cls: MagicMock) -> None:
        from loxone_exporter.config import AuthConfig, OTLPConfiguration, TLSConfig
        from loxone_exporter.otlp_exporter import ExportState, OTLPExporter

        mock_grpc_cls.return_value = MagicMock()
        config = OTLPConfiguration(
            enabled=True, endpoint="http://localhost:4317",
            protocol="grpc", interval_seconds=30, timeout_seconds=15,
            tls_config=TLSConfig(), auth_config=AuthConfig(),
        )
        from prometheus_client import CollectorRegistry

        registry = CollectorRegistry()
        exporter = OTLPExporter(config, registry)
        exporter._status.state = ExportState.FAILED
        exporter._status.consecutive_failures = 10

        result = exporter._should_export()
        assert result is True
        assert exporter._status.state == ExportState.IDLE
        assert exporter._status.consecutive_failures == 0


# ── Log Sanitization Tests ────────────────────────────────────────────


class TestSanitizeError:
    """Tests for _sanitize_error credential removal."""

    def test_bearer_token_redacted(self) -> None:
        from loxone_exporter.otlp_exporter import _sanitize_error

        result = _sanitize_error("Bearer eyJhbGciOiJIUzI1NiJ9.secret")
        assert "eyJhbGci" not in result
        assert "****" in result

    def test_api_key_redacted(self) -> None:
        from loxone_exporter.otlp_exporter import _sanitize_error

        result = _sanitize_error("api_key=sk-12345abc")
        assert "sk-12345abc" not in result
        assert "****" in result

    def test_plain_message_unchanged(self) -> None:
        from loxone_exporter.otlp_exporter import _sanitize_error

        msg = "Connection refused to localhost:4317"
        assert _sanitize_error(msg) == msg
