# Feature Specification: Loxone Miniserver Syslog Integration

**Feature Branch**: `002-syslog-integration`  
**Created**: 2026-02-08  
**Status**: Draft  
**Input**: User description: "i want to add support for retriewing logs from loxone miniserver. miniserver support syslog format. check documentstion of loxone miniserver and api for more information about logs. logs will be sended either to grafana loki instance or stored to local disk"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Local Disk Log Storage (Priority: P1)

Operations team needs to retrieve and store system logs from Loxone Miniserver to local disk for debugging and compliance purposes. The logs contain system events, warnings, and errors in syslog format.

**Why this priority**: This is the foundational capability that enables log collection. It provides immediate value by allowing administrators to preserve logs without requiring external dependencies. Local storage serves as a fallback option and supports air-gapped environments.

**Independent Test**: Can be fully tested by configuring local disk storage, connecting to a Miniserver, and verifying that syslog-formatted log files are created on disk with proper timestamps and content. Delivers immediate value by preserving logs that would otherwise be lost when Miniserver log buffer rolls over.

**Acceptance Scenarios**:

1. **Given** the exporter is configured with local disk storage enabled and connected to a Miniserver, **When** system logs are available from the Miniserver, **Then** logs are written to local disk in syslog format with timestamp rotation
2. **Given** the exporter is retrieving logs, **When** a connection interruption occurs, **Then** the exporter resumes log retrieval from the last known position after reconnection without data loss
3. **Given** the exporter is writing logs to disk, **When** the disk reaches a configured storage threshold, **Then** the exporter rotates or archives old log files according to retention policy
4. **Given** the exporter has been running for 24 hours, **When** viewing the stored logs, **Then** all logs contain valid syslog format headers with facility, severity, timestamp, and hostname

---

### User Story 2 - Grafana Loki Integration (Priority: P2)

Operations team wants to send Loxone Miniserver logs to Grafana Loki for centralized log aggregation, correlation with metrics, and visualization in Grafana dashboards alongside Prometheus metrics.

**Why this priority**: Enables integration with modern observability stack, allowing correlation between metrics and logs. This is the primary use case for production monitoring but depends on external infrastructure (Loki instance).

**Independent Test**: Can be fully tested by configuring Loki endpoint, starting the exporter, and querying Loki to verify logs appear with proper labels and timestamps. Delivers value by enabling centralized monitoring and alerting based on log patterns.

**Acceptance Scenarios**:

1. **Given** the exporter is configured with Loki endpoint and credentials, **When** logs are retrieved from Miniserver, **Then** logs are sent to Loki with proper labels including miniserver name, severity, and facility
2. **Given** the exporter is sending logs to Loki, **When** Loki is temporarily unavailable, **Then** the exporter buffers logs and retries with exponential backoff without losing log entries
3. **Given** logs are being sent to Loki, **When** a user queries Loki for Miniserver logs, **Then** logs are searchable by miniserver name, timestamp, severity level, and message content
4. **Given** multiple Miniservers are configured, **When** logs are sent to Loki, **Then** each Miniserver's logs are properly labeled to distinguish the source

---

### User Story 3 - Dual Output Configuration (Priority: P3)

Operations team wants to send logs to both Grafana Loki (for real-time monitoring) and local disk (for compliance and backup) simultaneously.

**Why this priority**: Provides redundancy and supports hybrid use cases where both real-time monitoring and local archival are needed. This is an enhancement over single-output configurations.

**Independent Test**: Can be fully tested by configuring both Loki and local disk outputs, verifying logs appear in both destinations with identical content. Delivers value by eliminating the need to choose between real-time monitoring and long-term storage.

**Acceptance Scenarios**:

1. **Given** the exporter is configured with both Loki and local disk outputs, **When** logs are retrieved, **Then** identical log entries are sent to both destinations
2. **Given** dual output is configured, **When** Loki becomes unavailable, **Then** local disk logging continues uninterrupted and Loki delivery resumes when connectivity is restored
3. **Given** dual output is configured, **When** disk storage fails, **Then** Loki delivery continues and an error is logged about the disk failure

---

### User Story 4 - Log Filtering and Configuration (Priority: P4)

Administrators want to filter logs by severity level, control log retrieval frequency, and configure retention policies to manage storage and reduce noise.

**Why this priority**: Enhances operational control and reduces storage/bandwidth costs. This is an optimization feature that builds upon the core log retrieval functionality.

**Independent Test**: Can be fully tested by configuring various filter rules and retention policies, verifying only matching logs are stored/forwarded and old logs are removed per policy. Delivers value by reducing storage costs and focusing attention on relevant log entries.

**Acceptance Scenarios**:

1. **Given** the exporter is configured to filter logs at severity level "warning" and above, **When** logs are retrieved, **Then** only warning, error, and critical logs are stored/forwarded
2. **Given** a retention policy of 30 days is configured, **When** logs older than 30 days exist, **Then** these logs are automatically removed from local storage
3. **Given** log retrieval interval is set to 5 minutes, **When** the exporter runs, **Then** logs are retrieved every 5 minutes without gaps or duplicates

---

### Edge Cases

- What happens when Loxone Miniserver API is unavailable or returns authentication errors?
- How does the system handle malformed syslog entries from the Miniserver?
- What occurs when local disk is full and cannot write more logs?
- How are logs handled during Miniserver firmware updates or reboots?
- What happens when the exporter is restarted - does it retrieve historical logs or only new ones?
- How does the system handle clock skew between Miniserver and exporter?
- What occurs when Loki push endpoint rate-limits the exporter?
- How are logs managed when a Miniserver is removed from configuration?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST retrieve logs from Loxone Miniserver via the Miniserver API in syslog format
- **FR-002**: System MUST support storing retrieved logs to local disk filesystem
- **FR-003**: System MUST support sending retrieved logs to a Grafana Loki instance via Loki push API
- **FR-004**: System MUST allow configuration to enable local disk storage, Loki forwarding, or both simultaneously
- **FR-005**: System MUST preserve syslog format structure including facility, severity, timestamp, hostname, and message
- **FR-006**: System MUST authenticate with Loxone Miniserver using configured credentials before retrieving logs
- **FR-007**: System MUST handle connection interruptions gracefully and resume log retrieval without data loss
- **FR-008**: System MUST support multiple Miniserver instances with independent log retrieval configurations
- **FR-009**: System MUST implement retry logic with exponential backoff when Loki endpoint is unavailable
- **FR-010**: System MUST track the last retrieved log position per Miniserver to avoid duplicate log entries
- **FR-011**: System MUST rotate local log files when they reach a configurable size threshold
- **FR-012**: System MUST support filtering logs by minimum severity level (debug, info, warning, error, critical)
- **FR-013**: System MUST support configurable log retrieval intervals
- **FR-014**: System MUST support configurable log retention policies for local disk storage
- **FR-015**: System MUST label logs sent to Loki with miniserver name, severity, facility, and timestamp
- **FR-016**: System MUST provide health metrics for log retrieval status (connected, last retrieval time, errors)
- **FR-017**: System MUST log errors when disk storage operations fail but continue operation if Loki is available
- **FR-018**: System MUST buffer logs in memory when Loki is unavailable, up to a configurable limit
- **FR-019**: System MUST validate syslog format of retrieved logs and log warnings for malformed entries
- **FR-020**: System MUST handle [NEEDS CLARIFICATION: authentication method for Loki - basic auth, bearer token, or mTLS?]

### Key Entities

- **Syslog Entry**: Represents a single log entry from Miniserver containing facility (kernel, user, system, etc.), severity (emergency, alert, critical, error, warning, notice, info, debug), timestamp, hostname, process name, process ID, and message content
- **Log Destination**: Configuration defining where logs should be sent - either local disk path or Loki endpoint URL with credentials
- **Retrieval State**: Tracks the last successfully retrieved log timestamp and position for each Miniserver to enable resume after interruption
- **Log Buffer**: Temporary in-memory storage for logs when destination is temporarily unavailable, with size limits and overflow behavior

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Administrators can retrieve and store Miniserver logs within 60 seconds of configuration
- **SC-002**: System successfully retrieves and stores at least 1000 log entries per hour from a single Miniserver under normal load
- **SC-003**: Log retrieval latency from Miniserver to storage/forwarding is under 5 seconds for 95% of entries
- **SC-004**: Zero log entries are lost during planned restarts or connection interruptions
- **SC-005**: System handles simultaneous log retrieval from 10 Miniservers without performance degradation
- **SC-006**: 99% of logs sent to Loki are successfully delivered within the configured retry window
- **SC-007**: Local disk log files are readable and parseable by standard syslog analysis tools
- **SC-008**: System continues operating for at least 30 days without manual intervention or memory leaks
- **SC-009**: Configuration changes (adding/removing destinations) take effect within 30 seconds without data loss
- **SC-010**: Users can locate specific log entries in Loki within 10 seconds using standard query syntax

## Assumptions

- Loxone Miniserver firmware supports log retrieval via documented API endpoints
- Syslog format from Miniserver follows RFC 3164 or RFC 5424 standards
- Network connectivity between exporter and Miniserver is stable (occasional interruptions handled by retry logic)
- Grafana Loki instance (if used) is accessible via HTTP/HTTPS and supports the Loki push API
- Local disk has sufficient storage for the configured retention period
- System clock on exporter host is synchronized via NTP or similar mechanism
- Miniserver API provides log retrieval with filtering by timestamp to enable incremental fetches
- Log volume from a single Miniserver does not exceed 1000 entries per minute under normal operation
- Existing Prometheus metrics infrastructure remains the primary exporter function
- Authentication method for Miniserver log API uses same credentials as WebSocket connection for metrics
- Default Loki authentication method is HTTP Basic Auth (can be extended for other methods)
- Log entries from Miniserver are in chronological order or contain reliable timestamps for ordering

## Dependencies

- Loxone Miniserver API documentation for log retrieval endpoints
- Grafana Loki push API documentation and endpoint availability
- Python syslog parsing library or RFC-compliant parser
- Local filesystem with write permissions for log storage
- Network access from exporter to Miniserver and Loki (if configured)

## Scope

### In Scope

- Retrieving logs from Loxone Miniserver via API
- Storing logs to local disk in syslog format
- Forwarding logs to Grafana Loki
- Configuration for single or dual output destinations
- Log filtering by severity level
- Log file rotation and retention management
- Connection resilience with retry logic
- Health metrics for log retrieval status
- Multi-Miniserver support

### Out of Scope

- Parsing or transforming log message content beyond syslog format
- Real-time log streaming (logs retrieved at configured intervals, not live stream)
- Historical log retrieval from before exporter deployment
- Log encryption at rest on local disk
- Custom log output formats other than syslog
- Integration with log aggregators other than Loki (e.g., Elasticsearch, Splunk)
- Log-based alerting (handled by Loki/Grafana)
- Miniserver configuration changes via exporter
- Log replay or re-sending after successful delivery
