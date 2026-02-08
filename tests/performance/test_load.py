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
