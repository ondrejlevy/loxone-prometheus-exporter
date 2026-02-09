"""Loxone Prometheus Exporter entry point.

Usage::

    python -m loxone_exporter [--config CONFIG_PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from prometheus_client import CollectorRegistry

from loxone_exporter.config import ConfigError, load_config
from loxone_exporter.logging import setup_logging
from loxone_exporter.loxone_client import LoxoneClient
from loxone_exporter.metrics import (
    LoxoneCollector,
    otlp_consecutive_failures,
    otlp_export_duration,
    otlp_export_status,
    otlp_exported_metrics_total,
    otlp_last_success_timestamp,
    scrape_errors_total,
)
from loxone_exporter.otlp_exporter import OTLPExporter
from loxone_exporter.server import create_app, run_http_server

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="loxone_exporter",
        description="Export Loxone Miniserver metrics to Prometheus",
    )
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="Path to YAML config file (default: config.yml / config.yaml / env vars)",
    )
    return parser.parse_args(argv)


async def _run(config_path: str | None) -> None:
    """Main async entry point."""
    # Load configuration
    config = load_config(config_path)

    # Set up logging
    setup_logging(level=config.log_level, fmt=config.log_format)

    logger.info(
        "Starting Loxone Prometheus Exporter with %d miniserver(s)",
        len(config.miniservers),
    )

    # Create clients for each miniserver
    clients = [LoxoneClient(ms) for ms in config.miniservers]
    states = [client.get_state() for client in clients]

    # Create Prometheus registry with collector
    registry = CollectorRegistry(auto_describe=True)
    collector = LoxoneCollector(states=states, config=config)
    registry.register(collector)
    registry.register(scrape_errors_total)

    # Register OTLP health metrics
    if config.opentelemetry.enabled:
        registry.register(otlp_export_status)
        registry.register(otlp_last_success_timestamp)
        registry.register(otlp_consecutive_failures)
        registry.register(otlp_export_duration)
        registry.register(otlp_exported_metrics_total)

    # Create HTTP app
    app = create_app(config, states=states, registry=registry)

    # Create OTLP exporter if enabled
    otlp_exporter: OTLPExporter | None = None
    if config.opentelemetry.enabled:
        otlp_exporter = OTLPExporter(config.opentelemetry, registry)
        app["otlp_exporter"] = otlp_exporter
        logger.info("OTLP export enabled: %s → %s",
                     config.opentelemetry.protocol, config.opentelemetry.endpoint)
    else:
        logger.info("OTLP export disabled")

    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    # Run all tasks
    async with asyncio.TaskGroup() as tg:
        # Start WebSocket clients
        for client in clients:
            tg.create_task(client.run())

        # Start HTTP server
        tg.create_task(run_http_server(app, config))

        # Start OTLP exporter if enabled
        if otlp_exporter is not None:
            async def _run_otlp(exporter: OTLPExporter) -> None:
                await exporter.start()
                try:
                    # Keep running until cancelled
                    while True:
                        await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    await exporter.stop()
                    raise

            tg.create_task(_run_otlp(otlp_exporter))

        # Wait for shutdown signal, then cancel the group
        async def _wait_for_shutdown() -> None:
            await shutdown_event.wait()
            logger.info("Shutting down gracefully...")
            if otlp_exporter is not None:
                await otlp_exporter.stop()
            raise asyncio.CancelledError()

        tg.create_task(_wait_for_shutdown())


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    args = _parse_args(argv)
    try:
        asyncio.run(_run(args.config))
    except KeyboardInterrupt:
        pass
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Fatal error: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
