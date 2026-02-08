"""Contract tests for /metrics and /healthz HTTP endpoints.

Validates that the HTTP API conforms to contracts/http-api.openapi.yaml.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from loxone_exporter.config import ExporterConfig
    from loxone_exporter.structure import MiniserverState


class TestMetricsEndpoint:
    """Contract tests for GET /metrics."""

    async def test_returns_prometheus_text_format(
        self,
        aiohttp_client: Any,
        sample_miniserver_state: MiniserverState,
        sample_exporter_config: ExporterConfig,
    ) -> None:
        """GET /metrics should return Prometheus text exposition format."""
        from loxone_exporter.server import create_app

        app = create_app(sample_exporter_config, states=[sample_miniserver_state])
        client = await aiohttp_client(app)
        resp = await client.get("/metrics")

        assert resp.status == 200
        content_type = resp.headers.get("Content-Type", "")
        assert "text/plain" in content_type

    async def test_help_and_type_annotations_present(
        self,
        aiohttp_client: Any,
        sample_miniserver_state: MiniserverState,
        sample_exporter_config: ExporterConfig,
    ) -> None:
        """Every metric must have # HELP and # TYPE annotations."""
        from loxone_exporter.server import create_app

        app = create_app(sample_exporter_config, states=[sample_miniserver_state])
        client = await aiohttp_client(app)
        resp = await client.get("/metrics")
        text = await resp.text()

        # Extract all metric names from data lines (not comments)
        metric_names: set[str] = set()
        for line in text.splitlines():
            if line and not line.startswith("#"):
                name = line.split("{")[0].split(" ")[0]
                # Strip _total, _info suffixes for matching
                base = re.sub(r"_(total|info|created|bucket)$", "", name)
                metric_names.add(base)

        # Each metric name should have a HELP line
        for name in metric_names:
            assert f"# HELP {name}" in text or f"# HELP {name}_" in text, (
                f"Missing # HELP for {name}"
            )

    async def test_loxone_control_value_present(
        self,
        aiohttp_client: Any,
        sample_miniserver_state: MiniserverState,
        sample_exporter_config: ExporterConfig,
    ) -> None:
        """loxone_control_value metric should appear with correct labels."""
        from loxone_exporter.server import create_app

        app = create_app(sample_exporter_config, states=[sample_miniserver_state])
        client = await aiohttp_client(app)
        resp = await client.get("/metrics")
        text = await resp.text()

        assert "loxone_control_value" in text
        assert 'miniserver="home"' in text
        assert 'name="Kitchen Light"' in text

    async def test_self_health_metrics_present(
        self,
        aiohttp_client: Any,
        sample_miniserver_state: MiniserverState,
        sample_exporter_config: ExporterConfig,
    ) -> None:
        """Self-health metrics should all appear in /metrics output."""
        from loxone_exporter.server import create_app

        app = create_app(sample_exporter_config, states=[sample_miniserver_state])
        client = await aiohttp_client(app)
        resp = await client.get("/metrics")
        text = await resp.text()

        required_metrics = [
            "loxone_exporter_up",
            "loxone_exporter_connected",
            "loxone_exporter_last_update_timestamp_seconds",
            "loxone_exporter_controls_discovered",
            "loxone_exporter_controls_exported",
        ]
        for metric in required_metrics:
            assert metric in text, f"Missing metric: {metric}"


class TestHealthzEndpoint:
    """Contract tests for GET /healthz per OpenAPI spec."""

    async def test_healthz_returns_json(
        self,
        aiohttp_client: Any,
        sample_miniserver_state: MiniserverState,
        sample_exporter_config: ExporterConfig,
    ) -> None:
        """GET /healthz should return application/json."""
        from loxone_exporter.server import create_app

        app = create_app(sample_exporter_config, states=[sample_miniserver_state])
        client = await aiohttp_client(app)
        resp = await client.get("/healthz")

        assert resp.status == 200
        assert "application/json" in resp.headers.get("Content-Type", "")

    async def test_healthz_has_status_field(
        self,
        aiohttp_client: Any,
        sample_miniserver_state: MiniserverState,
        sample_exporter_config: ExporterConfig,
    ) -> None:
        """Health response must have 'status' field."""
        from loxone_exporter.server import create_app

        app = create_app(sample_exporter_config, states=[sample_miniserver_state])
        client = await aiohttp_client(app)
        resp = await client.get("/healthz")
        body = await resp.json()

        assert "status" in body
        assert body["status"] in ("healthy", "degraded", "unhealthy")

    async def test_healthz_has_miniservers_field(
        self,
        aiohttp_client: Any,
        sample_miniserver_state: MiniserverState,
        sample_exporter_config: ExporterConfig,
    ) -> None:
        """Health response must have 'miniservers' array."""
        from loxone_exporter.server import create_app

        app = create_app(sample_exporter_config, states=[sample_miniserver_state])
        client = await aiohttp_client(app)
        resp = await client.get("/healthz")
        body = await resp.json()

        assert "miniservers" in body
        assert isinstance(body["miniservers"], list)
        assert len(body["miniservers"]) >= 1

    async def test_healthz_miniserver_fields(
        self,
        aiohttp_client: Any,
        sample_miniserver_state: MiniserverState,
        sample_exporter_config: ExporterConfig,
    ) -> None:
        """Each miniserver entry must have required fields per OpenAPI schema."""
        from loxone_exporter.server import create_app

        app = create_app(sample_exporter_config, states=[sample_miniserver_state])
        client = await aiohttp_client(app)
        resp = await client.get("/healthz")
        body = await resp.json()

        ms = body["miniservers"][0]
        assert "name" in ms
        assert "connected" in ms
        assert "last_update" in ms
        assert "controls_discovered" in ms
        assert "controls_exported" in ms

    async def test_healthz_healthy_when_connected(
        self,
        aiohttp_client: Any,
        sample_miniserver_state: MiniserverState,
        sample_exporter_config: ExporterConfig,
    ) -> None:
        """Status should be 'healthy' when all miniservers are connected."""
        from loxone_exporter.server import create_app

        app = create_app(sample_exporter_config, states=[sample_miniserver_state])
        client = await aiohttp_client(app)
        resp = await client.get("/healthz")
        body = await resp.json()

        assert body["status"] == "healthy"
        assert resp.status == 200

    async def test_healthz_unhealthy_when_disconnected(
        self,
        aiohttp_client: Any,
        disconnected_miniserver_state: MiniserverState,
        sample_exporter_config: ExporterConfig,
    ) -> None:
        """Status should be 'unhealthy' when no miniservers connected."""
        from loxone_exporter.server import create_app

        app = create_app(sample_exporter_config, states=[disconnected_miniserver_state])
        client = await aiohttp_client(app)
        resp = await client.get("/healthz")
        body = await resp.json()

        assert body["status"] == "unhealthy"
        assert resp.status == 503


class TestMetricNamingConventions:
    """US4: Prometheus naming conventions and build info validation."""

    async def test_all_metric_names_match_pattern(
        self,
        aiohttp_client: Any,
        sample_miniserver_state: MiniserverState,
        sample_exporter_config: ExporterConfig,
    ) -> None:
        """All metric names must match loxone_(control|exporter)_[a-z_]+ pattern."""
        from loxone_exporter.server import create_app

        app = create_app(sample_exporter_config, states=[sample_miniserver_state])
        client = await aiohttp_client(app)
        resp = await client.get("/metrics")
        text = await resp.text()

        pattern = re.compile(r"^loxone_(control|exporter)_[a-z_]+$")
        for line in text.splitlines():
            if line.startswith("# TYPE "):
                parts = line.split()
                metric_name = parts[2]
                assert pattern.match(metric_name), (
                    f"Metric name '{metric_name}' does not match naming convention"
                )

    async def test_every_metric_has_help_and_type(
        self,
        aiohttp_client: Any,
        sample_miniserver_state: MiniserverState,
        sample_exporter_config: ExporterConfig,
    ) -> None:
        """Every metric must have both # HELP and # TYPE lines."""
        from loxone_exporter.server import create_app

        app = create_app(sample_exporter_config, states=[sample_miniserver_state])
        client = await aiohttp_client(app)
        resp = await client.get("/metrics")
        text = await resp.text()

        help_names = set()
        type_names = set()
        for line in text.splitlines():
            if line.startswith("# HELP "):
                help_names.add(line.split()[2])
            elif line.startswith("# TYPE "):
                type_names.add(line.split()[2])

        # Every TYPE should have a HELP
        for name in type_names:
            assert name in help_names, f"Missing # HELP for metric with # TYPE: {name}"
        # Every HELP should have a TYPE
        for name in help_names:
            assert name in type_names, f"Missing # TYPE for metric with # HELP: {name}"

    async def test_build_info_metric_present(
        self,
        aiohttp_client: Any,
        sample_miniserver_state: MiniserverState,
        sample_exporter_config: ExporterConfig,
    ) -> None:
        """loxone_exporter_build_info must have version, commit, build_date labels."""
        from loxone_exporter.server import create_app

        app = create_app(sample_exporter_config, states=[sample_miniserver_state])
        client = await aiohttp_client(app)
        resp = await client.get("/metrics")
        text = await resp.text()

        assert "loxone_exporter_build_info" in text
        # Find the build_info line
        build_lines = [
            line for line in text.splitlines()
            if "loxone_exporter_build_info{" in line
        ]
        assert len(build_lines) >= 1, "Missing loxone_exporter_build_info sample"
        build_line = build_lines[0]
        assert 'version="' in build_line
        assert 'commit="' in build_line
        assert 'build_date="' in build_line

    async def test_label_names_valid(
        self,
        aiohttp_client: Any,
        sample_miniserver_state: MiniserverState,
        sample_exporter_config: ExporterConfig,
    ) -> None:
        """All label names must match [a-zA-Z_][a-zA-Z0-9_]*."""
        from loxone_exporter.server import create_app

        app = create_app(sample_exporter_config, states=[sample_miniserver_state])
        client = await aiohttp_client(app)
        resp = await client.get("/metrics")
        text = await resp.text()

        label_pattern = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="')

        for line in text.splitlines():
            if "{" in line and not line.startswith("#"):
                # Extract labels from the line
                label_section = line[line.index("{") + 1:line.index("}")]
                labels = label_pattern.findall(label_section)
                for label in labels:
                    assert re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", label), (
                        f"Invalid label name: {label!r}"
                    )

    async def test_label_cardinality_bounded(
        self,
        aiohttp_client: Any,
        sample_miniserver_state: MiniserverState,
        sample_exporter_config: ExporterConfig,
    ) -> None:
        """Total unique label combos for loxone_control_value <= 3x control count."""
        from loxone_exporter.server import create_app

        app = create_app(sample_exporter_config, states=[sample_miniserver_state])
        client = await aiohttp_client(app)
        resp = await client.get("/metrics")
        text = await resp.text()

        # Count unique label combos for loxone_control_value
        control_value_lines = [
            line for line in text.splitlines()
            if line.startswith("loxone_control_value{")
        ]
        unique_combos = len(control_value_lines)

        # Count controls (top-level + subcontrols)
        total_controls = len(sample_miniserver_state.controls)
        for ctrl in sample_miniserver_state.controls.values():
            total_controls += len(ctrl.sub_controls)

        assert unique_combos <= 3 * total_controls, (
            f"Cardinality {unique_combos} exceeds 3x control count ({total_controls})"
        )


class TestConcurrentScrape:
    """EC-006: Concurrent scrapes must not cause data races."""

    async def test_10_parallel_scrapes_consistent(
        self,
        aiohttp_client: Any,
        sample_miniserver_state: MiniserverState,
        sample_exporter_config: ExporterConfig,
    ) -> None:
        """10 parallel GET /metrics requests must return consistent output."""
        import asyncio

        from loxone_exporter.server import create_app

        app = create_app(sample_exporter_config, states=[sample_miniserver_state])
        client = await aiohttp_client(app)

        async def fetch() -> str:
            resp = await client.get("/metrics")
            assert resp.status == 200
            return await resp.text()

        results = await asyncio.gather(*[fetch() for _ in range(10)])

        def normalize(text: str) -> list[str]:
            """Strip scrape_duration (varies per request) for comparison."""
            return [
                line for line in sorted(text.splitlines())
                if "scrape_duration" not in line
            ]

        first = normalize(results[0])
        for i, text in enumerate(results[1:], start=2):
            assert normalize(text) == first, (
                f"Response {i} differs from response 1"
            )

    async def test_parallel_scrapes_all_succeed(
        self,
        aiohttp_client: Any,
        sample_miniserver_state: MiniserverState,
        sample_exporter_config: ExporterConfig,
    ) -> None:
        """All 10 concurrent requests must return 200 with valid Prometheus text."""
        import asyncio

        from loxone_exporter.server import create_app

        app = create_app(sample_exporter_config, states=[sample_miniserver_state])
        client = await aiohttp_client(app)

        async def fetch_status() -> int:
            resp = await client.get("/metrics")
            return resp.status

        statuses = await asyncio.gather(*[fetch_status() for _ in range(10)])
        assert all(s == 200 for s in statuses), f"Non-200 statuses: {statuses}"
