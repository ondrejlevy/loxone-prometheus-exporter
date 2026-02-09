"""OpenTelemetry Protocol (OTLP) metrics exporter.

Periodically pushes metrics from the Prometheus registry to an OTLP collector
using either gRPC or HTTP protocol. Implements exponential backoff retry logic,
overlap prevention, and health status tracking.

Design:
- Runs as an asyncio background task alongside the HTTP server
- Reads from the existing prometheus_client registry (no dual-write)
- Exports the same metrics visible on /metrics in OTLP format
- Failures are isolated: Prometheus endpoint never affected
"""

from __future__ import annotations

import asyncio
import copy
import enum
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    AggregationTemporality,
    MetricExportResult,
    MetricExporter,
)
from opentelemetry.sdk.resources import Resource

if TYPE_CHECKING:
    from prometheus_client import CollectorRegistry

    from loxone_exporter.config import OTLPConfiguration

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────

_BASE_DELAY: float = 1.0
_MULTIPLIER: float = 2.0
_MAX_DELAY: float = 300.0  # 5 minutes
_MAX_FAILURES: int = 10
_SHUTDOWN_TIMEOUT: float = 5.0


# ── Data Models ────────────────────────────────────────────────────────


class ExportState(enum.IntEnum):
    """OTLP export operational state."""

    DISABLED = 0
    IDLE = 1
    EXPORTING = 2
    RETRYING = 3
    FAILED = 4


@dataclass
class ExportStatus:
    """Runtime state tracking for OTLP export health."""

    state: ExportState = ExportState.DISABLED
    last_success_timestamp: float | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    current_backoff_seconds: float = _BASE_DELAY
    next_export_timestamp: float = 0.0


@dataclass
class OTLPMetric:
    """Single metric data point for OTLP export."""

    name: str
    description: str
    unit: str
    type: str  # 'gauge', 'counter', 'histogram'
    data_points: list[DataPoint] = field(default_factory=list)


@dataclass
class DataPoint:
    """Individual measurement for OTLP export."""

    attributes: dict[str, str] = field(default_factory=dict)
    value: float = 0.0
    timestamp_ns: int = 0


@dataclass
class HistogramDataPoint:
    """Histogram measurement for OTLP export."""

    attributes: dict[str, str] = field(default_factory=dict)
    count: int = 0
    sum_value: float = 0.0
    bucket_counts: list[int] = field(default_factory=list)
    explicit_bounds: list[float] = field(default_factory=list)
    timestamp_ns: int = 0


@dataclass
class MetricBatch:
    """Collection of metrics for a single OTLP export."""

    resource_attributes: dict[str, str] = field(default_factory=dict)
    scope_name: str = "loxone_exporter"
    scope_version: str = ""
    metrics: list[OTLPMetric] = field(default_factory=list)


# ── Prometheus → OTLP Conversion ──────────────────────────────────────


class PrometheusToOTLPBridge:
    """Converts prometheus_client registry metrics to OTLP data structures."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self._registry = registry

    def convert_metrics(self) -> MetricBatch:
        """Read all metrics from Prometheus registry and convert to OTLP batch.

        Returns:
            MetricBatch with all current metric values.
        """
        from loxone_exporter import __version__

        batch = MetricBatch(
            resource_attributes={
                "service.name": "loxone-prometheus-exporter",
                "service.version": __version__,
            },
            scope_name="loxone_exporter",
            scope_version=__version__,
        )

        now_ns = int(time.time() * 1_000_000_000)

        for metric_family in self._registry.collect():
            otlp_metric = self._convert_family(metric_family, now_ns)
            if otlp_metric is not None:
                batch.metrics.append(otlp_metric)

        return batch

    def _convert_family(self, family: Any, now_ns: int) -> OTLPMetric | None:
        """Convert a single Prometheus metric family to OTLPMetric."""
        if not family.samples:
            return None

        metric_type = family.type
        name = family.name
        description = family.documentation or ""

        if metric_type == "gauge":
            return self._convert_gauge(name, description, family.samples, now_ns)
        elif metric_type == "counter":
            return self._convert_counter(name, description, family.samples, now_ns)
        elif metric_type == "histogram":
            return self._convert_histogram(name, description, family.samples, now_ns)
        elif metric_type == "info":
            return self._convert_info(name, description, family.samples, now_ns)
        else:
            # Unsupported type — skip
            logger.debug("Skipping unsupported metric type %s for %s", metric_type, name)
            return None

    def _convert_gauge(
        self, name: str, description: str, samples: list[Any], now_ns: int
    ) -> OTLPMetric:
        """Convert Prometheus Gauge → OTLP Gauge."""
        metric = OTLPMetric(name=name, description=description, unit="", type="gauge")
        for sample in samples:
            dp = DataPoint(
                attributes={str(k): str(v) for k, v in sample.labels.items()},
                value=float(sample.value),
                timestamp_ns=now_ns,
            )
            metric.data_points.append(dp)
        return metric

    def _convert_counter(
        self, name: str, description: str, samples: list[Any], now_ns: int
    ) -> OTLPMetric:
        """Convert Prometheus Counter → OTLP Sum (monotonic, cumulative)."""
        metric = OTLPMetric(name=name, description=description, unit="", type="counter")
        for sample in samples:
            # Skip _created and _total suffix variants — use the base
            if sample.name.endswith("_created"):
                continue
            dp = DataPoint(
                attributes={str(k): str(v) for k, v in sample.labels.items()},
                value=float(sample.value),
                timestamp_ns=now_ns,
            )
            metric.data_points.append(dp)
        return metric

    def _convert_histogram(
        self, name: str, description: str, samples: list[Any], now_ns: int
    ) -> OTLPMetric:
        """Convert Prometheus Histogram → OTLP Histogram."""
        metric = OTLPMetric(name=name, description=description, unit="", type="histogram")

        # Group samples by label set (excluding 'le')
        buckets_by_labels: dict[tuple[tuple[str, str], ...], dict[str, Any]] = {}

        for sample in samples:
            labels = {str(k): str(v) for k, v in sample.labels.items() if k != "le"}
            label_key = tuple(sorted(labels.items()))

            if label_key not in buckets_by_labels:
                buckets_by_labels[label_key] = {
                    "labels": labels,
                    "buckets": [],
                    "count": 0,
                    "sum": 0.0,
                }

            if sample.name.endswith("_bucket"):
                le = sample.labels.get("le", "+Inf")
                buckets_by_labels[label_key]["buckets"].append((le, int(sample.value)))
            elif sample.name.endswith("_count"):
                buckets_by_labels[label_key]["count"] = int(sample.value)
            elif sample.name.endswith("_sum"):
                buckets_by_labels[label_key]["sum"] = float(sample.value)

        for label_key, data in buckets_by_labels.items():
            # Sort buckets by bound, exclude +Inf
            sorted_buckets = sorted(
                [(b, c) for b, c in data["buckets"] if b != "+Inf"],
                key=lambda x: float(x[0]),
            )
            explicit_bounds = [float(b) for b, _ in sorted_buckets]
            bucket_counts = [c for _, c in sorted_buckets]
            # Add overflow bucket (count for +Inf)
            inf_count = next(
                (c for b, c in data["buckets"] if b == "+Inf"), data["count"]
            )
            bucket_counts.append(inf_count)

            hdp = HistogramDataPoint(
                attributes=data["labels"],
                count=data["count"],
                sum_value=data["sum"],
                bucket_counts=bucket_counts,
                explicit_bounds=explicit_bounds,
                timestamp_ns=now_ns,
            )
            # Store as a special data point — we use metric type to distinguish
            metric.data_points.append(hdp)  # type: ignore[arg-type]

        return metric

    def _convert_info(
        self, name: str, description: str, samples: list[Any], now_ns: int
    ) -> OTLPMetric:
        """Convert Prometheus Info → OTLP Gauge (value=1 with info labels)."""
        metric = OTLPMetric(name=name, description=description, unit="", type="gauge")
        for sample in samples:
            dp = DataPoint(
                attributes={str(k): str(v) for k, v in sample.labels.items()},
                value=1.0,
                timestamp_ns=now_ns,
            )
            metric.data_points.append(dp)
        return metric


# ── SDK Exporter Factory ──────────────────────────────────────────────


def create_otlp_exporter(config: OTLPConfiguration) -> MetricExporter:
    """Create the appropriate OTLP SDK exporter based on protocol config.

    Args:
        config: Validated OTLP configuration.

    Returns:
        A MetricExporter instance (gRPC or HTTP).

    Raises:
        ConfigurationError: If protocol is not supported.
    """
    from loxone_exporter.config import ConfigurationError

    endpoint = config.endpoint
    timeout_ms = config.timeout_seconds * 1000

    # Build common kwargs
    headers: dict[str, str] = {}
    if config.auth_config and config.auth_config.headers:
        headers.update(config.auth_config.headers)

    if config.protocol == "grpc":
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
            OTLPMetricExporter as GRPCExporter,
        )

        kwargs: dict[str, Any] = {
            "endpoint": endpoint,
            "timeout": timeout_ms,
            "headers": tuple(headers.items()) if headers else None,
            "insecure": True,
        }

        if config.tls_config and config.tls_config.enabled:
            kwargs["insecure"] = False
            if config.tls_config.cert_path:
                import pathlib

                cert_data = pathlib.Path(config.tls_config.cert_path).read_bytes()
                from grpc import ssl_channel_credentials

                kwargs["credentials"] = ssl_channel_credentials(root_certificates=cert_data)

        return GRPCExporter(**kwargs)

    elif config.protocol == "http":
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter as HTTPExporter,
        )

        # HTTP exporter uses /v1/metrics path by default
        http_endpoint = endpoint
        if not http_endpoint.endswith("/v1/metrics"):
            http_endpoint = http_endpoint.rstrip("/") + "/v1/metrics"

        kwargs_http: dict[str, Any] = {
            "endpoint": http_endpoint,
            "timeout": config.timeout_seconds,
            "headers": headers if headers else None,
        }

        if config.tls_config and config.tls_config.enabled and config.tls_config.cert_path:
            kwargs_http["certificate_file"] = config.tls_config.cert_path

        return HTTPExporter(**kwargs_http)

    else:
        raise ConfigurationError(
            f"Unsupported OTLP protocol: {config.protocol!r}. Must be 'grpc' or 'http'."
        )


# ── Main Exporter Class ──────────────────────────────────────────────


class OTLPExporter:
    """Manages periodic OTLP metric export lifecycle.

    Runs as an asyncio background task, periodically collecting metrics from
    the Prometheus registry, converting them to OTLP format, and pushing to
    the configured collector endpoint.
    """

    def __init__(
        self,
        config: OTLPConfiguration,
        registry: CollectorRegistry,
    ) -> None:
        """Initialize OTLP exporter.

        Args:
            config: Validated OTLP configuration.
            registry: Prometheus metrics registry to export from.
        """
        self._config = config
        self._registry = registry
        self._bridge = PrometheusToOTLPBridge(registry)
        self._sdk_exporter = create_otlp_exporter(config)
        self._status = ExportStatus(state=ExportState.IDLE)
        self._task: asyncio.Task[None] | None = None
        self._exporting = False  # overlap guard
        self._logger = logger.getChild("OTLPExporter")

    async def start(self) -> None:
        """Start export background task.

        Creates asyncio task running the export loop.
        Returns immediately after scheduling.

        Raises:
            RuntimeError: If called more than once.
        """
        if self._task is not None:
            raise RuntimeError("OTLPExporter already started")

        self._status.state = ExportState.IDLE
        self._status.next_export_timestamp = time.time() + self._config.interval_seconds
        self._task = asyncio.create_task(self._export_loop(), name="otlp-export-loop")
        self._logger.info(
            "OTLP export started: protocol=%s endpoint=%s interval=%ds",
            self._config.protocol,
            self._config.endpoint,
            self._config.interval_seconds,
        )

    async def stop(self) -> None:
        """Stop export task gracefully.

        Cancels background task and waits for completion.
        Safe to call multiple times.
        """
        if self._task is None:
            return

        self._task.cancel()
        try:
            await asyncio.wait_for(self._task, timeout=_SHUTDOWN_TIMEOUT)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        finally:
            self._task = None

        # Shutdown SDK exporter
        try:
            self._sdk_exporter.shutdown()
        except Exception:
            self._logger.warning("Error shutting down OTLP SDK exporter", exc_info=True)

        self._logger.info("OTLP export stopped")

    def get_status(self) -> ExportStatus:
        """Get current export status snapshot.

        Returns a deep copy safe to use from HTTP request handlers.
        """
        return copy.deepcopy(self._status)

    # ── Internal Methods ──────────────────────────────────────────

    async def _export_loop(self) -> None:
        """Main export loop: sleep → check → export → handle result → repeat."""
        try:
            while True:
                await asyncio.sleep(self._config.interval_seconds)

                if not self._should_export():
                    continue

                self._status.state = ExportState.EXPORTING
                self._exporting = True

                try:
                    success = await self._export_once()

                    if success:
                        self._handle_success()
                    else:
                        await self._handle_failure()
                finally:
                    self._exporting = False

        except asyncio.CancelledError:
            self._logger.debug("Export loop cancelled")
            raise

    def _should_export(self) -> bool:
        """Check if export should proceed (prevents overlap).

        Returns False if a previous export is still running.
        """
        if self._exporting:
            self._logger.warning(
                "Skipping OTLP export: previous export still in progress"
            )
            return False

        if self._status.state == ExportState.FAILED:
            # Reset on new cycle
            self._logger.info(
                "Resetting OTLP export from FAILED state for new cycle"
            )
            self._status.consecutive_failures = 0
            self._status.current_backoff_seconds = _BASE_DELAY
            self._status.state = ExportState.IDLE

        return True

    async def _export_once(self) -> bool:
        """Execute a single export attempt.

        Returns True on success, False on failure.
        """
        try:
            start_time = time.monotonic()
            batch = self._bridge.convert_metrics()
            metric_count = len(batch.metrics)

            if metric_count == 0:
                self._logger.debug("No metrics to export")
                return True

            # Use asyncio.to_thread for the synchronous SDK export call
            result = await asyncio.to_thread(
                self._do_sdk_export, batch
            )

            if result == MetricExportResult.SUCCESS:
                duration = time.monotonic() - start_time
                self._logger.debug(
                    "OTLP export successful: %d metric families in %.3fs",
                    metric_count, duration,
                )
                self._update_health_metrics_success(metric_count, duration)
                return True
            else:
                duration = time.monotonic() - start_time
                self._logger.warning(
                    "OTLP export failed with result: %s", result
                )
                self._update_health_metrics_failure(duration)
                return False

        except Exception as exc:
            duration = time.monotonic() - start_time
            self._logger.error(
                "OTLP export error: %s", _sanitize_error(str(exc))
            )
            self._update_health_metrics_failure(duration)
            return False

    def _do_sdk_export(self, batch: MetricBatch) -> MetricExportResult:
        """Perform the actual SDK export call (synchronous, runs in thread).

        Converts our MetricBatch into OpenTelemetry SDK metric data
        and calls the SDK exporter.
        """
        from opentelemetry.sdk.metrics.export import (
            Gauge,
            Metric,
            MetricsData,
            NumberDataPoint,
            ResourceMetrics,
            ScopeMetrics,
            Sum,
        )
        from opentelemetry.sdk.resources import Resource as OTELResource
        from opentelemetry.sdk.util.instrumentation import InstrumentationScope

        resource = OTELResource.create(batch.resource_attributes)
        scope = InstrumentationScope(
            name=batch.scope_name,
            version=batch.scope_version,
        )

        sdk_metrics: list[Metric] = []
        now_ns = int(time.time() * 1_000_000_000)

        for m in batch.metrics:
            if m.type == "gauge":
                data_points = [
                    NumberDataPoint(
                        attributes=dp.attributes,
                        start_time_unix_nano=0,
                        time_unix_nano=dp.timestamp_ns or now_ns,
                        value=dp.value,
                    )
                    for dp in m.data_points
                    if isinstance(dp, DataPoint)
                ]
                if data_points:
                    sdk_metrics.append(
                        Metric(
                            name=m.name,
                            description=m.description,
                            unit=m.unit,
                            data=Gauge(data_points=data_points),
                        )
                    )

            elif m.type == "counter":
                data_points_sum = [
                    NumberDataPoint(
                        attributes=dp.attributes,
                        start_time_unix_nano=0,
                        time_unix_nano=dp.timestamp_ns or now_ns,
                        value=dp.value,
                    )
                    for dp in m.data_points
                    if isinstance(dp, DataPoint)
                ]
                if data_points_sum:
                    sdk_metrics.append(
                        Metric(
                            name=m.name,
                            description=m.description,
                            unit=m.unit,
                            data=Sum(
                                data_points=data_points_sum,
                                aggregation_temporality=AggregationTemporality.CUMULATIVE,
                                is_monotonic=True,
                            ),
                        )
                    )

            elif m.type == "histogram":
                from opentelemetry.sdk.metrics.export import (
                    Histogram as OTELHistogram,
                    HistogramDataPoint as OTELHistogramDP,
                )

                hist_points = [
                    OTELHistogramDP(
                        attributes=hdp.attributes,
                        start_time_unix_nano=0,
                        time_unix_nano=hdp.timestamp_ns or now_ns,
                        count=hdp.count,
                        sum=hdp.sum_value,
                        bucket_counts=hdp.bucket_counts,
                        explicit_bounds=hdp.explicit_bounds,
                        min=0,
                        max=0,
                    )
                    for hdp in m.data_points
                    if isinstance(hdp, HistogramDataPoint)
                ]
                if hist_points:
                    sdk_metrics.append(
                        Metric(
                            name=m.name,
                            description=m.description,
                            unit=m.unit,
                            data=OTELHistogram(
                                data_points=hist_points,
                                aggregation_temporality=AggregationTemporality.CUMULATIVE,
                            ),
                        )
                    )

        if not sdk_metrics:
            return MetricExportResult.SUCCESS

        scope_metrics = ScopeMetrics(
            scope=scope,
            metrics=sdk_metrics,
            schema_url="",
        )
        resource_metrics = ResourceMetrics(
            resource=resource,
            scope_metrics=[scope_metrics],
            schema_url="",
        )
        metrics_data = MetricsData(resource_metrics=[resource_metrics])

        return self._sdk_exporter.export(metrics_data)

    def _handle_success(self) -> None:
        """Handle successful export — reset failures, update timestamps."""
        self._status.state = ExportState.IDLE
        self._status.last_success_timestamp = time.time()
        self._status.last_error = None
        self._status.consecutive_failures = 0
        self._status.current_backoff_seconds = _BASE_DELAY
        self._status.next_export_timestamp = time.time() + self._config.interval_seconds
        self._sync_health_metrics()

    async def _handle_failure(self) -> None:
        """Handle failed export — increment failures, apply backoff."""
        self._status.consecutive_failures += 1

        if self._status.consecutive_failures >= _MAX_FAILURES:
            self._status.state = ExportState.FAILED
            self._logger.critical(
                "OTLP export failed after %d consecutive attempts. "
                "Will retry on next scheduled cycle.",
                _MAX_FAILURES,
            )
        else:
            self._status.state = ExportState.RETRYING
            backoff = _calculate_backoff(self._status.consecutive_failures)
            self._status.current_backoff_seconds = backoff
            self._logger.warning(
                "OTLP export failed (attempt %d/%d). Retrying in %.1fs",
                self._status.consecutive_failures,
                _MAX_FAILURES,
                backoff,
            )
            await asyncio.sleep(backoff)

            # Retry immediately after backoff
            self._status.state = ExportState.EXPORTING
            self._exporting = True
            try:
                success = await self._export_once()
                if success:
                    self._handle_success()
                else:
                    await self._handle_failure()
            finally:
                self._exporting = False

        self._sync_health_metrics()

    def _sync_health_metrics(self) -> None:
        """Sync ExportStatus with Prometheus health metrics (T048)."""
        try:
            from loxone_exporter.metrics import (
                otlp_consecutive_failures,
                otlp_export_status,
                otlp_last_success_timestamp,
            )

            otlp_export_status.set(float(self._status.state))
            otlp_consecutive_failures.set(float(self._status.consecutive_failures))
            if self._status.last_success_timestamp is not None:
                otlp_last_success_timestamp.set(self._status.last_success_timestamp)
        except Exception:
            # Health metric updates are best-effort
            self._logger.debug("Failed to update OTLP health metrics", exc_info=True)

    def _update_health_metrics_success(self, metric_count: int, duration: float) -> None:
        """Update health metrics after successful export (T049)."""
        try:
            from loxone_exporter.metrics import (
                otlp_export_duration,
                otlp_exported_metrics_total,
            )

            otlp_export_duration.observe(duration)
            otlp_exported_metrics_total.inc(metric_count)
        except Exception:
            self._logger.debug("Failed to update OTLP success metrics", exc_info=True)

    def _update_health_metrics_failure(self, duration: float) -> None:
        """Update health metrics after failed export (T050)."""
        try:
            from loxone_exporter.metrics import otlp_export_duration

            otlp_export_duration.observe(duration)
        except Exception:
            self._logger.debug("Failed to update OTLP failure metrics", exc_info=True)


# ── Helper Functions ──────────────────────────────────────────────────


def _calculate_backoff(consecutive_failures: int) -> float:
    """Calculate exponential backoff delay.

    Formula: min(base_delay * (multiplier ^ (failures - 1)), max_delay)

    Args:
        consecutive_failures: Number of consecutive failures (1-10).

    Returns:
        Delay in seconds, capped at MAX_DELAY.
    """
    if consecutive_failures <= 0:
        return _BASE_DELAY
    delay = _BASE_DELAY * (_MULTIPLIER ** (consecutive_failures - 1))
    return min(delay, _MAX_DELAY)


def _sanitize_error(message: str) -> str:
    """Remove potential credentials from error messages."""
    import re

    patterns = [
        (re.compile(r"(Bearer\s+)\S+", re.IGNORECASE), r"\1****"),
        (re.compile(r"(Authorization:\s*)\S+", re.IGNORECASE), r"\1****"),
        (re.compile(r"(api[_-]?key[=:]\s*)\S+", re.IGNORECASE), r"\1****"),
        (re.compile(r"(token[=:]\s*)\S+", re.IGNORECASE), r"\1****"),
    ]
    for pattern, replacement in patterns:
        message = pattern.sub(replacement, message)
    return message
