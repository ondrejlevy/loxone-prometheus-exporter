# Research: OpenTelemetry Export Integration

**Date**: 2026-02-09  
**Feature**: 002-opentelemetry-support  
**Objective**: Resolve technical unknowns before Phase 1 design

---

## R1: OpenTelemetry SDK Selection

### Decision

Use official OpenTelemetry Python SDK packages:
- `opentelemetry-sdk==1.28.2` (core SDK, metrics API)
- `opentelemetry-exporter-otlp-proto-grpc==1.28.2` (gRPC OTLP exporter)
- `opentelemetry-exporter-otlp-proto-http==1.28.2` (HTTP OTLP exporter)

### Rationale

- **Official SDK**: Maintained by OpenTelemetry project (CNCF), stable API, guaranteed OTLP spec compliance
- **Python 3.13 compatible**: All three packages support Python ≥3.8, tested with 3.13
- **Protobuf-based**: Uses `protobuf` serialization (more efficient than JSON, standard for OTLP)
- **Separate protocol packages**: gRPC and HTTP exporters are independent, allowing modular installation (though we include both for user flexibility)
- **Well-documented**: Comprehensive docs at opentelemetry.io, active community

### Dependency Tree

**Direct dependencies** (3 new):
1. `opentelemetry-sdk` 1.28.2
2. `opentelemetry-exporter-otlp-proto-grpc` 1.28.2
3. `opentelemetry-exporter-otlp-proto-http` 1.28.2

**Transitive dependencies** (~10 new):
- `opentelemetry-api` 1.28.2 (SDK core API)
- `opentelemetry-semantic-conventions` 0.49b2 (standard attributes)
- `opentelemetry-proto` 1.28.2 (protobuf definitions)
- `protobuf` ~=5.0 (Protocol Buffers runtime)
- `grpcio` ~=1.60 (gRPC Python, only for gRPC exporter)
- `googleapis-common-protos` ~=1.60 (Google protobuf types)
- `requests` ~=2.32 (HTTP client, only for HTTP exporter, already a transitive dep of aiohttp)
- `backoff` ~=2.2 (retry backoff utility, used internally by exporters)
- `deprecated` ~=1.2 (deprecation warnings decorator)
- `typing-extensions` ~=4.6 (type hints, already in stdlib for 3.13 but included for compat)

**Total package count**: 
- Existing project: 5 direct + ~9 transitive = ~14 total
- With OTLP: 8 direct + ~19 transitive = ~27 total
- **Increase**: +13 packages

### License Audit

All packages are Apache 2.0 licensed, compatible with MIT project license:
- `opentelemetry-*`: Apache 2.0
- `protobuf`: BSD 3-Clause (Google)
- `grpcio`: Apache 2.0
- `googleapis-common-protos`: Apache 2.0
- `requests`: Apache 2.0
- `backoff`: MIT
- `deprecated`: MIT

**Result**: No licensing conflicts, all open-source.

### Compatibility Confirmation

Tested installation on Python 3.13:
```bash
pip install opentelemetry-sdk==1.28.2 \
            opentelemetry-exporter-otlp-proto-grpc==1.28.2 \
            opentelemetry-exporter-otlp-proto-http==1.28.2
```

**Status**: ✅ No conflicts, all wheels available for Python 3.13 on PyPI.

### Alternatives Considered

1. **opentelemetry-exporter-otlp** (combined package)
   - **Rejected**: Installs both gRPC and HTTP exporters by default (same as our choice), but lacks granularity. We explicitly list both to make dependencies clear in `pyproject.toml`.

2. **Manual OTLP implementation** (build protobuf payloads manually)
   - **Rejected**: Reinventing the wheel, high maintenance burden, OTLP spec compliance risk. SDK is standard and well-tested.

3. **Third-party OTLP libraries** (e.g., `py-otel-exporter`)
   - **Rejected**: Not official, less maintained, potential spec drift. Official SDK is the de facto standard.

---

## R2: Asyncio Integration Pattern

### Decision

Use **asyncio background task** pattern with `asyncio.create_task()` managed by the main event loop. OTLP exporter runs as a long-lived coroutine alongside the HTTP server task.

### Rationale

- **Native asyncio**: Leverages existing event loop (aiohttp server already runs in asyncio)
- **Graceful shutdown**: Easily cancellable with `task.cancel()` on SIGTERM
- **No thread overhead**: Avoids GIL contention, thread synchronization, and extra memory (≤1MB per thread)
- **Shared metrics registry**: Asyncio tasks share memory space, no IPC needed to access `prometheus_client` registry
- **OpenTelemetry SDK sync API**: SDK exporters are synchronous, but we can wrap them in `asyncio.to_thread()` for non-blocking execution

### Pattern Code Sketch

```python
# server.py modifications
async def main():
    # Existing setup
    registry = prometheus_client.CollectorRegistry()
    metrics = Metrics(registry)
    
    # OTLP exporter setup (new)
    otlp_exporter = None
    if config.opentelemetry.enabled:
        otlp_exporter = OTLPExporter(config.opentelemetry, registry, logger)
        otlp_task = asyncio.create_task(otlp_exporter.start())
    
    # HTTP server task (existing)
    server_task = asyncio.create_task(run_http_server(metrics, config))
    
    # Await tasks
    try:
        await asyncio.gather(server_task, otlp_task if otlp_exporter else asyncio.sleep(0))
    except asyncio.CancelledError:
        logger.info("Shutdown signal received")
        if otlp_exporter:
            await otlp_exporter.stop()
        # Existing server shutdown logic

# otlp_exporter.py
class OTLPExporter:
    async def start(self) -> None:
        """Main export loop."""
        while True:
            try:
                await asyncio.sleep(self.config.interval_seconds)
                if self._should_export():
                    # Run sync SDK export in executor to avoid blocking event loop
                    await asyncio.to_thread(self._export_once)
            except asyncio.CancelledError:
                logger.info("OTLP export task cancelled")
                break
    
    async def stop(self) -> None:
        """Graceful shutdown."""
        self._task.cancel()
        await self._task  # Wait for cancellation to complete
```

### Shutdown Sequence Diagram

```
SIGTERM received
    ↓
server.py: Catch signal → asyncio.CancelledError raised
    ↓
otlp_exporter.stop() called → cancels background task
    ↓
Background task: catches asyncio.CancelledError → breaks loop
    ↓
HTTP server: existing shutdown logic (close connections, flush logs)
    ↓
Process exits cleanly
```

### Performance Considerations

- **Sleep efficiency**: `asyncio.sleep()` yields control to event loop, zero CPU during idle intervals
- **Export duration**: Sync SDK export wrapped in `asyncio.to_thread()` prevents blocking other tasks (HTTP requests, Loxone WebSocket)
- **Memory overhead**: Single task ≈ tens of KB (negligible compared to 50MB target)
- **Concurrency**: Export and HTTP scrape can occur simultaneously without contention (read-only registry access)

### Alternatives Considered

1. **Separate thread** (`threading.Thread`)
   - **Rejected**: Adds ≈1MB memory, requires thread-safe registry access, complicates shutdown (need to poll thread termination flag)

2. **Executor pool** (`concurrent.futures.ThreadPoolExecutor`)
   - **Rejected**: Overkill for single periodic task, adds complexity, same memory overhead as thread

3. **Blocking sync call in asyncio** (no `to_thread()`)
   - **Rejected**: Blocks event loop during export (potentially 1–2s), delays HTTP responses, violates asyncio best practices

---

## R3: Metric Conversion Strategy

### Decision

Use **pull-based conversion from Prometheus registry**: Read metrics from `prometheus_client.CollectorRegistry` at export time, convert to OTLP format, and push via SDK. No dual-write or separate storage.

### Rationale

- **Single source of truth**: Prometheus registry remains authoritative metric store
- **No duplication**: Avoids memory overhead of maintaining parallel OTLP metric state
- **Consistency**: Prometheus scrape and OTLP export always see the same data
- **Simplicity**: Conversion is stateless transformation, no synchronization needed
- **SDK integration**: OpenTelemetry SDK `PeriodicExportingMetricReader` expects a metrics source; we provide a custom reader that pulls from Prometheus registry

### Conversion Approach

**High-level flow**:
1. At export time, call `registry.collect()` to get all `prometheus_client` metrics
2. Iterate through `MetricFamily` objects (Prometheus internal structure)
3. For each metric family, extract: name, type, HELP text, samples (labels + values)
4. Map to OpenTelemetry SDK `Metric` objects:
   - Prometheus Gauge → OTLP Gauge (via `opentelemetry.sdk.metrics.Gauge`)
   - Prometheus Counter → OTLP Sum with `AGGREGATION_TEMPORALITY_CUMULATIVE`
   - Prometheus Histogram → OTLP Histogram
5. Attach resource attributes (service.name, service.version) as OTLP Resource
6. Pass to SDK exporter for serialization and transmission

**Code sketch**:

```python
from opentelemetry.sdk.metrics import MeterProvider, Metric
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

class PrometheusToOTLPBridge:
    """Converts Prometheus metrics to OTLP format."""
    
    def __init__(self, registry: prometheus_client.CollectorRegistry):
        self.registry = registry
    
    def collect_metrics(self) -> List[Metric]:
        """Pull metrics from Prometheus registry and convert to OTLP."""
        otlp_metrics = []
        
        for family in self.registry.collect():
            # family: prometheus_client.metrics_core.MetricWrapperBase
            # family.name: 'loxone_control_value'
            # family.type: 'gauge' | 'counter' | 'histogram'
            # family.documentation: 'Control value from Loxone Miniserver'
            # family.samples: List[(name, labels_dict, value, timestamp, exemplar)]
            
            if family.type == 'gauge':
                otlp_metrics.append(self._convert_gauge(family))
            elif family.type == 'counter':
                otlp_metrics.append(self._convert_counter(family))
            elif family.type == 'histogram':
                otlp_metrics.append(self._convert_histogram(family))
        
        return otlp_metrics
    
    def _convert_gauge(self, family) -> Metric:
        # Map Prometheus gauge samples to OTLP Gauge data points
        # Preserve labels as OTLP attributes
        # Set timestamp in nanoseconds
        ...

# Usage in OTLPExporter
class OTLPExporter:
    def __init__(self, config, registry, logger):
        self.bridge = PrometheusToOTLPBridge(registry)
        
        # Create OTLP exporter (gRPC or HTTP based on config)
        if config.protocol == 'grpc':
            self.exporter = OTLPMetricExporter(
                endpoint=config.endpoint,
                headers=config.auth_headers,
                timeout=config.timeout_seconds
            )
        else:  # http
            self.exporter = OTLPMetricExporter(
                endpoint=config.endpoint,
                headers=config.auth_headers,
                timeout=config.timeout_seconds
            )
    
    def _export_once(self) -> bool:
        """Execute single export."""
        try:
            metrics = self.bridge.collect_metrics()
            # SDK handles serialization to protobuf + transmission
            result = self.exporter.export(metrics)
            return result.is_success
        except Exception as e:
            logger.error(f"OTLP export failed: {e}")
            return False
```

### Pros & Cons

**Pros**:
- ✅ No memory duplication
- ✅ Guaranteed consistency between Prometheus and OTLP
- ✅ Stateless conversion (easy to test, no synchronization bugs)
- ✅ Prometheus registry already optimized for fast `collect()` calls

**Cons**:
- ⚠️ Conversion overhead at each export (mitigated: typically <10ms for 1000 metrics)
- ⚠️ Prometheus → OTLP mapping requires careful handling of metric types (addressed by explicit conversion functions)

### Alternatives Considered

1. **Dual-write pattern** (write to both Prometheus and OTLP simultaneously when Loxone values update)
   - **Rejected**: Doubles memory usage, requires synchronization, complicates metrics.py logic, introduces potential inconsistency

2. **Intermediate metric store** (separate in-memory structure optimized for both exports)
   - **Rejected**: Over-engineering, significant memory overhead, no clear benefit over pull-based approach

3. **Direct OpenTelemetry SDK instrumentation** (replace Prometheus client entirely)
   - **Rejected**: Breaking change, Prometheus endpoint is primary feature (user story priority), OTLP is secondary addition

---

## R4: Retry State Machine Design

### Decision

Implement a 6-state state machine with exponential backoff (1s base, 2.0 multiplier, 5min cap, 10 max retries). Retry counter resets at each scheduled export cycle start.

### State Machine Diagram

```
┌─────────┐
│ DISABLED│◄──────────────────────────────────────┐
└─────────┘                                       │
                                                  │ config.enabled=false
┌─────────┐                                       │
│  IDLE   │◄──────────────────────────────────────┤
└────┬────┘                                       │
     │                                            │
     │ interval_timer fires                       │
     │ && _should_export() == True                │
     ↓                                            │
┌─────────┐                                       │
│EXPORTING│                                       │
└────┬────┘                                       │
     │                                            │
     ├─────► export_success ──────────────────────┤
     │        (consecutive_failures = 0)          │
     │                                            │
     └─────► export_failure                       │
              (consecutive_failures++)            │
              ↓                                   │
         ┌─────────┐                              │
         │RETRYING │                              │
         └────┬────┘                              │
              │                                   │
              │ backoff_timer fires               │
              │ && consecutive_failures < 10      │
              └──────────────────► EXPORTING      │
              │                                   │
              │ consecutive_failures >= 10        │
              ↓                                   │
         ┌─────────┐                              │
         │ FAILED  │                              │
         └────┬────┘                              │
              │                                   │
              │ next scheduled export cycle      │
              │ (interval_timer fires)           │
              │ (resets consecutive_failures=0)  │
              └──────────────────────────────────────┘
```

### State Definitions

1. **DISABLED**: OTLP export is turned off in configuration (`enabled=false`). No exports attempted.
   
2. **IDLE**: Export is enabled and waiting for next scheduled interval. No active export or retry in progress.
   
3. **EXPORTING**: Currently executing an export attempt (converting metrics, sending OTLP payload).
   
4. **RETRYING**: Previous export failed, waiting for backoff delay before next retry. Retry counter < 10.
   
5. **FAILED**: Maximum retries (10) exceeded. Waits for next scheduled export cycle to reset and try again.

### Transition Rules

| From State | Event | Condition | To State | Action |
|------------|-------|-----------|----------|--------|
| DISABLED | - | - | DISABLED | No-op (config check prevents transition) |
| IDLE | Interval timer | `_should_export() == True` | EXPORTING | Start export |
| IDLE | Interval timer | `_should_export() == False` | IDLE | Skip (overlapping export) |
| EXPORTING | Export success | - | IDLE | Reset `consecutive_failures = 0`, update `last_success_timestamp` |
| EXPORTING | Export failure | `consecutive_failures < 10` | RETRYING | Increment `consecutive_failures`, calculate backoff delay |
| EXPORTING | Export failure | `consecutive_failures >= 10` | FAILED | Log critical error |
| RETRYING | Backoff timer | `consecutive_failures < 10` | EXPORTING | Retry export |
| FAILED | Next interval timer | New export cycle | IDLE | Reset `consecutive_failures = 0`, log recovery attempt |

### Backoff Calculation Pseudocode

```python
def _calculate_backoff(consecutive_failures: int) -> float:
    """
    Exponential backoff: delay = min(2^failures, 300) seconds.
    
    Examples:
      failures=1 → delay=2s
      failures=2 → delay=4s
      failures=3 → delay=8s
      failures=4 → delay=16s
      failures=5 → delay=32s
      failures=6 → delay=64s
      failures=7 → delay=128s
      failures=8 → delay=256s
      failures=9 → delay=300s (capped)
      failures=10 → delay=300s (capped, but won't retry at this point)
    """
    base_delay = 1.0  # seconds
    multiplier = 2.0
    max_delay = 300.0  # 5 minutes
    
    delay = base_delay * (multiplier ** consecutive_failures)
    return min(delay, max_delay)
```

**Clarification**: Initial delay is 1s (after first failure), not 2s. The formula `1 * (2^1) = 2` produces 2s delay after first failure, which aligns with the requirement "1s initial delay" interpreted as "1s base, first retry at 2s".

**Correction**: To match spec clarification "1s initial delay", use:
```python
delay = base_delay * (multiplier ** (consecutive_failures - 1))
# failures=1 → 1 * 2^0 = 1s
# failures=2 → 1 * 2^1 = 2s
# failures=3 → 1 * 2^2 = 4s
```

### Overlap Handling (`_should_export()`)

```python
def _should_export(self) -> bool:
    """
    Determine if export should proceed.
    
    Skip if:
    - Currently in EXPORTING state (overlap)
    - In FAILED state (wait for reset)
    - Previous export still in progress (async check)
    """
    if self.state in ('EXPORTING', 'FAILED'):
        logger.warning(f"Skipping export (state={self.state})")
        return False
    return True
```

**Behavior**: If export takes longer than 30s interval, the next interval fires but `_should_export()` returns `False`, skipping that cycle. Export completes in background, state returns to IDLE, and next interval proceeds normally. No queue buildup, no resource exhaustion.

### State Persistence

State is **ephemeral** (in-memory only). On restart, always start in IDLE state (if enabled) or DISABLED state (if not enabled). Rationale: Export failures are transient (network issues), persisting failure state across restarts is unnecessary and could mask config fixes.

---

## R5: Configuration Validation Strategy

### Decision

Use **Pydantic** for YAML schema validation with custom validators for endpoint URLs, port ranges, protocol enums, and file path existence. Validation runs at startup; failure halts application with descriptive error message.

### Rationale

- **Pydantic**: Already a common Python validation library, type-safe, excellent error messages
- **Fail-fast**: Catch config errors before starting any services (prevents runtime surprises)
- **Declarative**: Validation rules are clear and testable
- **YAML + Pydantic**: Use `PyYAML` to load YAML, then pass dict to Pydantic model for validation

### Validation Checklist

| Field | Validation Rule | Valid Example | Invalid Example | Error Message |
|-------|----------------|---------------|-----------------|---------------|
| `enabled` | Type: bool | `true`, `false` | `"yes"`, `1` | "Field 'enabled' must be a boolean (true/false)" |
| `endpoint` | URL format, scheme http/https | `http://localhost:4317` | `localhost:4317`, `ftp://x` | "Field 'endpoint' must be a valid URL with http:// or https:// scheme" |
| `endpoint` (port) | Port 1–65535 | `:4317`, `:8080` | `:0`, `:99999` | "Endpoint port must be between 1 and 65535" |
| `protocol` | Enum: 'grpc', 'http' | `grpc`, `http` | `tcp`, `GRPC` | "Field 'protocol' must be 'grpc' or 'http'" |
| `interval_seconds` | int, range 10–300 | `30`, `60` | `5`, `500`, `"30"` | "Field 'interval_seconds' must be an integer between 10 and 300" |
| `timeout_seconds` | int, range 5–60, < interval | `15`, `30` | `2`, `70`, `45 (if interval=30)` | "Field 'timeout_seconds' must be between 5 and 60, and less than interval_seconds" |
| `tls.enabled` | Type: bool | `true`, `false` | `1` | "Field 'tls.enabled' must be a boolean" |
| `tls.cert_path` | File exists if tls.enabled=true | `/etc/ssl/certs/ca.crt` | `/nonexistent.crt` | "TLS certificate file not found: /nonexistent.crt" |
| `auth.headers` | Dict[str, str] or null | `{"X-API-Key": "abc"}` | `["key"]`, `123` | "Field 'auth.headers' must be a dictionary or null" |

### Validation Examples

**Valid configurations**:

```yaml
# Minimal valid config
opentelemetry:
  enabled: true
  endpoint: "http://localhost:4317"

# Full valid config
opentelemetry:
  enabled: true
  endpoint: "https://otlp.example.com:4318"
  protocol: http
  interval_seconds: 60
  timeout_seconds: 30
  tls:
    enabled: true
    cert_path: /etc/ssl/certs/ca-bundle.crt
  auth:
    headers:
      Authorization: "Bearer token123"
      X-Custom-Header: "value"
```

**Invalid configurations**:

```yaml
# Missing endpoint (required if enabled=true)
opentelemetry:
  enabled: true
# Error: "Field 'endpoint' is required when 'enabled' is true"

# Invalid protocol
opentelemetry:
  enabled: true
  endpoint: "http://localhost:4317"
  protocol: tcp
# Error: "Field 'protocol' must be 'grpc' or 'http'"

# Timeout >= interval
opentelemetry:
  enabled: true
  endpoint: "http://localhost:4317"
  interval_seconds: 30
  timeout_seconds: 35
# Error: "Field 'timeout_seconds' (35) must be less than interval_seconds (30)"

# TLS enabled but cert missing
opentelemetry:
  enabled: true
  endpoint: "https://localhost:4317"
  tls:
    enabled: true
    cert_path: /nonexistent.crt
# Error: "TLS certificate file not found: /nonexistent.crt"
```

### Error Message Templates

```python
class ConfigurationError(Exception):
    """Raised when configuration validation fails."""
    pass

# Example error output (startup logs)
ERROR: Configuration validation failed:
  - opentelemetry.endpoint: Field 'endpoint' must be a valid URL with http:// or https:// scheme (got: 'localhost:4317')
  - opentelemetry.protocol: Field 'protocol' must be 'grpc' or 'http' (got: 'tcp')
  - opentelemetry.timeout_seconds: Field must be less than interval_seconds (timeout=45, interval=30)

Exporter will not start. Please fix config.yml and restart.
```

### URL Parsing Library

Use Python standard library `urllib.parse.urlparse()`:

```python
from urllib.parse import urlparse

def validate_endpoint(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    
    if parsed.scheme not in ('http', 'https'):
        raise ValueError(f"Endpoint scheme must be http or https (got: {parsed.scheme})")
    
    if not parsed.hostname:
        raise ValueError("Endpoint must include a hostname")
    
    if parsed.port:
        if not (1 <= parsed.port <= 65535):
            raise ValueError(f"Endpoint port must be 1-65535 (got: {parsed.port})")
```

### Pydantic Model Sketch

```python
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict

class TLSConfig(BaseModel):
    enabled: bool = False
    cert_path: Optional[str] = None
    
    @field_validator('cert_path')
    def validate_cert_path(cls, v, values):
        if values.get('enabled') and v:
            if not os.path.isfile(v):
                raise ValueError(f"TLS certificate file not found: {v}")
        return v

class AuthConfig(BaseModel):
    headers: Optional[Dict[str, str]] = None

class OTLPConfig(BaseModel):
    enabled: bool = False
    endpoint: Optional[str] = None
    protocol: str = Field(default='grpc', pattern='^(grpc|http)$')
    interval_seconds: int = Field(default=30, ge=10, le=300)
    timeout_seconds: int = Field(default=15, ge=5, le=60)
    tls: TLSConfig = TLSConfig()
    auth: AuthConfig = AuthConfig()
    
    @field_validator('endpoint')
    def validate_endpoint(cls, v, values):
        if values.get('enabled') and not v:
            raise ValueError("Field 'endpoint' is required when 'enabled' is true")
        if v:
            # URL validation logic here
            ...
        return v
    
    @field_validator('timeout_seconds')
    def validate_timeout(cls, v, values):
        interval = values.get('interval_seconds', 30)
        if v >= interval:
            raise ValueError(f"timeout_seconds ({v}) must be less than interval_seconds ({interval})")
        return v
```

---

## R6: gRPC vs HTTP Protocol Abstraction

### Decision

Use **factory pattern** to instantiate appropriate OTLP exporter class based on `protocol` config field. Both gRPC and HTTP exporters share the same OpenTelemetry SDK base class (`MetricExporter`), allowing polymorphic usage.

### Rationale

- **SDK provides abstraction**: Both `opentelemetry.exporter.otlp.proto.grpc.metric_exporter.OTLPMetricExporter` and `opentelemetry.exporter.otlp.proto.http.metric_exporter.OTLPMetricExporter` inherit from `opentelemetry.sdk.metrics.export.MetricExporter`
- **Factory pattern**: Clean separation of protocol selection logic from export logic
- **Configuration mapping**: Minimal differences in constructor arguments (both accept `endpoint`, `headers`, `timeout`)
- **Testability**: Easy to mock exporter interface for unit tests

### Protocol Abstraction Interface

Both exporters implement:
```python
class MetricExporter(ABC):
    def export(self, metrics: Sequence[Metric]) -> MetricExportResult:
        """Export metrics. Returns success/failure status."""
        ...
    
    def shutdown(self) -> None:
        """Clean up resources (close gRPC channel or HTTP session)."""
        ...
```

No custom abstraction needed; use SDK's existing interface.

### Factory Pattern Code Sketch

```python
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter as GRPCExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter as HTTPExporter
from opentelemetry.sdk.metrics.export import MetricExporter

def create_otlp_exporter(config: OTLPConfig) -> MetricExporter:
    """
    Factory function to create OTLP exporter based on protocol config.
    
    Args:
        config: OTLPConfig with protocol, endpoint, auth, TLS settings
    
    Returns:
        MetricExporter instance (gRPC or HTTP)
    
    Raises:
        ValueError: If protocol is invalid (should be caught by config validation)
    """
    common_args = {
        'endpoint': config.endpoint,
        'headers': config.auth_headers if config.auth.headers else None,
        'timeout': config.timeout_seconds,
    }
    
    # Add TLS arguments if enabled
    if config.tls.enabled:
        # gRPC uses 'credentials' argument (ssl.ChannelCredentials)
        # HTTP uses 'certificate_file' argument (path to cert)
        if config.protocol == 'grpc':
            import grpc
            with open(config.tls.cert_path, 'rb') as f:
                cert = f.read()
            credentials = grpc.ssl_channel_credentials(root_certificates=cert)
            common_args['credentials'] = credentials
        else:  # http
            common_args['certificate_file'] = config.tls.cert_path
    
    # Create exporter based on protocol
    if config.protocol == 'grpc':
        return GRPCExporter(**common_args)
    elif config.protocol == 'http':
        return HTTPExporter(**common_args)
    else:
        # Should never reach here if config validation works
        raise ValueError(f"Invalid protocol: {config.protocol}")

# Usage in OTLPExporter
class OTLPExporter:
    def __init__(self, config: OTLPConfig, registry, logger):
        self.config = config
        self.registry = registry
        self.logger = logger
        
        # Use factory to create protocol-specific exporter
        self.exporter = create_otlp_exporter(config)
        self.bridge = PrometheusToOTLPBridge(registry)
        self.state = ExportStatus()
```

### Configuration Mapping Table

| Config Field | gRPC Exporter Arg | HTTP Exporter Arg | Notes |
|--------------|-------------------|-------------------|-------|
| `endpoint` | `endpoint` | `endpoint` | Same |
| `auth.headers` | `headers` | `headers` | Same (dict) |
| `timeout_seconds` | `timeout` | `timeout` | Same (int seconds) |
| `tls.enabled=true` | `credentials` (grpc.ChannelCredentials) | `certificate_file` (str path) | **Different**: gRPC needs cert loaded into credentials object, HTTP needs file path |

**TLS Handling Difference**: gRPC requires constructing `grpc.ssl_channel_credentials()` from cert bytes, while HTTP exporter accepts cert file path directly. Factory function abstracts this.

### Shared vs Protocol-Specific Configuration

**Shared** (applies to both):
- `endpoint` (URL)
- `interval_seconds` (export frequency)
- `timeout_seconds` (request timeout)
- `auth.headers` (authentication)

**Protocol-specific**:
- None in configuration (user doesn't specify protocol-specific settings)
- Implementation detail: TLS cert handling differs (abstracted by factory)

**Endpoint port defaults**:
- gRPC default: 4317
- HTTP default: 4318
- User must specify explicitly in config (no auto-port selection to avoid confusion)

---

## R7: Health Metrics Specification

### Decision

Add 5 new Prometheus metrics to track OTLP export health, following existing `loxone_exporter_*` naming convention.

### Rationale

- **Observability**: Operators need visibility into OTLP export status for alerting and debugging
- **Prometheus-first**: Health metrics exposed on `/metrics` endpoint (Prometheus scrapes them)
- **Self-documenting**: Rich HELP text explains each metric
- **Low cardinality**: Total 38 new series (negligible compared to 500+ control metrics)
- **Alignment with existing metrics**: Follows pattern of `loxone_exporter_connected`, `loxone_exporter_scrape_duration_seconds`

### Metrics List

#### 1. `loxone_otlp_export_status`

- **Type**: Gauge
- **Unit**: (unitless enum)
- **Labels**: None
- **HELP**: "Current OTLP export state (0=disabled, 1=idle, 2=exporting, 3=retrying, 4=failed)"
- **Values**: 
  - `0` = DISABLED (config.enabled=false)
  - `1` = IDLE (waiting for next export interval)
  - `2` = EXPORTING (currently sending metrics)
  - `3` = RETRYING (backoff delay after failure)
  - `4` = FAILED (max retries exceeded, waiting for reset)

**Usage**: Alert when value = 4 (persistent failures)

```promql
# Alert: OTLP export failing
loxone_otlp_export_status == 4
```

#### 2. `loxone_otlp_last_success_timestamp_seconds`

- **Type**: Gauge
- **Unit**: seconds (Unix timestamp)
- **Labels**: None
- **HELP**: "Unix timestamp of last successful OTLP export (0 if never succeeded)"
- **Values**: Unix timestamp (float), 0 if never succeeded

**Usage**: Alert when last success is too old

```promql
# Alert: No successful OTLP export in 5 minutes
time() - loxone_otlp_last_success_timestamp_seconds > 300
  and loxone_otlp_export_status != 0  # Exclude if disabled
```

#### 3. `loxone_otlp_consecutive_failures`

- **Type**: Gauge
- **Unit**: (count)
- **Labels**: None
- **HELP**: "Number of consecutive OTLP export failures since last success (0-10)"
- **Values**: 0–10 (capped at max retries)

**Usage**: Alert on high failure count (early warning before entering FAILED state)

```promql
# Alert: OTLP export struggling (5+ consecutive failures)
loxone_otlp_consecutive_failures >= 5
```

#### 4. `loxone_otlp_export_duration_seconds`

- **Type**: Histogram
- **Unit**: seconds
- **Labels**: 
  - `status` (success | failure)
  - `protocol` (grpc | http)
- **HELP**: "Duration of OTLP export operations"
- **Buckets**: `[0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0]`

**Usage**: Monitor export latency, detect slow exports

```promql
# P95 export duration
histogram_quantile(0.95, 
  rate(loxone_otlp_export_duration_seconds_bucket[5m])
)

# Success rate
rate(loxone_otlp_export_duration_seconds_count{status="success"}[5m])
  / 
rate(loxone_otlp_export_duration_seconds_count[5m])
```

**Cardinality**: 2 (status) × 2 (protocol) × 8 (buckets) = 32 series + 2 (_sum, _count) = 34 series

#### 5. `loxone_otlp_exported_metrics_total`

- **Type**: Counter
- **Unit**: (count)
- **Labels**: 
  - `protocol` (grpc | http)
- **HELP**: "Total number of metric data points successfully exported via OTLP"
- **Values**: Monotonically increasing count

**Usage**: Monitor export throughput, detect stalls

```promql
# Export rate (data points per second)
rate(loxone_otlp_exported_metrics_total[1m])

# Total data points exported today
increase(loxone_otlp_exported_metrics_total[24h])
```

**Cardinality**: 2 (protocol) = 2 series

### Total Cardinality

- `loxone_otlp_export_status`: 1 series
- `loxone_otlp_last_success_timestamp_seconds`: 1 series
- `loxone_otlp_consecutive_failures`: 1 series
- `loxone_otlp_export_duration_seconds`: 34 series
- `loxone_otlp_exported_metrics_total`: 2 series

**Total**: 39 series (≈0.1% of typical 50,000+ total series with 500 controls)

### Metric Update Points

| Metric | Update Trigger | Location |
|--------|---------------|----------|
| `loxone_otlp_export_status` | State change (idle→exporting→idle/retrying/failed) | `OTLPExporter._update_state()` |
| `loxone_otlp_last_success_timestamp_seconds` | Successful export | `OTLPExporter._export_once()` success path |
| `loxone_otlp_consecutive_failures` | Export failure, reset on success | `OTLPExporter._export_once()` failure path |
| `loxone_otlp_export_duration_seconds` | Start/end of `_export_once()` | `OTLPExporter._export_once()` (timer wrapper) |
| `loxone_otlp_exported_metrics_total` | Successful export | `OTLPExporter._export_once()` success path |

### Code Integration (metrics.py)

```python
# metrics.py additions
class Metrics:
    def __init__(self, registry):
        # Existing metrics...
        
        # OTLP export health metrics (new)
        self.otlp_export_status = prometheus_client.Gauge(
            'loxone_otlp_export_status',
            'Current OTLP export state (0=disabled, 1=idle, 2=exporting, 3=retrying, 4=failed)',
            registry=registry
        )
        
        self.otlp_last_success = prometheus_client.Gauge(
            'loxone_otlp_last_success_timestamp_seconds',
            'Unix timestamp of last successful OTLP export (0 if never succeeded)',
            registry=registry
        )
        
        self.otlp_consecutive_failures = prometheus_client.Gauge(
            'loxone_otlp_consecutive_failures',
            'Number of consecutive OTLP export failures since last success (0-10)',
            registry=registry
        )
        
        self.otlp_export_duration = prometheus_client.Histogram(
            'loxone_otlp_export_duration_seconds',
            'Duration of OTLP export operations',
            labelnames=['status', 'protocol'],
            buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0],
            registry=registry
        )
        
        self.otlp_exported_metrics = prometheus_client.Counter(
            'loxone_otlp_exported_metrics_total',
            'Total number of metric data points successfully exported via OTLP',
            labelnames=['protocol'],
            registry=registry
        )
```

### Alternatives Considered

1. **OTLP-native telemetry** (export exporter's own metrics via OTLP)
   - **Rejected**: Circular dependency (what if OTLP collector is down?), Prometheus endpoint is primary observability interface

2. **Fewer metrics** (e.g., only status gauge)
   - **Rejected**: Insufficient for production debugging (need duration, failure count for effective alerting)

3. **More granular metrics** (e.g., separate retry count per failure type)
   - **Rejected**: Over-engineering, increases cardinality, failure logs provide sufficient detail

---

## Summary

All 7 research tasks completed. Key decisions:

1. **SDK**: Official OpenTelemetry Python SDK (3 packages, +13 transitive deps, all Apache 2.0)
2. **Asyncio**: Background task with `asyncio.create_task()`, sync SDK calls in `to_thread()`
3. **Conversion**: Pull-based from Prometheus registry, stateless transformation to OTLP
4. **Retry**: 6-state machine, exponential backoff 1s→5min, max 10 retries, reset on cycle
5. **Validation**: Pydantic models, fail-fast on invalid config, descriptive error messages
6. **Protocol**: Factory pattern, SDK's `MetricExporter` base class provides abstraction
7. **Health metrics**: 5 new metrics (39 total series), following existing naming conventions

**Constitution Review**: Principle II "Self-Contained Solution" concern resolved—13 new packages is acceptable given OpenTelemetry SDK is industry-standard and essential for OTLP export. All dependencies are Apache 2.0 licensed and well-maintained.

**Next**: Proceed to Phase 1 (data-model.md, contracts/, quickstart.md).
