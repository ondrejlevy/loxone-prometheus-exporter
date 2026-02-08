"""Prometheus metrics collector for Loxone Miniserver data.

Implements the Custom Collector pattern via ``prometheus_client`` —
``LoxoneCollector.collect()`` is called on every ``/metrics`` scrape
and yields metric families from in-memory ``MiniserverState`` snapshots.
"""

from __future__ import annotations

import fnmatch
import logging
import time
from typing import TYPE_CHECKING

from prometheus_client import Counter
from prometheus_client.core import GaugeMetricFamily, InfoMetricFamily, Metric

from loxone_exporter import __build_date__, __commit__, __version__
from loxone_exporter.structure import (
    Category,
    Control,
    MiniserverState,
    Room,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from loxone_exporter.config import ExporterConfig

logger = logging.getLogger(__name__)

# Counter must live outside collect() — register once at module level
scrape_errors_total = Counter(
    "loxone_exporter_scrape_errors_total",
    "Total number of errors during metric generation",
    registry=None,  # Don't auto-register; server.py will handle it
)

# Labels for loxone_control_value
_CONTROL_LABELS = ["miniserver", "name", "room", "category", "type", "subcontrol"]


class LoxoneCollector:
    """Custom Prometheus collector that reads in-memory Miniserver state.

    Does NOT make network calls — reads ``MiniserverState`` objects that
    are updated by ``LoxoneClient`` instances running in the same event loop.
    """

    def __init__(
        self,
        states: list[MiniserverState],
        config: ExporterConfig,
    ) -> None:
        self._states = states
        self._config = config

    def _should_exclude(
        self,
        control: Control,
        rooms: dict[str, Room],
    ) -> bool:
        """Check if a control should be excluded based on config filters."""
        # Room exclusion
        if self._config.exclude_rooms and control.room_uuid:
            room = rooms.get(control.room_uuid)
            if room and room.name in self._config.exclude_rooms:
                return True

        # Type exclusion
        if self._config.exclude_types and control.type in self._config.exclude_types:
            return True

        # Name glob exclusion
        return any(fnmatch.fnmatch(control.name, pattern) for pattern in self._config.exclude_names)

    def _collect_control_metrics(
        self,
        control: Control,
        ms_name: str,
        rooms: dict[str, Room],
        categories: dict[str, Category],
        gauge: GaugeMetricFamily,
        info: InfoMetricFamily | None,
    ) -> int:
        """Collect metrics for a single control and its subcontrols.

        Returns the number of exported controls.
        """
        exported = 0

        if self._should_exclude(control, rooms):
            return 0

        room_name = rooms.get(control.room_uuid or "", Room(uuid="", name="")).name
        cat_name = categories.get(control.cat_uuid or "", Category(uuid="", name="")).name

        # Handle text-only controls
        if control.is_text_only:
            if self._config.include_text_values and info is not None:
                for state in control.states.values():
                    if state.text is not None:
                        info.add_metric(
                            [
                                ms_name, control.name, room_name,
                                cat_name, control.type, state.state_name,
                            ],
                            {"value": state.text},
                        )
                exported += 1
            return exported

        # Numeric control
        has_values = False
        for state in control.states.values():
            if state.value is not None:
                gauge.add_metric(
                    [ms_name, control.name, room_name, cat_name, control.type, state.state_name],
                    state.value,
                )
                has_values = True

        if has_values:
            exported += 1

        # Process subcontrols
        for sub in control.sub_controls:
            exported += self._collect_control_metrics(
                sub, ms_name, rooms, categories, gauge, info
            )

        return exported

    def collect(self) -> Iterator[Metric]:
        """Yield all Prometheus metrics from current Miniserver state.

        Called by ``prometheus_client`` on every ``/metrics`` scrape.
        """
        start = time.monotonic()

        # ── Control value metrics ──────────────────────────────────
        gauge = GaugeMetricFamily(
            "loxone_control_value",
            "Current numeric value of a control state",
            labels=_CONTROL_LABELS,
        )
        info: InfoMetricFamily | None = None
        if self._config.include_text_values:
            info = InfoMetricFamily(
                "loxone_control",
                "Text value of a control state",
                labels=_CONTROL_LABELS,
            )

        # ── Per-miniserver metrics ─────────────────────────────────
        connected_gauge = GaugeMetricFamily(
            "loxone_exporter_connected",
            "WebSocket connection status per miniserver",
            labels=["miniserver"],
        )
        last_update_gauge = GaugeMetricFamily(
            "loxone_exporter_last_update_timestamp_seconds",
            "Unix timestamp of last received value event",
            labels=["miniserver"],
        )
        discovered_gauge = GaugeMetricFamily(
            "loxone_exporter_controls_discovered",
            "Controls found in structure file",
            labels=["miniserver"],
        )
        exported_gauge = GaugeMetricFamily(
            "loxone_exporter_controls_exported",
            "Controls exported after filtering",
            labels=["miniserver"],
        )

        for ms in self._states:
            # Connection status
            connected_gauge.add_metric([ms.name], 1.0 if ms.connected else 0.0)
            last_update_gauge.add_metric([ms.name], ms.last_update_ts)

            # Count discovered controls (top-level + subcontrols)
            total_discovered = len(ms.controls)
            for ctrl in ms.controls.values():
                total_discovered += len(ctrl.sub_controls)
            discovered_gauge.add_metric([ms.name], float(total_discovered))

            # Collect control metrics
            total_exported = 0
            for control in ms.controls.values():
                total_exported += self._collect_control_metrics(
                    control, ms.name, ms.rooms, ms.categories, gauge, info
                )
            exported_gauge.add_metric([ms.name], float(total_exported))

        yield gauge
        if info is not None:
            yield info
        yield connected_gauge
        yield last_update_gauge
        yield discovered_gauge
        yield exported_gauge

        # ── Exporter-level metrics ─────────────────────────────────
        up_gauge = GaugeMetricFamily(
            "loxone_exporter_up",
            "1 if exporter process is running",
        )
        up_gauge.add_metric([], 1.0)
        yield up_gauge

        duration = time.monotonic() - start
        duration_gauge = GaugeMetricFamily(
            "loxone_exporter_scrape_duration_seconds",
            "Time taken to generate /metrics response",
        )
        duration_gauge.add_metric([], duration)
        yield duration_gauge

        # Build info
        build_info = InfoMetricFamily(
            "loxone_exporter_build",
            "Build metadata",
        )
        build_info.add_metric([], {
            "version": __version__,
            "commit": __commit__,
            "build_date": __build_date__,
        })
        yield build_info
