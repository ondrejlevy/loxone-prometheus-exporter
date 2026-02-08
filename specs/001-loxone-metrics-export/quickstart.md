# Quickstart Guide: Loxone Prometheus Exporter

## Prerequisites

- Python 3.13+
- Docker or Podman (for containerized deployment)
- docker-compose / podman-compose (for orchestrated deployment)
- A Loxone Miniserver on the local network
- A Loxone user account with read permissions

## Development Setup

### 1. Clone and enter the repository

```bash
git clone <repo-url>
cd loxone-prometheus-exporter
```

### 2. Create a virtual environment

```bash
python3.13 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -e ".[dev]"
```

This installs the package in editable mode with development dependencies (pytest, pytest-asyncio, mypy, ruff, coverage).

### 4. Create a config file

```bash
cp config.example.yml config.yml
```

Edit `config.yml` with your Miniserver details:

```yaml
miniservers:
  - name: "home"
    host: "192.168.1.100"
    username: "prometheus"
    password: "your-password"

listen_port: 9504
log_level: "debug"
log_format: "text"
```

Or use environment variables for a minimal setup:

```bash
export LOXONE_HOST=192.168.1.100
export LOXONE_USERNAME=prometheus
export LOXONE_PASSWORD=your-password
```

### 5. Run the exporter

```bash
python -m loxone_exporter
```

Or with explicit config path:

```bash
python -m loxone_exporter --config config.yml
```

### 6. Verify it works

```bash
# Check health
curl http://localhost:9504/healthz

# Scrape metrics
curl http://localhost:9504/metrics
```

## Running Tests

### Unit tests (no Miniserver needed)

```bash
pytest tests/unit/ -v
```

### All tests with coverage

```bash
pytest --cov=loxone_exporter --cov-report=term-missing
```

### Type checking

```bash
mypy src/loxone_exporter/
```

### Linting

```bash
ruff check src/ tests/
ruff format --check src/ tests/
```

### Full CI check (all of the above)

```bash
pytest --cov=loxone_exporter --cov-report=term-missing && \
mypy src/loxone_exporter/ && \
ruff check src/ tests/ && \
ruff format --check src/ tests/
```

## Docker Deployment

### Build the image

```bash
docker build -t loxone-prometheus-exporter:latest .
```

### Run with docker-compose

```bash
# Copy and edit config
cp config.example.yml config.yml

# Start all services (exporter + Prometheus + Grafana)
docker compose up -d

# Check logs
docker compose logs -f exporter
```

### docker-compose.yml structure

```yaml
services:
  exporter:
    build: .
    ports:
      - "9504:9504"
    volumes:
      - ./config.yml:/app/config.yml:ro
    environment:
      - LOXONE_USERNAME=prometheus
      - LOXONE_PASSWORD=secret
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9504/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3

  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    restart: unless-stopped

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    volumes:
      - grafana-data:/var/lib/grafana
    restart: unless-stopped

volumes:
  prometheus-data:
  grafana-data:
```

### prometheus.yml

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: "loxone"
    static_configs:
      - targets: ["exporter:9504"]
```

## Project Structure

```
loxone-prometheus-exporter/
├── src/loxone_exporter/
│   ├── __init__.py          # Package version
│   ├── __main__.py          # Entry point, argument parsing, asyncio.run()
│   ├── config.py            # YAML + env var config loading & validation
│   ├── loxone_client.py     # WebSocket connection lifecycle & reconnect
│   ├── loxone_auth.py       # Token-based + hash-based authentication
│   ├── loxone_protocol.py   # Binary message header & payload parsing
│   ├── structure.py         # LoxAPP3.json → Controls, Rooms, Categories
│   ├── metrics.py           # Prometheus CustomCollector implementation
│   ├── server.py            # aiohttp HTTP server (/metrics, /healthz)
│   └── logging.py           # Structured logging setup (JSON/text)
├── tests/
│   ├── unit/                # Pure unit tests, no network
│   ├── integration/         # Tests against mock WebSocket server
│   └── conftest.py          # Shared fixtures
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── config.example.yml
├── prometheus.yml
└── README.md
```

## Common Tasks

| Task | Command |
|------|---------|
| Run exporter | `python -m loxone_exporter` |
| Run tests | `pytest` |
| Run with coverage | `pytest --cov=loxone_exporter` |
| Type check | `mypy src/loxone_exporter/` |
| Lint | `ruff check src/ tests/` |
| Format | `ruff format src/ tests/` |
| Build Docker image | `docker build -t loxone-prometheus-exporter .` |
| Start with compose | `docker compose up -d` |
| View logs | `docker compose logs -f exporter` |
| Stop all | `docker compose down` |
