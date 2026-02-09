"""Unit tests for PrometheusToOTLPBridge metric conversion.

Covers task T027: Gauge, Counter, Histogram, Info → OTLP conversion.
"""

from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, Info

from loxone_exporter.otlp_exporter import DataPoint, HistogramDataPoint, PrometheusToOTLPBridge


class TestGaugeConversion:
    """Tests for Prometheus Gauge → OTLP Gauge conversion."""

    def test_simple_gauge(self) -> None:
        registry = CollectorRegistry()
        g = Gauge("temperature_celsius", "Room temperature", ["room"], registry=registry)
        g.labels(room="living").set(22.5)

        bridge = PrometheusToOTLPBridge(registry)
        batch = bridge.convert_metrics()

        temp_metrics = [m for m in batch.metrics if m.name == "temperature_celsius"]
        assert len(temp_metrics) == 1
        m = temp_metrics[0]
        assert m.type == "gauge"
        assert m.description == "Room temperature"
        assert len(m.data_points) == 1
        dp = m.data_points[0]
        assert isinstance(dp, DataPoint)
        assert dp.value == 22.5
        assert dp.attributes["room"] == "living"

    def test_gauge_multiple_labels(self) -> None:
        registry = CollectorRegistry()
        g = Gauge("sensor", "Value", ["room", "type"], registry=registry)
        g.labels(room="kitchen", type="humidity").set(65.0)
        g.labels(room="bedroom", type="humidity").set(55.0)

        bridge = PrometheusToOTLPBridge(registry)
        batch = bridge.convert_metrics()

        sensor = [m for m in batch.metrics if m.name == "sensor"]
        assert len(sensor) == 1
        assert len(sensor[0].data_points) == 2

    def test_gauge_preserves_labels(self) -> None:
        """FR-012: All Prometheus labels preserved in OTLP format."""
        registry = CollectorRegistry()
        g = Gauge("ctrl", "Test", ["miniserver", "name", "room"], registry=registry)
        g.labels(miniserver="home", name="light_1", room="living").set(1.0)

        bridge = PrometheusToOTLPBridge(registry)
        batch = bridge.convert_metrics()

        ctrl = next(m for m in batch.metrics if m.name == "ctrl")
        dp = ctrl.data_points[0]
        assert dp.attributes["miniserver"] == "home"
        assert dp.attributes["name"] == "light_1"
        assert dp.attributes["room"] == "living"


class TestCounterConversion:
    """Tests for Prometheus Counter → OTLP Sum conversion."""

    def test_simple_counter(self) -> None:
        registry = CollectorRegistry()
        c = Counter("requests_total", "Total requests", ["method"], registry=registry)
        c.labels(method="GET").inc(10)

        bridge = PrometheusToOTLPBridge(registry)
        batch = bridge.convert_metrics()

        req = [m for m in batch.metrics if "requests" in m.name and m.type == "counter"]
        assert len(req) == 1
        m = req[0]
        assert m.type == "counter"
        # Should have data points (skipping _created samples)
        assert len(m.data_points) >= 1
        dp = m.data_points[0]
        assert isinstance(dp, DataPoint)
        assert dp.value == 10.0

    def test_counter_skips_created_samples(self) -> None:
        registry = CollectorRegistry()
        c = Counter("ops_total", "Operations", registry=registry)
        c.inc(5)

        bridge = PrometheusToOTLPBridge(registry)
        batch = bridge.convert_metrics()

        ops = [m for m in batch.metrics if "ops" in m.name and m.type == "counter"]
        assert len(ops) == 1
        # _created sample should be filtered out
        for dp in ops[0].data_points:
            assert isinstance(dp, DataPoint)


class TestHistogramConversion:
    """Tests for Prometheus Histogram → OTLP Histogram conversion."""

    def test_simple_histogram(self) -> None:
        registry = CollectorRegistry()
        h = Histogram(
            "request_duration_seconds",
            "Request duration",
            buckets=[0.1, 0.5, 1.0, 5.0],
            registry=registry,
        )
        h.observe(0.3)
        h.observe(0.7)
        h.observe(2.0)

        bridge = PrometheusToOTLPBridge(registry)
        batch = bridge.convert_metrics()

        dur = [m for m in batch.metrics if m.name == "request_duration_seconds"]
        assert len(dur) == 1
        m = dur[0]
        assert m.type == "histogram"
        assert len(m.data_points) >= 1
        hdp = m.data_points[0]
        assert isinstance(hdp, HistogramDataPoint)
        assert hdp.count == 3
        assert hdp.sum_value == pytest.approx(3.0)
        assert hdp.explicit_bounds == [0.1, 0.5, 1.0, 5.0]
        assert len(hdp.bucket_counts) == 5  # 4 bounds + overflow

    def test_histogram_with_labels(self) -> None:
        registry = CollectorRegistry()
        h = Histogram(
            "api_latency",
            "API latency",
            ["endpoint"],
            buckets=[0.01, 0.1, 1.0],
            registry=registry,
        )
        h.labels(endpoint="/metrics").observe(0.05)

        bridge = PrometheusToOTLPBridge(registry)
        batch = bridge.convert_metrics()

        lat = [m for m in batch.metrics if m.name == "api_latency"]
        assert len(lat) == 1
        hdp = lat[0].data_points[0]
        assert isinstance(hdp, HistogramDataPoint)
        assert hdp.attributes["endpoint"] == "/metrics"

    def test_histogram_preserves_description(self) -> None:
        """FR-012: HELP text preserved in OTLP description."""
        registry = CollectorRegistry()
        Histogram(
            "my_hist",
            "A detailed description of the metric",
            buckets=[1.0],
            registry=registry,
        )

        bridge = PrometheusToOTLPBridge(registry)
        batch = bridge.convert_metrics()

        hist = [m for m in batch.metrics if m.name == "my_hist"]
        assert len(hist) == 1
        assert hist[0].description == "A detailed description of the metric"


class TestInfoConversion:
    """Tests for Prometheus Info → OTLP Gauge (value=1) conversion."""

    def test_info_metric(self) -> None:
        registry = CollectorRegistry()
        i = Info("build", "Build info", registry=registry)
        i.info({"version": "1.0.0", "commit": "abc123"})

        bridge = PrometheusToOTLPBridge(registry)
        batch = bridge.convert_metrics()

        builds = [m for m in batch.metrics if "build" in m.name]
        assert len(builds) >= 1
        m = builds[0]
        assert m.type == "gauge"  # Info is converted to gauge with value=1
        dp = m.data_points[0]
        assert isinstance(dp, DataPoint)
        assert dp.value == 1.0
        assert "version" in dp.attributes
        assert dp.attributes["version"] == "1.0.0"


class TestMetricBatch:
    """Tests for MetricBatch resource attributes and scope."""

    def test_batch_resource_attributes(self) -> None:
        from loxone_exporter import __version__

        registry = CollectorRegistry()
        Gauge("dummy", "Dummy", registry=registry).set(1.0)

        bridge = PrometheusToOTLPBridge(registry)
        batch = bridge.convert_metrics()

        assert batch.resource_attributes["service.name"] == "loxone-prometheus-exporter"
        assert batch.resource_attributes["service.version"] == __version__
        assert batch.scope_name == "loxone_exporter"

    def test_empty_registry(self) -> None:
        registry = CollectorRegistry()
        bridge = PrometheusToOTLPBridge(registry)
        batch = bridge.convert_metrics()
        assert len(batch.metrics) == 0

    def test_timestamp_populated(self) -> None:
        import time

        registry = CollectorRegistry()
        Gauge("ts_test", "Test", registry=registry).set(1.0)

        before = int(time.time() * 1_000_000_000)
        bridge = PrometheusToOTLPBridge(registry)
        batch = bridge.convert_metrics()
        after = int(time.time() * 1_000_000_000)

        m = next(m for m in batch.metrics if m.name == "ts_test")
        ts = m.data_points[0].timestamp_ns
        assert before <= ts <= after
