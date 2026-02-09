# Implementation Tasks: OpenTelemetry Metrics Export Support

**Feature**: 002-opentelemetry-support  
**Date**: 2026-02-09  
**Plan**: [plan.md](plan.md) | **Spec**: [spec.md](spec.md)

## Task Summary

**Total Tasks**: 67  
**MVP Scope**: Phase 1 + Phase 2 + Phase 3 (User Story 1) = 30 tasks  
**Format**: All tasks follow checklist format with Task ID, parallelizable marker [P], and story label [Story]

---

## Phase 1: Setup & Dependencies

**Goal**: Install OpenTelemetry SDK dependencies and validate project structure.

**Tasks**:

- [X] T001 Add OpenTelemetry dependencies to pyproject.toml
- [X] T002 [P] Update .github/agents/copilot-instructions.md with OpenTelemetry SDK references
- [X] T003 Install dependencies and verify no conflicts with existing packages
- [X] T004 Create src/loxone_exporter/otlp_exporter.py module skeleton

**Completion Criteria**:
- ✅ `pyproject.toml` includes opentelemetry-sdk~=1.28, opentelemetry-exporter-otlp-proto-grpc~=1.28, opentelemetry-exporter-otlp-proto-http~=1.28
- ✅ `pip install -e .` succeeds without conflicts
- ✅ `otlp_exporter.py` module exists with docstring

---

## Phase 2: Foundational Infrastructure

**Goal**: Implement core configuration, validation, and factory patterns that all user stories depend on.

**Tasks**:

- [X] T005 Add OTLPConfiguration data model in config.py
- [X] T006 Add TLSConfig and AuthConfig nested models in config.py
- [X] T007 Implement YAML parsing for opentelemetry config section in config.py
- [X] T008 Implement environment variable override logic for OTLP config in config.py
- [X] T009 Implement configuration validation rules (VR-001 through VR-011) in config.py
- [X] T010 Add ConfigurationError exception class in config.py
- [X] T011 [P] Write unit tests for OTLP config validation in tests/unit/test_config.py
- [X] T012 [P] Update config.example.yml with commented OTLP section
- [X] T013 Add ExportStatus data model in otlp_exporter.py
- [X] T014 Add MetricBatch, OTLPMetric, DataPoint data models in otlp_exporter.py
- [X] T015 Implement create_otlp_exporter factory function in otlp_exporter.py
- [X] T016 [P] Write unit tests for factory function (gRPC/HTTP selection) in tests/unit/test_otlp_retry.py

**Completion Criteria**:
- ✅ Configuration parsing handles all fields from config-schema.md
- ✅ Invalid config with enabled=true fails at startup with descriptive error
- ✅ Environment variables override YAML values correctly
- ✅ Factory creates correct exporter type based on protocol config
- ✅ Unit tests achieve ≥90% coverage for config validation

**Independent Test**: Run `pytest tests/unit/test_config.py -k otlp -v` → all tests pass

---

## Phase 3: User Story 1 - Enable OpenTelemetry Export (P1)

**Story Goal**: Operators can configure OTLP collector endpoint and the exporter successfully sends metrics at regular intervals.

**Independent Test Criteria**: 
- Start exporter with OTLP enabled pointing to local collector
- Verify metrics appear in collector within 2x configured interval
- Prometheus endpoint remains functional during OTLP export

**Tasks**:

- [X] T017 [US1] Implement PrometheusToOTLPBridge.convert_metrics() in otlp_exporter.py
- [X] T018 [US1] Implement Prometheus Gauge → OTLP Gauge conversion in otlp_exporter.py
- [X] T019 [US1] Implement Prometheus Counter → OTLP Sum conversion in otlp_exporter.py
- [X] T020 [US1] Implement Prometheus Histogram → OTLP Histogram conversion in otlp_exporter.py
- [X] T021 [US1] Implement OTLPExporter.__init__() with SDK exporter setup in otlp_exporter.py
- [X] T022 [US1] Implement OTLPExporter._export_loop() asyncio task in otlp_exporter.py
- [X] T023 [US1] Implement OTLPExporter._export_once() method in otlp_exporter.py
- [X] T024 [US1] Implement OTLPExporter.start() and stop() lifecycle methods in otlp_exporter.py
- [X] T025 [US1] Integrate OTLP exporter task into server.py main() function
- [X] T026 [US1] Handle SIGTERM gracefully for OTLP exporter in server.py
- [X] T027 [P] [US1] Write unit tests for metric conversion (Gauge/Counter/Histogram→OTLP) in tests/unit/test_otlp_conversion.py
- [X] T028 [P] [US1] Create mock OTLP collector fixture in tests/integration/test_otlp_collector.py
- [X] T029 [P] [US1] Write integration test for successful export flow in tests/integration/test_otlp_collector.py (includes: verify Prometheus /metrics responds <500ms during OTLP export failures)
- [X] T030 [P] [US1] Write contract tests for OTLP format compliance in tests/contract/test_otlp_export.py (includes: verify all Prometheus labels/descriptions preserved in OTLP format per FR-012)

**Completion Criteria**:
- ✅ Metrics exported to OTLP collector match Prometheus scrape data
- ✅ Export occurs at configured interval (±2s tolerance)
- ✅ Prometheus endpoint serves metrics without interruption during OTLP export (<500ms response time even during OTLP failures)
- ✅ Integration test with mock collector passes
- ✅ Contract tests verify OTLP protobuf structure
- ✅ Contract tests confirm all Prometheus metric metadata (labels, HELP text, type) preserved in OTLP format

**Parallel Opportunities**:
- T027, T028, T029, T030 can run in parallel (independent test files)

---

## Phase 4: User Story 2 - Configure Export Behavior (P2)

**Story Goal**: Operators can customize export intervals, protocols, authentication, and disable the feature entirely.

**Independent Test Criteria**:
- Test with OTLP disabled → no connection attempts, Prometheus-only mode
- Test with different intervals → exports occur at specified frequency
- Test with auth headers → credentials sent in OTLP requests

**Tasks**:

- [X] T031 [US2] Implement _calculate_backoff() exponential backoff logic in otlp_exporter.py
- [X] T032 [US2] Implement _should_export() overlap prevention check in otlp_exporter.py
- [X] T033 [US2] Implement retry state machine (IDLE→EXPORTING→RETRYING→FAILED) in otlp_exporter.py
- [X] T034 [US2] Implement _handle_success() and _handle_failure() state transitions in otlp_exporter.py
- [X] T035 [US2] Add TLS credential handling for gRPC protocol in create_otlp_exporter()
- [X] T036 [US2] Add TLS certificate path handling for HTTP protocol in create_otlp_exporter()
- [X] T037 [P] [US2] Write unit tests for backoff calculation in tests/unit/test_otlp_retry.py
- [X] T038 [P] [US2] Write unit tests for state transitions in tests/unit/test_otlp_retry.py
- [X] T039 [P] [US2] Write unit tests for overlap prevention in tests/unit/test_otlp_retry.py
- [X] T040 [P] [US2] Write integration test for collector unreachable scenario in tests/integration/test_otlp_collector.py
- [X] T041 [P] [US2] Write integration test for timeout handling in tests/integration/test_otlp_collector.py
- [X] T042 [P] [US2] Write integration test for authentication failure in tests/integration/test_otlp_collector.py

**Completion Criteria**:
- ✅ Disabled config prevents OTLP connections (verified by no network traffic)
- ✅ Custom intervals respected (measured export timestamps)
- ✅ Auth headers present in OTLP requests (captured in collector logs)
- ✅ Retry backoff follows 1s→2s→4s→...→300s (max) pattern
- ✅ Overlapping exports skipped (logged with reason)

**Parallel Opportunities**:
- T037, T038, T039 (unit tests) can run in parallel
- T040, T041, T042 (integration tests) can run sequentially (share mock collector setup)

---

## Phase 5: User Story 3 - Monitor Export Health (P3)

**Story Goal**: Operators can observe OTLP export status through health metrics and endpoints.

**Independent Test Criteria**:
- Query `/healthz` endpoint → includes OTLP status section
- Query `/metrics` → includes all 5 OTLP health metrics
- Simulate failure → health metrics reflect degraded state

**Tasks**:

- [X] T043 [US3] Add loxone_otlp_export_status gauge metric in metrics.py
- [X] T044 [US3] Add loxone_otlp_last_success_timestamp_seconds gauge in metrics.py
- [X] T045 [US3] Add loxone_otlp_consecutive_failures gauge in metrics.py
- [X] T046 [US3] Add loxone_otlp_export_duration_seconds histogram in metrics.py
- [X] T047 [US3] Add loxone_otlp_exported_metrics_total counter in metrics.py
- [X] T048 [US3] Implement _update_state() to sync ExportStatus with metrics in otlp_exporter.py
- [X] T049 [US3] Update health metrics on export success in otlp_exporter.py
- [X] T050 [US3] Update health metrics on export failure in otlp_exporter.py
- [X] T051 [US3] Implement OTLPExporter.get_status() method in otlp_exporter.py
- [X] T052 [US3] Extend /healthz endpoint response with OTLP status in server.py
- [X] T053 [P] [US3] Write unit tests for metric updates in tests/unit/test_metrics.py
- [X] T054 [P] [US3] Write integration test for health endpoint with OTLP in tests/integration/test_otlp_collector.py
- [X] T055 [P] [US3] Write contract test for health metrics format in tests/contract/test_metrics_endpoint.py

**Completion Criteria**:
- ✅ All 5 health metrics present on `/metrics` endpoint
- ✅ Health endpoint JSON includes `otlp` section with state/last_success/failures
- ✅ Metrics update in real-time during export lifecycle
- ✅ Health status shows "degraded" when OTLP in FAILED state
- ✅ Contract tests verify metric naming conventions

**Parallel Opportunities**:
- T053, T054, T055 can run in parallel (independent test files)

---

## Phase 6: Polish & Cross-Cutting Concerns

**Goal**: Documentation, performance validation, and production readiness.

**Tasks**:

- [X] T056 [P] Update README.md with OTLP configuration section
- [X] T057 [P] Create docker-compose.override.yml with OTLP collector example
- [X] T058 [P] Create otel-collector-config.yaml example in repository root
- [X] T059 [P] Update prometheus.yml to scrape OTLP collector endpoint
- [X] T060 Add structured logging for OTLP export events (INFO, WARNING, ERROR, CRITICAL)
- [X] T061 Implement log sanitization to prevent credential leakage in otlp_exporter.py
- [X] T062 [P] Write performance test for 1000 metrics with OTLP in tests/performance/test_load.py
- [X] T063 Verify memory footprint ≤10MB overhead with OTLP enabled
- [X] T064 Verify export latency P95 <500ms for 1000 metrics
- [X] T065 [P] Run full test suite and achieve ≥80% coverage
- [ ] T066 Update CHANGELOG.md with OTLP support feature entry
- [ ] T067 Tag release v0.2.0 with OpenTelemetry support

**Completion Criteria**:
- ✅ README includes OTLP quick start guide
- ✅ Docker Compose example runs and exports successfully
- ✅ Performance tests pass without degradation
- ✅ All logs sanitized (no tokens/passwords visible)
- ✅ Full test coverage ≥80%

**Parallel Opportunities**:
- T056, T057, T058, T059 (documentation) can run in parallel
- T062, T063, T064 (performance) must run sequentially (share measurement baseline)

---

## Dependencies & Execution Order

### Critical Path (Blocking Dependencies)

```
Phase 1 (Setup)
    ↓
Phase 2 (Foundational)
    ↓
    ├─→ Phase 3 (US1: Enable Export) ← MVP
    │       ↓
    ├─→ Phase 4 (US2: Configure Behavior)
    │       ↓
    └─→ Phase 5 (US3: Monitor Health)
            ↓
        Phase 6 (Polish)
```

### Phase Dependencies

| Phase | Blocks | Reason |
|-------|--------|--------|
| Phase 1 | Phase 2, 3, 4, 5 | Dependencies must be installed |
| Phase 2 | Phase 3, 4, 5 | Config and factory patterns needed |
| Phase 3 | Phase 4, 5 | Export functionality must exist before adding features |
| Phase 4 | Phase 6 (performance) | Retry logic must be complete for load testing |
| Phase 5 | Phase 6 (docs) | Health metrics must exist to document |

### Task-Level Dependencies

Within each phase, tasks can be parallelized except where noted:

**Phase 2 Foundational**:
- T005-T010 (config) → must complete before T011 (tests)
- T013-T015 (models/factory) → must complete before T016 (tests)

**Phase 3 US1**:
- T017-T020 (conversion) → must complete before T023 (export_once)
- T021-T024 (exporter core) → must complete before T025-T026 (integration)
- T017-T026 → must complete before T027-T030 (tests)

**Phase 4 US2**:
- T031-T034 (retry logic) → must complete before T037-T039 (unit tests)
- T035-T036 (TLS) → independent, can parallel with retry
- T031-T036 → must complete before T040-T042 (integration tests)

**Phase 5 US3**:
- T043-T047 (metrics definitions) → must complete before T048-T050 (updates)
- T048-T051 (exporter integration) → must complete before T052 (health endpoint)
- T043-T052 → must complete before T053-T055 (tests)

---

## Parallel Execution Examples

### Phase 2: Foundational (After Core Models Complete)

Parallel batch (2 developers):
- Dev A: T011 (config tests)
- Dev B: T012 (example file) + T016 (factory tests)

**Expected duration**: ~2 hours (vs 4 hours sequential)

### Phase 3: User Story 1 (After Core Implementation Complete)

Parallel batch (4 developers):
- Dev A: T027 (conversion unit tests)
- Dev B: T028 + T029 (integration tests)
- Dev C: T030 (contract tests)
- Dev D: (can start Phase 4 T031-T032)

**Expected duration**: ~3 hours (vs 8 hours sequential)

### Phase 4: User Story 2 (Unit Tests)

Parallel batch (3 developers):
- Dev A: T037 (backoff tests)
- Dev B: T038 (state tests)
- Dev C: T039 (overlap tests)

**Expected duration**: ~1.5 hours (vs 4.5 hours sequential)

### Phase 5: User Story 3 (Tests)

Parallel batch (3 developers):
- Dev A: T053 (metrics unit tests)
- Dev B: T054 (health integration test)
- Dev C: T055 (contract tests)

**Expected duration**: ~2 hours (vs 6 hours sequential)

### Phase 6: Polish (Documentation)

Parallel batch (4 developers):
- Dev A: T056 (README)
- Dev B: T057 (docker-compose)
- Dev C: T058 (collector config)
- Dev D: T059 (prometheus config)

**Expected duration**: ~1 hour (vs 4 hours sequential)

---

## Implementation Strategy

### MVP First (Phases 1-3)

**Scope**: 30 tasks (T001-T030)  
**Delivers**: User Story 1 (Enable OpenTelemetry Export)  
**Value**: Core OTLP export functionality, operators can send metrics to collectors

**Recommendation**: Complete MVP before starting Phase 4. This allows early testing and feedback on core functionality.

### Incremental Delivery

**Iteration 1** (MVP): Phases 1-3 → Deploy to staging, validate basic export  
**Iteration 2** (Config): Phase 4 → Add retry logic, auth, TLS → Deploy  
**Iteration 3** (Monitoring): Phase 5 → Add health metrics → Deploy  
**Iteration 4** (Production): Phase 6 → Documentation, performance tuning → Deploy to production

**Total estimated effort**: 15-20 developer-days (single developer, sequential)  
**With parallelization**: 8-12 developer-days (2-4 developers)

---

## Testing Strategy

### Test Coverage by Phase

| Phase | Unit Tests | Integration Tests | Contract Tests | Performance Tests |
|-------|-----------|------------------|----------------|-------------------|
| Phase 1 | - | - | - | - |
| Phase 2 | T011, T016 | - | - | - |
| Phase 3 | T027 | T028, T029 | T030 | - |
| Phase 4 | T037, T038, T039 | T040, T041, T042 | - | - |
| Phase 5 | T053 | T054 | T055 | - |
| Phase 6 | - | - | - | T062, T063, T064 |

**Total test tasks**: 16 out of 67 tasks (24%)

### Test Execution Order

1. **Unit tests first**: Fast feedback, no external dependencies
2. **Integration tests**: Require mock OTLP collector setup
3. **Contract tests**: Verify OTLP format compliance
4. **Performance tests last**: Baseline established, all features complete

### Coverage Gates

- **After Phase 2**: ≥90% coverage for config.py (OTLP sections)
- **After Phase 3**: ≥85% coverage for otlp_exporter.py
- **After Phase 6**: ≥80% coverage for entire project

---

## Risk Mitigation

### High-Risk Areas

1. **Metric conversion accuracy** (T017-T020)
   - **Risk**: Data loss or corruption during Prometheus→OTLP conversion
   - **Mitigation**: Contract tests (T030) validate every metric type
   
2. **Retry state machine complexity** (T031-T034)
   - **Risk**: Edge cases cause infinite loops or crashes
   - **Mitigation**: Comprehensive unit tests (T037-T039) cover all transitions

3. **Performance degradation** (T062-T064)
   - **Risk**: OTLP export slows Prometheus scraping
   - **Mitigation**: Performance tests validate <500ms P95 export duration

4. **Configuration validation gaps** (T005-T010)
   - **Risk**: Invalid config causes runtime crashes
   - **Mitigation**: Fail-fast validation at startup, extensive unit tests (T011)

---

## Definition of Done (Per Task)

Each task is considered complete when:
- ✅ Code implemented and follows project style (ruff, mypy pass)
- ✅ Docstrings added (module, class, function)
- ✅ Unit tests written (if applicable) and passing
- ✅ Integration tests passing (if applicable)
- ✅ Manual testing completed (for integration tasks)
- ✅ Code reviewed (PR approved)
- ✅ Documentation updated (if user-facing change)

---

## Task Statistics

**By Phase**:
- Phase 1 (Setup): 4 tasks
- Phase 2 (Foundational): 12 tasks
- Phase 3 (US1): 14 tasks
- Phase 4 (US2): 12 tasks
- Phase 5 (US3): 13 tasks
- Phase 6 (Polish): 12 tasks

**By Type**:
- Implementation: 42 tasks (63%)
- Testing: 16 tasks (24%)
- Documentation: 7 tasks (10%)
- Validation: 2 tasks (3%)

**Parallelizable**: 29 tasks marked [P] (43%)

**Story Distribution**:
- User Story 1 (P1): 14 tasks (21%)
- User Story 2 (P2): 12 tasks (18%)
- User Story 3 (P3): 13 tasks (19%)
- Infrastructure: 28 tasks (42%)

---

## Next Steps

1. **Review this task breakdown** with team
2. **Assign tasks** to developers
3. **Create GitHub issues** from tasks (one issue per task)
4. **Start with Phase 1** (T001-T004)
5. **Run daily standups** to track progress and blockers
6. **Deploy MVP** after completing Phase 3

**Estimated timeline**:
- **Single developer**: 3-4 weeks
- **2 developers**: 2-3 weeks
- **4 developers**: 1.5-2 weeks

---

## References

- [spec.md](spec.md) - Feature specification with user stories
- [plan.md](plan.md) - Implementation plan and technical context
- [data-model.md](data-model.md) - Entity definitions
- [contracts/config-schema.md](contracts/config-schema.md) - Configuration specification
- [contracts/otlp-export.md](contracts/otlp-export.md) - Module interface
- [contracts/health-metrics.md](contracts/health-metrics.md) - Health metrics specification
- [quickstart.md](quickstart.md) - Development and testing guide
