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
from loxone_exporter.metrics import LoxoneCollector, scrape_errors_total
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

    # Create HTTP app
    app = create_app(config, states=states, registry=registry)

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

        # Wait for shutdown signal, then cancel the group
        async def _wait_for_shutdown() -> None:
            await shutdown_event.wait()
            logger.info("Shutting down gracefully...")
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
