# OTLP Export Health Metrics

**Feature**: 002-opentelemetry-support  
**Date**: 2026-02-09

This document specifies the Prometheus metrics that track OpenTelemetry export health and performance.

---

## Overview

OTLP export health metrics follow the existing `loxone_exporter_*` naming convention. All metrics are exposed on the Prometheus `/metrics` endpoint alongside existing metrics. 

**Rationale**: Prometheus-first observability ensures operators can monitor OTLP export health using existing Prometheus/Grafana dashboards, without requiring a separate OTLP-based monitoring solution.

---

## Metrics Specification

### 1. `loxone_otlp_export_status`

Current OTLP export operational state.

**Type**: Gauge  
**Unit**: (unitless enum)  
**Labels**: None  

**HELP Text**:
```
Current OTLP export state (0=disabled, 1=idle, 2=exporting, 3=retrying, 4=failed)
```

**Values**:
| Value | State | Description |
|-------|-------|-------------|
| 0 | DISABLED | OTLP export is turned off (`config.enabled=false`) |
| 1 | IDLE | Waiting for next scheduled export interval |
| 2 | EXPORTING | Currently executing an export attempt |
| 3 | RETRYING | Waiting for backoff delay after failure |
| 4 | FAILED | Maximum retries (10) exceeded, waiting for next cycle to reset |

**Update Frequency**: On every state transition  
**Update Location**: `OTLPExporter._update_state()`

**Prometheus Scrape Output**:
```prometheus
# HELP loxone_otlp_export_status Current OTLP export state (0=disabled, 1=idle, 2=exporting, 3=retrying, 4=failed)
# TYPE loxone_otlp_export_status gauge
loxone_otlp_export_status 1
```

**Alerting Examples**:

Persistent failure:
```promql
# Alert: OTLP export in failed state for 5+ minutes
loxone_otlp_export_status == 4
  for: 5m
```

Export enabled but stuck in retrying:
```promql
# Alert: OTLP export retrying for 10+ minutes
loxone_otlp_export_status == 3
  for: 10m
```

---

### 2. `loxone_otlp_last_success_timestamp_seconds`

Unix timestamp of last successful OTLP export.

**Type**: Gauge  
**Unit**: seconds (Unix timestamp)  
**Labels**: None  

**HELP Text**:
```
Unix timestamp of last successful OTLP export (0 if never succeeded)
```

**Values**:
- Unix timestamp (float, seconds since epoch): Last successful export time
- `0`: Never succeeded since startup (or OTLP disabled)

**Update Frequency**: On successful export  
**Update Location**: `OTLPExporter._handle_success()`

**Prometheus Scrape Output**:
```prometheus
# HELP loxone_otlp_last_success_timestamp_seconds Unix timestamp of last successful OTLP export (0 if never succeeded)
# TYPE loxone_otlp_last_success_timestamp_seconds gauge
loxone_otlp_last_success_timestamp_seconds 1707502345.123
```

**Alerting Examples**:

Stale exports (no success in 5 minutes):
```promql
# Alert: No successful OTLP export in 5 minutes
(time() - loxone_otlp_last_success_timestamp_seconds) > 300
  and loxone_otlp_export_status != 0  # Exclude if disabled
```

Never succeeded after startup:
```promql
# Alert: OTLP export never succeeded after 2 minutes of uptime
loxone_otlp_last_success_timestamp_seconds == 0
  and loxone_otlp_export_status != 0
  and time() - loxone_exporter_start_time_seconds > 120
```

**Dashboard Visualization**:
```promql
# Time since last successful export
time() - loxone_otlp_last_success_timestamp_seconds
```

---

### 3. `loxone_otlp_consecutive_failures`

Number of consecutive export failures since last success.

**Type**: Gauge  
**Unit**: (count)  
**Labels**: None  

**HELP Text**:
```
Number of consecutive OTLP export failures since last success (0-10)
```

**Values**:
- `0`: No failures (healthy state)
- `1-9`: Failures occurred, retrying with exponential backoff
- `10`: Max retries exceeded, export in FAILED state

**Update Frequency**: On export failure (increment), on success (reset to 0)  
**Update Location**: `OTLPExporter._handle_failure()`, `OTLPExporter._handle_success()`

**Prometheus Scrape Output**:
```prometheus
# HELP loxone_otlp_consecutive_failures Number of consecutive OTLP export failures since last success (0-10)
# TYPE loxone_otlp_consecutive_failures gauge
loxone_otlp_consecutive_failures 3
```

**Alerting Examples**:

Early warning (high failure rate):
```promql
# Alert: 5+ consecutive OTLP export failures
loxone_otlp_consecutive_failures >= 5
```

Critical (approaching max retries):
```promql
# Alert: 8+ consecutive failures, about to enter FAILED state
loxone_otlp_consecutive_failures >= 8
```

**Dashboard Visualization**:
```promql
# Failure count over time
loxone_otlp_consecutive_failures
```

---

### 4. `loxone_otlp_export_duration_seconds`

Duration of OTLP export operations (histogram).

**Type**: Histogram  
**Unit**: seconds  
**Labels**:
- `status`: `success` | `failure`
- `protocol`: `grpc` | `http`

**HELP Text**:
```
Duration of OTLP export operations
```

**Buckets**: `[0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0]` (seconds)

**Rationale for buckets**:
- 0.01s (10ms): Fast local export baseline
- 0.05-0.1s: Typical local collector latency
- 0.5-1.0s: Acceptable latency for remote collectors
- 2.5-5.0s: Slow network or large metric batch
- 10.0s: Near-timeout threshold (default timeout is 15s)

**Update Frequency**: On every export attempt (success or failure)  
**Update Location**: `OTLPExporter._export_once()` (timer wrapper)

**Prometheus Scrape Output**:
```prometheus
# HELP loxone_otlp_export_duration_seconds Duration of OTLP export operations
# TYPE loxone_otlp_export_duration_seconds histogram
loxone_otlp_export_duration_seconds_bucket{status="success",protocol="grpc",le="0.01"} 0
loxone_otlp_export_duration_seconds_bucket{status="success",protocol="grpc",le="0.05"} 5
loxone_otlp_export_duration_seconds_bucket{status="success",protocol="grpc",le="0.1"} 23
loxone_otlp_export_duration_seconds_bucket{status="success",protocol="grpc",le="0.5"} 45
loxone_otlp_export_duration_seconds_bucket{status="success",protocol="grpc",le="1.0"} 47
loxone_otlp_export_duration_seconds_bucket{status="success",protocol="grpc",le="2.5"} 48
loxone_otlp_export_duration_seconds_bucket{status="success",protocol="grpc",le="5.0"} 48
loxone_otlp_export_duration_seconds_bucket{status="success",protocol="grpc",le="10.0"} 48
loxone_otlp_export_duration_seconds_bucket{status="success",protocol="grpc",le="+Inf"} 48
loxone_otlp_export_duration_seconds_sum{status="success",protocol="grpc"} 18.234
loxone_otlp_export_duration_seconds_count{status="success",protocol="grpc"} 48
```

**Cardinality**: 2 (status) × 2 (protocol) × (8 buckets + sum + count) = 40 series

**Alerting Examples**:

High P95 latency:
```promql
# Alert: P95 export duration > 2 seconds
histogram_quantile(0.95, 
  rate(loxone_otlp_export_duration_seconds_bucket{status="success"}[5m])
) > 2
```

High failure rate:
```promql
# Alert: >50% of exports failing
rate(loxone_otlp_export_duration_seconds_count{status="failure"}[5m])
  / 
rate(loxone_otlp_export_duration_seconds_count[5m])
  > 0.5
```

**Dashboard Visualization**:

P50/P95/P99 latency:
```promql
histogram_quantile(0.50, rate(loxone_otlp_export_duration_seconds_bucket[5m]))
histogram_quantile(0.95, rate(loxone_otlp_export_duration_seconds_bucket[5m]))
histogram_quantile(0.99, rate(loxone_otlp_export_duration_seconds_bucket[5m]))
```

Success rate (as percentage):
```promql
100 * (
  rate(loxone_otlp_export_duration_seconds_count{status="success"}[5m])
  / 
  rate(loxone_otlp_export_duration_seconds_count[5m])
)
```

---

### 5. `loxone_otlp_exported_metrics_total`

Total number of metric data points successfully exported via OTLP.

**Type**: Counter  
**Unit**: (count)  
**Labels**:
- `protocol`: `grpc` | `http`

**HELP Text**:
```
Total number of metric data points successfully exported via OTLP
```

**Values**: Monotonically increasing count of exported data points

**Increment**: On successful export, incremented by the number of data points in the exported batch (typically 500-1000 per export)

**Update Frequency**: On successful export  
**Update Location**: `OTLPExporter._export_once()` (success path)

**Prometheus Scrape Output**:
```prometheus
# HELP loxone_otlp_exported_metrics_total Total number of metric data points successfully exported via OTLP
# TYPE loxone_otlp_exported_metrics_total counter
loxone_otlp_exported_metrics_total{protocol="grpc"} 24567
```

**Cardinality**: 2 (protocol) = 2 series

**Alerting Examples**:

Export stalled (no increase in metrics exported):
```promql
# Alert: No metrics exported in 5 minutes
rate(loxone_otlp_exported_metrics_total[5m]) == 0
  and loxone_otlp_export_status != 0  # Exclude if disabled
```

**Dashboard Visualization**:

Export rate (data points per second):
```promql
rate(loxone_otlp_exported_metrics_total[1m])
```

Total exported today:
```promql
increase(loxone_otlp_exported_metrics_total[24h])
```

Cumulative exported since startup:
```promql
loxone_otlp_exported_metrics_total
```

---

## Total Cardinality Summary

| Metric | Series Count | Calculation |
|--------|--------------|-------------|
| `loxone_otlp_export_status` | 1 | Single gauge, no labels |
| `loxone_otlp_last_success_timestamp_seconds` | 1 | Single gauge, no labels |
| `loxone_otlp_consecutive_failures` | 1 | Single gauge, no labels |
| `loxone_otlp_export_duration_seconds` | 40 | 2 status × 2 protocol × (8 buckets + sum + count) |
| `loxone_otlp_exported_metrics_total` | 2 | 2 protocol |
| **Total** | **45** | Negligible compared to 50,000+ control metrics |

**Impact**: <0.1% increase in total series count for typical deployment (500 controls = ~50,000 series)

---

## Integration with Existing Metrics

OTLP health metrics complement existing exporter health metrics:

### Existing Metrics (for comparison)

| Metric | Purpose |
|--------|---------|
| `loxone_exporter_up` | Overall exporter health (0/1) |
| `loxone_exporter_connected` | Per-miniserver connection status (0/1) |
| `loxone_exporter_scrape_duration_seconds` | Prometheus scrape duration |
| `loxone_exporter_scrape_errors_total` | Prometheus scrape error count |

### New OTLP Metrics (this feature)

| Metric | Purpose |
|--------|---------|
| `loxone_otlp_export_status` | OTLP export state (0-4) |
| `loxone_otlp_last_success_timestamp_seconds` | OTLP export freshness |
| `loxone_otlp_consecutive_failures` | OTLP export failure tracking |
| `loxone_otlp_export_duration_seconds` | OTLP export latency/success rate |
| `loxone_otlp_exported_metrics_total` | OTLP export throughput |

**Unified Health View**: Operators can combine both sets of metrics to monitor:
1. Loxone connectivity (`loxone_exporter_connected`)
2. Prometheus scrape health (`loxone_exporter_scrape_duration_seconds`)
3. OTLP export health (`loxone_otlp_export_status`, `loxone_otlp_consecutive_failures`)

---

## Health Endpoint Integration

The `/healthz` endpoint (existing) is extended to include OTLP export status:

### Extended Health Response

```json
{
  "status": "healthy",
  "miniservers": {
    "living": {
      "connected": true,
      "controls": 234,
      "last_update": 1707502345.123
    }
  },
  "otlp": {
    "enabled": true,
    "state": "idle",
    "last_success": 1707502320.456,
    "consecutive_failures": 0,
    "protocol": "grpc"
  }
}
```

**Fields**:
- `otlp.enabled` (bool): From `config.opentelemetry.enabled`
- `otlp.state` (str): From `loxone_otlp_export_status` (enum name lowercase)
- `otlp.last_success` (float): From `loxone_otlp_last_success_timestamp_seconds`
- `otlp.consecutive_failures` (int): From `loxone_otlp_consecutive_failures`
- `otlp.protocol` (str): From `config.opentelemetry.protocol`

**Overall Status Logic**:
- `"healthy"`: Exporter up, at least one miniserver connected, OTLP idle/exporting/retrying (or disabled)
- `"degraded"`: Exporter up, OTLP in FAILED state (but Prometheus still functional)
- `"unhealthy"`: Exporter down or all miniservers disconnected

**Example (OTLP disabled)**:
```json
{
  "status": "healthy",
  "miniservers": { ... },
  "otlp": {
    "enabled": false
  }
}
```

**Example (OTLP failed)**:
```json
{
  "status": "degraded",
  "miniservers": { ... },
  "otlp": {
    "enabled": true,
    "state": "failed",
    "last_success": 1707501800.123,
    "consecutive_failures": 10,
    "protocol": "grpc",
    "last_error": "Failed to connect to otlp-collector:4317: connection refused"
  }
}
```

---

## Grafana Dashboard Examples

### Panel 1: OTLP Export Status

**Type**: Stat  
**Query**:
```promql
loxone_otlp_export_status
```

**Value Mappings**:
- 0 → "Disabled" (gray)
- 1 → "Idle" (green)
- 2 → "Exporting" (blue)
- 3 → "Retrying" (yellow)
- 4 → "Failed" (red)

**Thresholds**: Green (1), yellow (3), red (4)

---

### Panel 2: Time Since Last Success

**Type**: Stat  
**Query**:
```promql
time() - loxone_otlp_last_success_timestamp_seconds
```

**Unit**: seconds (auto-format: 1m 23s)  
**Thresholds**: <60s (green), 60-300s (yellow), >300s (red)

---

### Panel 3: Export Success Rate

**Type**: Gauge  
**Query**:
```promql
rate(loxone_otlp_export_duration_seconds_count{status="success"}[5m])
  / 
rate(loxone_otlp_export_duration_seconds_count[5m])
  * 100
```

**Unit**: percent  
**Thresholds**: >95% (green), 80-95% (yellow), <80% (red)

---

### Panel 4: Export Latency (P50, P95, P99)

**Type**: Time series  
**Queries**:
```promql
histogram_quantile(0.50, rate(loxone_otlp_export_duration_seconds_bucket[5m]))
histogram_quantile(0.95, rate(loxone_otlp_export_duration_seconds_bucket[5m]))
histogram_quantile(0.99, rate(loxone_otlp_export_duration_seconds_bucket[5m]))
```

**Unit**: seconds  
**Legend**: P50, P95, P99

---

### Panel 5: Metrics Exported Rate

**Type**: Time series  
**Query**:
```promql
rate(loxone_otlp_exported_metrics_total[1m])
```

**Unit**: data points/sec  
**Legend**: {{protocol}}

---

## Prometheus Alerts

### Alert 1: OTLP Export Failing

```yaml
- alert: LoxoneOTLPExportFailing
  expr: loxone_otlp_export_status == 4
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Loxone OTLP export in failed state"
    description: "OTLP export has failed 10 consecutive times and is now in failed state. Check collector connectivity and logs."
```

---

### Alert 2: OTLP Export Stale

```yaml
- alert: LoxoneOTLPExportStale
  expr: |
    (time() - loxone_otlp_last_success_timestamp_seconds) > 300
      and loxone_otlp_export_status != 0
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "Loxone OTLP export stale"
    description: "No successful OTLP export in {{ $value | humanizeDuration }}. Check exporter logs and collector status."
```

---

### Alert 3: OTLP Export High Latency

```yaml
- alert: LoxoneOTLPExportHighLatency
  expr: |
    histogram_quantile(0.95, 
      rate(loxone_otlp_export_duration_seconds_bucket{status="success"}[5m])
    ) > 2
  for: 10m
  labels:
    severity: info
  annotations:
    summary: "Loxone OTLP export latency high"
    description: "P95 OTLP export latency is {{ $value | humanizeDuration }}. Consider optimizing collector or network."
```

---

### Alert 4: OTLP Export Low Success Rate

```yaml
- alert: LoxoneOTLPExportLowSuccessRate
  expr: |
    rate(loxone_otlp_export_duration_seconds_count{status="success"}[5m])
      / 
    rate(loxone_otlp_export_duration_seconds_count[5m])
      < 0.8
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Loxone OTLP export success rate low"
    description: "OTLP export success rate is {{ $value | humanizePercentage }}. Investigate collector issues."
```

---

## Summary

Five health metrics provide comprehensive OTLP export observability:

1. **Status**: Current operational state (disabled/idle/exporting/retrying/failed)
2. **Freshness**: Time since last successful export
3. **Reliability**: Consecutive failure count (0-10)
4. **Performance**: Export duration histogram with success/failure breakdown
5. **Throughput**: Total metrics exported counter

**Usage**:
- **Operators**: Monitor via Grafana dashboards and Prometheus alerts
- **Debugging**: Correlate metrics with structured logs for root cause analysis
- **Capacity planning**: Track export latency and throughput trends

See `otlp-export.md` for metric update implementation and `quickstart.md` for dashboard setup examples.
