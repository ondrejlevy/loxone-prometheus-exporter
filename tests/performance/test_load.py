"""Performance / load tests — T039.

Generates 500+ mock controls, measures memory and scrape latency.
Success criteria:
  - SC-005: memory ≤ 50 MB
  - Scrape latency reasonable (< 2 s for 500 controls)
  - CPU usage not directly measurable in a unit test, so we measure wall-clock time
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from loxone_exporter.config import ExporterConfig, MiniserverConfig
from loxone_exporter.structure import MiniserverState, parse_structure


def _generate_large_loxapp3(n_controls: int = 500) -> dict[str, Any]:
    """Generate a LoxAPP3.json-style dict with *n_controls* controls."""
    rooms: dict[str, Any] = {}
    cats: dict[str, Any] = {}

    # Create 10 rooms
    for i in range(10):
        room_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"room-{i}"))
        rooms[room_uuid] = {"name": f"Room {i}", "uuid": room_uuid}

    # Create 5 categories
    for i in range(5):
        cat_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"cat-{i}"))
        cats[cat_uuid] = {
            "name": f"Category {i}",
            "uuid": cat_uuid,
            "type": "undefined",
        }

    room_uuids = list(rooms.keys())
    cat_uuids = list(cats.keys())

    controls: dict[str, Any] = {}
    for i in range(n_controls):
        ctrl_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"ctrl-{i}"))
        state_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"state-{i}"))
        controls[ctrl_uuid] = {
            "name": f"Control {i}",
            "type": "InfoOnlyAnalog",
            "uuidAction": ctrl_uuid,
            "room": room_uuids[i % len(room_uuids)],
            "cat": cat_uuids[i % len(cat_uuids)],
            "states": {"value": state_uuid},
        }

    return {
        "msInfo": {"serialNr": "PERF_TEST_SERIAL", "msName": "PerfMS"},
        "softwareVersion": "14.5.12.28",
        "rooms": rooms,
        "cats": cats,
        "controls": controls,
    }


def _build_large_state(
    loxapp3: dict[str, Any],
) -> MiniserverState:
    """Build a MiniserverState with all controls populated."""
    controls, rooms, categories, state_map = parse_structure(loxapp3)

    ms = MiniserverState(
        name="perf-test",
        serial=loxapp3["msInfo"]["serialNr"],
        firmware=str(loxapp3["softwareVersion"]),
        connected=True,
        last_update_ts=1738934567.123,
        controls=controls,
        rooms=rooms,
        categories=categories,
        state_map=state_map,
    )

    # Set a numeric value for every control's "value" state
    for ctrl in ms.controls.values():
        for state in ctrl.states.values():
            state.value = 42.0

    return ms


class TestPerformance:
    """Performance tests with 500+ mock controls."""

    def test_scrape_latency_under_2s(self) -> None:
        """Scraping 500 controls should complete in <2 s."""
        from loxone_exporter.metrics import LoxoneCollector

        loxapp3 = _generate_large_loxapp3(500)
        ms_state = _build_large_state(loxapp3)

        config = ExporterConfig(
            miniservers=(
                MiniserverConfig(
                    name="perf",
                    host="10.0.0.1",
                    port=80,
                    username="u",
                    password="p",
                ),
            ),
            listen_port=9504,
            listen_address="0.0.0.0",
            log_level="warning",
            log_format="text",
        )
        collector = LoxoneCollector(states=[ms_state], config=config)

        start = time.monotonic()
        metrics = list(collector.collect())
        elapsed = time.monotonic() - start

        assert elapsed < 2.0, f"Scrape took {elapsed:.3f}s, expected <2s"
        # Verify we actually got metrics
        families = [m for m in metrics if m.name == "loxone_control_value"]
        assert len(families) == 1
        assert len(families[0].samples) >= 500

    def test_memory_under_50mb(self) -> None:
        """Memory consumption with 500 controls should stay under 50 MB (SC-005)."""
        import tracemalloc

        tracemalloc.start()

        loxapp3 = _generate_large_loxapp3(600)
        ms_state = _build_large_state(loxapp3)

        config = ExporterConfig(
            miniservers=(
                MiniserverConfig(
                    name="perf",
                    host="10.0.0.1",
                    port=80,
                    username="u",
                    password="p",
                ),
            ),
            listen_port=9504,
            listen_address="0.0.0.0",
            log_level="warning",
            log_format="text",
        )

        from loxone_exporter.metrics import LoxoneCollector

        collector = LoxoneCollector(states=[ms_state], config=config)
        # Trigger a full collect cycle
        _ = list(collector.collect())

        _, peak_mb = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_mb_val = peak_mb / (1024 * 1024)
        assert peak_mb_val < 50.0, (
            f"Peak memory {peak_mb_val:.1f} MB exceeds 50 MB limit"
        )

    def test_repeated_scrapes_stable(self) -> None:
        """Repeated scrapes should not leak memory or degrade."""
        from loxone_exporter.metrics import LoxoneCollector

        loxapp3 = _generate_large_loxapp3(500)
        ms_state = _build_large_state(loxapp3)

        config = ExporterConfig(
            miniservers=(
                MiniserverConfig(
                    name="perf",
                    host="10.0.0.1",
                    port=80,
                    username="u",
                    password="p",
                ),
            ),
            listen_port=9504,
            listen_address="0.0.0.0",
            log_level="warning",
            log_format="text",
        )
        collector = LoxoneCollector(states=[ms_state], config=config)

        durations: list[float] = []
        for _ in range(10):
            start = time.monotonic()
            _ = list(collector.collect())
            durations.append(time.monotonic() - start)

        avg = sum(durations) / len(durations)
        # Last scrape should not be dramatically slower than first
        assert durations[-1] < avg * 3, (
            f"Last scrape {durations[-1]:.3f}s >> avg {avg:.3f}s"
        )


# ── T062-T064: OTLP Performance Tests ────────────────────────────────


class TestOTLPPerformance:
    """Performance tests for OTLP export with 1000 metrics."""

    def test_conversion_1000_metrics_under_500ms(self) -> None:
        """T062/T064: Converting 1000 metric families should take <500ms P95."""
        from prometheus_client import CollectorRegistry, Gauge

        from loxone_exporter.otlp_exporter import PrometheusToOTLPBridge

        registry = CollectorRegistry()
        for i in range(1000):
            g = Gauge(f"perf_metric_{i}", f"Perf test {i}", ["room"], registry=registry)
            g.labels(room=f"room_{i % 10}").set(float(i))

        bridge = PrometheusToOTLPBridge(registry)

        durations: list[float] = []
        for _ in range(20):
            start = time.monotonic()
            batch = bridge.convert_metrics()
            duration = time.monotonic() - start
            durations.append(duration)

        durations.sort()
        p95 = durations[int(len(durations) * 0.95)]
        assert p95 < 0.5, f"P95 conversion latency {p95:.3f}s exceeds 500ms"
        assert len(batch.metrics) >= 1000

    def test_sdk_export_1000_metrics(self) -> None:
        """T062: Full SDK export (mock) with 1000 metrics completes quickly."""
        from unittest.mock import MagicMock, patch

        from opentelemetry.sdk.metrics.export import MetricExportResult
        from prometheus_client import CollectorRegistry, Gauge

        from loxone_exporter.config import AuthConfig, OTLPConfiguration, TLSConfig
        from loxone_exporter.otlp_exporter import OTLPExporter

        registry = CollectorRegistry()
        for i in range(1000):
            g = Gauge(f"sdk_perf_{i}", f"SDK perf {i}", registry=registry)
            g.set(float(i))

        mock_exporter = MagicMock()
        mock_exporter.export.return_value = MetricExportResult.SUCCESS

        config = OTLPConfiguration(
            enabled=True, endpoint="http://localhost:4317",
            protocol="grpc", interval_seconds=30, timeout_seconds=15,
            tls_config=TLSConfig(), auth_config=AuthConfig(),
        )
        with patch(
            "loxone_exporter.otlp_exporter.create_otlp_exporter",
            return_value=mock_exporter,
        ):
            exporter = OTLPExporter(config, registry)

        batch = exporter._bridge.convert_metrics()

        start = time.monotonic()
        result = exporter._do_sdk_export(batch)
        duration = time.monotonic() - start

        assert result == MetricExportResult.SUCCESS
        assert duration < 2.0, f"SDK export took {duration:.3f}s, expected <2s"

    def test_memory_overhead_under_10mb(self) -> None:
        """T063: OTLP conversion adds ≤10MB memory overhead."""
        import tracemalloc

        from prometheus_client import CollectorRegistry, Gauge

        from loxone_exporter.otlp_exporter import PrometheusToOTLPBridge

        registry = CollectorRegistry()
        for i in range(1000):
            g = Gauge(f"mem_perf_{i}", f"Mem perf {i}", registry=registry)
            g.set(float(i))

        bridge = PrometheusToOTLPBridge(registry)

        tracemalloc.start()
        snapshot1 = tracemalloc.take_snapshot()

        # Convert metrics 10 times to amplify memory usage
        for _ in range(10):
            bridge.convert_metrics()

        snapshot2 = tracemalloc.take_snapshot()
        tracemalloc.stop()

        stats = snapshot2.compare_to(snapshot1, "lineno")
        total_diff = sum(s.size_diff for s in stats if s.size_diff > 0)
        mb = total_diff / (1024 * 1024)

        assert mb < 10.0, f"Memory overhead {mb:.1f}MB exceeds 10MB limit"
