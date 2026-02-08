<!--
SYNC IMPACT REPORT (Generated: 2026-02-07)
==============================================
Version Change: INITIAL → 1.0.0
Constitution Type: New constitution creation

Modified Principles:
- ADDED: I. Local-First Architecture (NON-NEGOTIABLE)
- ADDED: II. Self-Contained Solution (NON-NEGOTIABLE)
- ADDED: III. Observable Metrics Export
- ADDED: IV. Test-First Development
- ADDED: V. Simplicity & Maintainability

Added Sections:
- Deployment Constraints
- Development Workflow
- Governance

Template Updates Required:
✅ plan-template.md - Constitution Check section references this file
✅ spec-template.md - Requirements align with local-first principles
✅ tasks-template.md - Task categorization includes testing discipline
✅ checklist-template.md - Generic template, no changes needed
✅ agent-file-template.md - Generic template, no changes needed

Follow-up TODOs: None - all placeholders resolved

Notes:
- This is the initial constitution for Loxone Prometheus Exporter
- Emphasizes local deployment without cloud/external dependencies
- All principles are testable and enforceable
- Governance establishes amendment procedures for future changes
-->

# Loxone Prometheus Exporter Constitution

## Core Principles

### I. Local-First Architecture (NON-NEGOTIABLE)

The entire solution MUST be deployable and operational in a completely local environment without any cloud services or external dependencies beyond the target systems (Loxone Miniserver and Prometheus).

**Requirements:**
- All components run on local infrastructure (bare metal, VM, or containers)
- No external API calls except to the Loxone Miniserver being monitored
- No telemetry, analytics, or phone-home functionality
- Configuration via local files only (no remote config fetching)
- All dependencies must be vendorable or statically linkable where applicable

**Rationale:** Users deploying home automation monitoring must retain complete control and privacy. Cloud dependencies introduce security risks, privacy concerns, and single points of failure unacceptable in local infrastructure monitoring.

### II. Self-Contained Solution (NON-NEGOTIABLE)

The exporter MUST function as a standalone application with minimal external dependencies. Any required third-party libraries must be open-source, well-maintained, and essential to core functionality.

**Requirements:**
- Single binary or self-contained deployment artifact preferred
- Standard runtime dependencies only (system libraries, language runtime)
- No mandatory databases, message queues, or service meshes
- All features accessible through the core exporter process
- Documentation must include complete dependency list with versions and licenses

**Rationale:** Minimizing dependencies reduces attack surface, simplifies deployment, and ensures long-term maintainability. Home automation systems require stable, predictable infrastructure.

### III. Observable Metrics Export

All metrics exposed to Prometheus MUST follow Prometheus naming conventions and best practices. The exporter MUST provide comprehensive visibility into both Loxone system state and exporter health.

**Requirements:**
- Metric names follow `loxone_<subsystem>_<metric>_<unit>` convention
- All metrics include appropriate labels (miniserver, room, category, etc.)
- Exporter self-health metrics (scrape duration, error counts, connection status)
- HELP and TYPE annotations for all metrics
- Graceful handling of Loxone API unavailability (stale metrics vs. removal)

**Rationale:** Prometheus exporters are the primary interface for monitoring. Consistent, well-documented metrics enable effective alerting and dashboarding.

### IV. Test-First Development

Features MUST be developed following Test-Driven Development (TDD) practices. Tests verify contracts, integration points, and core functionality before implementation.

**Requirements:**
- Unit tests for metric transformation logic
- Integration tests against mock Loxone API responses
- Contract tests verifying Prometheus scrape endpoint compliance
- Tests written and reviewed before implementation begins
- Minimum 80% code coverage for non-trivial logic

**Rationale:** Monitoring infrastructure must be reliable. TDD ensures correctness, prevents regressions, and provides executable documentation of expected behavior.

### V. Simplicity & Maintainability

The solution MUST prioritize clarity and maintainability over premature optimization. Code should be self-documenting with explicit error handling.

**Requirements:**
- YAGNI principle: implement only requested features
- Clear separation: API client, metrics mapper, HTTP server
- Explicit error messages with context (which miniserver, what operation)
- Configuration validation with helpful error messages on startup
- Direct dependencies graph (avoid transitive dependency sprawl)

**Rationale:** Home automation systems are long-lived. Code maintainability over 5+ years is more valuable than marginal performance gains. New contributors should understand the codebase quickly.

## Deployment Constraints

**Local Hosting Requirements:**
- Must run on common Linux distributions (Debian, Ubuntu, Alpine) and container platforms (Docker, Podman)
- Resource footprint: ≤50MB memory, ≤5% CPU (single core) under normal load
- No privileged container capabilities required
- Configuration via environment variables and/or local config file (YAML/TOML)
- Graceful degradation: if Loxone unavailable, exporter continues serving with error metrics

**Security Posture:**
- Credential management: environment variables or file-based (no hardcoding)
- Support for Loxone token-based authentication
- Optional TLS for exporter HTTP endpoint
- No credential logging (sanitize logs)

**Operational Requirements:**
- Health check endpoint (`/health` or similar)
- Structured logging (JSON) with configurable verbosity
- Prometheus metrics endpoint on standard `/metrics` path
- Graceful shutdown (SIGTERM handling)

## Development Workflow

**Constitution Compliance:**
- All feature specifications must reference applicable principles
- Implementation plans must include justification for any new dependencies
- Code reviews verify: local-first architecture, no external calls, test coverage
- Dependency updates require security and license review

**Quality Gates:**
1. **Pre-implementation:** Spec reviewed, tests defined, dependencies justified
2. **Implementation:** Tests pass, coverage ≥80%, no linter violations
3. **Pre-merge:** Manual testing against real Loxone Miniserver (where possible), documentation updated

**Versioning:**
- Semantic versioning (MAJOR.MINOR.PATCH)
- MAJOR: Breaking configuration changes or metric name changes
- MINOR: New features, new metrics, backward-compatible changes
- PATCH: Bug fixes, documentation, dependency updates

## Governance

This constitution supersedes all other development practices and guidelines. All features, pull requests, and architectural decisions must comply with these principles.

**Amendment Process:**
1. Proposed changes documented with rationale and impact analysis
2. Review by maintainers (consensus required for NON-NEGOTIABLE principles)
3. Update constitution with version bump per semantic rules (see mode instructions)
4. Update affected templates (plan, spec, tasks) and agent guidance
5. Migrate existing code if necessary (grace period determined case-by-case)

**Enforcement:**
- All pull requests must pass Constitution Check (automated where possible)
- Violations of NON-NEGOTIABLE principles are blocking
- Complexity/dependency additions require explicit justification in PR description
- Maintainers may grant temporary exceptions for critical security fixes (must be documented)

**Living Document:**
- Constitution reviewed annually or when major architectural changes proposed
- User feedback and operational learnings inform amendments
- Changes tracked in git history with clear commit messages

**Version**: 1.0.0 | **Ratified**: 2026-02-07 | **Last Amended**: 2026-02-07
