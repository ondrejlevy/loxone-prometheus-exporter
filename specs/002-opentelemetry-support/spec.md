# Feature Specification: OpenTelemetry Metrics Export Support

**Feature Branch**: `002-opentelemetry-support`  
**Created**: 2026-02-08  
**Status**: Draft  
**Input**: User description: "do projektu chceme pridat podporu pro vystup ve formatu opentelemetry. tz to aby aplikace umela posilat metriky na otel collector ktery by byl definovany v konfiguraci. podpora by by mela jit pres nastaveni vypnout"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Enable OpenTelemetry Export (Priority: P1)

Operators want to send Loxone metrics to their existing OpenTelemetry infrastructure instead of or alongside Prometheus scraping. The application reads OpenTelemetry collector connection details from configuration and pushes metrics at regular intervals.

**Why this priority**: This is the core functionality - without it, users cannot integrate the exporter with OpenTelemetry-based monitoring stacks. It delivers immediate value by enabling metrics export to OTLP endpoints.

**Independent Test**: Can be fully tested by configuring an OTLP endpoint, starting the exporter, and verifying that metrics appear in the OpenTelemetry collector. Delivers value by allowing metrics to flow to existing observability platforms.

**Acceptance Scenarios**:

1. **Given** the configuration file contains valid OpenTelemetry collector settings, **When** the exporter starts, **Then** it successfully connects to the collector and begins sending metrics
2. **Given** the exporter is running with OpenTelemetry enabled, **When** Loxone control values change, **Then** updated metrics are sent to the OpenTelemetry collector within the configured export interval
3. **Given** the OpenTelemetry collector endpoint is unreachable, **When** the exporter attempts to send metrics, **Then** it logs connection errors and continues operating normally (metrics remain available via Prometheus endpoint)

---

### User Story 2 - Configure Export Behavior (Priority: P2)

Operators need to control when and how metrics are exported to OpenTelemetry, including the ability to disable the feature entirely, configure export intervals, and set collector connection parameters.

**Why this priority**: Configuration flexibility is essential for production deployments, but the basic export functionality (P1) must exist first. This enables operators to optimize resource usage and adapt to different infrastructure requirements.

**Independent Test**: Can be tested by trying different configuration combinations (disabled, different intervals, various endpoints) and verifying the exporter behaves accordingly. Delivers value by making the feature adaptable to different environments.

**Acceptance Scenarios**:

1. **Given** OpenTelemetry export is disabled in configuration, **When** the exporter starts, **Then** no OpenTelemetry connection is attempted and metrics are only available via Prometheus endpoint
2. **Given** a custom export interval is configured, **When** metrics are exported, **Then** exports occur at the specified interval rather than the default
3. **Given** authentication credentials are provided in configuration, **When** connecting to the OpenTelemetry collector, **Then** credentials are used in the OTLP requests

---

### User Story 3 - Monitor Export Health (Priority: P3)

Operators want to verify that OpenTelemetry export is functioning correctly through health metrics and status endpoints, similar to how Prometheus scrape health is currently monitored.

**Why this priority**: Health monitoring is important for production operations but requires the core export functionality to exist first. It complements the primary export feature by providing observability into the exporter itself.

**Independent Test**: Can be tested by checking health endpoints and metrics when OpenTelemetry is enabled/disabled, connected/disconnected. Delivers value by providing operational visibility into the export pipeline.

**Acceptance Scenarios**:

1. **Given** OpenTelemetry export is enabled and connected, **When** health metrics are queried, **Then** metrics indicate successful connection and last export timestamp
2. **Given** the OpenTelemetry collector becomes unavailable, **When** health status is checked, **Then** the health endpoint indicates degraded status but overall exporter remains operational
3. **Given** OpenTelemetry export is disabled, **When** health metrics are queried, **Then** metrics indicate the feature is intentionally disabled (not an error state)

---

### Edge Cases

- What happens when the OpenTelemetry collector endpoint is temporarily unavailable? (System should retry with backoff and continue operating)
- How does the system handle invalid OpenTelemetry configuration? (System should fail to start with clear error message, or fall back to Prometheus-only mode depending on configuration)
- What happens when both Prometheus scraping and OpenTelemetry push are enabled simultaneously? (Both should work independently - Prometheus pull and OTLP push)
- How does the system handle authentication failures to the OpenTelemetry collector? (Log authentication errors, retry with backoff, remain operational for Prometheus)
- What happens when metric export takes longer than the export interval? (Skip the interval and export on next cycle, or queue exports - [NEEDS CLARIFICATION: should exports queue or skip on overlap?])

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST support sending metrics to an OpenTelemetry collector via OTLP (OpenTelemetry Protocol)
- **FR-002**: System MUST read OpenTelemetry collector connection details from configuration file (endpoint URL, port, protocol)
- **FR-003**: System MUST allow OpenTelemetry export to be enabled or disabled via configuration setting
- **FR-004**: System MUST export the same metrics currently exposed via Prometheus endpoint (loxone_control_value, self-health metrics)
- **FR-005**: System MUST support configurable export interval for pushing metrics to OpenTelemetry collector
- **FR-006**: System MUST continue operating and serving Prometheus metrics even when OpenTelemetry collector is unreachable
- **FR-007**: System MUST log OpenTelemetry connection status, export success/failures with appropriate log levels
- **FR-008**: System MUST support TLS/SSL connections to OpenTelemetry collectors when configured
- **FR-009**: System MUST support authentication headers for OpenTelemetry collectors (API keys, tokens)
- **FR-010**: System MUST provide health metrics indicating OpenTelemetry export status and connection state
- **FR-011**: System MUST handle both gRPC and HTTP protocols for OTLP as specified in configuration [NEEDS CLARIFICATION: should both gRPC and HTTP protocols be supported, or just one initially?]
- **FR-012**: System MUST preserve metric metadata (labels, descriptions) when converting from Prometheus format to OTLP format
- **FR-013**: System MUST use exponential backoff when retrying failed exports to OpenTelemetry collector [NEEDS CLARIFICATION: should there be a maximum retry limit or should it retry indefinitely?]

### Key Entities *(include if feature involves data)*

- **OpenTelemetry Configuration**: Settings that define how the exporter connects to and communicates with the OpenTelemetry collector, including endpoint URL, port, protocol type (gRPC/HTTP), TLS settings, authentication credentials, export interval, and enabled/disabled state

- **OTLP Metrics Batch**: A collection of metrics formatted according to OpenTelemetry Protocol specification, containing resource attributes (application metadata), scope metrics (instrumentation information), and data points with timestamps and values

- **Export Status**: State information tracking the health of OpenTelemetry export, including connection state, last successful export timestamp, consecutive failure count, and error messages

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Operators can configure and enable OpenTelemetry export without modifying code, using only configuration file changes
- **SC-002**: Metrics appear in the OpenTelemetry collector within 2x the configured export interval after a value change in Loxone
- **SC-003**: System continues serving Prometheus metrics with zero interruption when OpenTelemetry collector is unavailable
- **SC-004**: OpenTelemetry export can be completely disabled, resulting in zero network traffic to collector endpoints
- **SC-005**: Configuration validation catches invalid settings before exporter startup, providing clear error messages
- **SC-006**: Health endpoints accurately reflect OpenTelemetry export status within 5 seconds of state changes
- **SC-007**: System handles export of 1000+ metrics to OpenTelemetry collector without degradation in Prometheus scrape performance

## Assumptions

- OpenTelemetry collectors are standard OTLP-compatible endpoints (OpenTelemetry Collector, cloud vendor OTLP endpoints, etc.)
- Operators have network connectivity from the exporter to their OpenTelemetry collectors
- The existing metric collection and storage mechanism in the exporter can support dual export (Prometheus pull + OTLP push)
- OpenTelemetry authentication typically uses headers with API keys or tokens (not certificate-based authentication initially)
- Export intervals are measured in seconds, with typical range of 10-60 seconds
- The application will use standard OpenTelemetry SDK libraries for the implementation language
- Default export interval is 30 seconds if not specified in configuration
- Default protocol is gRPC if not specified in configuration
- TLS is disabled by default and must be explicitly enabled in configuration
