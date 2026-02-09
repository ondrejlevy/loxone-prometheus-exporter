# Copilot Instructions — Loxone Prometheus Exporter

## Project Overview

Prometheus exporter for Loxone Miniserver control values. Connects to one or more Loxone Miniservers via WebSocket, auto-discovers all controls from `LoxAPP3.json`, subscribes to real-time binary value events, and exposes them as Prometheus gauge metrics on `GET /metrics`. Includes a `GET /healthz` JSON health endpoint.

- **Language**: Python 3.13 (strict typing, `from __future__ import annotations`)
- **Runtime**: Single `asyncio` event loop — all I/O is async
- **Package layout**: `src/loxone_exporter/` (setuptools with `src` layout)
- **Entry point**: `python -m loxone_exporter [--config config.yml]`
- **Container**: `python:3.13-slim` multi-stage Docker build, non-root user
- **License**: MIT

## Architecture

```
__main__.py          CLI parsing, asyncio.TaskGroup orchestration, signal handling
    │
config.py            YAML + env-var config loading, frozen dataclasses, validation
    │
server.py            aiohttp HTTP server → /metrics (Prometheus text), /healthz (JSON)
    │
metrics.py           Custom Prometheus collector (LoxoneCollector.collect())
    │                    reads MiniserverState in-memory — NO network calls
    │
loxone_client.py     WebSocket lifecycle per Miniserver: connect → auth → structure → subscribe → receive loop
    │                    exponential backoff reconnect (1s → 30s cap), keepalive every 30s
    ├── loxone_auth.py       Token-based (RSA+AES+HMAC, fw ≥ 9.x) + hash-based fallback (fw 8.x)
    ├── loxone_protocol.py   Binary header (8B) + VALUE_STATES (24B entries) + TEXT_STATES parser
    │
structure.py         LoxAPP3.json → Control, Room, Category, StateEntry dataclasses + state_map
    │
logging.py           JSON / text structured logging with credential redaction
```

### Key Data Flow

1. `LoxoneClient.run()` opens a WebSocket to `ws://<host>:<port>/ws/rfc6455`
2. Authenticates (token-based → hash-based fallback)
3. Downloads `LoxAPP3.json` → `parse_structure()` → populates `MiniserverState`
4. Sends `enablebinstatusupdate` → receives binary `VALUE_STATES` / `TEXT_STATES`
5. On `/metrics` scrape, `LoxoneCollector.collect()` reads `MiniserverState` (in-memory, no network)
6. Filtering (exclude rooms/types/names) happens in `collect()` via `fnmatch`

## Code Conventions

- **Typing**: All functions have full type annotations. `mypy --strict` must pass.
- **Imports**: Use `from __future__ import annotations` in every module. Use `TYPE_CHECKING` guard for import-only types.
- **Dataclasses**: Prefer `@dataclass(frozen=True)` for config/data objects. `MiniserverState` is mutable (updated by client).
- **Async**: All I/O uses `asyncio`. WebSocket via `websockets` library. HTTP via `aiohttp`.
- **Error handling**: Domain-specific exceptions (`ConfigError`, `AuthenticationError`, `LoxoneConnectionError`). Never silently swallow errors.
- **Logging**: Use `logging.getLogger(__name__)`. Credentials are auto-redacted by `logging.py` sanitizer.
- **Line length**: 100 chars (`ruff` enforced).
- **Naming**: PEP 8. Private functions prefixed with `_`. Constants in `UPPER_SNAKE_CASE`.

## Linting & Static Analysis

```bash
ruff check src/ tests/          # Lint (E, W, F, I, N, UP, B, S, SIM, TCH, RUF rules)
ruff format src/ tests/         # Format
mypy src/                       # Strict type checking (Python 3.13)
```

- Ruff rules are configured in `pyproject.toml` `[tool.ruff.lint]`
- Security rules (flake8-bandit `S`) enabled; `S101` (assert) suppressed in tests
- `S104` (bind to 0.0.0.0) suppressed in `config.py` (intentional default)

## Testing

- **Framework**: `pytest` + `pytest-asyncio` (auto mode) + `pytest-cov`
- **Coverage target**: ≥80% with branch coverage
- **Test structure**:
  - `tests/unit/` — Pure logic tests (config, protocol, structure, metrics, auth, logging)
  - `tests/integration/` — WebSocket client against `mock_miniserver.py`
  - `tests/contract/` — HTTP endpoint tests against OpenAPI contract
  - `tests/performance/` — Load tests
- **Shared fixtures**: `tests/conftest.py` provides `sample_loxapp3`, `sample_miniserver_state`, `sample_exporter_config`
- **Markers**: `@pytest.mark.integration`, `@pytest.mark.contract`
- **TDD**: Write tests first. Tests must fail before implementation.

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=loxone_exporter --cov-report=term-missing

# Skip integration tests
pytest -m "not integration"

# Run only unit tests
pytest tests/unit/
```

## Prometheus Metrics

### Control Metrics

| Metric | Type | Labels |
|---|---|---|
| `loxone_control_value` | gauge | `miniserver`, `name`, `room`, `category`, `type`, `subcontrol` |
| `loxone_control_info` | info | same (only when `include_text_values: true`) |

### Self-Health Metrics

| Metric | Type |
|---|---|
| `loxone_exporter_up` | gauge (always 1) |
| `loxone_exporter_connected` | gauge (per miniserver) |
| `loxone_exporter_last_update_timestamp_seconds` | gauge (per miniserver) |
| `loxone_exporter_controls_discovered` | gauge (per miniserver) |
| `loxone_exporter_controls_exported` | gauge (per miniserver) |
| `loxone_exporter_scrape_duration_seconds` | gauge |
| `loxone_exporter_scrape_errors_total` | counter |
| `loxone_exporter_build_info` | info |

## Configuration

- **YAML file**: `config.yml` / `config.yaml` (auto-detected) or `--config path`
- **Env vars**: `LOXONE_HOST`, `LOXONE_USERNAME`, `LOXONE_PASSWORD`, `LOXONE_PORT`, `LOXONE_NAME`, `LOXONE_LISTEN_PORT`, `LOXONE_LOG_LEVEL` — override first miniserver in YAML
- **Env-only mode**: No YAML needed if all required env vars are set
- **Validation**: `ConfigError` with descriptive message on any invalid config
- See `config.example.yml` and `specs/001-loxone-metrics-export/contracts/config-schema.md`

## Specification Documents

Detailed design documents live in `specs/001-loxone-metrics-export/`:

| File | Content |
|---|---|
| `spec.md` | Feature specification, user stories, acceptance criteria, edge cases |
| `plan.md` | Implementation plan, tech context, constitution checks |
| `tasks.md` | Task breakdown by user story (T001–T030+) |
| `research.md` | Loxone protocol research, auth flows, binary format details |
| `data-model.md` | Entity relationship diagram, all dataclass fields |
| `contracts/config-schema.md` | YAML config schema, env var mapping, validation rules |
| `contracts/internal-modules.md` | Module interfaces and behavioral contracts |
| `contracts/http-api.openapi.yaml` | OpenAPI 3.1 spec for `/metrics` and `/healthz` |

**Always consult these specs** when making changes to ensure consistency with the design.

## Dependencies

### Runtime
- `websockets~=16.0` — WebSocket client
- `prometheus_client~=0.24` — Prometheus metrics
- `aiohttp~=3.13` — HTTP server (same asyncio loop)
- `PyYAML~=6.0` — Config parsing
- `pycryptodome~=3.23` — Loxone auth crypto (RSA, AES, HMAC)

### Dev
- `pytest>=8.0`, `pytest-asyncio>=0.24`, `pytest-aiohttp>=1.0`, `pytest-cov>=6.0`
- `mypy>=1.13`, `ruff>=0.8`, `types-PyYAML>=6.0`

Pinned versions for reproducible Docker builds: `requirements.lock`

---

## Local Development

### Prerequisites

- **Python**: 3.13+ (managed via `pyenv`)
- **Container runtime**: Podman (used instead of Docker)
- **pyenv**: For managing Python versions
- **Git**: Version control

### Python Setup with pyenv

```bash
# Install Python 3.13 via pyenv (if not already installed)
pyenv install 3.13

# Set local Python version for this project
pyenv local 3.13

# Verify
python --version   # Should show Python 3.13.x

# Create virtual environment using pyenv's Python
python -m venv .venv
source .venv/bin/activate

# Install the project in editable mode with dev dependencies
pip install -e ".[dev]"
```

> **Note**: The `.python-version` file created by `pyenv local` is gitignored. Each developer sets their own pyenv version.

### Daily Development Workflow

```bash
# Activate the virtual environment
source .venv/bin/activate

# Run the exporter locally (requires config.yml with valid Miniserver credentials)
python -m loxone_exporter --config config.yml

# Run all tests
pytest

# Run tests with coverage
pytest --cov=loxone_exporter --cov-report=term-missing

# Type check
mypy src/

# Lint & format
ruff check src/ tests/
ruff format src/ tests/

# Full quality gate (run before committing)
pytest && mypy src/ && ruff check src/ tests/
```

### Container Development with Podman

This project uses **Podman** as the container runtime instead of Docker. Podman is a drop-in replacement — all `docker` commands work with `podman` and `docker compose` commands work with `podman compose`.

#### Building the Container Image

```bash
# Build with version metadata
podman build \
  --build-arg VERSION=$(git describe --tags --always) \
  --build-arg COMMIT=$(git rev-parse --short HEAD) \
  --build-arg BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
  -t loxone-exporter .

# Run the container standalone
podman run --rm -p 9504:9504 \
  -v ./config.yml:/app/config.yml:ro \
  loxone-exporter
```

#### Running the Full Stack with Podman Compose

```bash
# Copy and edit the config file
cp config.example.yml config.yml
# Edit config.yml with your Miniserver credentials

# Start all services (exporter + Prometheus + Grafana)
podman compose up -d

# View logs
podman compose logs -f exporter

# Stop all services
podman compose down

# Rebuild after code changes
podman compose up -d --build
```

#### Podman-Specific Notes

- **Rootless mode**: Podman runs rootless by default. The Dockerfile uses UID/GID 1000 (`exporter` user), which works seamlessly.
- **Compose**: Use `podman compose` (comes with podman-compose plugin or podman v4+). Alternatively install `podman-compose` via pip.
- **Volumes**: Bind mounts in `docker-compose.yml` work identically with Podman.
- **Networking**: Podman compose creates a shared network for services. Inter-container DNS (e.g., `exporter:9504` in Prometheus config) works out of the box.
- **Healthcheck**: The `HEALTHCHECK` directive in the Dockerfile is supported by Podman.
- **If using Docker aliases**: You can also alias `docker` to `podman` in your shell:
  ```bash
  alias docker=podman
  alias docker-compose="podman compose"
  ```

### Environment Variables for Local Development

For local testing without a config file, set env vars:

```bash
export LOXONE_HOST=192.168.1.100
export LOXONE_USERNAME=prometheus
export LOXONE_PASSWORD=your-password
export LOXONE_LOG_LEVEL=debug
export LOXONE_LOG_FORMAT=text    # Human-readable for local dev

python -m loxone_exporter
```

### Endpoints (Local)

| URL | Description |
|---|---|
| `http://localhost:9504/metrics` | Prometheus metrics |
| `http://localhost:9504/healthz` | Health status JSON |
| `http://localhost:9090` | Prometheus UI (via compose) |
| `http://localhost:3000` | Grafana UI (via compose, admin/changeme) |

---

## Important Patterns for Copilot

### Mandatory: Ruff Lint & Format After Every Change

**After every code change you make**, you MUST run ruff to check and fix lint/format issues before considering the task complete:

```bash
ruff check --fix src/ tests/
ruff format src/ tests/
ruff check src/ tests/   # Final verification — must show "All checks passed!"
```

If `ruff check` reports any remaining errors after `--fix`, you MUST resolve them manually before committing or finishing the task. **Never leave ruff violations in the codebase.** This is a hard gate — treat any ruff failure as a blocking error.

### When Adding a New Module
1. Add type annotations to all functions
2. Use `from __future__ import annotations` at the top
3. Add module docstring explaining purpose
4. Use `TYPE_CHECKING` guard for import-only types
5. Write tests first in appropriate `tests/` subdirectory
6. Update `specs/001-loxone-metrics-export/contracts/internal-modules.md` if it affects module interfaces

### When Modifying Metrics
1. Follow Prometheus naming: `loxone_<subsystem>_<metric>_<unit>`
2. Keep label cardinality bounded (labels come from Miniserver config, not unbounded input)
3. Every metric must have `# HELP` and `# TYPE` annotations
4. Update `data-model.md` and `http-api.openapi.yaml` if adding new metric families

### When Modifying Configuration
1. Update `ExporterConfig` / `MiniserverConfig` dataclasses in `config.py`
2. Update validation in `_validate_config()`
3. Update `config.example.yml` with annotated example
4. Update `contracts/config-schema.md`
5. Add/update tests in `tests/unit/test_config.py`

### When Modifying Protocol Handling
1. Refer to `specs/001-loxone-metrics-export/research.md` for Loxone binary protocol details
2. Binary format: 8-byte header + payload. UUID bytes are little-endian.
3. VALUE_STATES: 24-byte entries (16B UUID + 8B double)
4. TEXT_STATES: Variable-length (16B UUID + 16B icon UUID + 4B length + text + padding)

### When Working with Secrets / Credentials
1. Never log credentials — `logging.py` has auto-redaction patterns
2. Passwords come from config YAML or `LOXONE_PASSWORD` env var
3. The `config.yml` file is gitignored; only `config.example.yml` is committed
4. Auth uses `pycryptodome` for RSA/AES; import from `Crypto.*`

### When Modifying Docker / Podman Setup
1. Base image: `python:3.13-slim` with pinned digest
2. Multi-stage build: builder installs deps → final image copies site-packages
3. Non-root user (`exporter`, UID 1000)
4. Healthcheck: `python -c "urllib.request.urlopen('http://localhost:9504/healthz')"` (no curl in slim)
5. Dependencies locked in `requirements.lock` for reproducible builds
6. Use `podman` commands in documentation and scripts (not `docker`)
