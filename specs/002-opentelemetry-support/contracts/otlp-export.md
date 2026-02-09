# Module Contract: otlp_exporter.py

**Feature**: 002-opentelemetry-support  
**Date**: 2026-02-09

This document defines the public interface and implementation contract for the OTLP exporter module.

---

## Module Overview

`otlp_exporter.py` encapsulates all OpenTelemetry export logic, including:
- Periodic metrics export lifecycle
- Protocol abstraction (gRPC/HTTP)
- Retry state machine with exponential backoff
- Prometheus → OTLP metric conversion
- Health status tracking

**Design Principles**:
- Single Responsibility: All OTLP logic contained in this module
- Asyncio Integration: Runs as background task in main event loop
- Error Isolation: Export failures don't affect Prometheus endpoint
- Observable: Exposes health status via Prometheus metrics

---

## Public Interface

### Class: `OTLPExporter`

Main class managing OTLP export lifecycle.

#### Constructor

```python
def __init__(
    self,
    config: OTLPConfiguration,
    registry: prometheus_client.CollectorRegistry,
    metrics: Metrics,
    logger: logging.Logger
) -> None:
    """
    Initialize OTLP exporter.
    
    Args:
        config: Validated OTLP configuration from config file
        registry: Prometheus metrics registry to export from
        metrics: Metrics instance for updating health metrics
        logger: Logger instance for structured logging
    
    Raises:
        ConfigurationError: If config validation failed (should be caught at startup)
    """
```

**Initialization sequence**:
1. Validate configuration (redundant check, should already be validated)
2. Create OTLP SDK exporter via factory (gRPC or HTTP based on protocol)
3. Initialize `PrometheusToOTLPBridge` for metric conversion
4. Initialize `ExportStatus` (state = IDLE)
5. Register health metrics with Metrics instance

**Example**:
```python
config = OTLPConfiguration(...)  # From YAML
registry = prometheus_client.CollectorRegistry()
metrics = Metrics(registry)
logger = logging.getLogger(__name__)

exporter = OTLPExporter(config, registry, metrics, logger)
```

#### Method: `start()`

```python
async def start(self) -> None:
    """
    Start export background task.
    
    Begins periodic export loop in current asyncio event loop.
    Returns immediately after scheduling the task.
    
    Should be called during application startup, after HTTP server initialization.
    
    Raises:
        RuntimeError: If called more than once
    """
```

**Behavior**:
- Creates asyncio task running `_export_loop()`
- Returns control immediately (non-blocking)
- Task runs until `stop()` called or exception raised

**Example**:
```python
# In server.py main()
otlp_exporter = OTLPExporter(...)
await otlp_exporter.start()  # Non-blocking
```

#### Method: `stop()`

```python
async def stop(self) -> None:
    """
    Stop export task gracefully.
    
    Cancels background task and waits for cancellation to complete.
    Should be called on SIGTERM or application shutdown.
    
    Safe to call multiple times (no-op if already stopped).
    
    Timeout: 5 seconds (hard limit to prevent hanging shutdown)
    """
```

**Behavior**:
1. Cancel export task via `task.cancel()`
2. Await task completion (catches `asyncio.CancelledError`)
3. Close SDK exporter (cleanup gRPC channel or HTTP session)
4. Log shutdown complete

**Example**:
```python
# In server.py shutdown handler
async def shutdown():
    await otlp_exporter.stop()
    # ... shutdown other components
```

#### Method: `get_status()`

```python
def get_status(self) -> ExportStatus:
    """
    Get current export status.
    
    Returns snapshot of current state for health endpoint.
    Thread-safe (returns copy, not reference).
    
    Returns:
        ExportStatus with current state, last success timestamp, failure count, etc.
    """
```

**Behavior**:
- Returns deep copy of internal `ExportStatus` state
- Non-blocking, safe to call from HTTP request handler

**Example**:
```python
# In health endpoint handler
status = otlp_exporter.get_status()
return {
    "otlp": {
        "enabled": True,
        "state": status.state.name.lower(),
        "last_success": status.last_success_timestamp,
        "consecutive_failures": status.consecutive_failures,
        "protocol": config.protocol
    }
}
```

---

## Internal Methods (Private)

These methods are implementation details, not part of the public interface.

### `_export_loop()`

```python
async def _export_loop(self) -> None:
    """
    Main export loop: sleep → check → export → handle result → repeat.
    
    Runs until cancelled (via stop()).
    Catches and logs all exceptions (never crashes).
    """
```

**Pseudocode**:
```python
while True:
    try:
        await asyncio.sleep(config.interval_seconds)
        
        if not self._should_export():
            continue  # Skip overlapping export
        
        success = await self._export_once()
        
        if success:
            self._handle_success()
        else:
            self._handle_failure()
    
    except asyncio.CancelledError:
        logger.info("Export loop cancellation")
        break
    except Exception as e:
        logger.error(f"Unexpected error in export loop: {e}")
        # Continue loop (don't crash)
```

### `_should_export()`

```python
def _should_export(self) -> bool:
    """
    Determine if export should proceed.
    
    Returns False if:
    - Currently in EXPORTING state (overlap prevention)
    - In FAILED state (wait for reset)
    
    Returns True otherwise (IDLE or RETRYING states).
    """
```

**Overlap handling** (FR-015):
- If previous export is still running when interval fires → skip
- Prevents queue buildup and resource exhaustion
- Logs warning with skip reason

### `_export_once()`

```python
async def _export_once(self) -> bool:
    """
    Execute single export attempt.
    
    Steps:
    1. Update state to EXPORTING
    2. Convert metrics (Prometheus → OTLP)
    3. Send via SDK exporter (in executor to avoid blocking)
    4. Update metrics (duration, count)
    5. Return success/failure
    
    Returns:
        True if export succeeded, False otherwise
    
    Side effects:
        - Updates ExportStatus state
        - Updates health metrics
        - Logs export result
    """
```

**Implementation**:
```python
async def _export_once(self) -> bool:
    start_time = time.time()
    self._update_state(State.EXPORTING)
    
    try:
        # Convert metrics (fast, <10ms typically)
        batch = self.bridge.convert_metrics()
        
        # Send OTLP (blocking SDK call, run in executor)
        result = await asyncio.to_thread(
            self.sdk_exporter.export,
            batch.metrics
        )
        
        duration = time.time() - start_time
        
        if result.is_success:
            # Update metrics
            self.metrics.otlp_export_duration.labels(
                status='success',
                protocol=self.config.protocol
            ).observe(duration)
            
            self.metrics.otlp_exported_metrics.labels(
                protocol=self.config.protocol
            ).inc(len(batch.metrics))
            
            logger.info(f"OTLP export succeeded ({len(batch.metrics)} metrics, {duration:.2f}s)")
            return True
        else:
            logger.warning(f"OTLP export failed: {result.error}")
            return False
    
    except Exception as e:
        duration = time.time() - start_time
        self.metrics.otlp_export_duration.labels(
            status='failure',
            protocol=self.config.protocol
        ).observe(duration)
        
        logger.error(f"OTLP export exception: {e}", exc_info=True)
        return False
```

### `_convert_metrics()`

```python
def _convert_metrics(self) -> MetricBatch:
    """
    Convert Prometheus registry to OTLP MetricBatch.
    
    Delegates to PrometheusToOTLPBridge.
    
    Returns:
        MetricBatch ready for SDK export
    
    Raises:
        ConversionError: If metric conversion fails (logged, not propagated)
    """
```

**Performance**: Typically <10ms for 1000 metrics (measured in research)

### `_send_otlp()`

```python
async def _send_otlp(self, batch: MetricBatch) -> MetricExportResult:
    """
    Send OTLP payload via SDK exporter.
    
    Wraps synchronous SDK export call in asyncio.to_thread() to avoid blocking.
    
    Args:
        batch: MetricBatch to export
    
    Returns:
        MetricExportResult (success=True/False, error=Optional[str])
    
    Timeout: config.timeout_seconds (enforced by SDK exporter)
    """
```

**Timeout handling**:
- SDK exporter configured with `timeout=config.timeout_seconds`
- If timeout exceeded → SDK returns failure result (not exception)
- Treated as export failure, triggers retry logic

### `_handle_success()`

```python
def _handle_success(self) -> None:
    """
    Handle successful export.
    
    Actions:
    - Reset consecutive_failures = 0
    - Update last_success_timestamp
    - Transition state to IDLE
    - Update Prometheus health metrics
    """
```

### `_handle_failure()`

```python
def _handle_failure(self) -> None:
    """
    Handle failed export.
    
    Actions:
    - Increment consecutive_failures
    - Calculate backoff delay
    - Transition state to RETRYING (if failures < 10) or FAILED (if >= 10)
    - Update Prometheus health metrics
    - Log error with context
    """
```

**Retry logic** (FR-013):
- Failures 1–9: Transition to RETRYING, schedule retry after backoff delay
- Failure 10: Transition to FAILED, log critical error, wait for next scheduled cycle

### `_calculate_backoff()`

```python
def _calculate_backoff(self, consecutive_failures: int) -> float:
    """
    Calculate exponential backoff delay.
    
    Formula: min(base_delay * (multiplier ^ (failures - 1)), max_delay)
    
    Args:
        consecutive_failures: Current failure count (1-10)
    
    Returns:
        Delay in seconds (1.0 - 300.0)
    
    Examples:
        failures=1 → 1s
        failures=2 → 2s
        failures=3 → 4s
        failures=5 → 16s
        failures=9 → 256s
        failures=10 → 300s (capped)
    """
```

**Implementation**:
```python
def _calculate_backoff(self, failures: int) -> float:
    base_delay = 1.0
    multiplier = 2.0
    max_delay = 300.0
    
    delay = base_delay * (multiplier ** (failures - 1))
    return min(delay, max_delay)
```

### `_update_state()`

```python
def _update_state(self, new_state: State) -> None:
    """
    Update export status state and corresponding Prometheus metrics.
    
    Args:
        new_state: Target state (IDLE, EXPORTING, RETRYING, FAILED)
    
    Side effects:
        - Updates self.status.state
        - Updates loxone_otlp_export_status metric
        - Logs state transition
    """
```

---

## Helper Class: `PrometheusToOTLPBridge`

Converts Prometheus metrics to OTLP format. Internal to `otlp_exporter.py` module.

### Constructor

```python
def __init__(self, registry: prometheus_client.CollectorRegistry):
    """
    Initialize bridge.
    
    Args:
        registry: Prometheus metrics registry to read from
    """
```

### Method: `convert_metrics()`

```python
def convert_metrics(self) -> MetricBatch:
    """
    Convert all metrics in Prometheus registry to OTLP format.
    
    Returns:
        MetricBatch with resource attributes, scope info, and converted metrics
    
    Conversion rules:
    - Prometheus Gauge → OTLP Gauge
    - Prometheus Counter → OTLP Sum (CUMULATIVE)
    - Prometheus Histogram → OTLP Histogram (CUMULATIVE)
    - Labels → Attributes (1:1 mapping)
    - HELP text → Description
    - Timestamps: seconds → nanoseconds
    """
```

**Implementation sketch**:
```python
def convert_metrics(self) -> MetricBatch:
    resource_attrs = {
        "service.name": "loxone-prometheus-exporter",
        "service.version": get_version(),
    }
    
    otlp_metrics = []
    
    for family in self.registry.collect():
        if family.type == 'gauge':
            otlp_metrics.append(self._convert_gauge(family))
        elif family.type == 'counter':
            otlp_metrics.append(self._convert_counter(family))
        elif family.type == 'histogram':
            otlp_metrics.append(self._convert_histogram(family))
    
    return MetricBatch(
        resource_attributes=resource_attrs,
        scope_name="loxone_exporter",
        scope_version=get_version(),
        metrics=otlp_metrics
    )
```

---

## Factory Function: `create_otlp_exporter()`

Creates protocol-specific OTLP SDK exporter.

```python
def create_otlp_exporter(config: OTLPConfiguration) -> MetricExporter:
    """
    Factory function to create OTLP exporter based on protocol config.
    
    Args:
        config: OTLPConfiguration with protocol, endpoint, auth, TLS settings
    
    Returns:
        MetricExporter instance (gRPC or HTTP)
    
    Raises:
        ValueError: If protocol is invalid (should be caught by config validation)
    """
```

**Implementation**:
```python
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
    OTLPMetricExporter as GRPCExporter
)
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter as HTTPExporter
)

def create_otlp_exporter(config: OTLPConfiguration) -> MetricExporter:
    common_args = {
        'endpoint': config.endpoint,
        'timeout': config.timeout_seconds,
    }
    
    # Add auth headers if configured
    if config.auth_config.headers:
        common_args['headers'] = config.auth_config.headers
    
    # Add TLS credentials if enabled
    if config.tls_config.enabled:
        if config.protocol == 'grpc':
            import grpc
            with open(config.tls_config.cert_path, 'rb') as f:
                cert = f.read()
            credentials = grpc.ssl_channel_credentials(root_certificates=cert)
            common_args['credentials'] = credentials
        else:  # http
            common_args['certificate_file'] = config.tls_config.cert_path
    
    # Create protocol-specific exporter
    if config.protocol == 'grpc':
        return GRPCExporter(**common_args)
    elif config.protocol == 'http':
        return HTTPExporter(**common_args)
    else:
        raise ValueError(f"Invalid protocol: {config.protocol}")
```

---

## Dependencies

### Input Dependencies

- **OTLPConfiguration** (from `config.py`): Validated configuration
- **prometheus_client.CollectorRegistry**: Source of metrics to export
- **Metrics** (from `metrics.py`): For updating health metrics
- **logging.Logger**: For structured logging

### Output Dependencies

- **None** (side effect: OTLP export to external collector)

### External Libraries

- `opentelemetry.sdk.metrics`: Core OpenTelemetry SDK
- `opentelemetry.exporter.otlp.proto.grpc.metric_exporter`: gRPC exporter
- `opentelemetry.exporter.otlp.proto.http.metric_exporter`: HTTP exporter
- `asyncio`: For background task management
- `time`: For timestamps and duration measurement

---

## Error Handling

### Startup Errors

| Error | Cause | Behavior |
|-------|-------|----------|
| `ConfigurationError` | Invalid OTLP config | Raise exception, fail startup (FR-014) |
| `ImportError` | OpenTelemetry SDK not installed | Raise exception, fail startup |

### Runtime Errors

| Error | Cause | Behavior |
|-------|-------|----------|
| Connection failure | Collector unreachable | Log warning, increment failure count, retry with backoff |
| Timeout | Collector slow to respond | Treat as connection failure, retry |
| Authentication failure | Invalid credentials | Log error, treat as connection failure, retry |
| Serialization error | Metric conversion failed | Log error, skip this metric, continue export |
| Max retries exceeded | 10 consecutive failures | Log critical, enter FAILED state, wait for next cycle |

**Error isolation**: Export failures never crash the exporter. Prometheus endpoint remains operational (FR-006).

### Logging Levels

| Level | Event | Example |
|-------|-------|---------|
| INFO | Normal operation | "OTLP export succeeded (523 metrics, 0.45s)" |
| WARNING | Transient failures | "OTLP export failed (connection refused), retrying in 4s (attempt 3/10)" |
| ERROR | Unexpected errors | "OTLP metric conversion failed for family 'loxone_exporter_up': TypeError" |
| CRITICAL | Persistent failures | "OTLP export failed 10 consecutive times, entering failed state" |

---

## Thread Safety

- **Asyncio task**: Runs in main event loop, no threading
- **Prometheus registry**: Read-only access, safe for concurrent reads
- **ExportStatus**: Accessed only within export task (single thread), no locking needed
- **Metrics updates**: `prometheus_client` metrics are thread-safe by design

**Concurrency notes**:
- HTTP scrape and OTLP export can occur simultaneously (no contention)
- Multiple export attempts cannot overlap (enforced by `_should_export()` check)

---

## Testing Interface

### Unit Test Entry Points

```python
# Test retry logic
exporter._calculate_backoff(5)  # → 16.0

# Test state transitions
exporter._handle_success()  # → state=IDLE, failures=0
exporter._handle_failure()  # → state=RETRYING, failures++

# Test conversion
bridge = PrometheusToOTLPBridge(registry)
batch = bridge.convert_metrics()
assert batch.metrics[0].name == "loxone_control_value"
```

### Integration Test Entry Points

```python
# Mock OTLP collector
mock_exporter = MockOTLPExporter()
exporter.sdk_exporter = mock_exporter

# Trigger export
await exporter._export_once()

# Verify mock received metrics
assert mock_exporter.received_metrics_count == 523
```

### Contract Test Entry Points

```python
# Verify OTLP format compliance
batch = bridge.convert_metrics()

# Check resource attributes
assert batch.resource_attributes["service.name"] == "loxone-prometheus-exporter"

# Check metric structure
metric = batch.metrics[0]
assert metric.name is not None
assert metric.description is not None
assert metric.type in (MetricType.GAUGE, MetricType.SUM, MetricType.HISTOGRAM)
assert len(metric.data_points) > 0
```

---

## Performance Characteristics

| Operation | Typical Duration | Notes |
|-----------|------------------|-------|
| Metric conversion | <10ms (1000 metrics) | Stateless transformation |
| OTLP serialization | <5ms (1000 metrics) | SDK protobuf encoding |
| Network transmission | 10-100ms | Depends on collector latency |
| **Total export duration** | **50-200ms** | P95, local collector |

**Memory footprint**:
- MetricBatch: ~50KB (transient, freed after export)
- SDK exporter: ~2MB (gRPC channel, buffers)
- **Total overhead**: ~5-10MB (measured in research)

**CPU usage**:
- Export cycle: <1% CPU (single core) for 30s interval with 1000 metrics
- Negligible impact on HTTP scrape latency

---

## Summary

`otlp_exporter.py` provides a clean, self-contained interface for OTLP metrics export:

- **Public API**: 3 methods (start, stop, get_status)
- **Asyncio-native**: Background task, no threading complexity
- **Error-resilient**: Comprehensive retry logic, isolated failures
- **Observable**: Rich health metrics and structured logging
- **Testable**: Clear internal interfaces, mockable dependencies

**Integration points**:
- `config.py`: Reads OTLPConfiguration
- `metrics.py`: Updates health metrics
- `server.py`: Calls start/stop lifecycle methods

See `config-schema.md` for configuration details and `health-metrics.md` for observability metrics.
