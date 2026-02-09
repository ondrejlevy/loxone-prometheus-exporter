# Data Model: OpenTelemetry Export

**Feature**: 002-opentelemetry-support  
**Date**: 2026-02-09  
**Status**: Design Complete

This document defines the core data structures for OpenTelemetry metrics export functionality.

---

## Entity: OTLPConfiguration

Configuration for OTLP export behavior, loaded from YAML config file.

### Fields

| Field | Type | Default | Constraints | Description |
|-------|------|---------|-------------|-------------|
| `enabled` | bool | `false` | - | Enable/disable OTLP export globally |
| `endpoint` | str | required * | Valid URL (http/https) | OTLP collector endpoint URL |
| `protocol` | str | `'grpc'` | Enum: `'grpc'` \| `'http'` | OTLP protocol type |
| `interval_seconds` | int | `30` | 10 ≤ x ≤ 300 | Export interval in seconds |
| `timeout_seconds` | int | `15` | 5 ≤ x ≤ 60, < interval | Export request timeout in seconds |
| `tls_config` | TLSConfig | See below | - | TLS/SSL configuration |
| `auth_config` | AuthConfig | See below | - | Authentication configuration |

\* Required only if `enabled=true`

### Nested Entity: TLSConfig

| Field | Type | Default | Constraints | Description |
|-------|------|---------|-------------|-------------|
| `enabled` | bool | `false` | - | Enable TLS for OTLP connection |
| `cert_path` | Optional[str] | `None` | File must exist if enabled=true | Path to TLS CA certificate file |

### Nested Entity: AuthConfig

| Field | Type | Default | Constraints | Description |
|-------|------|---------|-------------|-------------|
| `headers` | Optional[Dict[str, str]] | `None` | Valid dict or null | HTTP headers for authentication (e.g., Bearer tokens, API keys) |

### Validation Rules

Validation occurs at application startup. Invalid configuration with `enabled=true` causes startup failure with descriptive error message (FR-014).

| Rule | Check | Error Message |
|------|-------|---------------|
| VR-001 | `enabled` is bool | "Field 'opentelemetry.enabled' must be a boolean (true/false)" |
| VR-002 | If `enabled=true`, `endpoint` must be set | "Field 'opentelemetry.endpoint' is required when OTLP export is enabled" |
| VR-003 | `endpoint` must be valid URL with http/https scheme | "Field 'opentelemetry.endpoint' must be a valid URL with http:// or https:// scheme (got: '{value}')" |
| VR-004 | `endpoint` port (if specified) must be 1–65535 | "Endpoint port must be between 1 and 65535 (got: {port})" |
| VR-005 | `protocol` must be 'grpc' or 'http' | "Field 'opentelemetry.protocol' must be 'grpc' or 'http' (got: '{value}')" |
| VR-006 | `interval_seconds` must be int in range [10, 300] | "Field 'opentelemetry.interval_seconds' must be an integer between 10 and 300 (got: {value})" |
| VR-007 | `timeout_seconds` must be int in range [5, 60] | "Field 'opentelemetry.timeout_seconds' must be an integer between 5 and 60 (got: {value})" |
| VR-008 | `timeout_seconds` < `interval_seconds` | "Field 'opentelemetry.timeout_seconds' ({timeout}) must be less than interval_seconds ({interval})" |
| VR-009 | If `tls.enabled=true`, `tls.cert_path` must be set | "Field 'opentelemetry.tls.cert_path' is required when TLS is enabled" |
| VR-010 | If `tls.cert_path` is set, file must exist and be readable | "TLS certificate file not found or not readable: {path}" |
| VR-011 | `auth.headers` must be dict or null | "Field 'opentelemetry.auth.headers' must be a dictionary or null (got: {type})" |

### Configuration Example (YAML)

```yaml
opentelemetry:
  enabled: true
  endpoint: "http://localhost:4317"
  protocol: grpc
  interval_seconds: 30
  timeout_seconds: 15
  tls:
    enabled: false
    cert_path: null
  auth:
    headers:
      Authorization: "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

### Environment Variable Overrides

Configuration values can be overridden via environment variables:

| Environment Variable | Overrides Field | Example |
|---------------------|-----------------|---------|
| `LOXONE_OTLP_ENABLED` | `enabled` | `true` |
| `LOXONE_OTLP_ENDPOINT` | `endpoint` | `http://otel-collector:4317` |
| `LOXONE_OTLP_PROTOCOL` | `protocol` | `grpc` |
| `LOXONE_OTLP_INTERVAL` | `interval_seconds` | `60` |
| `LOXONE_OTLP_TIMEOUT` | `timeout_seconds` | `30` |
| `LOXONE_OTLP_TLS_ENABLED` | `tls.enabled` | `true` |
| `LOXONE_OTLP_TLS_CERT_PATH` | `tls.cert_path` | `/etc/ssl/certs/ca.crt` |
| `LOXONE_OTLP_AUTH_HEADER_*` | `auth.headers[key]` | `LOXONE_OTLP_AUTH_HEADER_AUTHORIZATION=Bearer xyz` |

---

## Entity: ExportStatus

Runtime state tracking OTLP export health. Updated by `OTLPExporter` during export lifecycle.

### Fields

| Field | Type | Initial Value | Description |
|-------|------|---------------|-------------|
| `state` | StateEnum | `DISABLED` or `IDLE` | Current export state (see state machine below) |
| `last_success_timestamp` | Optional[float] | `None` | Unix timestamp (seconds) of last successful export |
| `last_error` | Optional[str] | `None` | Error message from most recent failed export attempt |
| `consecutive_failures` | int | `0` | Count of failures since last success (0–10) |
| `current_backoff_seconds` | float | `1.0` | Current retry delay in seconds (1–300) |
| `next_export_timestamp` | float | `time.time() + interval` | Scheduled Unix timestamp for next export attempt |

### StateEnum Values

| Value | Code | Description |
|-------|------|-------------|
| DISABLED | 0 | OTLP export is turned off (`config.enabled=false`) |
| IDLE | 1 | Waiting for next scheduled export interval |
| EXPORTING | 2 | Currently executing an export attempt |
| RETRYING | 3 | Waiting for backoff delay after failure (consecutive_failures < 10) |
| FAILED | 4 | Maximum retries exceeded, waiting for next cycle to reset |

### State Machine

```
┌──────────┐
│ DISABLED │◄────────────────────────────────────┐
└──────────┘                                     │
                                                 │ config.enabled=false
┌──────────┐                                     │
│   IDLE   │◄────────────────────────────────────┤
└─────┬────┘                                     │
      │                                          │
      │ Interval timer & _should_export()=True   │
      ↓                                          │
┌──────────┐                                     │
│EXPORTING │                                     │
└─────┬────┘                                     │
      │                                          │
      ├────► Success ──────────────────────────► │
      │      (failures=0)                        │
      │                                          │
      └────► Failure (failures++)                │
             ↓                                   │
        ┌──────────┐                             │
        │RETRYING  │                             │
        └─────┬────┘                             │
              │                                  │
              │ Backoff timer & failures<10      │
              └─────────────► EXPORTING          │
              │                                  │
              │ failures>=10                     │
              ↓                                  │
        ┌──────────┐                             │
        │  FAILED  │                             │
        └─────┬────┘                             │
              │                                  │
              │ Next interval (reset failures)   │
              └──────────────────────────────────┘
```

### State Transitions

| From | Event | Condition | To | Actions |
|------|-------|-----------|----|---------| 
| - | Startup | `config.enabled=false` | DISABLED | None |
| - | Startup | `config.enabled=true` | IDLE | Set next_export_timestamp |
| IDLE | Interval timer | `_should_export()=True` | EXPORTING | None |
| IDLE | Interval timer | `_should_export()=False` | IDLE | Log skip reason |
| EXPORTING | Export completes | Success | IDLE | Reset consecutive_failures=0, update last_success_timestamp, schedule next |
| EXPORTING | Export fails | failures < 10 | RETRYING | Increment consecutive_failures, calculate backoff, set last_error |
| EXPORTING | Export fails | failures >= 10 | FAILED | Log critical error, set last_error |
| RETRYING | Backoff timer | failures < 10 | EXPORTING | None |
| FAILED | Next interval | New cycle | IDLE | Reset consecutive_failures=0, log recovery attempt |

### Backoff Calculation

Exponential backoff with cap:

```
delay = base_delay * (multiplier ^ (consecutive_failures - 1))
capped_delay = min(delay, max_delay)

Where:
  base_delay = 1.0 seconds
  multiplier = 2.0
  max_delay = 300.0 seconds (5 minutes)

Examples:
  failures=1 → 1 * 2^0 = 1s
  failures=2 → 1 * 2^1 = 2s
  failures=3 → 1 * 2^2 = 4s
  failures=4 → 1 * 2^3 = 8s
  failures=5 → 1 * 2^4 = 16s
  failures=6 → 1 * 2^5 = 32s
  failures=7 → 1 * 2^6 = 64s
  failures=8 → 1 * 2^7 = 128s
  failures=9 → 1 * 2^8 = 256s
  failures=10 → 1 * 2^9 = 300s (capped)
```

### Metrics Exposure

ExportStatus fields map to Prometheus metrics (exposed on `/metrics` endpoint):

| Field | Metric Name | Type | Labels |
|-------|-------------|------|--------|
| `state` | `loxone_otlp_export_status` | Gauge | - |
| `last_success_timestamp` | `loxone_otlp_last_success_timestamp_seconds` | Gauge | - |
| `consecutive_failures` | `loxone_otlp_consecutive_failures` | Gauge | - |

Additional metrics (not direct field mappings):
- `loxone_otlp_export_duration_seconds` (Histogram, labels: status, protocol)
- `loxone_otlp_exported_metrics_total` (Counter, labels: protocol)

See `contracts/health-metrics.md` for full metric specifications.

---

## Entity: MetricBatch

Internal representation of OTLP metrics payload before SDK serialization. Not persisted; constructed on-demand during each export.

### Structure

```python
@dataclass
class MetricBatch:
    """OTLP metrics batch for a single export."""
    
    resource_attributes: Dict[str, str]
    """Application metadata attached to all metrics in batch.
    
    Standard attributes:
      - service.name: "loxone-prometheus-exporter"
      - service.version: "<version from package>"
      - deployment.environment: "production" (or from config)
    """
    
    scope_name: str
    """Instrumentation scope name (e.g., "loxone_exporter")."""
    
    scope_version: str
    """Exporter version (same as service.version)."""
    
    metrics: List[OTLPMetric]
    """List of individual metrics in this batch."""

@dataclass
class OTLPMetric:
    """Single metric with metadata and data points."""
    
    name: str
    """Metric name (e.g., "loxone_control_value")."""
    
    description: str
    """Human-readable description (from Prometheus HELP text)."""
    
    unit: str
    """Metric unit (e.g., "", "celsius", "percent"). Empty string for unitless."""
    
    type: MetricType
    """Metric type enum: GAUGE, SUM, HISTOGRAM."""
    
    data_points: List[DataPoint]
    """Individual measurements with labels and timestamps."""

@dataclass
class DataPoint:
    """Single measurement within a metric."""
    
    attributes: Dict[str, str]
    """Labels/dimensions (e.g., {"miniserver": "living", "uuid": "...", "name": "..."}). 
    Converted from Prometheus labels."""
    
    value: float
    """Measurement value."""
    
    timestamp_ns: int
    """Unix timestamp in nanoseconds."""
```

### Conversion Rules: Prometheus → OTLP

| Prometheus Element | OTLP Element | Mapping |
|--------------------|--------------|---------|
| Metric name | `OTLPMetric.name` | Direct copy (e.g., `loxone_control_value`) |
| HELP text | `OTLPMetric.description` | Direct copy |
| TYPE | `OTLPMetric.type` | `gauge` → GAUGE, `counter` → SUM, `histogram` → HISTOGRAM |
| Unit suffix (if any) | `OTLPMetric.unit` | Extract from name (e.g., `_seconds` → "seconds", `_bytes` → "bytes", none → "") |
| Labels | `DataPoint.attributes` | Convert Prometheus labels dict to OTLP attributes dict (1:1 mapping) |
| Sample value | `DataPoint.value` | Direct copy (float) |
| Sample timestamp | `DataPoint.timestamp_ns` | Convert seconds to nanoseconds: `int(timestamp * 1e9)` |

**Type-Specific Mappings**:

- **Gauge**: Prometheus Gauge → OTLP Gauge (instantaneous value, no aggregation temporality)
- **Counter**: Prometheus Counter → OTLP Sum with `aggregation_temporality=CUMULATIVE` (monotonically increasing)
- **Histogram**: Prometheus Histogram → OTLP Histogram with `aggregation_temporality=CUMULATIVE` (cumulative bucket counts)

**Metadata Preservation** (FR-012):
- All Prometheus labels preserved as OTLP attributes (no loss)
- All Prometheus HELP text preserved as OTLP descriptions
- All Prometheus TYPE information preserved via explicit type conversion

### Example: Prometheus → OTLP Conversion

**Input (Prometheus scrape format)**:

```
# HELP loxone_control_value Current value of Loxone control
# TYPE loxone_control_value gauge
loxone_control_value{miniserver="living",uuid="0e1234-56",name="Temperature",room="Bedroom",category="Climate",type="analog"} 21.5 1707502345.123
```

**Output (OTLP MetricBatch structure)**:

```python
MetricBatch(
    resource_attributes={
        "service.name": "loxone-prometheus-exporter",
        "service.version": "0.2.0",
        "deployment.environment": "production"
    },
    scope_name="loxone_exporter",
    scope_version="0.2.0",
    metrics=[
        OTLPMetric(
            name="loxone_control_value",
            description="Current value of Loxone control",
            unit="",
            type=MetricType.GAUGE,
            data_points=[
                DataPoint(
                    attributes={
                        "miniserver": "living",
                        "uuid": "0e1234-56",
                        "name": "Temperature",
                        "room": "Bedroom",
                        "category": "Climate",
                        "type": "analog"
                    },
                    value=21.5,
                    timestamp_ns=1707502345123000000
                )
            ]
        )
        # ... more metrics ...
    ]
)
```

### Cardinality & Performance

- **Batch size**: Typically 500–1000 metrics per export (matches Prometheus scrape)
- **Data points per batch**: 500–1000 (one data point per metric; histograms have multiple buckets but count as single metric)
- **Memory footprint**: ~50KB–100KB per batch (transient, freed after export)
- **Conversion time**: <10ms for 1000 metrics (measured in research phase)

### SDK Serialization

`MetricBatch` is converted to OpenTelemetry SDK objects before SDK exporter serialization:

1. `MetricBatch` → `opentelemetry.sdk.metrics._internal.point.Metric` objects
2. SDK `MetricExporter.export()` → Protobuf-encoded OTLP payload
3. gRPC/HTTP exporter → transmit binary payload to collector

See `contracts/otlp-export.md` for `PrometheusToOTLPBridge` implementation details.

---

## Data Flow Diagram

```
┌─────────────────┐
│ Prometheus      │ (Existing)
│ CollectorRegistry│
└────────┬────────┘
         │
         │ (Pull on export interval)
         ↓
┌─────────────────┐
│PrometheusToOTLP │ (New)
│    Bridge       │
│                 │
│ - collect()     │
│ - convert()     │
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│  MetricBatch    │ (Transient)
│                 │
│ - Resource      │
│ - Scope         │
│ - Metrics[]     │
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│ OTLP Exporter   │ (New: SDK wrapper)
│  (gRPC/HTTP)    │
│                 │
│ - serialize()   │
│ - transmit()    │
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│ OTLP Collector  │ (External)
│  (User-hosted)  │
└─────────────────┘
```

**Concurrency Notes**:
- Prometheus registry is read-only during conversion (thread-safe)
- HTTP scrape and OTLP export can occur simultaneously (no contention)
- MetricBatch is created in OTLP export task, not shared across tasks

---

## Summary

Three core entities:

1. **OTLPConfiguration**: User-configured export behavior (YAML + env vars), validated at startup
2. **ExportStatus**: Runtime export health state, exposed via Prometheus metrics
3. **MetricBatch**: Transient OTLP payload structure, converted from Prometheus registry

These entities enable FR-001 through FR-015, support all three user stories (P1–P3), and maintain constitution compliance (local-first, self-contained, observable).

**Next**: See `contracts/` for detailed module interfaces and `quickstart.md` for usage examples.
