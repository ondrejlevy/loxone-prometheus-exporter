# Feature Specification: Loxone Miniserver Metrics Export to Prometheus

**Feature Branch**: `001-loxone-metrics-export`  
**Created**: 2026-02-07  
**Status**: Draft  
**Input**: User description: "Export hodnot a parametrů všech prvků v Loxone Miniserveru a jejich uložení jako metriky v Prometheus. Auto-discovery objektů, WebSocket listening, správné přiřazení labelů, nízká kardinalita."

## Clarifications

### Session 2026-02-07

- Q: How should Miniserver credentials be provided — config file only, env vars override, or env vars only? → A: Environment variables override config file values. Secrets can be injected via env vars; config file holds non-sensitive defaults.
- Q: How should complex controls with multiple sub-control values (e.g., IRoomControllerV2) map to Prometheus metrics? → A: One gauge per sub-control state, differentiated by a `subcontrol` label (e.g., `loxone_control_value{subcontrol="tempActual"}`).
- Q: How should controls with purely textual (non-numeric) values be handled? → A: Exclude text-only controls by default; provide a config option to opt them in, exported as info-type metrics with the text as a label value.
- Q: What format should the configuration file use? → A: YAML, consistent with the Prometheus ecosystem (Prometheus, Alertmanager, Grafana Agent all use YAML).
- Q: How should the exporter signal staleness during WebSocket disconnection? → A: Per-miniserver `loxone_exporter_connected` gauge (1/0) plus `loxone_exporter_last_update_timestamp_seconds`; control values retain their last known value.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Auto-Discovery and Basic Metrics Export (Priority: P1)

As a home automation operator, I want the exporter to automatically discover all controls and their values on my Loxone Miniserver and expose them as Prometheus metrics, so that I can monitor my entire smart home without manually configuring each control.

**Why this priority**: This is the core value proposition — without auto-discovery and metrics export, there is no product. A user should be able to point the exporter at a Miniserver and immediately see metrics.

**Independent Test**: Can be fully tested by starting the exporter with Miniserver credentials, then querying the `/metrics` endpoint and verifying that Loxone control values appear as properly named and labeled Prometheus metrics.

**Acceptance Scenarios**:

1. **Given** a running Loxone Miniserver with configured controls, **When** the exporter starts and connects to the Miniserver, **Then** it downloads the structure file (`LoxAPP3.json`), discovers all controls, rooms, and categories, and begins collecting values.
2. **Given** the exporter has completed initial discovery, **When** a Prometheus server (or user via browser/curl) scrapes the `/metrics` endpoint, **Then** all numeric control values are returned as Prometheus gauge metrics with appropriate labels (control name, room, category, control type).
3. **Given** the exporter is running and connected, **When** a control value changes on the Miniserver, **Then** the exporter receives the update (via WebSocket value events) and the next scrape of `/metrics` reflects the new value.
4. **Given** the exporter is running, **When** the `/metrics` endpoint is scraped, **Then** exporter self-health metrics are also present (connection status, scrape duration, error counts, number of discovered controls).

---

### User Story 2 - Filtering and Exclusion Rules (Priority: P2)

As a home automation operator, I want to configure which controls, rooms, or control types are excluded from metrics export, so that I can reduce noise and avoid exporting irrelevant data that increases Prometheus storage costs and cardinality.

**Why this priority**: Not all controls are monitoring-relevant. Users need the ability to exclude entire rooms (e.g., "Test Room"), specific control types (e.g., Pushbutton), or individual controls by name pattern to keep cardinality low and metrics meaningful.

**Independent Test**: Can be tested by configuring exclusion rules, restarting the exporter, and verifying that excluded controls do not appear in the `/metrics` output while included controls remain visible.

**Acceptance Scenarios**:

1. **Given** a configuration file with a list of excluded room names (e.g., `["Test Room", "Utility"]`), **When** the exporter discovers controls, **Then** controls belonging to those rooms are not exported as metrics.
2. **Given** a configuration file with excluded control types (e.g., `["Pushbutton", "Webpage"]`), **When** the exporter discovers controls, **Then** controls of those types are not exported as metrics.
3. **Given** a configuration file with excluded control name patterns (e.g., glob or regex `"Test*"`), **When** the exporter discovers controls, **Then** controls whose names match the pattern are not exported.
4. **Given** exclusion rules are applied, **When** the exporter exposes self-health metrics, **Then** the count of discovered controls and the count of exported controls are both visible, allowing the user to verify filtering is working.

---

### User Story 3 - Real-Time Value Updates via WebSocket (Priority: P3)

As a home automation operator, I want the exporter to maintain a persistent WebSocket connection to the Miniserver and receive value changes in real-time, so that metrics reflect the current state of my home accurately without polling delays.

**Why this priority**: WebSocket-based updates are more efficient than HTTP polling and provide near-instant metric freshness. This is important for time-sensitive monitoring (e.g., alarm states, temperature changes) but builds on the core discovery from P1.

**Independent Test**: Can be tested by changing a control value on the Miniserver (e.g., toggling a switch) and verifying within seconds that the `/metrics` endpoint reflects the updated value.

**Acceptance Scenarios**:

1. **Given** the exporter has connected to the Miniserver via WebSocket, **When** the exporter requests binary status update events (`enablebinstatusupdate`), **Then** the Miniserver begins sending value change events for all controls.
2. **Given** the WebSocket connection is active and receiving events, **When** a control value changes, **Then** the exporter updates its internal state within 1 second of receiving the event.
3. **Given** the WebSocket connection drops unexpectedly, **When** the exporter detects the disconnection, **Then** it attempts automatic reconnection with exponential backoff and logs the event. During disconnection, control metrics continue to serve their last known values, the `loxone_exporter_connected` gauge is set to 0, and `loxone_exporter_last_update_timestamp_seconds` stops advancing — enabling users to detect staleness.
4. **Given** the exporter reconnects after a disconnection, **When** the connection is re-established, **Then** the exporter re-downloads the structure file (to capture any configuration changes made during downtime) and re-enables status updates.

---

### User Story 4 - Prometheus-Compliant Metric Naming and Low Cardinality (Priority: P4)

As a home automation operator, I want all exported metrics to follow Prometheus naming conventions with low-cardinality labels, so that my Prometheus instance can efficiently store and query Loxone data without performance issues.

**Why this priority**: Correct metric naming and low cardinality are essential for long-term Prometheus health. Poor naming or high cardinality can make the monitoring system unusable. This story codifies the metric design principles.

**Independent Test**: Can be tested by scraping `/metrics` and programmatically validating that all metric names match the `loxone_<subsystem>_<metric>_<unit>` pattern, all metrics have HELP and TYPE annotations, and label cardinality stays within expected bounds.

**Acceptance Scenarios**:

1. **Given** the exporter is serving metrics, **When** `/metrics` is scraped, **Then** all Loxone control metrics follow the naming convention `loxone_control_value` (gauge) with labels `miniserver`, `name`, `room`, `category`, `type`, and `subcontrol`, and all self-health metrics follow `loxone_exporter_<metric>_<unit>`.
2. **Given** the exporter serves metrics, **When** analyzed for cardinality, **Then** the total number of unique label combinations per metric stays below 10 × the number of physical controls (labels are bounded by Miniserver configuration, not by unbounded user input).
3. **Given** the exporter has discovered controls, **When** `/metrics` is scraped, **Then** every metric has a `# HELP` line explaining what it represents and a `# TYPE` line declaring its metric type (gauge, counter, info).
4. **Given** controls have non-ASCII or special characters in their names, **When** these are used as label values, **Then** the values are preserved as-is (Prometheus supports UTF-8 label values) while label *names* conform to `[a-zA-Z_][a-zA-Z0-9_]*`.

---

### Edge Cases

- **Miniserver unreachable at startup**: The exporter MUST start gracefully, expose health metrics indicating a connection failure, and retry connecting with backoff. It MUST NOT crash or exit on transient network errors.
- **Miniserver firmware update/reboot**: The exporter MUST detect the disconnection, wait for the Miniserver to return, and re-establish connection and discovery automatically.
- **Structure file changes (new controls added)**: When the Miniserver configuration changes and the exporter reconnects, newly added controls MUST appear in metrics and removed controls MUST stop being exported (stale marker or removal).
- **Non-numeric control values**: Controls with purely textual state (e.g., TextState) MUST be excluded from export by default. A configuration option MUST allow users to opt in to exporting them as info-type metrics with the text value as a label. Boolean/digital values MUST be exported as 0/1 gauges.
- **Very large Miniserver configurations**: The exporter MUST handle Miniservers with 500+ controls without degraded performance or excessive memory usage.
- **Concurrent scrapes**: Multiple simultaneous Prometheus scrape requests MUST be handled safely without data races or inconsistent metric snapshots.
- **Credentials rotation**: If Miniserver credentials are changed, the exporter MUST detect authentication failures and log a clear error message rather than silently failing.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST connect to a Loxone Miniserver via WebSocket and download its structure file (`LoxAPP3.json`) to discover all controls, rooms, and categories.
- **FR-002**: System MUST subscribe to real-time value change events from the Miniserver via WebSocket (`enablebinstatusupdate`) and maintain an in-memory representation of current control values.
- **FR-003**: System MUST expose an HTTP endpoint (`/metrics`) serving all discovered control values as Prometheus-formatted metrics (Prometheus text exposition format).
- **FR-004**: System MUST name all metrics following Prometheus conventions: `loxone_<subsystem>_<metric>_<unit>` prefix, with `# HELP` and `# TYPE` annotations for every metric.
- **FR-005**: System MUST assign the following labels to each control metric: `miniserver` (miniserver name from config), `name` (control name), `room` (room name or empty), `category` (category name or empty), `type` (Loxone control type, e.g., "Switch", "Jalousie", "IRoomControllerV2"), and `subcontrol` (sub-control state name, e.g., "tempActual", "tempTarget", or "active" for simple controls).
- **FR-006**: System MUST export digital control values as gauge 0 or 1, and analog control values as gauge with their numeric value.
- **FR-007**: System MUST support a YAML configuration file allowing users to specify: Miniserver host/port, credentials, and exclusion lists (by room name, control type, and control name pattern). Credentials and other sensitive values MUST be overridable via environment variables; when an environment variable is set, it takes precedence over the corresponding config file value.
- **FR-007a**: System MUST exclude controls with purely textual (non-numeric, non-boolean) values from export by default. A configuration option MUST allow users to opt in to exporting these controls as Prometheus info-type metrics, with the text value exposed as a label.
- **FR-008**: System MUST expose exporter self-health metrics: `loxone_exporter_up` (exporter process liveness), `loxone_exporter_connected` (per-miniserver gauge, 1 when WebSocket connected, 0 when disconnected), `loxone_exporter_last_update_timestamp_seconds` (per-miniserver Unix timestamp of the last received value event), `loxone_exporter_scrape_duration_seconds`, `loxone_exporter_scrape_errors_total`, `loxone_exporter_controls_discovered`, `loxone_exporter_controls_exported`.
- **FR-009**: System MUST handle WebSocket disconnections gracefully with automatic reconnection using exponential backoff (starting at 1 second, max 30 seconds).
- **FR-010**: System MUST re-discover controls (re-download structure file) upon reconnection to the Miniserver.
- **FR-011**: System MUST support Loxone token-based authentication (firmware ≥9.x) and hash-based authentication (firmware 8.x).
- **FR-012**: System MUST expose a health check endpoint (`/healthz`) returning HTTP 200 when operational.
- **FR-013**: System MUST provide structured logging (JSON format) with configurable log levels.
- **FR-014**: System MUST handle graceful shutdown on SIGTERM (close WebSocket, finish pending scrapes, exit cleanly).
- **FR-015**: System MUST NOT make any network calls other than to the configured Loxone Miniserver(s). No telemetry, update checks, or external service dependencies.
- **FR-016**: System MUST keep label cardinality low: labels are derived only from Miniserver structure (rooms, categories, types), never from unbounded runtime data.
- **FR-017**: System MUST export a build info metric (`loxone_exporter_build_info`) as an info-type gauge with labels for version, commit, and build date.
- **FR-018**: System MUST support monitoring multiple Miniservers from a single exporter instance, distinguishing them via a `miniserver` label.
- **FR-019**: System MUST detect authentication failures on connection or reconnection attempts, log a clear error message identifying the affected Miniserver, and continue retrying with backoff rather than crashing.

### Key Entities

- **Miniserver**: The Loxone Miniserver being monitored. Key attributes: host, port, credentials, serial number, firmware version. One exporter instance may monitor one or more Miniservers.
- **Control**: A Loxone functional block (e.g., Switch, Dimmer, IRoomControllerV2, Jalousie). Key attributes: UUID, name, type, associated room, associated category, current value(s). Controls may have sub-controls with their own values.
- **Room**: A logical grouping of controls defined in Loxone Config. Key attributes: UUID, name. Used as a label on metrics.
- **Category**: A functional grouping of controls (e.g., "Lights", "Blinds", "Temperature"). Key attributes: UUID, name, type. Used as a label on metrics.
- **Metric**: A Prometheus time series derived from a control value. Key attributes: metric name, type (gauge/counter/info), labels, current value. One control may produce multiple time series — complex controls (e.g., IRoomControllerV2) emit one `loxone_control_value` gauge per sub-control state, differentiated by the `subcontrol` label (e.g., `tempActual`, `tempTarget`, `mode`). Simple controls (e.g., Switch) use their state name in the `subcontrol` label (e.g., `active`).

## Assumptions

- The Loxone Miniserver exposes its structure file at the standard path (`/data/LoxAPP3.json`) and supports the WebSocket API for real-time value events.
- Token-based authentication (firmware ≥9.x) is the primary authentication method. Hash-based authentication is supported as a fallback for older firmware.
- The structure file is the single source of truth for available controls, rooms, and categories. No additional configuration mapping is needed beyond what the Miniserver provides.
- Prometheus scrapes the exporter at intervals configured in Prometheus (typically 15s–60s). The exporter does not push metrics; it exposes them for pull-based scraping.
- A typical residential Miniserver has 50–300 controls. Enterprise installations may have up to 500+.
- Standard Prometheus resource consumption guidelines apply: exporters should be lightweight (≤50MB memory, minimal CPU).
- TLS for the exporter HTTP endpoint is out of scope for v1.0. The exporter listens on plain HTTP; TLS can be terminated at a reverse proxy if needed.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can deploy the exporter, point it at a Loxone Miniserver, and see all discoverable control values in Prometheus within 5 minutes of initial setup (excluding Prometheus configuration time).
- **SC-002**: 100% of numeric control values available in the Miniserver structure file are exported as Prometheus gauges without manual per-control configuration.
- **SC-003**: Total label cardinality (unique time series count) stays proportional to the number of controls — specifically, no more than 3× the number of exported controls (accounting for sub-controls and multi-value controls like IRoomControllerV2).
- **SC-004**: The exporter recovers from a Miniserver disconnection (network drop, reboot, firmware update) automatically within 60 seconds of the Miniserver becoming available again, without manual intervention.
- **SC-005**: The exporter consumes less than 50MB of memory and less than 5% of a single CPU core under normal operation with a 300-control Miniserver.
- **SC-006**: Metric values are updated within 2 seconds of a value change occurring on the Miniserver (assuming active WebSocket connection).
- **SC-007**: Exclusion rules reduce the exported metric count by the expected amount — excluding a room with N controls results in exactly N fewer exported control time series.
