# Loxone Prometheus Exporter

Export [Loxone Miniserver](https://www.loxone.com/) control values as [Prometheus](https://prometheus.io/) gauge metrics in real time.

## Features

- **Auto-discovery** — Connects via WebSocket, downloads LoxAPP3.json, and exports all controls automatically.
- **Real-time updates** — Binary WebSocket protocol delivers value changes within 2 seconds (typically < 500 ms).
- **Multi-Miniserver** — Monitor multiple Miniservers from a single exporter instance.
- **Filtering** — Exclude controls by room, type, or name glob pattern. Opt-in for text-only controls.
- **Resilient** — Exponential backoff reconnection (1 s → 30 s cap), keepalive, structure re-discovery on reconnect.
- **Prometheus-compliant** — All metrics follow naming conventions with `HELP` / `TYPE` annotations, bounded label cardinality.
- **Self-health metrics** — `loxone_exporter_connected`, `last_update_timestamp_seconds`, `scrape_duration_seconds`, `build_info`, etc.
- **OpenTelemetry OTLP export** — Push metrics to any OTLP-compatible collector (Grafana Alloy, OpenTelemetry Collector, Datadog, etc.) via gRPC or HTTP.
- **Docker-ready** — Multi-stage build, non-root user, healthcheck included.

## Quickstart

### Docker Compose (recommended)

```bash
cp config.example.yml config.yml
# Edit config.yml with your Miniserver credentials
docker compose up -d
```

Prometheus scrapes from `http://exporter:9504/metrics`.

### Local Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest

# Type check & lint
mypy src/
ruff check src/ tests/

# Start the exporter
python -m loxone_exporter --config config.yml
```

## Configuration

### YAML File

```yaml
miniservers:
  - name: home                  # Display name (used in labels)
    host: 192.168.1.100         # Miniserver IP or hostname
    port: 80                    # WebSocket port for unencrypted connections (default: 80)
    ssl_port: 443               # WebSocket port for encrypted connections (default: 443)
    username: admin
    password: secret
    use_encryption: false       # Use wss:// instead of ws:// (default: false)
    force_encryption: false     # Require encryption, fail if not used (default: false)
                                # Note: Miniserver 2 (Gen2) auto-enables encryption on ssl_port

listen_port: 9504               # HTTP server port (default: 9504)
listen_address: "0.0.0.0"      # Bind address (default: 0.0.0.0)
log_level: info                 # debug | info | warning | error
log_format: json                # json | text

# Filtering (optional)
exclude_rooms:
  - "Test Room"
exclude_types:
  - "Pushbutton"
exclude_names:
  - "Debug *"
include_text_values: false      # Export text controls as info metrics
```

### Encryption Options

The exporter supports encrypted WebSocket connections (`wss://`) for secure communication with your Miniserver:

- **`use_encryption`**: Manually enable encrypted connections. Set to `true` to use `wss://` instead of `ws://`.
- **`ssl_port`**: Port to use for encrypted connections (default: 443). This can be customized if your Miniserver uses a non-standard SSL port.
- **`force_encryption`**: When enabled, the connection will fail if encryption is not being used. Useful for enforcing security policies.
- **Auto-detection**: When connecting to a Miniserver 2 (Gen2), the exporter automatically switches to encrypted connections on `ssl_port` after detecting the Miniserver type from the structure file.

**Important**: 
- Encrypted connections use self-signed certificates on the Miniserver. The exporter automatically accepts these certificates for local network communication.
- HTTP API requests (for authentication) always use the `port` value, regardless of encryption settings.

### Environment Variables

Environment variables override the **first** Miniserver in the YAML file, or work standalone (no file needed):

| Variable | Description | Default |
|---|---|---|
| `LOXONE_HOST` | Miniserver host | *(required)* |
| `LOXONE_PORT` | WebSocket port | `80` |
| `LOXONE_USERNAME` | Username | *(required)* |
| `LOXONE_PASSWORD` | Password | *(required)* |
| `LOXONE_NAME` | Display name | value of `LOXONE_HOST` |
| `LOXONE_LISTEN_PORT` | HTTP listen port | `9504` |
| `LOXONE_LOG_LEVEL` | Log level | `info` |

### OpenTelemetry OTLP Export (Optional)

Add an `opentelemetry` section to push metrics to an OTLP collector in parallel with Prometheus scraping:

```yaml
opentelemetry:
  enabled: true
  endpoint: "http://otel-collector:4317"   # gRPC endpoint
  protocol: grpc                            # grpc | http
  interval_seconds: 30                      # Export interval (10-300)
  timeout_seconds: 15                       # Export timeout (5-60, must be < interval)
  # tls:
  #   enabled: true
  #   cert_path: /path/to/ca.crt
  # auth:
  #   headers:
  #     Authorization: "Bearer <token>"
```

#### OTLP Environment Variables

| Variable | Description | Default |
|---|---|---|
| `LOXONE_OTLP_ENABLED` | Enable OTLP export | `false` |
| `LOXONE_OTLP_ENDPOINT` | Collector endpoint URL | — |
| `LOXONE_OTLP_PROTOCOL` | `grpc` or `http` | `grpc` |
| `LOXONE_OTLP_INTERVAL` | Export interval (seconds) | `30` |
| `LOXONE_OTLP_TIMEOUT` | Export timeout (seconds) | `15` |
| `LOXONE_OTLP_TLS_ENABLED` | Enable TLS | `false` |
| `LOXONE_OTLP_TLS_CERT_PATH` | CA certificate path | — |
| `LOXONE_OTLP_AUTH_HEADER_*` | Auth headers (e.g. `LOXONE_OTLP_AUTH_HEADER_AUTHORIZATION`) | — |

### Direct Export to Grafana Cloud

You can send metrics directly to Grafana Cloud OTLP endpoint without deploying a separate collector. This "quickstart architecture" is suitable for development, testing, or production use when you don't need advanced features like sampling, data enrichment, or routing to multiple backends.

#### 1. Get Grafana Cloud OTLP Credentials

1. Sign in to [Grafana Cloud Portal](https://grafana.com/auth/sign-in/)
2. Select your stack from the Organization Overview
3. Click **Configure** on the OpenTelemetry tile
4. Generate an authentication token and note the following values:
   - **OTLP Endpoint** (e.g., `https://otlp-gateway-prod-eu-west-0.grafana.net/otlp`)
   - **Instance ID** (e.g., `123456`)
   - **API Token** (base64-encoded credentials for Basic auth)

#### 2. Configure the Exporter

Add the following to your `config.yml`:

```yaml
opentelemetry:
  enabled: true
  endpoint: "https://otlp-gateway-prod-eu-west-0.grafana.net/otlp"  # Your Grafana Cloud OTLP endpoint
  protocol: http                                                      # Grafana Cloud uses HTTP/protobuf
  interval_seconds: 60                                                # Export every 60 seconds
  timeout_seconds: 30
  auth:
    headers:
      Authorization: "Basic%20<your-base64-encoded-token>"            # Note: Use %20 for Python compatibility
```

**Important Notes:**

- **Protocol**: Use `http` (not `grpc`) for Grafana Cloud OTLP endpoints
- **Authorization Header**: Python requires URL-encoded space — use `Basic%20` instead of `Basic ` (space after "Basic")
- **Endpoint**: Do **not** append `/v1/metrics` — the exporter handles this automatically
- **TLS**: HTTPS endpoints work automatically; no additional TLS configuration needed
- **Resource Attributes**: The exporter automatically sets `service.name=loxone-prometheus-exporter` and `service.version=<version>` for identification in Grafana Cloud

#### 3. Alternative: Environment Variables

```bash
export LOXONE_OTLP_ENABLED=true
export LOXONE_OTLP_ENDPOINT="https://otlp-gateway-prod-eu-west-0.grafana.net/otlp"
export LOXONE_OTLP_PROTOCOL=http
export LOXONE_OTLP_INTERVAL=60
export LOXONE_OTLP_TIMEOUT=30
export LOXONE_OTLP_AUTH_HEADER_AUTHORIZATION="Basic%20<your-base64-encoded-token>"

python -m loxone_exporter --config config.yml
```

#### 4. Verify in Grafana Cloud

1. Navigate to your Grafana Cloud stack
2. Go to **Explore** → **Metrics**
3. Search for metrics starting with `loxone_` (e.g., `loxone_control_value`, `loxone_exporter_connected`)
4. Alternatively, use **Application Observability** if enabled to see automatic dashboards

#### Troubleshooting

- **401 Unauthorized**: Check that your Authorization header is correctly formatted with `Basic%20` (not `Basic `)
- **Connection timeout**: Verify the endpoint URL matches your region (e.g., `eu-west-0`, `us-central-0`)
- **No metrics visible**: Wait 1-2 minutes after first export, then check the OTLP health metrics in `/metrics`:
  ```
  loxone_otlp_export_status 1.0           # 1=idle (success), 4=failed
  loxone_otlp_consecutive_failures 0.0    # Should be 0
  ```

## Metrics Reference

### Control Metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `loxone_control_value` | gauge | `miniserver`, `name`, `room`, `category`, `type`, `subcontrol` | Current numeric value of a control state |
| `loxone_control_info` | info | *(same)* | Text value (only when `include_text_values: true`) |

### Self-Health Metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `loxone_exporter_up` | gauge | — | Always `1` if the process is running |
| `loxone_exporter_connected` | gauge | `miniserver` | `1` if WebSocket is connected |
| `loxone_exporter_last_update_timestamp_seconds` | gauge | `miniserver` | Unix timestamp of last value event |
| `loxone_exporter_controls_discovered` | gauge | `miniserver` | Controls found in structure file |
| `loxone_exporter_controls_exported` | gauge | `miniserver` | Controls exported after filtering |
| `loxone_exporter_scrape_duration_seconds` | gauge | — | Time to generate `/metrics` response |
| `loxone_exporter_scrape_errors_total` | counter | — | Errors during metric generation |
| `loxone_exporter_build_info` | info | `version`, `commit`, `build_date` | Build metadata |

### OTLP Health Metrics

Available when `opentelemetry.enabled: true`:

| Metric | Type | Description |
|---|---|---|
| `loxone_otlp_export_status` | gauge | Export state (0=disabled, 1=idle, 2=exporting, 3=retrying, 4=failed) |
| `loxone_otlp_last_success_timestamp_seconds` | gauge | Unix timestamp of last successful export |
| `loxone_otlp_consecutive_failures` | gauge | Number of consecutive export failures |
| `loxone_otlp_export_duration_seconds` | histogram | Export operation duration |
| `loxone_otlp_exported_metrics_total` | counter | Total metric families exported |

### Endpoints

| Path | Description |
|---|---|
| `GET /metrics` | Prometheus text exposition format |
| `GET /healthz` | JSON health status (`healthy` / `degraded` / `unhealthy`) |

## Architecture

```
┌─────────────┐     WebSocket     ┌──────────────┐
│   Loxone    │◄────────────────►│   Exporter   │
│  Miniserver │  binary protocol  │              │
└─────────────┘                   │  ┌────────┐  │    HTTP GET
                                  │  │Collector│──┼──► /metrics
                                  │  └────────┘  │
                                  │  ┌────────┐  │    HTTP GET
                                  │  │ Health │──┼──► /healthz
                                  │  └────────┘  │
                                  │  ┌────────┐  │    gRPC/HTTP
                                  │  │  OTLP  │──┼──► OTLP Collector
                                  │  │Exporter│  │    (optional)
                                  │  └────────┘  │
                                  └──────────────┘
```

Single asyncio event loop running:
- **LoxoneClient** per Miniserver (WebSocket → authenticate → subscribe → receive loop)
- **aiohttp** HTTP server (custom Prometheus collector reads in-memory state)
- **OTLPExporter** (optional) — periodically pushes metrics to OTLP collector with backoff retry

## Docker Build

```bash
docker build \
  --build-arg VERSION=$(git describe --tags --always) \
  --build-arg COMMIT=$(git rev-parse --short HEAD) \
  --build-arg BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
  -t loxone-exporter .
```

## Contributing

1. Fork and clone
2. `pip install -e ".[dev]"`
3. Write tests first (TDD)
4. `pytest && mypy src/ && ruff check src/ tests/`
5. Open a PR

## License

MIT
