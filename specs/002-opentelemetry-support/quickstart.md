# Quick Start: OpenTelemetry Export

**Feature**: 002-opentelemetry-support  
**Date**: 2026-02-09

This guide covers development setup, testing, configuration, and deployment for the OpenTelemetry export feature.

---

## Table of Contents

1. [Development Setup](#development-setup)
2. [Testing](#testing)
3. [Configuration Examples](#configuration-examples)
4. [Docker Compose Deployment](#docker-compose-deployment)
5. [Health Monitoring](#health-monitoring)
6. [Troubleshooting](#troubleshooting)

---

## Development Setup

### Prerequisites

- Python 3.13+
- Docker (for running test OTLP collector)
- Git

### 1. Clone and Install Dependencies

```bash
# Clone repository
cd loxone-prometheus-exporter

# Create virtual environment
python3.13 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install with development dependencies
pip install -e ".[dev]"
```

**New dependencies (added by this feature)**:
```
opentelemetry-sdk~=1.28
opentelemetry-exporter-otlp-proto-grpc~=1.28
opentelemetry-exporter-otlp-proto-http~=1.28
```

### 2. Start Test OTLP Collector

Using OpenTelemetry Collector with debug logging:

#### Option A: Docker Run (Quick Start)

```bash
# Create collector config
cat > otel-collector-config.yaml <<EOF
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

exporters:
  logging:
    loglevel: debug
  prometheus:
    endpoint: "0.0.0.0:9090"

service:
  pipelines:
    metrics:
      receivers: [otlp]
      exporters: [logging, prometheus]
EOF

# Run collector
docker run -d \
  --name otel-collector \
  -p 4317:4317 \
  -p 4318:4318 \
  -p 9090:9090 \
  -v $(pwd)/otel-collector-config.yaml:/etc/otel-collector-config.yaml:ro \
  otel/opentelemetry-collector:latest \
  --config=/etc/otel-collector-config.yaml

# Check collector logs
docker logs -f otel-collector
```

#### Option B: Docker Compose (with Grafana)

See [Docker Compose Deployment](#docker-compose-deployment) section below.

### 3. Configure Exporter for Development

Create or update `config.yml`:

```yaml
# Existing Loxone configuration
miniservers:
  - name: demo
    host: demo.loxone.com
    username: demo
    password: demo

# Exporter settings
exporter:
  port: 8000
  log_level: debug

# NEW: OpenTelemetry configuration
opentelemetry:
  enabled: true
  endpoint: "http://localhost:4317"
  protocol: grpc
  interval_seconds: 15  # Fast interval for testing
  timeout_seconds: 10
```

### 4. Run Exporter Locally

```bash
# Activate virtual environment if not already active
source .venv/bin/activate

# Run exporter
python -m loxone_exporter

# Expected output:
# INFO: Starting Loxone Prometheus Exporter v0.2.0
# INFO: Connecting to miniserver 'demo' at demo.loxone.com
# INFO: OTLP export enabled (protocol=grpc, endpoint=http://localhost:4317, interval=15s)
# INFO: HTTP server listening on :8000
# DEBUG: OTLP export succeeded (234 metrics, 0.08s)
```

### 5. Verify OTLP Export

Check collector received metrics:

```bash
# Check collector logs (should show received metrics)
docker logs otel-collector | grep -i "metricsexporter"

# Query Prometheus endpoint exposed by collector
curl -s http://localhost:9090/metrics | grep loxone_control_value

# Check exporter's own OTLP health metrics
curl -s http://localhost:8000/metrics | grep loxone_otlp
```

Expected health metrics:
```prometheus
loxone_otlp_export_status 1
loxone_otlp_last_success_timestamp_seconds 1707502345.123
loxone_otlp_consecutive_failures 0
loxone_otlp_exported_metrics_total{protocol="grpc"} 234
```

---

## Testing

### Test Categories

1. **Unit tests**: Retry logic, config validation, metric conversion
2. **Integration tests**: Mock OTLP collector, export flow
3. **Contract tests**: OTLP format compliance, Prometheus endpoint
4. **Performance tests**: Load testing with OTLP enabled

### Run All Tests

```bash
# Run full test suite with coverage
pytest -v --cov=loxone_exporter --cov-report=term-missing

# Expected output:
# tests/unit/test_config.py::test_otlp_config_validation PASSED
# tests/unit/test_otlp_retry.py::test_backoff_calculation PASSED
# tests/integration/test_otlp_collector.py::test_export_flow PASSED
# tests/contract/test_otlp_export.py::test_otlp_format PASSED
# ...
# Coverage: 85%
```

### Run OTLP-Specific Tests Only

```bash
# Unit tests
pytest -v tests/unit/test_otlp_retry.py
pytest -v tests/unit/test_config.py -k otlp

# Integration tests
pytest -v tests/integration/test_otlp_collector.py

# Contract tests
pytest -v tests/contract/test_otlp_export.py
```

### Run Individual Test Suites

#### Unit Tests: Retry Logic

```bash
pytest -v tests/unit/test_otlp_retry.py

# Test cases:
# - test_backoff_calculation: Verify exponential backoff formula
# - test_state_transitions: Verify state machine logic
# - test_max_retries: Verify FAILED state after 10 failures
# - test_retry_reset: Verify failure counter resets on success
# - test_overlap_prevention: Verify skip logic when export in progress
```

#### Unit Tests: Config Validation

```bash
pytest -v tests/unit/test_config.py -k otlp

# Test cases:
# - test_otlp_config_valid: Valid configurations accepted
# - test_otlp_config_missing_endpoint: Error when enabled without endpoint
# - test_otlp_config_invalid_url: Error on malformed endpoint URL
# - test_otlp_config_invalid_protocol: Error on unsupported protocol
# - test_otlp_config_timeout_validation: Error when timeout >= interval
# - test_otlp_config_tls_cert_not_found: Error when cert file missing
# - test_otlp_config_env_var_override: Env vars override YAML
```

#### Integration Tests: Mock OTLP Collector

```bash
pytest -v tests/integration/test_otlp_collector.py

# Test cases:
# - test_successful_export: End-to-end export to mock collector
# - test_collector_unreachable: Verify retry behavior on connection failure
# - test_collector_timeout: Verify timeout handling
# - test_authentication_failure: Verify auth error handling
# - test_concurrent_prometheus_scrape: Verify no interference with Prometheus
```

#### Contract Tests: OTLP Format Compliance

```bash
pytest -v tests/contract/test_otlp_export.py

# Test cases:
# - test_otlp_resource_attributes: Verify service.name, service.version
# - test_otlp_metric_names: Verify metric names preserved
# - test_otlp_metric_types: Verify gauge/counter/histogram conversion
# - test_otlp_attributes: Verify labels → attributes conversion
# - test_otlp_timestamps: Verify timestamp precision (nanoseconds)
# - test_otlp_descriptions: Verify HELP text preserved
```

#### Performance Tests: Load Testing

```bash
pytest -v tests/performance/test_load.py --otlp-enabled

# Test scenarios:
# - 1000 metrics @ 15s interval: Memory usage, CPU usage, export duration
# - Verify: Export duration < 500ms P95
# - Verify: Memory overhead < 10MB with OTLP enabled
# - Verify: Prometheus scrape latency unaffected (<100ms P95)
```

### Test with Different Protocols

```bash
# Test gRPC protocol
LOXONE_OTLP_PROTOCOL=grpc pytest -v tests/integration/test_otlp_collector.py

# Test HTTP protocol
LOXONE_OTLP_PROTOCOL=http pytest -v tests/integration/test_otlp_collector.py
```

### Type Checking & Linting

```bash
# Type check with mypy
mypy src/loxone_exporter

# Expected: src/loxone_exporter/otlp_exporter.py: success

# Lint with ruff
ruff check src/loxone_exporter tests

# Expected: All checks passed!
```

### Coverage Target

**Minimum coverage**: 80% (project standard)

**OTLP-specific modules**:
- `otlp_exporter.py`: ≥85% (core logic)
- `config.py` (OTLP sections): ≥90% (validation critical)

```bash
# Generate HTML coverage report
pytest --cov=loxone_exporter --cov-report=html
open htmlcov/index.html
```

---

## Configuration Examples

### Example 1: Local Development (gRPC, Minimal)

**Use case**: Testing against local OpenTelemetry Collector

```yaml
opentelemetry:
  enabled: true
  endpoint: "http://localhost:4317"
```

**Defaults applied**:
- `protocol`: `grpc`
- `interval_seconds`: `30`
- `timeout_seconds`: `15`
- `tls.enabled`: `false`

---

### Example 2: Production (gRPC with TLS and Auth)

**Use case**: Secure production deployment with corporate OTLP collector

```yaml
opentelemetry:
  enabled: true
  endpoint: "https://otlp-collector.corp.example.com:4317"
  protocol: grpc
  interval_seconds: 60
  timeout_seconds: 30
  tls:
    enabled: true
    cert_path: /etc/ssl/certs/corp-ca-bundle.crt
  auth:
    headers:
      Authorization: "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWI..."
```

**Features**:
- TLS encryption with corporate CA certificate
- JWT Bearer token authentication
- 60-second export interval (balanced for production)
- 30-second timeout (allows for slower networks)

---

### Example 3: Cloud Vendor (HTTP with API Key)

**Use case**: Exporting to Datadog, New Relic, Grafana Cloud, etc.

```yaml
opentelemetry:
  enabled: true
  endpoint: "https://otlp.grafana.net:443"
  protocol: http
  interval_seconds: 30
  timeout_seconds: 20
  tls:
    enabled: true
    cert_path: /etc/ssl/certs/ca-certificates.crt  # System bundle
  auth:
    headers:
      X-API-Key: "grafana-api-key-abcd1234"
      X-Instance-ID: "12345"
```

**Features**:
- HTTP protocol (more firewall-friendly)
- API key authentication (common for cloud vendors)
- System CA certificate bundle (no custom cert needed)
- Port 443 (standard HTTPS)

---

### Example 4: Dual Protocol Testing

**Use case**: Testing both gRPC and HTTP protocols

```yaml
opentelemetry:
  enabled: true
  endpoint: "http://localhost:4317"  # gRPC port
  protocol: grpc
```

Switch to HTTP:
```bash
# Override via environment variable
export LOXONE_OTLP_PROTOCOL=http
export LOXONE_OTLP_ENDPOINT=http://localhost:4318

# Run exporter (uses HTTP now)
python -m loxone_exporter
```

---

### Example 5: Disabled (Prometheus-Only Mode)

**Use case**: Temporarily disable OTLP export without removing configuration

```yaml
opentelemetry:
  enabled: false
  # All other fields ignored when disabled
```

Or via environment variable:
```bash
export LOXONE_OTLP_ENABLED=false
python -m loxone_exporter
```

---

### Example 6: High-Frequency Export

**Use case**: Testing or monitoring with fast update rate

```yaml
opentelemetry:
  enabled: true
  endpoint: "http://localhost:4317"
  interval_seconds: 10  # Minimum allowed
  timeout_seconds: 5
```

**Warning**: High-frequency exports increase network traffic and collector load. Use sparingly.

---

## Docker Compose Deployment

### Complete Stack with OTLP Collector

Create `docker-compose.override.yml` (or update existing `docker-compose.yml`):

```yaml
version: '3.8'

services:
  # Loxone exporter (updated with OTLP support)
  loxone-exporter:
    build: .
    container_name: loxone-exporter
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./config.yml:/app/config.yml:ro
    environment:
      - LOXONE_OTLP_ENABLED=true
      - LOXONE_OTLP_ENDPOINT=http://otel-collector:4317
      - LOXONE_OTLP_PROTOCOL=grpc
      - LOXONE_OTLP_INTERVAL=30
    depends_on:
      - otel-collector
    networks:
      - monitoring

  # OpenTelemetry Collector (new)
  otel-collector:
    image: otel/opentelemetry-collector:latest
    container_name: otel-collector
    restart: unless-stopped
    command: ["--config=/etc/otel-collector-config.yaml"]
    ports:
      - "4317:4317"  # OTLP gRPC
      - "4318:4318"  # OTLP HTTP
      - "9090:9090"  # Prometheus exporter
    volumes:
      - ./otel-collector-config.yaml:/etc/otel-collector-config.yaml:ro
    networks:
      - monitoring

  # Prometheus (existing, updated to scrape both exporter and collector)
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    restart: unless-stopped
    ports:
      - "9091:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/usr/share/prometheus/console_libraries'
      - '--web.console.templates=/usr/share/prometheus/consoles'
    networks:
      - monitoring

  # Grafana (existing)
  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - grafana-data:/var/lib/grafana
    networks:
      - monitoring

networks:
  monitoring:
    driver: bridge

volumes:
  prometheus-data:
  grafana-data:
```

### OTLP Collector Configuration

Create `otel-collector-config.yaml`:

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 10s
    send_batch_size: 1024

exporters:
  logging:
    loglevel: info
  
  prometheus:
    endpoint: "0.0.0.0:9090"
    namespace: "otlp"
    const_labels:
      source: "loxone-exporter"
  
  # Optional: Forward to another OTLP endpoint
  # otlp:
  #   endpoint: "https://remote-otlp-collector.example.com:4317"
  #   tls:
  #     insecure: false
  #     cert_file: /etc/ssl/certs/ca.crt
  #   headers:
  #     authorization: "Bearer token"

service:
  pipelines:
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [logging, prometheus]
  
  telemetry:
    logs:
      level: info
```

### Updated Prometheus Configuration

Update `prometheus.yml` to scrape both the exporter and collector:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  # Loxone Exporter (existing)
  - job_name: 'loxone-exporter'
    static_configs:
      - targets: ['loxone-exporter:8000']
    
  # OTLP Collector's Prometheus exporter (new)
  - job_name: 'otel-collector'
    static_configs:
      - targets: ['otel-collector:9090']
```

### Start the Stack

```bash
# Start all services
docker-compose up -d

# Check logs
docker-compose logs -f loxone-exporter
docker-compose logs -f otel-collector

# Verify services
docker-compose ps
```

**Expected services**:
- `loxone-exporter`: Port 8000 (Prometheus metrics + health)
- `otel-collector`: Ports 4317 (gRPC), 4318 (HTTP), 9090 (Prometheus)
- `prometheus`: Port 9091
- `grafana`: Port 3000

### Verify Deployment

```bash
# Check exporter health
curl http://localhost:8000/healthz

# Check exporter OTLP metrics
curl http://localhost:8000/metrics | grep loxone_otlp

# Check collector received metrics (Prometheus endpoint)
curl http://localhost:9090/metrics | grep loxone_control_value

# Access Grafana
open http://localhost:3000
# Login: admin / admin
```

---

## Health Monitoring

### Health Endpoint

Query `/healthz` for overall system status including OTLP export:

```bash
curl -s http://localhost:8000/healthz | jq
```

**Response (healthy)**:
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
    "last_success": 1707502330.456,
    "consecutive_failures": 0,
    "protocol": "grpc"
  }
}
```

**Response (OTLP failed)**:
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
    "last_error": "Connection refused: otlp-collector:4317"
  }
}
```

### Prometheus Metrics

Query key OTLP health metrics:

```bash
# Export status (0=disabled, 1=idle, 2=exporting, 3=retrying, 4=failed)
curl http://localhost:8000/metrics | grep loxone_otlp_export_status

# Last success timestamp
curl http://localhost:8000/metrics | grep loxone_otlp_last_success_timestamp

# Consecutive failures
curl http://localhost:8000/metrics | grep loxone_otlp_consecutive_failures

# Export duration histogram
curl http://localhost:8000/metrics | grep loxone_otlp_export_duration_seconds

# Total metrics exported
curl http://localhost:8000/metrics | grep loxone_otlp_exported_metrics_total
```

### Grafana Dashboard

Import dashboard JSON (create `grafana-dashboard-otlp.json`):

```json
{
  "dashboard": {
    "title": "Loxone Exporter - OTLP Export Health",
    "panels": [
      {
        "title": "OTLP Export Status",
        "type": "stat",
        "targets": [
          {
            "expr": "loxone_otlp_export_status"
          }
        ],
        "mappings": [
          {"value": 0, "text": "Disabled"},
          {"value": 1, "text": "Idle"},
          {"value": 2, "text": "Exporting"},
          {"value": 3, "text": "Retrying"},
          {"value": 4, "text": "Failed"}
        ]
      },
      {
        "title": "Time Since Last Success",
        "type": "stat",
        "targets": [
          {
            "expr": "time() - loxone_otlp_last_success_timestamp_seconds"
          }
        ],
        "unit": "s"
      },
      {
        "title": "Export Success Rate",
        "type": "gauge",
        "targets": [
          {
            "expr": "rate(loxone_otlp_export_duration_seconds_count{status=\"success\"}[5m]) / rate(loxone_otlp_export_duration_seconds_count[5m]) * 100"
          }
        ],
        "unit": "percent"
      }
    ]
  }
}
```

---

## Troubleshooting

### Issue: OTLP Export Failing (Connection Refused)

**Symptoms**:
- `loxone_otlp_export_status == 4` (FAILED)
- `loxone_otlp_consecutive_failures == 10`
- Logs: `ERROR: OTLP export failed: Connection refused`

**Diagnosis**:
```bash
# Check exporter logs
docker logs loxone-exporter | grep -i otlp

# Check collector is running
docker ps | grep otel-collector

# Test connectivity to collector
docker exec loxone-exporter nc -zv otel-collector 4317
```

**Solutions**:
1. **Collector not running**: Start collector: `docker-compose up -d otel-collector`
2. **Wrong endpoint**: Verify `endpoint` in config matches collector address
3. **Network isolation**: Ensure exporter and collector are on same Docker network
4. **Firewall**: Check firewall rules allow port 4317 (gRPC) or 4318 (HTTP)

---

### Issue: OTLP Export Timing Out

**Symptoms**:
- `loxone_otlp_consecutive_failures` increasing
- Logs: `WARNING: OTLP export failed: Timeout waiting for response`

**Diagnosis**:
```bash
# Check export duration
curl http://localhost:8000/metrics | grep loxone_otlp_export_duration_seconds

# Check collector logs for slow processing
docker logs otel-collector | grep -i "slow\|timeout"
```

**Solutions**:
1. **Increase timeout**: Set `timeout_seconds: 30` in config (from default 15)
2. **Collector overloaded**: Scale collector or reduce export frequency
3. **Network latency**: Use local collector or increase timeout for remote

---

### Issue: Authentication Failure

**Symptoms**:
- `loxone_otlp_consecutive_failures` increasing
- Logs: `ERROR: OTLP export failed: Unauthenticated`

**Diagnosis**:
```bash
# Check auth headers in config
grep -A5 "auth:" config.yml

# Check collector expects authentication
docker logs otel-collector | grep -i "auth\|unauthenticated"
```

**Solutions**:
1. **Missing auth**: Add `auth.headers` to config
2. **Invalid token**: Verify Bearer token or API key is current
3. **Auth header mismatch**: Confirm header name matches collector expectation (e.g., `Authorization` vs `X-API-Key`)

---

### Issue: TLS Certificate Error

**Symptoms**:
- Logs: `ERROR: TLS certificate file not found: /path/to/cert.crt`
- Exporter fails to start

**Diagnosis**:
```bash
# Check cert path exists
ls -l /path/to/cert.crt

# Check cert is readable
cat /path/to/cert.crt
```

**Solutions**:
1. **Cert not found**: Verify `tls.cert_path` points to correct file
2. **Permission denied**: Ensure exporter process can read cert file: `chmod 644 /path/to/cert.crt`
3. **Docker volume**: When using Docker, ensure cert is mounted: `-v /path/to/cert.crt:/app/cert.crt:ro`

---

### Issue: High OTLP Export Latency

**Symptoms**:
- P95 export duration > 2 seconds
- Logs: `INFO: OTLP export succeeded (2.34s)`

**Diagnosis**:
```bash
# Check P95 latency
curl http://localhost:8000/metrics | grep loxone_otlp_export_duration_seconds_bucket

# Calculate P95 in Prometheus
histogram_quantile(0.95, rate(loxone_otlp_export_duration_seconds_bucket[5m]))
```

**Solutions**:
1. **Large metric batch**: Reduce `interval_seconds` to export smaller batches more frequently
2. **Network latency**: Move collector closer or use local collector
3. **Collector slow**: Scale collector or optimize its processing pipeline
4. **Increase timeout**: Set `timeout_seconds` slightly higher to accommodate latency

---

### Issue: Metrics Not Appearing in OTLP Collector

**Symptoms**:
- OTLP export succeeds (`loxone_otlp_export_status == 1`)
- But metrics not visible in collector's Prometheus endpoint

**Diagnosis**:
```bash
# Check collector logs
docker logs otel-collector | grep -i "received\|exported"

# Check collector Prometheus endpoint
curl http://localhost:9090/metrics | grep loxone

# Check exporter sent metrics
curl http://localhost:8000/metrics | grep loxone_otlp_exported_metrics_total
```

**Solutions**:
1. **Collector not exporting**: Verify collector config has `prometheus` exporter in pipeline
2. **Namespace mismatch**: Check collector's `prometheus.namespace` setting
3. **Metric filtering**: Verify collector's processor pipeline doesn't filter Loxone metrics
4. **Collector restart**: Restart collector: `docker-compose restart otel-collector`

---

### Issue: Configuration Validation Error

**Symptoms**:
- Exporter fails to start: `ERROR: Configuration validation failed`

**Diagnosis**:
```bash
# Check config syntax
cat config.yml

# Validate YAML syntax
python -c "import yaml; yaml.safe_load(open('config.yml'))"
```

**Common errors**:
1. **Missing endpoint**: Add `endpoint` when `enabled: true`
2. **Invalid URL**: Ensure endpoint starts with `http://` or `https://`
3. **Timeout >= interval**: Set `timeout_seconds < interval_seconds`
4. **Invalid protocol**: Use `grpc` or `http` (lowercase)

---

## Summary

This quickstart guide covered:
1. ✅ Development setup with local OTLP collector
2. ✅ Comprehensive testing (unit, integration, contract, performance)
3. ✅ Configuration examples for various deployment scenarios
4. ✅ Docker Compose deployment with full monitoring stack
5. ✅ Health monitoring via metrics and endpoints
6. ✅ Troubleshooting common issues

**Next steps**:
- Review `contracts/` for detailed API specifications
- See `data-model.md` for entity definitions
- Check `config-schema.md` for complete configuration reference
- Run `/speckit.tasks` to generate implementation task breakdown

**Support**:
- Report issues on GitHub
- Check logs: `docker logs loxone-exporter`
- Query metrics: `curl http://localhost:8000/metrics | grep otlp`
