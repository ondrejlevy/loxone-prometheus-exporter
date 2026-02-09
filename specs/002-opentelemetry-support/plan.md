# Implementation Plan: OpenTelemetry Metrics Export Support

**Branch**: `002-opentelemetry-support` | **Date**: 2026-02-09 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/002-opentelemetry-support/spec.md`

## Summary

Add push-based OpenTelemetry Protocol (OTLP) metrics export alongside existing Prometheus pull-based scraping. The exporter will read OTLP collector configuration (endpoint, protocol [gRPC/HTTP], auth, TLS, interval) from YAML config, periodically push the same metrics currently exposed on `/metrics`, implement exponential backoff retry logic (1s–5min, max 10 failures), skip overlapping exports, and provide OTLP export health metrics. Configuration validation fails startup if invalid when enabled=true. Default: 30s interval, gRPC protocol, TLS disabled.

## Technical Context

**Language/Version**: Python 3.13 (existing project baseline)  
**Primary Dependencies**: `opentelemetry-sdk` 1.28.x, `opentelemetry-exporter-otlp-proto-grpc` 1.28.x, `opentelemetry-exporter-otlp-proto-http` 1.28.x (new); existing: `prometheus_client` 0.24.x, `websockets` 16.x, `aiohttp` 3.13.x  
**Storage**: N/A (in-memory metrics state, same as existing Prometheus export)  
**Testing**: pytest + pytest-asyncio (existing), will add OTLP-specific contract/integration tests  
**Target Platform**: Linux container (Docker/Podman, docker-compose orchestration) - existing  
**Project Type**: single  
**Performance Goals**: No degradation to existing Prometheus scrape (<2s freshness, ≤50MB memory), OTLP export within 2x configured interval, handle 1000+ metrics without performance impact  
**Constraints**: Local-first (no cloud), OTLP collector is user-configured endpoint, fail-fast on invalid config, exponential backoff 1s→5min max  
**Scale/Scope**: Same metric cardinality as existing (50–500+ controls per Miniserver), add OTLP export worker thread/task, ≤10 new config fields, 3 new health metrics

## Constitution Check (Pre-Research)

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Local-First Architecture (NON-NEGOTIABLE) | ✅ PASS | OTLP collector is user-specified local endpoint (FR-002). No cloud dependencies. User controls destination. |
| II. Self-Contained Solution (NON-NEGOTIABLE) | ✅ PASS | Adding 3 new OpenTelemetry SDK dependencies (opentelemetry-sdk, otlp-grpc, otlp-http). Research R1 confirmed: +13 total packages (3 direct + ~10 transitive), all Apache 2.0/MIT licensed, essential for OTLP export. Dependency increase justified and within acceptable bounds. |
| III. Observable Metrics Export | ✅ PASS | Core feature. FR-012 preserves existing Prometheus metric metadata. FR-010 adds OTLP export health metrics. Both export paths work independently. |
| IV. Test-First Development | ✅ PASS | Will include contract tests for OTLP export format, integration tests with mock OTLP collector, unit tests for retry logic, config validation tests. Target ≥80% coverage. |
| V. Simplicity & Maintainability | ✅ PASS | FR-015 skip overlap logic prevents queue complexity. FR-013/FR-014 provide explicit error handling. Separate OTLP exporter module, clear interface to existing metrics registry. |
| Deployment Constraints | ✅ PASS | Same Docker/Podman deployment. OTLP optional (disabled by default). Config via YAML + env vars. Resource targets maintained (≤50MB, ≤5% CPU). Health endpoint includes OTLP status. |

**Gate result: ✅ PASS** — All conditions satisfied. Research R1 confirmed +13 packages (within <20 target), R2 validated asyncio integration pattern, memory footprint target documented in performance goals.

## Project Structure

### Documentation (this feature)

```text
specs/002-opentelemetry-support/
├── plan.md              # This file
├── research.md          # Phase 0 output - OTLP SDK choices, retry patterns, asyncio integration
├── data-model.md        # Phase 1 output - OTLPConfig, ExportStatus, retry state machine
├── quickstart.md        # Phase 1 output - config examples, test setup with OTLP collector
├── contracts/           # Phase 1 output
│   ├── config-schema.md         # YAML config additions for OTLP
│   ├── otlp-export.md           # OTLP exporter module interface
│   └── health-metrics.md        # New OTLP health metrics specification
└── tasks.md             # Phase 2 output - NOT created yet
```

### Source Code (repository root)

```text
src/loxone_exporter/
├── __init__.py
├── __main__.py
├── config.py            # MODIFIED: add OTLP config section parsing + validation
├── logging.py           # existing
├── loxone_auth.py       # existing
├── loxone_client.py     # existing
├── loxone_protocol.py   # existing
├── metrics.py           # MODIFIED: add OTLP export health metrics
├── server.py            # MODIFIED: start OTLP export task alongside HTTP server
├── structure.py         # existing
└── otlp_exporter.py     # NEW: OTLP export logic, retry state machine, protocol abstraction

tests/
├── contract/
│   ├── test_metrics_endpoint.py     # existing
│   └── test_otlp_export.py          # NEW: verify OTLP format compliance
├── integration/
│   ├── mock_miniserver.py           # existing
│   ├── test_loxone_client.py        # existing
│   └── test_otlp_collector.py       # NEW: mock OTLP collector + export flow
├── performance/
│   └── test_load.py                 # MODIFIED: add OTLP export load test
└── unit/
    ├── test_auth.py                 # existing
    ├── test_config.py               # MODIFIED: add OTLP config validation tests
    ├── test_logging.py              # existing
    ├── test_metrics.py              # existing
    ├── test_protocol.py             # existing
    ├── test_structure.py            # existing
    └── test_otlp_retry.py           # NEW: retry state machine, backoff logic

config.example.yml       # MODIFIED: add commented OTLP section
README.md                # MODIFIED: document OTLP configuration
docker-compose.yml       # MODIFIED: optionally add OTLP collector example service
```

**Structure Decision**: Single project (Option 1). New `otlp_exporter.py` module encapsulates all OTLP logic. Modifications to existing `config.py`, `metrics.py`, `server.py` add integration points. Tests follow existing pattern (unit/integration/contract/performance).

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| N/A | Constitution check passed | N/A |

**Note**: The "REVIEW" status for Principle II will be resolved in Phase 0 research by documenting exact dependency counts and justifying each transitive dependency.

---

## Phase 0: Research & Clarifications

**Objective**: Resolve all technical unknowns before design phase. Generate `research.md` with findings.

### Research Tasks

**R1: OpenTelemetry SDK Selection**
- **Question**: Which OpenTelemetry Python SDK packages provide OTLP gRPC and HTTP export with minimal transitive dependencies?
- **Method**: Survey `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-grpc`, `opentelemetry-exporter-otlp-proto-http` package dependencies, check PyPI for version compatibility with Python 3.13
- **Deliverable**: Dependency tree (direct + transitive), total package count, license audit, compatibility confirmation

**R2: Asyncio Integration Pattern**
- **Question**: How should OTLP export integrate with existing asyncio event loop (background task, separate thread, executor)?
- **Method**: Review OpenTelemetry SDK docs for async support, research best practices for periodic background tasks in asyncio, consider impact on graceful shutdown (SIGTERM)
- **Deliverable**: Recommended pattern with code sketch, shutdown sequence diagram, performance considerations

**R3: Metric Conversion Strategy**
- **Question**: How to convert `prometheus_client` metrics registry to OTLP format without duplicating metric storage?
- **Method**: Explore OpenTelemetry SDK `MetricReader` and `MetricExporter` interfaces, research `prometheus_client` registry introspection, identify conversion approach (pull from Prometheus registry vs. dual write)
- **Deliverable**: Conversion approach with pros/cons, code sketch for metric bridging

**R4: Retry State Machine Design**
- **Question**: How to implement exponential backoff (1s, 2s, 4s... →5min cap, max 10 retries) that resets on scheduled export cycle and skips overlapping exports?
- **Method**: Survey retry patterns in existing Python OTLP exporters, research asyncio-safe backoff implementations, define state transitions
- **Deliverable**: State machine diagram (states: idle, exporting, retrying, failed, disabled), transition rules, backoff calculation pseudocode

**R5: Configuration Validation Strategy**
- **Question**: What validation rules ensure OTLP config is valid at startup (endpoint URL format, port range, protocol enum, auth header format)?
- **Method**: Review PyYAML validation approaches, research Python URL parsing libraries (urllib.parse), define validation ruleset
- **Deliverable**: Validation checklist with examples (valid/invalid configs), error message templates

**R6: gRPC vs HTTP Protocol Abstraction**
- **Question**: How to abstract gRPC and HTTP OTLP exporters behind common interface for runtime protocol selection?
- **Method**: Review OpenTelemetry SDK exporter base classes, design protocol factory pattern, identify shared vs. protocol-specific configuration
- **Deliverable**: Protocol abstraction interface, factory pattern code sketch, configuration mapping table

**R7: Health Metrics Specification**
- **Question**: What specific health metrics should track OTLP export status (connection state, last success timestamp, retry count, error types)?
- **Method**: Survey existing `loxone_exporter_*` health metrics, identify OTLP-specific observability needs, follow Prometheus naming conventions
- **Deliverable**: List of 3–5 new metrics with names, types, labels, HELP text, cardinality analysis

### Research Output: `research.md`

**Format**:
```markdown
# Research: OpenTelemetry Export Integration

## R1: OpenTelemetry SDK Selection
- Decision: [chosen packages + versions]
- Rationale: [why chosen]
- Dependency tree: [direct + transitive count]
- Total packages: [number]
- License audit: [all Apache 2.0 compatible]
- Alternatives considered: [other options, why rejected]

## R2: Asyncio Integration Pattern
[... same structure for each research task ...]
```

---

## Phase 1: Design Artifacts

**Objective**: Generate concrete design documents based on research findings. Re-evaluate constitution compliance.

### Phase 1 Deliverables

#### 1. `data-model.md` - Core Data Structures

**Content outline**:

```markdown
# Data Model: OpenTelemetry Export

## Entity: OTLPConfiguration

Configuration for OTLP export behavior.

**Fields**:
- `enabled` (bool): Enable/disable OTLP export (default: false)
- `endpoint` (str): OTLP collector URL (e.g., "http://localhost:4317")
- `protocol` (enum: 'grpc' | 'http'): OTLP protocol (default: 'grpc')
- `interval_seconds` (int): Export interval 10–300s (default: 30)
- `tls_enabled` (bool): Enable TLS (default: false)
- `tls_cert_path` (Optional[str]): Path to TLS cert file
- `auth_headers` (Optional[Dict[str, str]]): Authentication headers (e.g., {"Authorization": "Bearer token"})
- `timeout_seconds` (int): Export timeout 5–60s (default: 15)

**Validation Rules**:
- `endpoint` must be valid URL (http:// or https://)
- `port` extracted from URL must be 1–65535
- `protocol` must be 'grpc' or 'http'
- `interval_seconds` must be 10 ≤ x ≤ 300
- `timeout_seconds` must be 5 ≤ x ≤ 60, and < interval_seconds
- If `tls_enabled=true`, `tls_cert_path` must exist and be readable
- If `enabled=true` and validation fails → startup error (FR-014)

**Configuration Example** (YAML):
[config snippet]

## Entity: ExportStatus

Runtime state tracking OTLP export health.

**Fields**:
- `state` (enum: 'disabled' | 'idle' | 'exporting' | 'retrying' | 'failed'): Current export state
- `last_success_timestamp` (Optional[float]): Unix timestamp of last successful export
- `last_error` (Optional[str]): Last export error message
- `consecutive_failures` (int): Failure count since last success (0–10)
- `current_backoff_seconds` (float): Current retry delay (1s–300s)
- `next_export_timestamp` (float): Scheduled next export time

**State Transitions**:
[state machine diagram from research R4]

**Metrics Exposure**:
- `loxone_otlp_export_status` (gauge): state enum {0: disabled, 1: idle, 2: exporting, 3: retrying, 4: failed}
- `loxone_otlp_last_success_timestamp_seconds` (gauge): last_success_timestamp
- `loxone_otlp_consecutive_failures` (gauge): consecutive_failures

## Entity: MetricBatch

OTLP metrics payload structure (internal representation before SDK serialization).

**Fields**:
- `resource_attributes` (Dict[str, str]): Application metadata (service.name, service.version, deployment.environment)
- `scope_name` (str): Instrumentation scope (e.g., "loxone_exporter")
- `scope_version` (str): Exporter version
- `metrics` (List[Metric]): List of metric data points

**Metric Structure**:
- `name` (str): Metric name (e.g., "loxone_control_value")
- `description` (str): HELP text
- `unit` (str): Unit (e.g., "", "seconds")
- `type` (enum: 'gauge' | 'counter' | 'histogram'): Metric type
- `data_points` (List[DataPoint]): Individual measurements

**DataPoint Structure**:
- `attributes` (Dict[str, str]): Labels (miniserver, uuid, name, room, category, type)
- `value` (float): Measurement value
- `timestamp_ns` (int): Unix nanoseconds

**Conversion Rules**:
- Prometheus gauge → OTLP Gauge
- Prometheus counter → OTLP Sum (aggregation_temporality=CUMULATIVE)
- Preserve all labels as OTLP attributes
- Map Prometheus HELP → OTLP description
- Map Prometheus TYPE → OTLP data type
```

#### 2. `contracts/` - Module Interfaces

**contracts/config-schema.md**:
```markdown
# Config Schema: OTLP Section

## YAML Structure

```yaml
opentelemetry:
  enabled: false                     # bool, default: false
  endpoint: "http://localhost:4317"  # str, required if enabled=true
  protocol: grpc                     # 'grpc' | 'http', default: grpc
  interval_seconds: 30               # int 10-300, default: 30
  timeout_seconds: 15                # int 5-60, default: 15
  tls:
    enabled: false                   # bool, default: false
    cert_path: null                  # str | null, required if tls.enabled=true
  auth:
    headers:                         # dict | null, optional
      Authorization: "Bearer token"
```

## Environment Variable Overrides

- `LOXONE_OTLP_ENABLED=true|false`
- `LOXONE_OTLP_ENDPOINT=<url>`
- `LOXONE_OTLP_PROTOCOL=grpc|http`
- `LOXONE_OTLP_INTERVAL=<seconds>`
- `LOXONE_OTLP_AUTH_HEADER_<NAME>=<value>` (e.g., `LOXONE_OTLP_AUTH_HEADER_AUTHORIZATION=Bearer xyz`)

## Validation Rules

[Detailed validation from data-model.md OTLPConfiguration]
```

**contracts/otlp-export.md**:
```markdown
# Module Contract: otlp_exporter.py

## Public Interface

### Class: `OTLPExporter`

Manages OTLP metrics export lifecycle.

**Constructor**:
```python
def __init__(
    self,
    config: OTLPConfiguration,
    metrics_registry: prometheus_client.CollectorRegistry,
    logger: logging.Logger
) -> None
```

**Methods**:

```python
async def start(self) -> None:
    """Start export background task. Called during application startup."""

async def stop(self) -> None:
    """Stop export task gracefully. Called on SIGTERM."""

def get_status(self) -> ExportStatus:
    """Return current export status for health endpoint."""
```

**Internal Methods** (not exposed):

```python
async def _export_loop(self) -> None:
    """Main export loop: sleep → export → handle result → repeat."""

async def _export_once(self) -> bool:
    """Execute single export attempt. Returns True on success, False on failure."""

def _convert_metrics(self) -> MetricBatch:
    """Convert prometheus_client registry to OTLP MetricBatch."""

async def _send_otlp(self, batch: MetricBatch) -> None:
    """Send OTLP payload via gRPC or HTTP exporter."""

def _calculate_backoff(self, failure_count: int) -> float:
    """Calculate retry delay: min(2^failure_count, 300) seconds."""

def _should_export(self) -> bool:
    """Check if export should proceed (no overlap, not failed state)."""
```

## Dependencies

- Input: `OTLPConfiguration` (from config.py), `prometheus_client.CollectorRegistry` (from metrics.py)
- Output: None (side effect: OTLP export, metrics updates)
- External: `opentelemetry.sdk.metrics`, `opentelemetry.exporter.otlp`

## Error Handling

- Connection errors → log warning, increment failure count, schedule retry
- Timeout → log warning, treat as connection error
- Authentication failure → log error, treat as connection error
- Invalid config at startup → raise `ConfigurationError` (fails application start)
- Max retries exceeded (10) → log critical, enter 'failed' state, wait for next scheduled export cycle to reset
```

**contracts/health-metrics.md**:
```markdown
# OTLP Export Health Metrics

## New Metrics

### `loxone_otlp_export_status`

- **Type**: Gauge
- **Unit**: (unitless enum)
- **Labels**: None
- **HELP**: "Current OTLP export state (0=disabled, 1=idle, 2=exporting, 3=retrying, 4=failed)"
- **Values**: 0 (disabled), 1 (idle), 2 (exporting), 3 (retrying), 4 (failed)

### `loxone_otlp_last_success_timestamp_seconds`

- **Type**: Gauge
- **Unit**: seconds (Unix timestamp)
- **Labels**: None
- **HELP**: "Unix timestamp of last successful OTLP export"
- **Values**: Unix timestamp (float), or 0 if never succeeded

### `loxone_otlp_consecutive_failures`

- **Type**: Gauge
- **Unit**: (count)
- **Labels**: None
- **HELP**: "Number of consecutive OTLP export failures since last success"
- **Values**: 0–10 (capped at max retries)

### `loxone_otlp_export_duration_seconds`

- **Type**: Histogram
- **Unit**: seconds
- **Labels**: `status` (success | failure), `protocol` (grpc | http)
- **HELP**: "Duration of OTLP export operations"
- **Buckets**: [0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0]

### `loxone_otlp_exported_metrics_total`

- **Type**: Counter
- **Unit**: (count)
- **Labels**: `protocol` (grpc | http)
- **HELP**: "Total number of metric data points exported via OTLP"
- **Values**: Incremented by data point count on each successful export

## Cardinality Analysis

- `loxone_otlp_export_status`: 1 series
- `loxone_otlp_last_success_timestamp_seconds`: 1 series
- `loxone_otlp_consecutive_failures`: 1 series
- `loxone_otlp_export_duration_seconds`: 2 (status) × 2 (protocol) × 8 (buckets) = 32 series
- `loxone_otlp_exported_metrics_total`: 2 (protocol) = 2 series

**Total new series**: ~38 (negligible compared to existing metrics)
```

#### 3. `quickstart.md` - Testing & Deployment Guide

**Content outline**:

```markdown
# Quick Start: OpenTelemetry Export

## Development Setup

### 1. Install Dependencies

```bash
cd loxone-prometheus-exporter
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Start OTLP Collector (for testing)

Using OpenTelemetry Collector with Prometheus backend:

```yaml
# otel-collector-config.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

exporters:
  prometheus:
    endpoint: "0.0.0.0:9090"
  logging:
    loglevel: debug

service:
  pipelines:
    metrics:
      receivers: [otlp]
      exporters: [prometheus, logging]
```

```bash
docker run -d \
  --name otel-collector \
  -p 4317:4317 -p 4318:4318 -p 9090:9090 \
  -v $(pwd)/otel-collector-config.yaml:/etc/otel-collector-config.yaml \
  otel/opentelemetry-collector:latest \
  --config=/etc/otel-collector-config.yaml
```

### 3. Configure Exporter

Add to `config.yml`:

```yaml
opentelemetry:
  enabled: true
  endpoint: "http://localhost:4317"
  protocol: grpc
  interval_seconds: 30
```

### 4. Run Exporter

```bash
python -m loxone_exporter
```

### 5. Verify OTLP Export

Check collector logs:
```bash
docker logs -f otel-collector
```

Query Prometheus endpoint exposed by collector:
```bash
curl http://localhost:9090/metrics | grep loxone_control_value
```

## Testing Commands

### Run All Tests

```bash
pytest -v --cov=loxone_exporter --cov-report=term-missing
```

### Run OTLP-Specific Tests

```bash
# Contract tests (OTLP format validation)
pytest -v tests/contract/test_otlp_export.py

# Integration tests (mock collector)
pytest -v tests/integration/test_otlp_collector.py

# Unit tests (retry logic, config validation)
pytest -v tests/unit/test_otlp_retry.py
pytest -v tests/unit/test_config.py -k otlp
```

### Run Performance Tests

```bash
# Load test with OTLP export enabled
pytest -v tests/performance/test_load.py --otlp-enabled
```

### Type Checking & Linting

```bash
mypy src/loxone_exporter
ruff check src/loxone_exporter tests
```

## Configuration Examples

### gRPC with TLS

```yaml
opentelemetry:
  enabled: true
  endpoint: "https://otlp-collector.internal.example.com:4317"
  protocol: grpc
  tls:
    enabled: true
    cert_path: /etc/ssl/certs/otlp-ca.crt
  auth:
    headers:
      Authorization: "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

### HTTP with API Key

```yaml
opentelemetry:
  enabled: true
  endpoint: "http://localhost:4318"
  protocol: http
  interval_seconds: 15
  auth:
    headers:
      X-API-Key: "secret-api-key-12345"
```

### Disabled (Prometheus-only)

```yaml
opentelemetry:
  enabled: false
```

## Health Check

Query exporter health endpoint:

```bash
curl http://localhost:8000/healthz
```

Expected response with OTLP enabled:

```json
{
  "status": "healthy",
  "miniservers": {
    "livingroom": {
      "connected": true,
      "controls": 234,
      "last_update": 1707501234.567
    }
  },
  "otlp": {
    "enabled": true,
    "state": "idle",
    "last_success": 1707501220.123,
    "consecutive_failures": 0,
    "protocol": "grpc"
  }
}
```

## Docker Compose Example

Updated `docker-compose.yml` with OTLP collector:

```yaml
version: '3.8'

services:
  loxone-exporter:
    build: .
    environment:
      - LOXONE_OTLP_ENABLED=true
      - LOXONE_OTLP_ENDPOINT=http://otel-collector:4317
      - LOXONE_OTLP_PROTOCOL=grpc
    depends_on:
      - otel-collector
    volumes:
      - ./config.yml:/app/config.yml:ro

  otel-collector:
    image: otel/opentelemetry-collector:latest
    ports:
      - "4317:4317"  # gRPC
      - "4318:4318"  # HTTP
    volumes:
      - ./otel-collector-config.yaml:/etc/otel-collector-config.yaml:ro
    command: ["--config=/etc/otel-collector-config.yaml"]

  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9091:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
```

## Troubleshooting

### OTLP Export Failing

Check exporter logs:
```bash
docker logs loxone-exporter | grep -i otlp
```

Check health metrics:
```bash
curl http://localhost:8000/metrics | grep loxone_otlp
```

### Configuration Validation Errors

Run config validation:
```bash
python -m loxone_exporter --validate-config
```

### High Retry Count

Check `loxone_otlp_consecutive_failures` metric. If at 10 (max), exporter is in 'failed' state. Check:
1. OTLP collector is reachable: `telnet <collector-host> <port>`
2. Authentication credentials are correct
3. TLS certificate is valid and trusted
4. Network policies allow egress to collector

Reset by restarting exporter (resets retry counter on new export cycle).
```

---

## Phase 1 Completion: Agent Context Update

After generating Phase 1 artifacts, update the agent context file to include new technology choices:

```bash
.specify/scripts/bash/update-agent-context.sh copilot
```

This script will:
1. Detect the active AI agent (GitHub Copilot)
2. Update `.github/copilot-instructions.md`
3. Add OpenTelemetry SDK dependencies to technology list
4. Preserve manual additions between markers

---

## Constitution Check (Post-Design)

*Re-evaluated after Phase 1 design artifacts (data-model.md, contracts/, quickstart.md).*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Local-First Architecture (NON-NEGOTIABLE) | ✅ PASS | OTLP endpoint is user-configured (config-schema.md). No cloud dependencies. All data flows to user-specified local collector. Environment variables override YAML config. |
| II. Self-Contained Solution (NON-NEGOTIABLE) | ✅ PASS | Research R1 confirms: 3 direct OpenTelemetry deps (`opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-grpc`, `opentelemetry-exporter-otlp-proto-http`) add ~12 transitive dependencies (protobuf, grpc, backoff, deprecated). Total project deps: 5 existing + 3 new = 8 direct, ~21 total. All Apache 2.0 licensed. Within reasonable bounds. |
| III. Observable Metrics Export | ✅ PASS | health-metrics.md defines 5 new OTLP health metrics following Prometheus conventions. data-model.md MetricBatch preserves all labels/descriptions (FR-012). Both Prometheus and OTLP exports work independently. |
| IV. Test-First Development | ✅ PASS | quickstart.md defines test commands for OTLP-specific contract/integration/unit tests. Test structure in plan: `test_otlp_export.py` (contract), `test_otlp_collector.py` (integration), `test_otlp_retry.py` (unit). Target ≥80% coverage. |
| V. Simplicity & Maintainability | ✅ PASS | otlp-export.md contract: single `OTLPExporter` class with clear public interface (start/stop/get_status). Retry logic in `_calculate_backoff()` method (simple exponential with cap). Config validation in config.py with explicit error messages (config-schema.md). No over-engineering. |
| Deployment Constraints | ✅ PASS | quickstart.md docker-compose example adds OTLP collector as optional service. Health endpoint response includes OTLP status. SIGTERM handling in `OTLPExporter.stop()`. Resource target: ≤10MB memory overhead (research R2). Structured logging for OTLP events. |

**Gate result: PASS** — No violations introduced by Phase 1 design. Research R1 resolved Principle II concern (dependency count is acceptable). Ready to proceed to Phase 2 task breakdown.

---

## Next Steps

1. **Complete Phase 0**: Generate `research.md` by executing research tasks R1–R7
2. **Complete Phase 1**: Generate `data-model.md`, `contracts/`, `quickstart.md` based on research findings
3. **Update Agent Context**: Run `.specify/scripts/bash/update-agent-context.sh copilot`
4. **Phase 2 (separate command)**: Run `/speckit.tasks` to generate `tasks.md` with implementation checklist

**Command**: Phase 0 and Phase 1 are completed by this `/speckit.plan` execution. Phase 2 requires `/speckit.tasks` command.
