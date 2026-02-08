# Internal Module Contracts

Interfaces and behavioral contracts between internal modules. These are not formal
API schemas but define the boundaries between components for implementation guidance.

## Module Dependency Graph

```
__main__.py
    │
    ▼
config.py ──── loads YAML + env vars ──► ExporterConfig
    │
    ▼
server.py ──── aiohttp app, /metrics + /healthz
    │
    ▼
metrics.py ──── CustomCollector.collect()
    │                  │
    ▼                  ▼ reads
loxone_client.py   MiniserverState (in-memory)
    │
    ├── loxone_auth.py ──── token-based auth flow
    │       │
    │       ▼
    │   loxone_protocol.py ──── binary message parsing
    │
    ▼
structure.py ──── LoxAPP3.json → Controls, Rooms, Categories, StateMap
```

## Contract: config.py

### `load_config(path: str | None) -> ExporterConfig`

- If `path` is None, attempts to load from default locations: `./config.yml`, `./config.yaml`
- Merges environment variable overrides on top of YAML values
- Validates all fields per config-schema.md rules
- Raises `ConfigError` with descriptive message on any validation failure
- Returns fully validated `ExporterConfig` dataclass instance

### `ExporterConfig`

- Immutable after creation (frozen dataclass or similar)
- All miniserver entries have `name`, `host`, `username`, `password` populated
- Defaults applied for optional fields

## Contract: loxone_client.py

### `class LoxoneClient`

Manages WebSocket connection lifecycle for a single Miniserver.

```python
async def connect(self) -> None:
    """
    Establish WebSocket connection, authenticate, download structure,
    and subscribe to binary status updates.
    
    Updates MiniserverState.connected = True on success.
    Raises LoxoneConnectionError on failure (caller handles retry).
    """

async def run(self) -> None:
    """
    Main loop: connect, then read messages forever.
    Implements auto-reconnect with exponential backoff (1s → 300s).
    Sends keepalive every 30 seconds.
    
    Only returns on graceful shutdown (asyncio.CancelledError).
    """

def get_state(self) -> MiniserverState:
    """
    Returns current MiniserverState snapshot.
    Thread-safe: called from metrics collector during /metrics scrape.
    """
```

### Event Processing Contract

1. VALUE_STATES (type 2): Parse 24-byte entries, update `control.states[name].value`
2. TEXT_STATES (type 3): Parse UUID+text pairs, update `control.states[name].text`
3. Keepalive: Respond to keepalive messages within 5 seconds
4. OUT_OF_SERVICE header: Treat as disconnection, trigger reconnect

## Contract: loxone_auth.py

### `async def authenticate(ws, username, password) -> bool`

Attempts token-based authentication first, falls back to hash-based.

Token-based flow:
1. Request RSA public key from Miniserver
2. Generate AES-256 session key + IV
3. Encrypt session key with RSA public key
4. Exchange encrypted session key
5. Compute HMAC-SHA256 of credentials with session key
6. Send encrypted auth command
7. Parse token response

Hash-based fallback:
1. Request key from `jdev/sys/getkey2/{user}`
2. Compute `HMAC-SHA1(user:password, key)`
3. Send `authenticate/{hash}`

Returns `True` on success, raises `AuthenticationError` on failure.

## Contract: loxone_protocol.py

### `parse_header(data: bytes) -> MessageHeader`

```python
@dataclass
class MessageHeader:
    msg_type: int          # 0-7 (TEXT, FILE, EVENT_TABLE, OUT_OF_SERVICE, KEEPALIVE, WEATHER_TABLE, VALUE_STATES, TEXT_STATES)
    exact_length: int      # Payload length
    estimated: bool        # True if length is estimated
```

Parses 8-byte binary header: `struct.unpack("<BBBxI", data)`.

### `parse_value_states(payload: bytes) -> list[tuple[str, float]]`

Parses packed 24-byte entries. Returns list of `(uuid_str, value)` tuples.
UUID conversion: first 3 groups little-endian, last 2 groups big-endian (Loxone mixed-endian format).

### `parse_text_states(payload: bytes) -> list[tuple[str, str]]`

Parses UUID + null-terminated text pairs from payload.

## Contract: structure.py

### `parse_structure(data: dict) -> tuple[dict[str, Control], dict[str, Room], dict[str, Category], dict[str, StateRef]]`

Parses the LoxAPP3.json response into typed data structures.

1. Parse `rooms` → `dict[str, Room]`
2. Parse `cats` → `dict[str, Category]`
3. Parse `controls` → `dict[str, Control]`, including:
   - Flatten `subControls` into main control as nested `Control` objects
   - Build `state_map`: for each `control.states[name] = uuid`, create `state_map[uuid] = StateRef(control_uuid, name)`
   - Detect text-only controls (mark `is_text_only = True`)
4. Return all four dictionaries

## Contract: metrics.py

### `class LoxoneCollector`

Implements `prometheus_client.registry.Collector` protocol.

```python
def collect(self) -> Iterator[Metric]:
    """
    Called on every /metrics scrape by prometheus_client.
    
    1. Iterate all MiniserverState instances
    2. For each connected miniserver:
       a. Yield loxone_control_value GaugeMetricFamily for each numeric state
       b. If include_text_values: yield loxone_control_info for text states
       c. Yield loxone_exporter_connected = 1
       d. Yield loxone_exporter_last_update_timestamp_seconds
       e. Yield loxone_exporter_controls_discovered
       f. Yield loxone_exporter_controls_exported
    3. For each disconnected miniserver:
       a. Yield loxone_exporter_connected = 0
    4. Yield exporter-level metrics (up, scrape_duration, build_info)
    
    Must NOT block or make network calls — reads in-memory state only.
    Must apply exclusion filters (rooms, types, names) from config.
    """
```

**Counter handling**: `loxone_exporter_scrape_errors_total` is a Counter — register it separately with `REGISTRY` at module level (not inside `collect()`). Increment via `.inc()` in the HTTP handler's error path. Custom collectors can only yield Gauge/Info families; counters must live outside `collect()`.

### Label Construction

For each state entry, labels are built as:

```python
labels = {
    "miniserver": miniserver_state.config.name,
    "name": control.name,
    "room": rooms.get(control.room_uuid, Room("", "")).name,
    "category": categories.get(control.cat_uuid, Category("", "", "")).name,
    "type": control.type,
    "subcontrol": state_entry.state_name,
}
```

## Contract: server.py

### `async def create_app(config, clients) -> aiohttp.web.Application`

Creates aiohttp application with:
- `GET /metrics` → calls `prometheus_client.generate_latest()` → returns text; wraps call with timing to set `loxone_exporter_scrape_duration_seconds` (measures collect + serialization)
- `GET /healthz` → inspects client states → returns JSON per OpenAPI contract
- Graceful shutdown on SIGTERM/SIGINT: cancel client tasks, await cleanup

### Startup Sequence

```python
async def main(config: ExporterConfig) -> None:
    clients = [LoxoneClient(ms_config) for ms_config in config.miniservers]
    collector = LoxoneCollector(clients, config)
    REGISTRY.register(collector)
    
    app = await create_app(config, clients)
    
    async with asyncio.TaskGroup() as tg:
        for client in clients:
            tg.create_task(client.run())
        tg.create_task(run_http_server(app, config))
```
