# Configuration Schema Contract

**Format**: YAML
**File**: `config.yml` or `config.yaml`
**Env prefix**: `LOXONE_`

## Schema

```yaml
# Required: List of Miniserver connections
miniservers:
  - name: "home"                    # Required. Unique label → Prometheus `miniserver` label
    host: "192.168.1.100"           # Required. IP or hostname
    port: 80                        # Optional. Default: 80
    username: "prometheus"          # Required. Overridable via LOXONE_USERNAME env var
    password: "secret"              # Required. Overridable via LOXONE_PASSWORD env var

# HTTP server configuration
listen_port: 9504                   # Optional. Default: 9504
listen_address: "0.0.0.0"          # Optional. Default: "0.0.0.0"

# Logging configuration
log_level: "info"                   # Optional. Values: debug, info, warning, error. Default: "info"
log_format: "json"                  # Optional. Values: json, text. Default: "json"

# Filtering — all lists are optional, default empty
exclude_rooms: []                   # Room names to exclude from export
exclude_types: []                   # Control types to exclude (e.g., "TextState")
exclude_names: []                   # Control name patterns to exclude (glob syntax)

# Text control handling
include_text_values: false          # Optional. Default: false. Export text-only controls as info metrics
```

## Environment Variable Overrides

Environment variables take precedence over config file values. They apply to the **first** miniserver entry.

| Env Variable | Config Path | Type | Example |
|-------------|-------------|------|---------|
| `LOXONE_NAME` | `miniservers[0].name` | string | `home` (defaults to `LOXONE_HOST` if unset) |
| `LOXONE_USERNAME` | `miniservers[0].username` | string | `prometheus` |
| `LOXONE_PASSWORD` | `miniservers[0].password` | string | `secret123` |
| `LOXONE_HOST` | `miniservers[0].host` | string | `192.168.1.100` |
| `LOXONE_PORT` | `miniservers[0].port` | int | `80` |
| `LOXONE_LISTEN_PORT` | `listen_port` | int | `9504` |
| `LOXONE_LOG_LEVEL` | `log_level` | string | `debug` |

## Minimal Valid Config (env-only)

When all required fields come from environment variables, the config file may be omitted entirely. The exporter creates a default single-miniserver configuration from env vars.

```bash
LOXONE_HOST=192.168.1.100
LOXONE_USERNAME=prometheus
LOXONE_PASSWORD=secret
```

## Validation Rules

1. At least one miniserver must be configured (via YAML or env vars)
2. Each miniserver `name` must be unique across the list
3. `host` must be non-empty (valid hostname or IP)
4. `username` and `password` must be non-empty
5. `port` must be 1–65535
6. `listen_port` must be 1–65535
7. `log_level` must be one of: `debug`, `info`, `warning`, `error`
8. `log_format` must be one of: `json`, `text`
9. `exclude_names` entries are treated as glob patterns (using `fnmatch`)

## Error Behavior

- Missing required field → exit with error message and exit code 1
- Invalid field value → exit with error message and exit code 1
- Config file not found + no env vars → exit with usage help and exit code 1
- Config file parse error (invalid YAML) → exit with error message and exit code 1
