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
    port: 80                    # WebSocket port (default: 80)
    username: admin
    password: secret

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
                                  └──────────────┘
```

Single asyncio event loop running:
- **LoxoneClient** per Miniserver (WebSocket → authenticate → subscribe → receive loop)
- **aiohttp** HTTP server (custom Prometheus collector reads in-memory state)

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
