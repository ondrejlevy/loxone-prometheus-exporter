"""Tests for the Prometheus metrics collector."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loxone_exporter.config import ExporterConfig, MiniserverConfig

if TYPE_CHECKING:
    from loxone_exporter.structure import (
        MiniserverState,
    )


class TestLoxoneCollectorBasicMetrics:
    """Test LoxoneCollector.collect() with configured miniserver states."""

    def test_control_value_gauge_emitted(
        self, sample_miniserver_state: MiniserverState, sample_exporter_config: ExporterConfig
    ) -> None:
        """Each numeric control state should produce a loxone_control_value gauge."""
        from loxone_exporter.metrics import LoxoneCollector

        collector = LoxoneCollector(
            states=[sample_miniserver_state],
            config=sample_exporter_config,
        )
        metrics = list(collector.collect())
        control_values = [m for m in metrics if m.name == "loxone_control_value"]
        assert len(control_values) == 1  # One GaugeMetricFamily
        family = control_values[0]
        # Should have samples for each numeric state
        sample_names = [
            s.labels.get("name")
            for s in family.samples
            if s.name == "loxone_control_value"
        ]
        assert "Kitchen Light" in sample_names
        assert "Living Room Climate" in sample_names
        assert "Outside Temperature" in sample_names

    def test_control_value_labels_correct(
        self, sample_miniserver_state: MiniserverState, sample_exporter_config: ExporterConfig
    ) -> None:
        """Labels must include miniserver, name, room, category, type, subcontrol."""
        from loxone_exporter.metrics import LoxoneCollector

        collector = LoxoneCollector(
            states=[sample_miniserver_state],
            config=sample_exporter_config,
        )
        metrics = list(collector.collect())
        family = next(m for m in metrics if m.name == "loxone_control_value")

        # Find the Kitchen Light active sample
        kitchen_samples = [
            s for s in family.samples
            if s.labels.get("name") == "Kitchen Light" and s.labels.get("subcontrol") == "active"
        ]
        assert len(kitchen_samples) == 1
        labels = kitchen_samples[0].labels
        assert labels["miniserver"] == "home"
        assert labels["name"] == "Kitchen Light"
        assert labels["room"] == "Kitchen"
        assert labels["category"] == "Lighting"
        assert labels["type"] == "Switch"
        assert labels["subcontrol"] == "active"

    def test_digital_value_as_zero_or_one(
        self, sample_miniserver_state: MiniserverState, sample_exporter_config: ExporterConfig
    ) -> None:
        """Digital (Switch) values should be exported as 0 or 1."""
        from loxone_exporter.metrics import LoxoneCollector

        collector = LoxoneCollector(
            states=[sample_miniserver_state],
            config=sample_exporter_config,
        )
        metrics = list(collector.collect())
        family = next(m for m in metrics if m.name == "loxone_control_value")
        kitchen_active = next(
            s for s in family.samples
            if s.labels.get("name") == "Kitchen Light" and s.labels.get("subcontrol") == "active"
        )
        assert kitchen_active.value == 1.0

    def test_analog_value_preserved(
        self, sample_miniserver_state: MiniserverState, sample_exporter_config: ExporterConfig
    ) -> None:
        """Analog values should be exported as-is (e.g., 22.5)."""
        from loxone_exporter.metrics import LoxoneCollector

        collector = LoxoneCollector(
            states=[sample_miniserver_state],
            config=sample_exporter_config,
        )
        metrics = list(collector.collect())
        family = next(m for m in metrics if m.name == "loxone_control_value")
        temp_actual = next(
            s for s in family.samples
            if s.labels.get("name") == "Living Room Climate"
            and s.labels.get("subcontrol") == "tempActual"
        )
        assert temp_actual.value == 22.5

    def test_text_only_controls_excluded_by_default(
        self, sample_miniserver_state: MiniserverState, sample_exporter_config: ExporterConfig
    ) -> None:
        """Text-only controls (TextInput) should not appear in loxone_control_value."""
        from loxone_exporter.metrics import LoxoneCollector

        collector = LoxoneCollector(
            states=[sample_miniserver_state],
            config=sample_exporter_config,
        )
        metrics = list(collector.collect())
        family = next(m for m in metrics if m.name == "loxone_control_value")
        text_samples = [
            s for s in family.samples
            if s.labels.get("name") == "Status Display"
        ]
        assert len(text_samples) == 0

    def test_null_values_skipped(
        self, sample_miniserver_state: MiniserverState, sample_exporter_config: ExporterConfig
    ) -> None:
        """States with value=None should not appear in output."""
        from loxone_exporter.metrics import LoxoneCollector

        # Set a state value to None
        sample_miniserver_state.controls[
            "ccc00003-0000-0000-ffff000000000000"
        ].states["value"].value = None

        collector = LoxoneCollector(
            states=[sample_miniserver_state],
            config=sample_exporter_config,
        )
        metrics = list(collector.collect())
        family = next(m for m in metrics if m.name == "loxone_control_value")
        outside_samples = [
            s for s in family.samples
            if s.labels.get("name") == "Outside Temperature"
        ]
        assert len(outside_samples) == 0


class TestSelfHealthMetrics:
    """Exporter self-health metrics."""

    def test_exporter_up_metric(
        self, sample_miniserver_state: MiniserverState, sample_exporter_config: ExporterConfig
    ) -> None:
        """loxone_exporter_up should always be 1."""
        from loxone_exporter.metrics import LoxoneCollector

        collector = LoxoneCollector(
            states=[sample_miniserver_state],
            config=sample_exporter_config,
        )
        metrics = list(collector.collect())
        up = next(m for m in metrics if m.name == "loxone_exporter_up")
        assert up.samples[0].value == 1.0

    def test_connected_gauge_when_connected(
        self, sample_miniserver_state: MiniserverState, sample_exporter_config: ExporterConfig
    ) -> None:
        """loxone_exporter_connected should be 1 when connected."""
        from loxone_exporter.metrics import LoxoneCollector

        collector = LoxoneCollector(
            states=[sample_miniserver_state],
            config=sample_exporter_config,
        )
        metrics = list(collector.collect())
        connected = next(m for m in metrics if m.name == "loxone_exporter_connected")
        sample = next(s for s in connected.samples if s.labels.get("miniserver") == "home")
        assert sample.value == 1.0

    def test_connected_gauge_when_disconnected(
        self, disconnected_miniserver_state: MiniserverState, sample_exporter_config: ExporterConfig
    ) -> None:
        """loxone_exporter_connected should be 0 when disconnected."""
        from loxone_exporter.metrics import LoxoneCollector

        collector = LoxoneCollector(
            states=[disconnected_miniserver_state],
            config=sample_exporter_config,
        )
        metrics = list(collector.collect())
        connected = next(m for m in metrics if m.name == "loxone_exporter_connected")
        sample = next(s for s in connected.samples if s.labels.get("miniserver") == "home")
        assert sample.value == 0.0

    def test_last_update_timestamp(
        self, sample_miniserver_state: MiniserverState, sample_exporter_config: ExporterConfig
    ) -> None:
        """loxone_exporter_last_update_timestamp_seconds should reflect last_update_ts."""
        from loxone_exporter.metrics import LoxoneCollector

        collector = LoxoneCollector(
            states=[sample_miniserver_state],
            config=sample_exporter_config,
        )
        metrics = list(collector.collect())
        ts = next(m for m in metrics if m.name == "loxone_exporter_last_update_timestamp_seconds")
        sample = next(s for s in ts.samples if s.labels.get("miniserver") == "home")
        assert sample.value == 1738934567.123

    def test_controls_discovered_count(
        self, sample_miniserver_state: MiniserverState, sample_exporter_config: ExporterConfig
    ) -> None:
        """loxone_exporter_controls_discovered should count all controls."""
        from loxone_exporter.metrics import LoxoneCollector

        collector = LoxoneCollector(
            states=[sample_miniserver_state],
            config=sample_exporter_config,
        )
        metrics = list(collector.collect())
        discovered = next(m for m in metrics if m.name == "loxone_exporter_controls_discovered")
        sample = next(s for s in discovered.samples if s.labels.get("miniserver") == "home")
        # 4 top-level controls + 1 subcontrol = 5, or just top-level = 4
        # Discovery counts top-level controls
        assert sample.value >= 4

    def test_controls_exported_count(
        self, sample_miniserver_state: MiniserverState, sample_exporter_config: ExporterConfig
    ) -> None:
        """loxone_exporter_controls_exported should count exported controls (after filtering)."""
        from loxone_exporter.metrics import LoxoneCollector

        collector = LoxoneCollector(
            states=[sample_miniserver_state],
            config=sample_exporter_config,
        )
        metrics = list(collector.collect())
        exported = next(m for m in metrics if m.name == "loxone_exporter_controls_exported")
        sample = next(s for s in exported.samples if s.labels.get("miniserver") == "home")
        # Text-only control excluded → 3 top-level + subcontrols' states
        assert sample.value >= 3

    def test_scrape_duration_present(
        self, sample_miniserver_state: MiniserverState, sample_exporter_config: ExporterConfig
    ) -> None:
        """loxone_exporter_scrape_duration_seconds should be emitted."""
        from loxone_exporter.metrics import LoxoneCollector

        collector = LoxoneCollector(
            states=[sample_miniserver_state],
            config=sample_exporter_config,
        )
        metrics = list(collector.collect())
        duration = [m for m in metrics if m.name == "loxone_exporter_scrape_duration_seconds"]
        assert len(duration) == 1
        assert duration[0].samples[0].value >= 0


class TestFilteringAndExclusion:
    """US2: Filtering and exclusion rules for metrics export."""

    def _make_config(self, ms_config: MiniserverConfig, **overrides: Any) -> ExporterConfig:
        """Create an ExporterConfig with filtering overrides."""
        defaults: dict[str, Any] = {
            "miniservers": (ms_config,),
            "listen_port": 9504,
            "listen_address": "0.0.0.0",
            "log_level": "info",
            "log_format": "json",
        }
        defaults.update(overrides)
        return ExporterConfig(**defaults)

    def test_room_exclusion(
        self, sample_miniserver_state: MiniserverState, sample_miniserver_config: MiniserverConfig
    ) -> None:
        """Controls in excluded rooms should be omitted from loxone_control_value."""
        from loxone_exporter.metrics import LoxoneCollector

        config = self._make_config(sample_miniserver_config, exclude_rooms=["Kitchen"])
        collector = LoxoneCollector(states=[sample_miniserver_state], config=config)
        metrics = list(collector.collect())
        family = next(m for m in metrics if m.name == "loxone_control_value")
        names = {s.labels.get("name") for s in family.samples if s.name == "loxone_control_value"}
        assert "Kitchen Light" not in names
        # Other controls should still be present
        assert "Living Room Climate" in names
        assert "Outside Temperature" in names

    def test_type_exclusion(
        self, sample_miniserver_state: MiniserverState, sample_miniserver_config: MiniserverConfig
    ) -> None:
        """Controls of excluded types should be omitted."""
        from loxone_exporter.metrics import LoxoneCollector

        config = self._make_config(sample_miniserver_config, exclude_types=["InfoOnlyAnalog"])
        collector = LoxoneCollector(states=[sample_miniserver_state], config=config)
        metrics = list(collector.collect())
        family = next(m for m in metrics if m.name == "loxone_control_value")
        names = {s.labels.get("name") for s in family.samples if s.name == "loxone_control_value"}
        assert "Outside Temperature" not in names
        assert "Kitchen Light" in names

    def test_name_glob_exclusion(
        self, sample_miniserver_state: MiniserverState, sample_miniserver_config: MiniserverConfig
    ) -> None:
        """Controls matching name glob patterns should be excluded."""
        from loxone_exporter.metrics import LoxoneCollector

        config = self._make_config(sample_miniserver_config, exclude_names=["Kitchen*"])
        collector = LoxoneCollector(states=[sample_miniserver_state], config=config)
        metrics = list(collector.collect())
        family = next(m for m in metrics if m.name == "loxone_control_value")
        names = {s.labels.get("name") for s in family.samples if s.name == "loxone_control_value"}
        assert "Kitchen Light" not in names
        assert "Living Room Climate" in names

    def test_combined_filters(
        self, sample_miniserver_state: MiniserverState, sample_miniserver_config: MiniserverConfig
    ) -> None:
        """Multiple filter types should combine (union of exclusions)."""
        from loxone_exporter.metrics import LoxoneCollector

        config = self._make_config(
            sample_miniserver_config,
            exclude_rooms=["Kitchen"],
            exclude_types=["InfoOnlyAnalog"],
        )
        collector = LoxoneCollector(states=[sample_miniserver_state], config=config)
        metrics = list(collector.collect())
        family = next(m for m in metrics if m.name == "loxone_control_value")
        names = {s.labels.get("name") for s in family.samples if s.name == "loxone_control_value"}
        assert "Kitchen Light" not in names
        assert "Outside Temperature" not in names
        assert "Living Room Climate" in names

    def test_text_only_opt_in_produces_info_metric(
        self, sample_miniserver_state: MiniserverState, sample_miniserver_config: MiniserverConfig
    ) -> None:
        """With include_text_values=True, text controls produce loxone_control_info."""
        from loxone_exporter.metrics import LoxoneCollector

        config = self._make_config(sample_miniserver_config, include_text_values=True)
        collector = LoxoneCollector(states=[sample_miniserver_state], config=config)
        metrics = list(collector.collect())

        # Should have loxone_control_info metric
        info_families = [m for m in metrics if m.name == "loxone_control"]
        assert len(info_families) == 1
        info = info_families[0]
        text_samples = [
            s for s in info.samples
            if "Status Display" in str(s.labels)
        ]
        assert len(text_samples) > 0
        # Should contain the text value as a label
        text_sample = text_samples[0]
        assert text_sample.labels.get("value") == "All OK"

    def test_text_only_excluded_by_default_no_info_metric(
        self, sample_miniserver_state: MiniserverState, sample_miniserver_config: MiniserverConfig
    ) -> None:
        """Default config should NOT produce loxone_control_info."""
        from loxone_exporter.metrics import LoxoneCollector

        config = self._make_config(sample_miniserver_config)
        collector = LoxoneCollector(states=[sample_miniserver_state], config=config)
        metrics = list(collector.collect())
        info_families = [m for m in metrics if m.name == "loxone_control"]
        assert len(info_families) == 0

    def test_discovered_vs_exported_with_filtering(
        self, sample_miniserver_state: MiniserverState, sample_miniserver_config: MiniserverConfig
    ) -> None:
        """controls_discovered > controls_exported when filtering is applied."""
        from loxone_exporter.metrics import LoxoneCollector

        config = self._make_config(
            sample_miniserver_config,
            exclude_rooms=["Kitchen"],
            exclude_types=["InfoOnlyAnalog"],
        )
        collector = LoxoneCollector(states=[sample_miniserver_state], config=config)
        metrics = list(collector.collect())

        discovered = next(m for m in metrics if m.name == "loxone_exporter_controls_discovered")
        exported = next(m for m in metrics if m.name == "loxone_exporter_controls_exported")

        d_val = next(s for s in discovered.samples if s.labels.get("miniserver") == "home").value
        e_val = next(s for s in exported.samples if s.labels.get("miniserver") == "home").value

        assert d_val > e_val, f"discovered={d_val} should be > exported={e_val}"
        # Kitchen Light excluded (room) + Outside Temp excluded (type) + Status Display (text-only)
        # Only Living Room Climate should be exported
        assert e_val >= 1

    def test_discovered_equals_exported_without_filtering(
        self, sample_miniserver_state: MiniserverState, sample_miniserver_config: MiniserverConfig
    ) -> None:
        """Without filtering, discovered >= exported (text-only still excluded by default)."""
        from loxone_exporter.metrics import LoxoneCollector

        config = self._make_config(sample_miniserver_config)
        collector = LoxoneCollector(states=[sample_miniserver_state], config=config)
        metrics = list(collector.collect())

        discovered = next(m for m in metrics if m.name == "loxone_exporter_controls_discovered")
        exported = next(m for m in metrics if m.name == "loxone_exporter_controls_exported")

        d_val = next(s for s in discovered.samples if s.labels.get("miniserver") == "home").value
        e_val = next(s for s in exported.samples if s.labels.get("miniserver") == "home").value

        # discovered counts all controls, exported excludes text-only
        assert d_val >= e_val


# ── T053: OTLP Health Metrics Unit Tests ──────────────────────────────


class TestOTLPHealthMetrics:
    """Tests for OTLP health metrics defined in metrics.py."""

    def test_otlp_export_status_exists(self) -> None:
        from loxone_exporter.metrics import otlp_export_status

        assert otlp_export_status is not None
        assert otlp_export_status._name == "loxone_otlp_export_status"

    def test_otlp_last_success_timestamp_exists(self) -> None:
        from loxone_exporter.metrics import otlp_last_success_timestamp

        assert otlp_last_success_timestamp is not None
        assert otlp_last_success_timestamp._name == "loxone_otlp_last_success_timestamp_seconds"

    def test_otlp_consecutive_failures_exists(self) -> None:
        from loxone_exporter.metrics import otlp_consecutive_failures

        assert otlp_consecutive_failures is not None
        assert otlp_consecutive_failures._name == "loxone_otlp_consecutive_failures"

    def test_otlp_export_duration_exists(self) -> None:
        from loxone_exporter.metrics import otlp_export_duration

        assert otlp_export_duration is not None
        assert otlp_export_duration._name == "loxone_otlp_export_duration_seconds"

    def test_otlp_exported_metrics_total_exists(self) -> None:
        from loxone_exporter.metrics import otlp_exported_metrics_total

        assert otlp_exported_metrics_total is not None
        # Counter's _name doesn't include the _total suffix
        assert "loxone_otlp_exported_metrics" in otlp_exported_metrics_total._name

    def test_health_metrics_registered_in_registry(self) -> None:
        """Verify OTLP health metrics can be registered and collected."""
        from prometheus_client import CollectorRegistry

        from loxone_exporter.metrics import (
            otlp_consecutive_failures,
            otlp_export_duration,
            otlp_export_status,
            otlp_exported_metrics_total,
            otlp_last_success_timestamp,
        )

        registry = CollectorRegistry()
        registry.register(otlp_export_status)
        registry.register(otlp_last_success_timestamp)
        registry.register(otlp_consecutive_failures)
        registry.register(otlp_export_duration)
        registry.register(otlp_exported_metrics_total)

        # Set values and collect
        otlp_export_status.set(1.0)
        otlp_consecutive_failures.set(0.0)

        from prometheus_client import generate_latest

        output = generate_latest(registry).decode()
        assert "loxone_otlp_export_status" in output
        assert "loxone_otlp_consecutive_failures" in output

        # Clean up: unregister to avoid pollution
        registry.unregister(otlp_export_status)
        registry.unregister(otlp_last_success_timestamp)
        registry.unregister(otlp_consecutive_failures)
        registry.unregister(otlp_export_duration)
        registry.unregister(otlp_exported_metrics_total)
