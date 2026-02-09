# Config Schema: OTLP Section

**Feature**: 002-opentelemetry-support  
**Date**: 2026-02-09

This document defines the YAML configuration schema for OpenTelemetry export functionality.

---

## YAML Structure

### Complete Example

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
      Authorization: "Bearer token123"
      X-API-Key: "secret-key"
```

### Minimal Example (Disabled)

```yaml
opentelemetry:
  enabled: false
```

### Minimal Example (Enabled with defaults)

```yaml
opentelemetry:
  enabled: true
  endpoint: "http://otel-collector:4317"
```

---

## Field Specifications

### `opentelemetry.enabled`

- **Type**: boolean
- **Required**: No
- **Default**: `false`
- **Description**: Master switch for OTLP export feature. When `false`, no OTLP connections are attempted and all OTLP-related resources are skipped.

**Valid values**: `true`, `false`

**Examples**:
```yaml
enabled: true   # Enable OTLP export
enabled: false  # Disable (Prometheus-only mode)
```

---

### `opentelemetry.endpoint`

- **Type**: string (URL)
- **Required**: Yes, if `enabled=true`
- **Default**: None
- **Description**: OTLP collector endpoint URL. Must include scheme (`http://` or `https://`) and may include port.

**Valid values**: 
- `http://hostname:port` (unencrypted)
- `https://hostname:port` (TLS, requires `tls.enabled=true`)

**Port defaults** (standard OTLP ports):
- gRPC: 4317
- HTTP: 4318

**Examples**:
```yaml
endpoint: "http://localhost:4317"                    # Local gRPC
endpoint: "https://otlp.example.com:4318"            # Remote HTTP with TLS
endpoint: "http://192.168.1.100:4317"                # IP address
endpoint: "http://otel-collector.service.local:4317" # DNS name
```

**Invalid examples**:
```yaml
endpoint: "localhost:4317"         # Missing scheme (ERROR)
endpoint: "ftp://localhost:4317"   # Invalid scheme (ERROR)
endpoint: "http://host:99999"      # Invalid port (ERROR)
```

---

### `opentelemetry.protocol`

- **Type**: string (enum)
- **Required**: No
- **Default**: `grpc`
- **Description**: OTLP wire protocol. Choose based on collector configuration and network constraints.

**Valid values**: `grpc`, `http`

**Protocol comparison**:
- **gRPC**: Better performance, native OTLP protocol, requires gRPC-compatible infrastructure
- **HTTP**: More firewall-friendly, easier debugging (plain HTTP), slightly higher overhead

**Examples**:
```yaml
protocol: grpc  # Use gRPC protocol (port 4317 typically)
protocol: http  # Use HTTP protocol (port 4318 typically)
```

**Invalid examples**:
```yaml
protocol: TCP   # Not supported (ERROR)
protocol: GRPC  # Case-sensitive, must be lowercase (ERROR)
```

---

### `opentelemetry.interval_seconds`

- **Type**: integer
- **Required**: No
- **Default**: `30`
- **Constraints**: 10 ≤ value ≤ 300
- **Description**: How often (in seconds) to push metrics to the OTLP collector. Shorter intervals increase network traffic and collector load; longer intervals reduce freshness.

**Recommended values**:
- **10-15s**: High-frequency monitoring (aligns with Prometheus scrape)
- **30s**: Balanced (default)
- **60s**: Lower traffic, acceptable for most use cases
- **120-300s**: Low-frequency, batch-oriented export

**Examples**:
```yaml
interval_seconds: 15   # Export every 15 seconds
interval_seconds: 60   # Export every minute
```

**Invalid examples**:
```yaml
interval_seconds: 5     # Too short (ERROR: minimum 10)
interval_seconds: 500   # Too long (ERROR: maximum 300)
interval_seconds: "30"  # Must be integer, not string (ERROR)
```

---

### `opentelemetry.timeout_seconds`

- **Type**: integer
- **Required**: No
- **Default**: `15`
- **Constraints**: 5 ≤ value ≤ 60, must be < `interval_seconds`
- **Description**: Maximum time (in seconds) to wait for OTLP collector to respond before marking export as failed. Prevents hanging exports.

**Recommended values**:
- **10-15s**: Standard timeout for local collectors
- **30s**: Remote collectors or slower networks
- **≤ interval_seconds / 2**: Ensures export completes before next cycle

**Examples**:
```yaml
timeout_seconds: 10    # 10-second timeout
timeout_seconds: 30    # Longer timeout for remote collector
```

**Invalid examples**:
```yaml
timeout_seconds: 2      # Too short (ERROR: minimum 5)
timeout_seconds: 70     # Too long (ERROR: maximum 60)
timeout_seconds: 45     # ERROR if interval_seconds=30 (timeout must be < interval)
```

---

### `opentelemetry.tls.enabled`

- **Type**: boolean
- **Required**: No
- **Default**: `false`
- **Description**: Enable TLS/SSL encryption for OTLP connection. Required for HTTPS endpoints.

**Examples**:
```yaml
tls:
  enabled: true   # Use TLS
```

---

### `opentelemetry.tls.cert_path`

- **Type**: string (file path) or null
- **Required**: Yes, if `tls.enabled=true`
- **Default**: `null`
- **Description**: Absolute path to TLS CA certificate file for verifying collector's certificate. File must exist and be readable.

**Supported formats**: PEM-encoded X.509 certificates (`.crt`, `.pem`)

**Examples**:
```yaml
tls:
  enabled: true
  cert_path: /etc/ssl/certs/ca-certificates.crt  # Debian/Ubuntu system bundle
```

```yaml
tls:
  enabled: true
  cert_path: /app/certs/otlp-ca.crt              # Custom CA
```

**Invalid examples**:
```yaml
tls:
  enabled: true
  cert_path: /nonexistent.crt  # File doesn't exist (ERROR at startup)
```

---

### `opentelemetry.auth.headers`

- **Type**: dictionary (string keys/values) or null
- **Required**: No
- **Default**: `null`
- **Description**: HTTP headers for authentication. Commonly used for Bearer tokens, API keys, or custom authentication schemes.

**Common header names**:
- `Authorization`: Bearer tokens, Basic auth
- `X-API-Key`: API key-based authentication
- `X-Auth-Token`: Custom token headers

**Examples**:

Bearer token:
```yaml
auth:
  headers:
    Authorization: "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0..."
```

API key:
```yaml
auth:
  headers:
    X-API-Key: "secret-api-key-12345"
```

Multiple headers:
```yaml
auth:
  headers:
    Authorization: "Bearer token"
    X-Tenant-ID: "production"
    X-Trace-Context: "app=loxone-exporter"
```

No authentication (default):
```yaml
auth:
  headers: null
```

Or omit entirely:
```yaml
# auth section not specified (same as null)
```

---

## Environment Variable Overrides

All YAML configuration fields can be overridden via environment variables. Useful for containerized deployments (Docker, Kubernetes).

### Variable Naming Convention

`LOXONE_OTLP_<SECTION>_<FIELD>`

All uppercase, underscores separate levels.

### Supported Variables

| Environment Variable | Overrides | Type | Example |
|---------------------|-----------|------|---------|
| `LOXONE_OTLP_ENABLED` | `enabled` | bool | `true`, `false` |
| `LOXONE_OTLP_ENDPOINT` | `endpoint` | string | `http://otel:4317` |
| `LOXONE_OTLP_PROTOCOL` | `protocol` | string | `grpc`, `http` |
| `LOXONE_OTLP_INTERVAL` | `interval_seconds` | int | `60` |
| `LOXONE_OTLP_TIMEOUT` | `timeout_seconds` | int | `30` |
| `LOXONE_OTLP_TLS_ENABLED` | `tls.enabled` | bool | `true` |
| `LOXONE_OTLP_TLS_CERT_PATH` | `tls.cert_path` | string | `/etc/ssl/certs/ca.crt` |
| `LOXONE_OTLP_AUTH_HEADER_<NAME>` | `auth.headers[name]` | string | (see below) |

### Auth Header Environment Variables

Pattern: `LOXONE_OTLP_AUTH_HEADER_<HEADERNAME>=<value>`

The `<HEADERNAME>` portion is converted to the HTTP header name (preserving case).

**Examples**:

```bash
# Sets header: Authorization: Bearer xyz
export LOXONE_OTLP_AUTH_HEADER_AUTHORIZATION="Bearer xyz"

# Sets header: X-API-Key: secret123
export LOXONE_OTLP_AUTH_HEADER_X_API_KEY="secret123"

# Multiple headers:
export LOXONE_OTLP_AUTH_HEADER_AUTHORIZATION="Bearer token"
export LOXONE_OTLP_AUTH_HEADER_X_TENANT_ID="prod"
```

### Precedence

Environment variables take precedence over YAML configuration.

```yaml
# config.yml
opentelemetry:
  endpoint: "http://localhost:4317"
```

```bash
# Environment variable overrides YAML
export LOXONE_OTLP_ENDPOINT="http://prod-collector:4317"
```

**Result**: Exporter uses `http://prod-collector:4317`

---

## Configuration Examples

### Example 1: Local Development (gRPC, no auth)

```yaml
opentelemetry:
  enabled: true
  endpoint: "http://localhost:4317"
  protocol: grpc
  interval_seconds: 15
```

**Use case**: Testing against local OpenTelemetry Collector

---

### Example 2: Production (HTTP with TLS and Bearer token)

```yaml
opentelemetry:
  enabled: true
  endpoint: "https://otlp-collector.prod.example.com:4318"
  protocol: http
  interval_seconds: 60
  timeout_seconds: 30
  tls:
    enabled: true
    cert_path: /etc/ssl/certs/ca-bundle.crt
  auth:
    headers:
      Authorization: "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**Use case**: Secure production deployment with TLS and JWT authentication

---

### Example 3: Cloud Vendor (API Key auth)

```yaml
opentelemetry:
  enabled: true
  endpoint: "https://otlp.vendor.cloud:443"
  protocol: http
  interval_seconds: 30
  tls:
    enabled: true
    cert_path: /etc/ssl/certs/ca-certificates.crt
  auth:
    headers:
      X-API-Key: "vendor-api-key-abcd1234"
```

**Use case**: Exporting to cloud OTLP endpoint (e.g., Datadog, New Relic, Grafana Cloud)

---

### Example 4: Disabled (Prometheus-only)

```yaml
opentelemetry:
  enabled: false
```

**Use case**: OTLP feature explicitly disabled, metrics only via Prometheus `/metrics` endpoint

---

## Validation Error Messages

When configuration is invalid, the exporter fails to start with descriptive error messages:

### Example Validation Errors

**Missing endpoint**:
```
ERROR: Configuration validation failed:
  - opentelemetry.endpoint: Field 'endpoint' is required when OTLP export is enabled

Exporter will not start. Please add 'opentelemetry.endpoint' to config.yml and restart.
```

**Invalid protocol**:
```
ERROR: Configuration validation failed:
  - opentelemetry.protocol: Field 'protocol' must be 'grpc' or 'http' (got: 'tcp')

Exporter will not start. Please fix config.yml and restart.
```

**Timeout >= interval**:
```
ERROR: Configuration validation failed:
  - opentelemetry.timeout_seconds: Field must be less than interval_seconds (timeout=45, interval=30)

Exporter will not start. Please reduce timeout_seconds or increase interval_seconds in config.yml.
```

**TLS cert not found**:
```
ERROR: Configuration validation failed:
  - opentelemetry.tls.cert_path: TLS certificate file not found or not readable: /nonexistent.crt

Exporter will not start. Please provide valid cert path or disable TLS.
```

---

## Integration with Existing Config

The `opentelemetry` section is added to the existing `config.yml` structure alongside existing Loxone configuration:

```yaml
# Existing Loxone configuration
miniservers:
  - name: living
    host: 192.168.1.100
    username: admin
    password: secret

# Prometheus exporter settings
exporter:
  port: 8000
  log_level: info

# NEW: OpenTelemetry configuration
opentelemetry:
  enabled: true
  endpoint: "http://otel-collector:4317"
```

---

## Summary

- **Top-level key**: `opentelemetry`
- **8 configuration fields**: enabled, endpoint, protocol, interval_seconds, timeout_seconds, tls.{enabled, cert_path}, auth.headers
- **Environment variable overrides**: All fields can be set via `LOXONE_OTLP_*` env vars
- **Validation**: Fail-fast on startup with descriptive errors
- **Default behavior**: Disabled (no impact on existing Prometheus-only users)

See `data-model.md` for validation rule details and `quickstart.md` for complete deployment examples.
