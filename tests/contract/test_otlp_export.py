"""Contract tests for OTLP export format compliance.

Covers task T030: Verifies OTLP protobuf structure and metadata preservation.
"""

from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, Info

from loxone_exporter.otlp_exporter import (
    DataPoint,
    HistogramDataPoint,
    PrometheusToOTLPBridge,
)


@pytest.fixture()
def full_registry() -> CollectorRegistry:
    """Registry with all metric types for comprehensive contract testing."""
    registry = CollectorRegistry()

    # Gauge with multiple labels
    g = Gauge(
        "loxone_control_value",
        "Current numeric value of a control state",
        ["miniserver", "name", "room", "category", "type", "subcontrol"],
        registry=registry,
    )
    g.labels(
        miniserver="home",
        name="light_living",
        room="Living Room",
        category="Lights",
        type="Switch",
        subcontrol="value",
    ).set(1.0)

    # Counter
    c = Counter(
        "loxone_exporter_scrape_errors_total",
        "Total number of errors during metric generation",
        registry=registry,
    )
    c.inc(3)

    # Histogram
    h = Histogram(
        "loxone_exporter_scrape_duration_seconds",
        "Time taken to generate /metrics response",
        buckets=[0.001, 0.005, 0.01, 0.05, 0.1],
        registry=registry,
    )
    h.observe(0.003)

    # Info
    i = Info(
        "loxone_exporter_build",
        "Build metadata",
        registry=registry,
    )
    i.info({"version": "0.2.0", "commit": "abc123", "build_date": "2024-01-01"})

    return registry


class TestOTLPFormatCompliance:
    """Contract: OTLP export must match expected structure."""

    def test_batch_has_resource_attributes(self, full_registry: CollectorRegistry) -> None:
        bridge = PrometheusToOTLPBridge(full_registry)
        batch = bridge.convert_metrics()

        assert "service.name" in batch.resource_attributes
        assert batch.resource_attributes["service.name"] == "loxone-prometheus-exporter"
        assert "service.version" in batch.resource_attributes

    def test_batch_has_scope(self, full_registry: CollectorRegistry) -> None:
        bridge = PrometheusToOTLPBridge(full_registry)
        batch = bridge.convert_metrics()

        assert batch.scope_name == "loxone_exporter"
        assert batch.scope_version != ""

    def test_gauge_type_preserved(self, full_registry: CollectorRegistry) -> None:
        bridge = PrometheusToOTLPBridge(full_registry)
        batch = bridge.convert_metrics()

        gauges = [m for m in batch.metrics if m.name == "loxone_control_value"]
        assert len(gauges) == 1
        assert gauges[0].type == "gauge"

    def test_counter_type_preserved(self, full_registry: CollectorRegistry) -> None:
        bridge = PrometheusToOTLPBridge(full_registry)
        batch = bridge.convert_metrics()

        counters = [m for m in batch.metrics if "scrape_errors" in m.name and m.type == "counter"]
        assert len(counters) >= 1

    def test_histogram_type_preserved(self, full_registry: CollectorRegistry) -> None:
        bridge = PrometheusToOTLPBridge(full_registry)
        batch = bridge.convert_metrics()

        hists = [m for m in batch.metrics if m.name == "loxone_exporter_scrape_duration_seconds"]
        assert len(hists) == 1
        assert hists[0].type == "histogram"

    def test_all_labels_preserved_fr012(self, full_registry: CollectorRegistry) -> None:
        """FR-012: All Prometheus labels/descriptions preserved in OTLP format."""
        bridge = PrometheusToOTLPBridge(full_registry)
        batch = bridge.convert_metrics()

        ctrl = next(m for m in batch.metrics if m.name == "loxone_control_value")
        dp = ctrl.data_points[0]
        assert isinstance(dp, DataPoint)

        # Verify all 6 labels are preserved
        assert dp.attributes["miniserver"] == "home"
        assert dp.attributes["name"] == "light_living"
        assert dp.attributes["room"] == "Living Room"
        assert dp.attributes["category"] == "Lights"
        assert dp.attributes["type"] == "Switch"
        assert dp.attributes["subcontrol"] == "value"

    def test_help_text_preserved_fr012(self, full_registry: CollectorRegistry) -> None:
        """FR-012: Prometheus HELP text preserved as OTLP description."""
        bridge = PrometheusToOTLPBridge(full_registry)
        batch = bridge.convert_metrics()

        ctrl = next(m for m in batch.metrics if m.name == "loxone_control_value")
        assert ctrl.description == "Current numeric value of a control state"

    def test_histogram_buckets_preserved(self, full_registry: CollectorRegistry) -> None:
        bridge = PrometheusToOTLPBridge(full_registry)
        batch = bridge.convert_metrics()

        hist = next(m for m in batch.metrics if m.name == "loxone_exporter_scrape_duration_seconds")
        hdp = hist.data_points[0]
        assert isinstance(hdp, HistogramDataPoint)
        assert hdp.explicit_bounds == [0.001, 0.005, 0.01, 0.05, 0.1]
        assert hdp.count == 1
        assert hdp.sum_value > 0

    def test_info_converted_to_gauge(self, full_registry: CollectorRegistry) -> None:
        bridge = PrometheusToOTLPBridge(full_registry)
        batch = bridge.convert_metrics()

        builds = [m for m in batch.metrics if "build" in m.name]
        assert len(builds) >= 1
        m = builds[0]
        assert m.type == "gauge"
        dp = m.data_points[0]
        assert isinstance(dp, DataPoint)
        assert dp.value == 1.0

    def test_timestamps_are_nanoseconds(self, full_registry: CollectorRegistry) -> None:
        bridge = PrometheusToOTLPBridge(full_registry)
        batch = bridge.convert_metrics()

        for metric in batch.metrics:
            for dp in metric.data_points:
                if hasattr(dp, "timestamp_ns"):
                    # Should be in nanosecond range (>1e18 for recent timestamps)
                    assert dp.timestamp_ns > 1_000_000_000_000_000_000


class TestOTLPSDKExportContract:
    """Contract: _do_sdk_export produces valid SDK MetricsData."""

    def test_sdk_export_produces_valid_metrics_data(
        self, full_registry: CollectorRegistry
    ) -> None:
        from unittest.mock import MagicMock, patch

        from opentelemetry.sdk.metrics.export import MetricExportResult

        mock_exporter = MagicMock()
        mock_exporter.export.return_value = MetricExportResult.SUCCESS

        from loxone_exporter.otlp_exporter import OTLPExporter

        config = _make_config()
        with patch(
            "loxone_exporter.otlp_exporter.create_otlp_exporter",
            return_value=mock_exporter,
        ):
            exporter = OTLPExporter(config, full_registry)

        batch = exporter._bridge.convert_metrics()
        result = exporter._do_sdk_export(batch)

        assert result == MetricExportResult.SUCCESS
        mock_exporter.export.assert_called_once()

        # Verify structure of MetricsData
        metrics_data = mock_exporter.export.call_args[0][0]
        assert len(metrics_data.resource_metrics) == 1
        rm = metrics_data.resource_metrics[0]
        assert len(rm.scope_metrics) == 1
        sm = rm.scope_metrics[0]
        assert len(sm.metrics) > 0


def _make_config(**overrides):
    from loxone_exporter.config import AuthConfig, OTLPConfiguration, TLSConfig

    defaults = {
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
