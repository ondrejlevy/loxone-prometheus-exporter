"""HTTP server for /metrics and /healthz endpoints.

Uses aiohttp to serve Prometheus metrics and health checks in the same
asyncio event loop as the WebSocket clients.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import web
from prometheus_client import CollectorRegistry, generate_latest

from loxone_exporter.metrics import LoxoneCollector, scrape_errors_total

if TYPE_CHECKING:
    from loxone_exporter.config import ExporterConfig
    from loxone_exporter.structure import MiniserverState

logger = logging.getLogger(__name__)


async def _metrics_handler(request: web.Request) -> web.Response:
    """Handle GET /metrics — generate Prometheus text exposition format."""
    registry: CollectorRegistry = request.app["registry"]
    try:
        output = generate_latest(registry)
        return web.Response(
            body=output,
            content_type="text/plain; version=0.0.4",
            charset="utf-8",
        )
    except Exception:
        logger.exception("Error generating metrics")
        scrape_errors_total.inc()
        return web.Response(status=500, text="Internal error generating metrics")


async def _healthz_handler(request: web.Request) -> web.Response:
    """Handle GET /healthz — return JSON health status per OpenAPI spec."""
    states: list[MiniserverState] = request.app["states"]
    request.app["config"]

    miniservers = []
    for ms in states:
        # Count discovered and exported controls
        total_discovered = len(ms.controls)
        for ctrl in ms.controls.values():
            total_discovered += len(ctrl.sub_controls)

        # Exported count requires filtering — approximate by counting non-text controls
        total_exported = 0
        for ctrl in ms.controls.values():
            if not ctrl.is_text_only:
                total_exported += 1
                total_exported += sum(1 for sc in ctrl.sub_controls if not sc.is_text_only)

        miniservers.append({
            "name": ms.name,
            "connected": ms.connected,
            "last_update": ms.last_update_ts,
            "controls_discovered": total_discovered,
            "controls_exported": total_exported,
        })

    # Determine status
    connected_count = sum(1 for ms in states if ms.connected)
    total_count = len(states)

    if connected_count == total_count and total_count > 0:
        status = "healthy"
        http_status = 200
    elif connected_count > 0:
        status = "degraded"
        http_status = 200
    else:
        status = "unhealthy"
        http_status = 503

    body = {
        "status": status,
        "miniservers": miniservers,
    }

    # Include OTLP status if exporter is available
    otlp_exporter = request.app.get("otlp_exporter")
    if otlp_exporter is not None:
        from loxone_exporter.otlp_exporter import ExportState

        otlp_status = otlp_exporter.get_status()
        body["otlp"] = {
            "state": otlp_status.state.name.lower(),
            "last_success": otlp_status.last_success_timestamp,
            "consecutive_failures": otlp_status.consecutive_failures,
            "last_error": otlp_status.last_error,
        }
        # Degrade overall status if OTLP is in FAILED state
        if otlp_status.state == ExportState.FAILED and status == "healthy":
            body["status"] = "degraded"

    return web.json_response(body, status=http_status)


def create_app(
    config: ExporterConfig,
    states: list[MiniserverState],
    registry: CollectorRegistry | None = None,
) -> web.Application:
    """Create the aiohttp application with /metrics and /healthz routes.

    Args:
        config: Exporter configuration.
        states: List of MiniserverState objects (updated by LoxoneClients).
        registry: Prometheus registry. If None, creates a new one with LoxoneCollector.

    Returns:
        Configured ``aiohttp.web.Application``.
    """
    app = web.Application()

    if registry is None:
        registry = CollectorRegistry(auto_describe=True)
        collector = LoxoneCollector(states=states, config=config)
        registry.register(collector)
        # Register scrape errors counter
        registry.register(scrape_errors_total)

    app["registry"] = registry
    app["states"] = states
    app["config"] = config

    app.router.add_get("/metrics", _metrics_handler)
    app.router.add_get("/healthz", _healthz_handler)

    return app


async def run_http_server(app: web.Application, config: ExporterConfig) -> None:
    """Start the HTTP server and run until cancelled.

    Args:
        app: The aiohttp application.
        config: Exporter configuration for host/port binding.
    """
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.listen_address, config.listen_port)
    logger.info("HTTP server listening on %s:%d", config.listen_address, config.listen_port)
    await site.start()

    try:
        # Run forever until cancelled
        while True:
            await __import__("asyncio").sleep(3600)
    finally:
        await runner.cleanup()
