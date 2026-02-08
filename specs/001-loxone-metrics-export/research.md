# Research: Loxone Miniserver Metrics Export to Prometheus

**Generated**: 2026-02-07 | **Branch**: `001-loxone-metrics-export`
**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## R1: Python Version

**Decision**: Python 3.13 (`python:3.13-slim` Docker base image)

**Rationale**:
- Only version still in bugfix phase (EOL Oct 2029, ~3.5 years of binary releases)
- asyncio improvements directly relevant: `TaskGroup` nested cancellation fix (critical for WebSocket reconnect), `Queue.shutdown()` for SIGTERM, `Server.close_clients()` for HTTP endpoint shutdown
- Container-aware `os.process_cpu_count()` respects cgroup CPU limits
- All required libraries (websockets, aiohttp, prometheus_client) fully support 3.13

**Alternatives considered**:
- Python 3.12: Reasonable second choice, has `eager_task_factory` perf improvements. Rejected — entered security-only phase, no more bugfix binary releases.
- Python 3.11: Security-only since Oct 2024, EOL Oct 2027. Misses all asyncio perf improvements from 3.12+. Larger Docker images.
- Python 3.14: Too new (released Oct 2025). Library ecosystem edge cases possible.

**Docker image**: `python:3.13-slim` (Debian-based) over Alpine — `websockets` and `aiohttp` include C extensions that benefit from glibc. Avoids occasional musl DNS resolution quirks in long-running network daemons. Pin to `python:3.13.12-slim` for reproducible builds.

## R2: Prometheus Client Library

**Decision**: `prometheus_client` (official Python client) + `aiohttp.web` for HTTP server

**Rationale**:
- Official Prometheus project — 4,300 stars, 168 contributors, v0.24.1 (Jan 2026)
- **Custom collectors** via `GaugeMetricFamily` / `InfoMetricFamily` in `collect()` — ideal pattern for dynamic Loxone control discovery (controls appear/disappear on reconnect)
- Thread-safe `.set()` / `.inc()` operations, safe from async code
- Full feature set: Gauge, Counter, Info, labels, OpenMetrics text format, HELP/TYPE annotations — all required by spec
- Zero extra deps (pure Python)

**HTTP server**: `aiohttp.web` instead of built-in `start_http_server()` because:
- Built-in server runs in a daemon thread, cannot serve `/healthz`, cannot share asyncio event loop
- `aiohttp.web` runs in the same asyncio loop as the WebSocket client — single loop, clean shutdown
- Need custom routes: `/metrics` (calls `prometheus_client.generate_latest()`) + `/healthz`

**Alternatives rejected**:
- `prometheus-async`: Just a wrapper. Its `@time()` decorator not needed. Direct `prometheus_client` + `aiohttp` simpler.
- `aioprometheus`: Last commit 3 years ago. Non-standard API. No Info metric type. Dead project risk.
- `uvicorn/FastAPI`: Overkill for 2 routes on an exporter. Heavier dependency chain.

## R3: WebSocket Client Library

**Decision**: `websockets` library

**Rationale**:
- **Zero dependencies** (pure Python + optional C extension) — aligns with self-contained principle
- **Built-in reconnect** via `async for ws in connect(...)` — eliminates ~50 lines of boilerplate
- **Battle-tested with Loxone** — PyLoxone (primary Python Loxone integration, 275 stars) uses it in production
- Actively maintained: v16.0 released Jan 2026, 100% branch coverage, RFC 6455 compliant
- `await ws.recv()` returns `bytes` for binary frames, ready for `struct.unpack`
- Optional C extension for performance headroom

**Alternatives rejected**:
- `aiohttp` (WS client): 4+ deps, no built-in reconnect. Only useful if we needed HTTP client too (we don't — structure file can be fetched over WebSocket).
- `wsproto`: Too low-level (sans-I/O). Would require ~200 lines of connection management code that `websockets` provides out of the box.

## R4: Loxone WebSocket Protocol

### Connection Flow

1. HTTP GET `/jdev/cfg/apiKey` → version, serial number
2. HTTP GET `/data/LoxAPP3.json` → structure file (controls, rooms, categories)
3. Build state UUID → control mapping
4. WebSocket connect `ws://{host}/ws/rfc6455`
5. Key exchange: RSA-encrypt AES-256-CBC session key
6. Authenticate (token-based ≥9.x or hash-based 8.x)
7. Send `jdev/sps/enablebinstatusupdate`
8. Enter receive loop (header + payload framing)
9. Send `keepalive` every 30 seconds
10. On disconnect → reconnect with backoff → goto step 1

### Authentication — Token-Based (firmware ≥9.x)

1. GET `/jdev/sys/getPublicKey` → RSA 2048-bit public key (PEM)
2. Generate AES-256 key (32 bytes) + IV (16 bytes), RSA-encrypt, base64-encode
3. Send `jdev/sys/keyexchange/{base64_session_key}`
4. Send `jdev/sys/getkey2/{username}` → `key` (hex), `salt` (hex), `hashAlg` (SHA1/SHA256)
5. Compute `pwHash = HMAC(hashAlg, "utf8(user):utf8(password)", hex2bytes(key))`
6. Compute `hash = HMAC(hashAlg, "utf8(user):pwHash", hex2bytes(salt))`
7. Send `jdev/sys/gettoken/{hash}/{user}/{permission}/{uuid}/{client_name}` → token + validUntil
8. Token refresh: `jdev/sys/refreshtoken/{hash}/{user}` at 50% remaining lifetime
9. Subsequent connections: `jdev/sys/getkey` → hash token → `authwithtoken/{hash}/{user}`

**Crypto**: AES-256-CBC (32B key + 16B IV), RSA-2048, HMAC-SHA1/SHA256, PKCS7 padding. Loxone epoch: 2009-01-01T00:00:00.

### Authentication — Hash-Based (firmware 8.x)

1. Send `jdev/sys/getkey` → single-use key (hex)
2. Compute `HMAC-SHA1("utf8(user):utf8(password)", hex2bytes(key))`
3. Send `authenticate/{hash}`

### Structure File (LoxAPP3.json)

Top-level keys:
- `msInfo` — Miniserver metadata: `serialNr`, `msName`, `miniserverType` (0=Gen1, 1=Go Gen1, 2=Gen2, 3=Go Gen2, 4=Compact)
- `softwareVersion` — Firmware version array
- `controls` — Dictionary keyed by UUID
- `rooms` — Dictionary keyed by UUID, each has `name`
- `cats` — Dictionary keyed by UUID (categories), each has `name`

Control structure example:

```json
{
  "name": "Living Room Climate",
  "type": "IRoomControllerV2",
  "uuidAction": "15beed5b-01ab-d81f-ffff403fb0c34b9e",
  "room": "13efd3e5-019d-8ad2-ffff403fb0c34b9e",
  "cat": "152c22de-0338-94b5-ffff403fb0c34b9e",
  "states": {
    "tempActual": "15beed5b-...-state-uuid-1",
    "tempTarget": "15beed5b-...-state-uuid-2",
    "mode": "15beed5b-...-state-uuid-3"
  },
  "subControls": {
    "15beed5b-01ab-d7eb-...": {
      "name": "Heating and Cooling",
      "type": "IRCV2Daytimer",
      "states": {}
    }
  }
}
```

**Key insight**: `states` maps **state names** to **state UUIDs**. Binary value events contain these state UUIDs. Exporter must build reverse mapping: `state UUID → (control, state_name)`.

**Known control types**: Switch, TimedSwitch, Jalousie, Gate, Window, InfoOnlyAnalog, InfoOnlyDigital, TextInput, PresenceDetector, SmokeAlarm, IRoomControllerV2, IRoomController, Ventilation, LightControllerV2, Dimmer, EIBDimmer, AudioZoneV2, Slider, Alarm, Meter, Pushbutton, Webpage, Intercom.

### Binary Message Format

**Header** (8 bytes): `struct.unpack("<cBccI", data)` → `(0x03, identifier, info, reserved, payload_length)`

**Estimated length flag**: If `info & 0x01 != 0`, payload length is estimated — read next header for exact length before reading payload.

**Message types**:

| ID | Name | Payload |
|----|------|---------|
| 0 | TEXT | JSON response to commands |
| 1 | BINARY | Binary file (e.g., LoxAPP3.json over WS) |
| 2 | VALUE_STATES | **Primary**: packed 24-byte entries (UUID 16B LE + double 8B LE) |
| 3 | TEXT_STATES | Variable-length: UUID + icon UUID + length-prefixed UTF-8 text, 4-byte aligned |
| 4 | DAYTIMER_STATES | Schedule data (not needed for metrics) |
| 5 | OUT_OF_SERVICE | No payload — connection will close |
| 6 | KEEPALIVE | Keepalive response |
| 7 | WEATHER_STATES | Weather data (not needed for metrics) |

**Value States entry** (24 bytes each):

```python
event_uuid = uuid.UUID(bytes_le=payload[offset:offset+16])
value = struct.unpack("<d", payload[offset+16:offset+24])[0]
```

**Text States entry** (variable length, 4-byte aligned):
- 16 bytes: UUID (little-endian)
- 16 bytes: icon UUID
- 4 bytes: text length (uint32 LE)
- N bytes: UTF-8 text
- Padding to 4-byte boundary

**UUID encoding**: Mixed-endian (Microsoft GUID format). Python `uuid.UUID(bytes_le=data)` handles correctly. Loxone string format collapses last two UUID groups.

## R5: Crypto Library for Loxone Authentication

**Decision**: `pycryptodome`

**Rationale**:
- Required for RSA public key encryption (key exchange) and AES-256-CBC (session encryption)
- Self-contained, no system-level OpenSSL dependency
- BSD-2-Clause license
- Used by PyLoxone for the same purpose

**Alternatives considered**:
- `cryptography`: Uses OpenSSL bindings, heavier, requires system library. More capabilities than needed.
- Python stdlib `hashlib`: Sufficient for HMAC-SHA1/SHA256 but cannot do RSA or AES-CBC.

**Note**: HMAC-SHA1/SHA256 operations use Python stdlib `hashlib`/`hmac` modules — no external crypto library needed for those.

## R6: Dependency Summary

| Package | Version | Purpose | License | Transitive Deps |
|---------|---------|---------|---------|-----------------|
| `websockets` | 16.x | WebSocket client (Loxone connection) | BSD-3-Clause | 0 |
| `prometheus_client` | 0.24.x | Prometheus metrics exposition | Apache-2.0 | 0 |
| `aiohttp` | 3.13.x | HTTP server (/metrics, /healthz) | Apache-2.0 | 4 (attrs, multidict, yarl, frozenlist) |
| `PyYAML` | 6.x | YAML config file parsing | MIT | 0 |
| `pycryptodome` | 3.x | AES-256-CBC / RSA for Loxone auth | BSD-2-Clause | 0 |

**Total direct deps**: 5 | **Total transitive deps**: ~9 | All open-source, actively maintained.

## R7: Design Decisions Summary

| Decision | Choice | Key Reason |
|----------|--------|------------|
| Python version | 3.13 | Bugfix phase, asyncio TaskGroup fixes |
| Docker base | `python:3.13-slim` | glibc for C extensions, avoids musl DNS quirks |
| WebSocket client | `websockets` | Zero deps, built-in reconnect, proven with Loxone |
| Prometheus client | `prometheus_client` | Official, custom collectors, zero deps |
| HTTP server | `aiohttp.web` | Async, same event loop, multi-route |
| Config format | YAML (from spec clarification) | Prometheus ecosystem standard |
| Crypto | `pycryptodome` + stdlib `hmac` | Self-contained RSA/AES, stdlib for HMAC |
| Architecture | Single asyncio event loop | WS client + HTTP server share one loop, clean shutdown |
| Metrics pattern | Custom collector | Dynamic controls from LoxAPP3.json discovery, no registration churn |
