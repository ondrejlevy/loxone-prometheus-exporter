# Tasks: Loxone Miniserver Metrics Export to Prometheus

**Input**: Design documents from `/specs/001-loxone-metrics-export/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Included — Constitution Principle IV (Test-First Development) mandates TDD with ≥80% coverage.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization — directories, dependencies, Docker scaffolding

- [X] T001 Create project directory structure per plan: `src/loxone_exporter/`, `tests/unit/`, `tests/integration/`, `tests/contract/`, and package `__init__.py` with `__version__` in `src/loxone_exporter/__init__.py`
- [X] T002 Create `pyproject.toml` with project metadata, all runtime dependencies (`websockets~=16.0`, `prometheus_client~=0.24`, `aiohttp~=3.13`, `PyYAML~=6.0`, `pycryptodome~=3.0`), dev dependencies (`pytest`, `pytest-asyncio`, `pytest-cov`, `mypy`, `ruff`), and tool config sections (`[tool.pytest]`, `[tool.mypy]`, `[tool.ruff]`)
- [X] T003 [P] Create `Dockerfile` — `python:3.13-slim` base, `pip install .`, non-root user, `EXPOSE 9504`, `ENTRYPOINT ["python", "-m", "loxone_exporter"]`, `HEALTHCHECK` using `python -c "import urllib.request; urllib.request.urlopen('http://localhost:9504/healthz')"` (curl not available in slim image)
- [X] T004 [P] Create `docker-compose.yml` (exporter + Prometheus + Grafana services), `prometheus.yml` (scrape config targeting `exporter:9504`), and `config.example.yml` (annotated example per `contracts/config-schema.md`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure modules that MUST be complete before ANY user story can be implemented. These modules define data structures and parsers used by all stories.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T005 [P] Implement structured logging in `src/loxone_exporter/logging.py` — `setup_logging(level, format)` supporting JSON and text output, configurable via `log_level` and `log_format` from `ExporterConfig`, using stdlib `logging` with JSON formatter
- [X] T006 [P] Write config tests in `tests/unit/test_config.py` — YAML file loading, env var overrides (`LOXONE_NAME`, `LOXONE_HOST`, `LOXONE_USERNAME`, `LOXONE_PASSWORD`, `LOXONE_PORT`, `LOXONE_LISTEN_PORT`, `LOXONE_LOG_LEVEL`), env-only config (no file, `LOXONE_NAME` defaults to `LOXONE_HOST` value), validation errors (missing host, empty password, duplicate miniserver names, invalid port range), default values
- [X] T007 Implement `src/loxone_exporter/config.py` — `ExporterConfig` and `MiniserverConfig` frozen dataclasses, `load_config(path)` function loading YAML + merging env var overrides per `contracts/config-schema.md`, validation with `ConfigError`, default values for optional fields
- [X] T008 [P] Write protocol parser tests in `tests/unit/test_protocol.py` — 8-byte header parsing, VALUE_STATES payload parsing (24-byte entries, Loxone mixed-endian UUID → string conversion, double extraction), TEXT_STATES parsing (UUID + length-prefixed text with 4-byte alignment), estimated-length flag handling, empty payload, malformed data
- [X] T009 Implement `src/loxone_exporter/loxone_protocol.py` — `MessageHeader` dataclass, `parse_header(data)`, `parse_value_states(payload)` returning `list[tuple[str, float]]`, `parse_text_states(payload)` returning `list[tuple[str, str]]`, UUID bytes_le conversion per research.md R4
- [X] T010 [P] Write structure parser tests in `tests/unit/test_structure.py` — parsing rooms, categories, controls with states, subControls flattening, state_map (reverse UUID→control+state_name) building, text-only control detection (`is_text_only=True`), controls with missing room/category UUIDs, empty structure file
- [X] T011 Implement `src/loxone_exporter/structure.py` — `Room`, `Category`, `Control`, `StateEntry`, `StateRef`, `MiniserverState` dataclasses, `parse_structure(data)` returning `(controls, rooms, categories, state_map)` per `contracts/internal-modules.md`

**Checkpoint**: Foundation ready — all data structures, configuration, binary parsing, and structure parsing are tested and implemented. User story implementation can now begin.

---

## Phase 3: User Story 1 — Auto-Discovery and Basic Metrics Export (Priority: P1) 🎯 MVP

**Goal**: Connect to a Loxone Miniserver via WebSocket, authenticate, download the structure file, subscribe to value events, and serve all discovered control values as Prometheus gauge metrics on `/metrics`. Include exporter self-health metrics and a `/healthz` endpoint.

**Independent Test**: Start the exporter with valid Miniserver credentials, curl `http://localhost:9504/metrics`, and verify that Loxone control values appear as `loxone_control_value` gauges with correct labels (`miniserver`, `name`, `room`, `category`, `type`, `subcontrol`). Verify `/healthz` returns JSON status.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T022 [P] [US1] Create shared test fixtures in `tests/conftest.py` — sample `LoxAPP3.json` fixture (3+ controls across 2 rooms, 2 categories, including an IRoomControllerV2 with subControls), sample VALUE_STATES binary payload fixture, sample `ExporterConfig` fixture
- [X] T012 [P] [US1] Write auth tests in `tests/unit/test_auth.py` — token-based flow (mock RSA public key, AES session key generation, HMAC computation, encrypted command formatting), hash-based fallback (HMAC-SHA1 of `user:password` with hex key), authentication failure handling (`AuthenticationError`)
- [X] T013 [P] [US1] Write metrics collector tests in `tests/unit/test_metrics.py` — `LoxoneCollector.collect()` with mock `MiniserverState` containing controls with various types/states, verify `loxone_control_value` gauge output with correct labels, verify self-health metrics (`loxone_exporter_up`, `loxone_exporter_connected`, `loxone_exporter_last_update_timestamp_seconds`, `loxone_exporter_scrape_duration_seconds`, `loxone_exporter_controls_discovered`, `loxone_exporter_controls_exported`), verify digital values exported as 0/1
- [X] T014 [P] [US1] Write contract test in `tests/contract/test_metrics_endpoint.py` — full HTTP request to `/metrics`, verify Prometheus text exposition format, verify `# HELP` and `# TYPE` annotations present for all metrics, verify correct `Content-Type` header, verify `/healthz` returns JSON with `status` and `miniservers` fields per OpenAPI contract
- [X] T015 [P] [US1] Create mock Miniserver WebSocket server in `tests/integration/mock_miniserver.py` — accepts WS connections at `/ws/rfc6455`, responds to auth commands, serves sample `LoxAPP3.json`, sends VALUE_STATES binary frames with sample 24-byte entries, supports `enablebinstatusupdate` command

### Implementation for User Story 1

- [X] T016 [US1] Implement `src/loxone_exporter/loxone_auth.py` — `authenticate(ws, username, password)` with token-based auth (RSA key exchange via `pycryptodome`, AES-256-CBC session, HMAC-SHA256 credentials) and hash-based fallback (HMAC-SHA1), `AuthenticationError` exception, per `contracts/internal-modules.md` and research.md R4
- [X] T017 [US1] Implement `src/loxone_exporter/loxone_client.py` — `LoxoneClient` class with `connect()` (WebSocket open → auth → download structure → `enablebinstatusupdate`), basic `run()` loop (receive → dispatch VALUE_STATES/TEXT_STATES to state updates via `state_map`), `get_state()` returning `MiniserverState`, per `contracts/internal-modules.md`
- [X] T018 [US1] Implement `src/loxone_exporter/metrics.py` — `LoxoneCollector` implementing `prometheus_client.registry.Collector` protocol, `collect()` yielding `GaugeMetricFamily` for `loxone_control_value` with labels `{miniserver, name, room, category, type, subcontrol}`, plus all self-health metrics per data-model.md Prometheus Metrics Schema. Register `loxone_exporter_scrape_errors_total` Counter separately at module level (outside `collect()`)
- [X] T019 [US1] Implement `src/loxone_exporter/server.py` — `create_app(config, clients)` returning `aiohttp.web.Application` with `GET /metrics` (calls `generate_latest()`, returns `text/plain`) and `GET /healthz` (inspects client states, returns JSON per `contracts/http-api.openapi.yaml`), `run_http_server(app, config)` coroutine
- [X] T020 [US1] Implement `src/loxone_exporter/__main__.py` — CLI `--config` argument, `load_config()`, `setup_logging()`, register `LoxoneCollector` with Prometheus `REGISTRY`, `asyncio.TaskGroup` orchestrating `LoxoneClient.run()` tasks + HTTP server, SIGTERM/SIGINT handler cancelling the task group
- [X] T021 [US1] Write integration test in `tests/integration/test_loxone_client.py` — using `mock_miniserver.py`, test full flow: client connects → authenticates → downloads structure → subscribes → receives VALUE_STATES → `get_state()` returns updated values, verify end-to-end from WebSocket to metric availability, assert value update latency < 2s per SC-006

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently. The exporter connects to a Miniserver, discovers controls, receives value events, and serves them as Prometheus metrics. This is the MVP — `docker compose up` works end-to-end.

---

## Phase 4: User Story 2 — Filtering and Exclusion Rules (Priority: P2)

**Goal**: Allow users to configure exclusion rules (by room name, control type, control name pattern) to reduce exported metrics. Support opt-in export of text-only controls as info metrics.

**Independent Test**: Configure `exclude_rooms: ["Test Room"]` and `exclude_types: ["Pushbutton"]` in config, restart, and verify those controls are absent from `/metrics` while others remain. Verify `controls_discovered` > `controls_exported`.

### Tests for User Story 2

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T023 [P] [US2] Write filtering tests in `tests/unit/test_metrics.py` — room exclusion (controls in excluded rooms omitted), type exclusion (controls of excluded types omitted), name glob matching (`fnmatch` patterns like `"Test*"`), combined filters, text-only control exclusion by default, text-only control opt-in (`include_text_values=true` → `loxone_control_info` with text label), `controls_discovered` vs `controls_exported` counts accurate after filtering

### Implementation for User Story 2

- [X] T024 [US2] Implement exclusion filtering in `src/loxone_exporter/metrics.py` `collect()` — apply `exclude_rooms` (match room name), `exclude_types` (match control type), `exclude_names` (glob via `fnmatch.fnmatch`), skip `is_text_only` controls unless `include_text_values` is true, update `controls_exported` to reflect post-filter count
- [X] T025 [US2] Implement info metric export for text controls in `src/loxone_exporter/metrics.py` — when `include_text_values=true`, yield `InfoMetricFamily` for `loxone_control_info` with `value` label containing the text string, same base labels as `loxone_control_value`

**Checkpoint**: User Stories 1 AND 2 both work independently. Filtering reduces metric output as configured. Text controls can be opted in as info metrics.

---

## Phase 5: User Story 3 — Real-Time Value Updates via WebSocket (Priority: P3)

**Goal**: Make the WebSocket connection resilient with automatic reconnection, exponential backoff, keepalive, re-discovery on reconnect, and staleness signaling via connection metrics.

**Independent Test**: Kill the mock Miniserver, verify `loxone_exporter_connected` drops to 0 and `last_update_timestamp_seconds` stops advancing. Restart the mock, verify the exporter reconnects, re-discovers controls, and metrics resume updating.

### Tests for User Story 3

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T026 [P] [US3] Write reconnection tests in `tests/integration/test_loxone_client.py` — mock server disconnect → client detects, backoff delay observed (1s initial), reconnect succeeds → structure re-downloaded, events resume; OUT_OF_SERVICE message → triggers reconnect; keepalive timeout → triggers reconnect; backoff escalation (verify delays double up to 30s cap); backoff reset after successful reconnect; SC-004 recovery assertion (mock server returns online after backoff at max → verify reconnect within 60s of server availability); authentication failure on reconnect → clear error logged, retry continues (FR-019)

### Implementation for User Story 3

- [X] T027 [US3] Implement exponential backoff reconnection in `src/loxone_exporter/loxone_client.py` `run()` — `async for ws in websockets.connect(...)` pattern with backoff wrapper: initial 1s, doubling to 30s max, reset to 1s on successful connection + auth + structure download, log each reconnect attempt with delay; on `AuthenticationError`, log clear error identifying miniserver and continue backoff (FR-019)
- [X] T028 [US3] Implement keepalive handling in `src/loxone_exporter/loxone_client.py` — send `keepalive` text message every 30 seconds via `asyncio.create_task`, detect keepalive timeout (no response within 60s) as connection failure, handle `OUT_OF_SERVICE` (msg_type 5) as immediate disconnect trigger
- [X] T029 [US3] Implement re-discovery on reconnect in `src/loxone_exporter/loxone_client.py` — after successful re-authentication, re-download `LoxAPP3.json`, call `parse_structure()`, rebuild `state_map`, update `MiniserverState.controls/rooms/categories`, re-send `enablebinstatusupdate`
- [X] T030 [US3] Implement connection state tracking in `src/loxone_exporter/loxone_client.py` — set `MiniserverState.connected = True` after successful subscribe, set `MiniserverState.connected = False` on disconnect, update `MiniserverState.last_update_ts = time.time()` on every VALUE_STATES event; these fields are read by `LoxoneCollector.collect()` to yield `loxone_exporter_connected` and `loxone_exporter_last_update_timestamp_seconds`

**Checkpoint**: The exporter is resilient. It survives Miniserver reboots, network drops, and firmware updates. Connection status is signaled via Prometheus metrics. Users can alert on `loxone_exporter_connected == 0` for prolonged periods.

---

## Phase 6: User Story 4 — Prometheus-Compliant Metric Naming and Low Cardinality (Priority: P4)

**Goal**: Ensure all metrics strictly follow Prometheus naming conventions, include HELP/TYPE annotations, expose build info, and keep label cardinality bounded.

**Independent Test**: Scrape `/metrics` and programmatically validate: all metric names match `loxone_<subsystem>_<metric>_<unit>` pattern, every metric has HELP and TYPE lines, label cardinality ≤ 3× control count, `loxone_exporter_build_info` present with version/commit/build_date labels.

### Tests for User Story 4

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T031 [P] [US4] Write naming validation tests in `tests/contract/test_metrics_endpoint.py` — regex check all metric names match `loxone_(control|exporter)_[a-z_]+` pattern, every metric has `# HELP` and `# TYPE`, `loxone_exporter_build_info` present with `version`/`commit`/`build_date` labels, label names match `[a-zA-Z_][a-zA-Z0-9_]*`, total unique label combos for `loxone_control_value` ≤ 3× number of controls in test fixture

### Implementation for User Story 4

- [X] T032 [US4] Add build info to `src/loxone_exporter/__init__.py` — `__version__`, `__commit__`, `__build_date__` variables (defaults for dev, overridden at Docker build time via build args)
- [X] T033 [US4] Implement `loxone_exporter_build_info` metric in `src/loxone_exporter/metrics.py` — `InfoMetricFamily` yielding `{version, commit, build_date}` labels from `__init__` module variables
- [X] T034 [US4] Update `Dockerfile` to inject build metadata — `ARG VERSION COMMIT BUILD_DATE`, pass as environment variables or bake into `__init__.py` at build time

**Checkpoint**: All metrics follow Prometheus best practices. Build info is traceable. Cardinality is bounded and validated.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, validation, and refinements that span all user stories

- [X] T035 [P] Write `README.md` — project overview, features, quickstart (dev + Docker), configuration reference (all YAML fields + env var overrides), metrics reference (all metrics with types/labels), architecture diagram, contributing guide
- [X] T036 [P] Add credential sanitization to `src/loxone_exporter/logging.py` — ensure passwords and tokens are never logged, redact sensitive config fields in debug output
- [X] T037 Run full test suite with coverage report — `pytest --cov=loxone_exporter --cov-report=term-missing`, verify ≥80% coverage on all non-trivial modules, fix any coverage gaps
- [X] T038 Run `quickstart.md` end-to-end validation — verify all documented commands work: `pip install -e ".[dev]"`, `pytest`, `mypy src/`, `ruff check src/ tests/`, `docker build`, `docker compose up`
- [X] T039 Run basic performance/load test — generate 500+ mock controls, measure memory consumption (≤50MB per SC-005) and `/metrics` scrape latency, verify ≤5% single-core CPU under sustained scraping
- [X] T040 [P] Write concurrent scrape test in `tests/contract/test_metrics_endpoint.py` — 10 parallel GET `/metrics` requests, verify consistent output and no data races per edge case EC-006

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — **BLOCKS all user stories**
- **US1 (Phase 3)**: Depends on Foundational — **BLOCKS US2, US3, US4** (MVP must work first)
- **US2 (Phase 4)**: Depends on US1 (needs working collector to add filtering)
- **US3 (Phase 5)**: Depends on US1 (needs working client to add resilience)
- **US4 (Phase 6)**: Depends on US1 (needs working metrics to validate naming)
- **Polish (Phase 7)**: Depends on all user stories being complete

### User Story Dependencies

```
Phase 1: Setup
    │
    ▼
Phase 2: Foundational (BLOCKS ALL)
    │
    ▼
Phase 3: US1 — MVP (BLOCKS US2, US3, US4)
    │
    ├──────────────┬──────────────┐
    ▼              ▼              ▼
Phase 4: US2   Phase 5: US3   Phase 6: US4   (can run in parallel)
    │              │              │
    └──────────────┴──────────────┘
                   │
                   ▼
            Phase 7: Polish
```

### Within Each Phase

1. **Tests MUST be written FIRST and FAIL** before implementation (TDD per Constitution IV)
2. Data models / dataclasses before business logic
3. Business logic before HTTP/entry point layer
4. Integration/contract tests after implementation
5. Story complete before moving to next priority (unless parallelizing US2/US3/US4)

### Parallel Opportunities

**Phase 1**: T003 and T004 can run in parallel (different files)
**Phase 2**: T005, T006, T008, T010 can all run in parallel (different files, no deps). Then T007, T009, T011 implement against those tests.
**Phase 3**: T022, T012, T013, T014, T015 (fixtures + all test tasks) can run in parallel. Then T016→T017→T018→T019→T020 are sequential. T021 after implementation.
**Phase 4**: T023 (tests) first, then T024→T025 sequential.
**Phase 5**: T026 (tests) first, then T027→T028→T029→T030 partially parallel (T027+T028 parallel, T029+T030 after).
**Phase 6**: T031 (tests) first, then T032+T033 parallel, T034 after.
**Phase 7**: T035+T036 parallel, T037+T038 sequential (need full codebase).

---

## Parallel Example: Phase 2 (Foundational)

```bash
# Batch 1 — all tests + logging (parallel, different files):
T005: "Implement logging in src/loxone_exporter/logging.py"
T006: "Write config tests in tests/unit/test_config.py"
T008: "Write protocol tests in tests/unit/test_protocol.py"
T010: "Write structure tests in tests/unit/test_structure.py"

# Batch 2 — implementations (each depends on its test, but parallel with each other):
T007: "Implement config.py"       # depends on T006
T009: "Implement loxone_protocol.py"  # depends on T008
T011: "Implement structure.py"    # depends on T010
```

## Parallel Example: Phase 3 (User Story 1)

```bash
# Batch 1 — fixtures + all tests + mock server (parallel, different files):
T022: "Shared test fixtures in tests/conftest.py"
T012: "Write auth tests in tests/unit/test_auth.py"
T013: "Write metrics tests in tests/unit/test_metrics.py"
T014: "Write contract test in tests/contract/test_metrics_endpoint.py"
T015: "Create mock miniserver in tests/integration/mock_miniserver.py"

# Batch 2 — sequential implementation (dependency chain):
T016: "Implement loxone_auth.py"        # depends on T012
T017: "Implement loxone_client.py"      # depends on T016 + Phase 2
T018: "Implement metrics.py"            # depends on T013
T019: "Implement server.py"             # depends on T018
T020: "Implement __main__.py"           # depends on T017, T019
T021: "Integration test"                # depends on T015, T017
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: `docker compose up`, curl `/metrics`, verify Loxone values appear
5. Deploy if ready — this is a working exporter

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. Add US1 → Test → Deploy (MVP! Working exporter with auto-discovery)
3. Add US2 → Test → Deploy (Filtering reduces noise)
4. Add US3 → Test → Deploy (Resilience: survives reboots/drops)
5. Add US4 → Test → Deploy (Naming compliance, build info)
6. Polish → Final release

### Suggested MVP Scope

**US1 alone** is a complete, useful product. A user can:
- Point at a Miniserver → auto-discover all controls
- Scrape `/metrics` → get all values as Prometheus gauges
- Check `/healthz` → verify connection status
- Run via `docker compose up` → full local stack

US2–US4 add refinement but aren't required for initial value delivery.

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- [Story] label maps task to specific user story for traceability
- Each user story is independently completable and testable after US1 (MVP)
- Tests are written FIRST and must FAIL before implementation (Constitution Principle IV)
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Total tasks: 40 (4 setup + 7 foundational + 11 US1 + 3 US2 + 5 US3 + 4 US4 + 6 polish)
