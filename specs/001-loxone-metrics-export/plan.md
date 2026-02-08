# Implementation Plan: Loxone Miniserver Metrics Export to Prometheus

**Branch**: `001-loxone-metrics-export` | **Date**: 2026-02-07 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-loxone-metrics-export/spec.md`

## Summary

Build a Python-based Prometheus exporter that auto-discovers all controls on one or more Loxone Miniservers via WebSocket + structure file (`LoxAPP3.json`), subscribes to real-time value events, and exposes them as properly named and labeled Prometheus gauge metrics on a `/metrics` HTTP endpoint. Deployed as a Docker container image with docker-compose, supporting YAML config with env var overrides, exclusion filtering, and exporter self-health metrics.

## Technical Context

**Language/Version**: Python 3.13 (`python:3.13-slim` Docker base)  
**Primary Dependencies**: `websockets` 16.x (WS client), `prometheus_client` 0.24.x (metrics), `aiohttp` 3.13.x (HTTP server), `PyYAML` 6.x (config), `pycryptodome` 3.x (Loxone auth crypto)  
**Storage**: N/A (in-memory state only)  
**Testing**: pytest + pytest-asyncio + pytest-cov  
**Target Platform**: Linux container (Docker/Podman, docker-compose orchestration)  
**Project Type**: single  
**Performance Goals**: ≤50MB memory, ≤5% CPU (single core), ≤2s value freshness, handle 500+ controls  
**Constraints**: No external network calls, no cloud deps, single container, YAML config + env var overrides  
**Scale/Scope**: 1–N Miniservers, 50–500+ controls each, 15s–60s Prometheus scrape interval

## Constitution Check (Pre-Research)

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Local-First Architecture (NON-NEGOTIABLE) | ✅ PASS | Connects only to local Miniserver(s). No cloud/external calls (FR-015). Config via local YAML + env vars. |
| II. Self-Contained Solution (NON-NEGOTIABLE) | ✅ PASS | Single container image. No databases, queues, or service meshes. Python + minimal deps. |
| III. Observable Metrics Export | ✅ PASS | Core feature. Prometheus naming conventions, HELP/TYPE annotations, self-health metrics (FR-003, FR-004, FR-008). |
| IV. Test-First Development | ✅ PASS | pytest + pytest-asyncio. Unit tests for metric mapping, integration tests with mock Miniserver, contract tests for `/metrics` endpoint. Target ≥80% coverage. |
| V. Simplicity & Maintainability | ✅ PASS | Clear separation: loxone client → metrics mapper → HTTP server. YAGNI applies. Structured JSON logging. |
| Deployment Constraints | ✅ PASS | Docker/Podman container, ≤50MB memory, ≤5% CPU, health endpoint, SIGTERM handling, structured logging. |

**Gate result: PASS** — No violations. Proceed to Phase 0.

## Constitution Check (Post-Design)

*Re-evaluated after Phase 1 design artifacts (data-model.md, contracts/, quickstart.md).*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Local-First Architecture (NON-NEGOTIABLE) | ✅ PASS | Data model is entirely in-memory (MiniserverState). No external storage. Config schema uses local YAML + env vars only. HTTP endpoints serve locally. docker-compose stack is self-hosted (exporter + Prometheus + Grafana). |
| II. Self-Contained Solution (NON-NEGOTIABLE) | ✅ PASS | 5 direct deps, ~9 total with transitive. All open-source (BSD/Apache/MIT). Single `python:3.13-slim` container. No databases or queues in data model. Dependency list with licenses in research.md R6. |
| III. Observable Metrics Export | ✅ PASS | data-model.md defines 8 self-health metrics + `loxone_control_value` gauge with 6 labels. Proper `loxone_<subsystem>_<metric>_<unit>` naming. HELP/TYPE annotations in OpenAPI example. Cardinality bounded: worst-case ~4,500 series. Staleness via `loxone_exporter_connected` + `last_update_timestamp_seconds`. |
| IV. Test-First Development | ✅ PASS | quickstart.md defines test commands. Project structure includes `tests/unit/`, `tests/integration/`, `tests/contract/`. Coverage target ≥80%. Type checking via mypy. Linting via ruff. |
| V. Simplicity & Maintainability | ✅ PASS | 10 focused modules with clear contracts (internal-modules.md). Module dependency graph is acyclic. Config validation with descriptive errors. State machine has 6 states with clear transitions. No over-engineering. |
| Deployment Constraints | ✅ PASS | Dockerfile + docker-compose.yml in quickstart. Health endpoint `/healthz` returns JSON with per-miniserver status (OpenAPI contract). SIGTERM → asyncio cancellation in server.py contract. Structured JSON logging configurable. Resource targets documented. |

**Gate result: PASS** — No new violations introduced by Phase 1 design.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/
├── loxone_exporter/
│   ├── __init__.py          # Package init, version info
│   ├── __main__.py          # Entry point (python -m loxone_exporter)
│   ├── config.py            # YAML config loading + env var overrides
│   ├── loxone_client.py     # WebSocket client: connect, auth, structure download, event loop
│   ├── loxone_auth.py       # Token-based and hash-based authentication
│   ├── loxone_protocol.py   # Binary message parsing (headers, VALUE_STATES, TEXT_STATES)
│   ├── structure.py         # LoxAPP3.json parser: controls, rooms, categories, UUID mapping
│   ├── metrics.py           # Prometheus custom collector: control values → gauges/info
│   ├── server.py            # aiohttp HTTP server: /metrics, /healthz
│   └── logging.py           # Structured JSON logging setup
├── tests/
│   ├── unit/
│   │   ├── test_config.py
│   │   ├── test_structure.py
│   │   ├── test_protocol.py
│   │   ├── test_metrics.py
│   │   └── test_auth.py
│   ├── integration/
│   │   ├── test_loxone_client.py
│   │   └── mock_miniserver.py    # Mock WebSocket server for integration tests
│   └── contract/
│       └── test_metrics_endpoint.py  # Validate /metrics output format
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml           # Project metadata, dependencies, tool config
├── config.example.yml       # Example configuration file
└── README.md
```

**Structure Decision**: Single project layout. The exporter is a single Python package (`loxone_exporter`) with clear module separation following Constitution Principle V (Simplicity). Modules map 1:1 to the architectural layers: Loxone client (connection + auth + protocol) → structure parser → metrics mapper → HTTP server. Tests mirror the source structure with unit/integration/contract separation per Constitution Principle IV (Test-First).

## Complexity Tracking

> No Constitution Check violations. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| *(none)* | | |
