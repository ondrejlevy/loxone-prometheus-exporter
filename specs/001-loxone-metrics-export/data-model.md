# Data Model: Loxone Miniserver Metrics Export to Prometheus

**Generated**: 2026-02-07 | **Branch**: `001-loxone-metrics-export`
**Spec**: [spec.md](spec.md) | **Research**: [research.md](research.md)

## Entity Relationship Diagram

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│   Miniserver    │      │      Room       │      │    Category     │
├─────────────────┤      ├─────────────────┤      ├─────────────────┤
│ name: str       │      │ uuid: str       │      │ uuid: str       │
│ host: str       │      │ name: str       │      │ name: str       │
│ port: int       │      └────────▲────────┘      │ type: str       │
│ serial: str     │               │               └────────▲────────┘
│ firmware: str   │               │                        │
│ connected: bool │      ┌────────┴────────────────────────┘
│ last_update: f  │      │ room_uuid       cat_uuid
└────────┬────────┘      │
         │ 1          ┌──┴──────────────┐        ┌─────────────────┐
         │            │    Control      │        │   StateEntry    │
         │ has many   ├─────────────────┤ 1    N ├─────────────────┤
         └───────────>│ uuid: str       │───────>│ state_uuid: str │
                      │ name: str       │        │ state_name: str │
                      │ type: str       │        │ value: float    │
                      │ room_uuid: str? │        │ text: str?      │
                      │ cat_uuid: str?  │        │ is_digital: bool│
                      │ is_text_only: b │        └─────────────────┘
                      │ sub_controls: [] │
                      └─────────────────┘
```

## Entities

### MiniserverConfig

Configuration for a single Miniserver connection. Loaded from YAML config + env var overrides.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | `str` | Yes | — | User-defined label, used as `miniserver` label in metrics |
| `host` | `str` | Yes | — | Hostname or IP address |
| `port` | `int` | No | `80` | WebSocket port |
| `username` | `str` | Yes | — | Loxone user (overridable via env var) |
| `password` | `str` | Yes | — | Loxone password (overridable via env var) |

**Validation rules**:
- `name` must be non-empty and unique across miniservers
- `host` must be a valid hostname or IPv4/IPv6 address
- `port` must be 1–65535
- `username` and `password` must be non-empty

### MiniserverState

Runtime state for an active Miniserver connection. In-memory only.

| Field | Type | Description |
|-------|------|-------------|
| `config` | `MiniserverConfig` | Reference to configuration |
| `serial` | `str` | From `msInfo.serialNr` |
| `firmware` | `str` | From `softwareVersion` array, joined |
| `connected` | `bool` | WebSocket connection active |
| `last_update_ts` | `float` | Unix timestamp of last received value event |
| `controls` | `dict[str, Control]` | Keyed by control UUID |
| `rooms` | `dict[str, Room]` | Keyed by room UUID |
| `categories` | `dict[str, Category]` | Keyed by category UUID |
| `state_map` | `dict[str, StateRef]` | Reverse mapping: state UUID → (control UUID, state name) |

### Room

| Field | Type | Source |
|-------|------|--------|
| `uuid` | `str` | Key in `LoxAPP3.json → rooms` |
| `name` | `str` | `rooms[uuid].name` |

### Category

| Field | Type | Source |
|-------|------|--------|
| `uuid` | `str` | Key in `LoxAPP3.json → cats` |
| `name` | `str` | `cats[uuid].name` |
| `type` | `str` | `cats[uuid].type` |

### Control

| Field | Type | Source |
|-------|------|--------|
| `uuid` | `str` | Key in `LoxAPP3.json → controls` |
| `name` | `str` | `controls[uuid].name` |
| `type` | `str` | `controls[uuid].type` (e.g., "Switch", "IRoomControllerV2") |
| `room_uuid` | `str \| None` | `controls[uuid].room` → Room lookup |
| `cat_uuid` | `str \| None` | `controls[uuid].cat` → Category lookup |
| `states` | `dict[str, StateEntry]` | Keyed by state name (e.g., "tempActual") |
| `sub_controls` | `list[Control]` | Nested controls from `subControls` |
| `is_text_only` | `bool` | True if all states are text-only (no numeric values) |

**Derived fields** (resolved at discovery time):
- `room_name` → `rooms[room_uuid].name` or `""`
- `category_name` → `categories[cat_uuid].name` or `""`

### StateEntry

Represents a single value-bearing state of a control.

| Field | Type | Description |
|-------|------|-------------|
| `state_uuid` | `str` | UUID from `control.states[state_name]` |
| `state_name` | `str` | Key in the control's `states` dict (e.g., "tempActual", "active") |
| `value` | `float \| None` | Last known numeric value (from VALUE_STATES binary events) |
| `text` | `str \| None` | Last known text value (from TEXT_STATES events) |
| `is_digital` | `bool` | True if this state represents a digital (boolean) value |

### StateRef

Reverse mapping entry used to look up incoming value events.

| Field | Type | Description |
|-------|------|-------------|
| `control_uuid` | `str` | UUID of the parent control |
| `state_name` | `str` | Name of the state within that control |

### ExporterConfig

Top-level YAML configuration structure.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `miniservers` | `list[MiniserverConfig]` | Yes | — | One or more Miniserver configs |
| `listen_port` | `int` | No | `9504` | HTTP server port for `/metrics` and `/healthz` |
| `listen_address` | `str` | No | `"0.0.0.0"` | HTTP server bind address |
| `log_level` | `str` | No | `"info"` | Logging level: debug, info, warning, error |
| `log_format` | `str` | No | `"json"` | Log format: json or text |
| `exclude_rooms` | `list[str]` | No | `[]` | Room names to exclude from export |
| `exclude_types` | `list[str]` | No | `[]` | Control types to exclude |
| `exclude_names` | `list[str]` | No | `[]` | Control name patterns (glob) to exclude |
| `include_text_values` | `bool` | No | `false` | Export text-only controls as info metrics |

**Env var override mapping**:
- `LOXONE_USERNAME` → `miniservers[0].username`
- `LOXONE_PASSWORD` → `miniservers[0].password`
- `LOXONE_HOST` → `miniservers[0].host`
- `LOXONE_PORT` → `miniservers[0].port`
- `LOXONE_LISTEN_PORT` → `listen_port`
- `LOXONE_LOG_LEVEL` → `log_level`

For multi-miniserver setups, env vars apply to the first miniserver entry. Additional miniservers must be configured in the YAML file.

## State Transitions

### Connection State Machine

```
                    ┌──────────────┐
                    │  DISCONNECTED │
                    └───────┬──────┘
                            │ start / reconnect
                            ▼
                    ┌──────────────┐
                    │  CONNECTING  │
                    └───────┬──────┘
                            │ ws connected
                            ▼
                    ┌──────────────┐
                    │ AUTHENTICATING│
                    └───────┬──────┘
                            │ auth success
                            ▼
                    ┌──────────────┐
                    │  DISCOVERING │──── download LoxAPP3.json
                    └───────┬──────┘     build state_map
                            │ structure loaded
                            ▼
                    ┌──────────────┐
                    │  SUBSCRIBING │──── send enablebinstatusupdate
                    └───────┬──────┘
                            │ initial values received
                            ▼
                    ┌──────────────┐
                    │   CONNECTED  │◄── keepalive every 30s
                    └───────┬──────┘
                            │ ws error / timeout / OUT_OF_SERVICE
                            ▼
                    ┌──────────────┐
                    │  BACKOFF     │──── exponential: 1s → 2s → 4s → ... → 300s
                    └───────┬──────┘
                            │ wait complete
                            ▼
                    (back to CONNECTING)
```

### Value Update Flow

```
Binary frame received (type 2: VALUE_STATES)
    │
    ▼ Parse 24-byte entries: (uuid, double_value)
    │
    ▼ Lookup state_map[uuid] → (control_uuid, state_name)
    │  └── If unknown UUID → log warning, skip
    │
    ▼ Update control.states[state_name].value = double_value
    │
    ▼ Update miniserver.last_update_ts = time.time()
    │
    Done (metric read happens on next /metrics scrape)
```

## Prometheus Metrics Schema

### Control Metrics

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `loxone_control_value` | gauge | `miniserver`, `name`, `room`, `category`, `type`, `subcontrol` | Current numeric value of a control state |
| `loxone_control_info` | info | `miniserver`, `name`, `room`, `category`, `type`, `subcontrol`, `value` | Text value of a control state (opt-in) |

### Exporter Self-Health Metrics

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `loxone_exporter_up` | gauge | — | 1 if exporter process is running |
| `loxone_exporter_connected` | gauge | `miniserver` | 1 if WebSocket connected, 0 if disconnected |
| `loxone_exporter_last_update_timestamp_seconds` | gauge | `miniserver` | Unix timestamp of last received value event |
| `loxone_exporter_scrape_duration_seconds` | gauge | — | Time taken to generate `/metrics` response |
| `loxone_exporter_scrape_errors_total` | counter | — | Total number of errors during metric generation |
| `loxone_exporter_controls_discovered` | gauge | `miniserver` | Number of controls found in structure file |
| `loxone_exporter_controls_exported` | gauge | `miniserver` | Number of controls exported (after exclusion filtering) |
| `loxone_exporter_build_info` | info | `version`, `commit`, `build_date` | Build metadata |

### Label Cardinality Analysis

| Label | Source | Bounded By | Typical Range |
|-------|--------|------------|---------------|
| `miniserver` | Config file `name` field | Number of configured miniservers | 1–3 |
| `name` | `control.name` from LoxAPP3.json | Number of controls | 50–500 |
| `room` | `rooms[uuid].name` | Number of rooms | 5–30 |
| `category` | `cats[uuid].name` | Number of categories | 5–20 |
| `type` | `control.type` | Number of distinct control types | 5–15 |
| `subcontrol` | `state_name` from `control.states` | States per control | 1–10 |

**Worst-case cardinality**: 3 miniservers × 500 controls × ~3 states/control = ~4,500 time series. Well within SC-003 bound (3× controls = 1,500 per miniserver, 4,500 total).
