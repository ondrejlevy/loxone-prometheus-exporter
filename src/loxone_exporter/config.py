"""Configuration loading with YAML file support and environment variable overrides."""

from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Raised when configuration is invalid or missing."""


# Alias used by OTLP exporter module
ConfigurationError = ConfigError


_VALID_LOG_LEVELS = {"debug", "info", "warning", "error"}
_VALID_LOG_FORMATS = {"json", "text"}
_HOSTNAME_RE = re.compile(
    r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)


@dataclass(frozen=True)
class TLSConfig:
    """TLS configuration for OTLP exporter."""

    enabled: bool = False
    cert_path: str | None = None


@dataclass(frozen=True)
class AuthConfig:
    """Authentication configuration for OTLP exporter."""

    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class OTLPConfiguration:
    """Configuration for OTLP metrics export."""

    enabled: bool = False
    endpoint: str = ""
    protocol: str = "grpc"
    interval_seconds: int = 30
    timeout_seconds: int = 15
    tls_config: TLSConfig = field(default_factory=TLSConfig)
    auth_config: AuthConfig = field(default_factory=AuthConfig)


@dataclass(frozen=True)
class MiniserverConfig:
    """Configuration for a single Loxone Miniserver connection.

    Encryption options:
    - use_encryption: Manually enable wss:// encrypted connections.
    - force_encryption: Require encryption and enable it from the start.
      Setting force_encryption=True implies use_encryption=True.
    - Auto-detection: When neither option is set, encryption is automatically
      enabled when Miniserver 2 (Gen2) is detected.
    - ssl_port: Port to use for encrypted connections (default: 443).
      When auto-detection triggers or use_encryption is enabled, this port is used.
    """

    name: str
    host: str
    port: int = 80
    ssl_port: int = 443
    username: str = ""
    password: str = ""
    use_encryption: bool = False
    force_encryption: bool = False


@dataclass(frozen=True)
class ExporterConfig:
    """Top-level exporter configuration."""

    miniservers: tuple[MiniserverConfig, ...]
    listen_port: int = 9504
    listen_address: str = "0.0.0.0"
    log_level: str = "info"
    log_format: str = "json"
    exclude_rooms: list[str] = field(default_factory=list)
    exclude_types: list[str] = field(default_factory=list)
    exclude_names: list[str] = field(default_factory=list)
    include_text_values: bool = False
    opentelemetry: OTLPConfiguration = field(default_factory=OTLPConfiguration)


def _validate_port(value: int, field_name: str) -> None:
    if not isinstance(value, int) or value < 1 or value > 65535:
        raise ConfigError(f"{field_name} must be between 1 and 65535, got {value}")


def _validate_host(host: str, context: str) -> None:
    """Validate that host is a valid IP address or hostname."""
    try:
        ipaddress.ip_address(host)
        return
    except ValueError:
        pass
    if not _HOSTNAME_RE.match(host):
        raise ConfigError(f"{context}: invalid host {host!r} — must be a valid IP or hostname")


def _validate_listen_address(address: str) -> None:
    """Validate listen_address is a valid bind address (IP or 0.0.0.0)."""
    try:
        ipaddress.ip_address(address)
    except ValueError:
        raise ConfigError(
            f"listen_address must be a valid IP address, got {address!r}"
        ) from None


def _validate_config(config: ExporterConfig) -> None:
    """Validate the fully assembled config and raise ConfigError on problems."""
    if not config.miniservers:
        raise ConfigError("At least one miniserver must be configured")

    _validate_port(config.listen_port, "listen_port")
    _validate_listen_address(config.listen_address)

    if config.log_level not in _VALID_LOG_LEVELS:
        raise ConfigError(
            f"log_level must be one of {sorted(_VALID_LOG_LEVELS)}, got {config.log_level!r}"
        )
    if config.log_format not in _VALID_LOG_FORMATS:
        raise ConfigError(
            f"log_format must be one of {sorted(_VALID_LOG_FORMATS)}, got {config.log_format!r}"
        )

    names: set[str] = set()
    for ms in config.miniservers:
        if not ms.host:
            raise ConfigError(f"Miniserver {ms.name!r}: host must not be empty")
        _validate_host(ms.host, f"Miniserver {ms.name!r}")
        if not ms.username:
            raise ConfigError(f"Miniserver {ms.name!r}: username must not be empty")
        if not ms.password:
            raise ConfigError(f"Miniserver {ms.name!r}: password must not be empty")
        if not ms.name:
            raise ConfigError("Miniserver name must not be empty")
        _validate_port(ms.port, f"Miniserver {ms.name!r} port")
        _validate_port(ms.ssl_port, f"Miniserver {ms.name!r} ssl_port")
        if ms.name in names:
            raise ConfigError(f"Duplicate miniserver name {ms.name!r}")
        names.add(ms.name)


def _build_ms_config(raw: dict[str, Any]) -> MiniserverConfig:
    """Build a MiniserverConfig from a raw dict."""
    return MiniserverConfig(
        name=str(raw.get("name", "")),
        host=str(raw.get("host", "")),
        port=int(raw.get("port", 80)),
        ssl_port=int(raw.get("ssl_port", 443)),
        username=str(raw.get("username", "")),
        password=str(raw.get("password", "")),
        use_encryption=bool(raw.get("use_encryption", False)),
        force_encryption=bool(raw.get("force_encryption", False)),
    )


def _safe_int(value: str, field_name: str) -> int:
    """Safely convert a string to int, raising ConfigError on failure."""
    try:
        return int(value)
    except ValueError:
        raise ConfigError(
            f"{field_name} must be a valid integer, got {value!r}"
        ) from None


def _validate_otlp_config(otlp: OTLPConfiguration) -> None:
    """Validate OTLP configuration. Raises ConfigurationError on problems.

    Only validates when enabled=true. When disabled, skips all checks.
    """
    # VR-001: enabled must be bool (already enforced by dataclass type)
    if not isinstance(otlp.enabled, bool):
        raise ConfigurationError(
            "Field 'opentelemetry.enabled' must be a boolean (true/false)"
        )

    if not otlp.enabled:
        return  # No further validation needed when disabled

    # VR-002: endpoint required when enabled
    if not otlp.endpoint:
        raise ConfigurationError(
            "Field 'opentelemetry.endpoint' is required when OTLP export is enabled"
        )

    # VR-003: endpoint must be valid URL with http/https
    from urllib.parse import urlparse

    parsed = urlparse(otlp.endpoint)
    if parsed.scheme not in ("http", "https"):
        raise ConfigurationError(
            f"Field 'opentelemetry.endpoint' must be a valid URL with http:// or "
            f"https:// scheme (got: '{otlp.endpoint}')"
        )

    # VR-004: port must be 1-65535
    if parsed.port is not None and (parsed.port < 1 or parsed.port > 65535):
        raise ConfigurationError(
            f"Endpoint port must be between 1 and 65535 (got: {parsed.port})"
        )

    # VR-005: protocol must be grpc or http
    if otlp.protocol not in ("grpc", "http"):
        raise ConfigurationError(
            f"Field 'opentelemetry.protocol' must be 'grpc' or 'http' (got: '{otlp.protocol}')"
        )

    # VR-006: interval_seconds must be 10-300
    if not isinstance(otlp.interval_seconds, int) or not (10 <= otlp.interval_seconds <= 300):
        raise ConfigurationError(
            f"Field 'opentelemetry.interval_seconds' must be an integer between "
            f"10 and 300 (got: {otlp.interval_seconds})"
        )

    # VR-007: timeout_seconds must be 5-60
    if not isinstance(otlp.timeout_seconds, int) or not (5 <= otlp.timeout_seconds <= 60):
        raise ConfigurationError(
            f"Field 'opentelemetry.timeout_seconds' must be an integer between "
            f"5 and 60 (got: {otlp.timeout_seconds})"
        )

    # VR-008: timeout < interval
    if otlp.timeout_seconds >= otlp.interval_seconds:
        raise ConfigurationError(
            f"Field 'opentelemetry.timeout_seconds' ({otlp.timeout_seconds}) must be "
            f"less than interval_seconds ({otlp.interval_seconds})"
        )

    # VR-009: TLS cert_path required when TLS enabled
    if otlp.tls_config.enabled and not otlp.tls_config.cert_path:
        raise ConfigurationError(
            "Field 'opentelemetry.tls.cert_path' is required when TLS is enabled"
        )

    # VR-010: TLS cert_path must exist and be readable
    if otlp.tls_config.cert_path:
        cert = Path(otlp.tls_config.cert_path)
        if not cert.exists() or not cert.is_file():
            raise ConfigurationError(
                f"TLS certificate file not found or not readable: {otlp.tls_config.cert_path}"
            )

    # VR-011: auth.headers must be dict or None
    if otlp.auth_config.headers is not None and not isinstance(otlp.auth_config.headers, dict):
        raise ConfigurationError(
            f"Field 'opentelemetry.auth.headers' must be a dictionary or null "
            f"(got: {type(otlp.auth_config.headers).__name__})"
        )


def _build_otlp_config(raw: dict[str, Any]) -> OTLPConfiguration:
    """Build OTLPConfiguration from raw YAML dict."""
    if not raw:
        return OTLPConfiguration()

    tls_raw = raw.get("tls", {})
    if not isinstance(tls_raw, dict):
        tls_raw = {}

    auth_raw = raw.get("auth", {})
    if not isinstance(auth_raw, dict):
        auth_raw = {}

    tls_config = TLSConfig(
        enabled=bool(tls_raw.get("enabled", False)),
        cert_path=tls_raw.get("cert_path"),
    )

    auth_headers = auth_raw.get("headers")
    auth_config = AuthConfig(
        headers=dict(auth_headers) if isinstance(auth_headers, dict) else {},
    )

    return OTLPConfiguration(
        enabled=bool(raw.get("enabled", False)),
        endpoint=str(raw.get("endpoint", "")),
        protocol=str(raw.get("protocol", "grpc")),
        interval_seconds=int(raw.get("interval_seconds", 30)),
        timeout_seconds=int(raw.get("timeout_seconds", 15)),
        tls_config=tls_config,
        auth_config=auth_config,
    )


def _apply_otlp_env_overrides(raw_otlp: dict[str, Any]) -> dict[str, Any]:
    """Apply LOXONE_OTLP_* environment variable overrides onto the raw OTLP config."""
    env_enabled = os.environ.get("LOXONE_OTLP_ENABLED")
    if env_enabled is not None:
        raw_otlp["enabled"] = env_enabled.lower() in ("true", "1", "yes")

    env_endpoint = os.environ.get("LOXONE_OTLP_ENDPOINT")
    if env_endpoint:
        raw_otlp["endpoint"] = env_endpoint

    env_protocol = os.environ.get("LOXONE_OTLP_PROTOCOL")
    if env_protocol:
        raw_otlp["protocol"] = env_protocol

    env_interval = os.environ.get("LOXONE_OTLP_INTERVAL")
    if env_interval:
        raw_otlp["interval_seconds"] = _safe_int(env_interval, "LOXONE_OTLP_INTERVAL")

    env_timeout = os.environ.get("LOXONE_OTLP_TIMEOUT")
    if env_timeout:
        raw_otlp["timeout_seconds"] = _safe_int(env_timeout, "LOXONE_OTLP_TIMEOUT")

    env_tls = os.environ.get("LOXONE_OTLP_TLS_ENABLED")
    if env_tls is not None:
        if "tls" not in raw_otlp:
            raw_otlp["tls"] = {}
        raw_otlp["tls"]["enabled"] = env_tls.lower() in ("true", "1", "yes")

    env_cert = os.environ.get("LOXONE_OTLP_TLS_CERT_PATH")
    if env_cert:
        if "tls" not in raw_otlp:
            raw_otlp["tls"] = {}
        raw_otlp["tls"]["cert_path"] = env_cert

    # Handle LOXONE_OTLP_AUTH_HEADER_* env vars
    for key, value in os.environ.items():
        if key.startswith("LOXONE_OTLP_AUTH_HEADER_"):
            header_name = key[len("LOXONE_OTLP_AUTH_HEADER_"):]
            if header_name:
                if "auth" not in raw_otlp:
                    raw_otlp["auth"] = {}
                if "headers" not in raw_otlp["auth"] or raw_otlp["auth"]["headers"] is None:
                    raw_otlp["auth"]["headers"] = {}
                # Convert env var name to proper header: AUTHORIZATION → Authorization
                raw_otlp["auth"]["headers"][header_name.replace("_", "-").title()] = value

    return raw_otlp


def _apply_env_overrides(
    raw_config: dict[str, Any],
) -> dict[str, Any]:
    """Apply LOXONE_ environment variable overrides onto the raw config dict."""
    if "miniservers" not in raw_config or not raw_config["miniservers"]:
        raw_config["miniservers"] = [{}]

    ms0 = raw_config["miniservers"][0]

    env_name = os.environ.get("LOXONE_NAME")
    env_host = os.environ.get("LOXONE_HOST")
    env_user = os.environ.get("LOXONE_USERNAME")
    env_pass = os.environ.get("LOXONE_PASSWORD")
    env_port = os.environ.get("LOXONE_PORT")
    env_listen_port = os.environ.get("LOXONE_LISTEN_PORT")
    env_log_level = os.environ.get("LOXONE_LOG_LEVEL")

    if env_host:
        ms0["host"] = env_host
    if env_user:
        ms0["username"] = env_user
    if env_pass:
        ms0["password"] = env_pass
    if env_port:
        ms0["port"] = _safe_int(env_port, "LOXONE_PORT")
    if env_name:
        ms0["name"] = env_name
    elif "name" not in ms0 or not ms0["name"]:
        # Default name to host value
        ms0["name"] = ms0.get("host", "")

    if env_listen_port:
        raw_config["listen_port"] = _safe_int(env_listen_port, "LOXONE_LISTEN_PORT")
    if env_log_level:
        raw_config["log_level"] = env_log_level

    return raw_config


def load_config(path: str | None) -> ExporterConfig:
    """Load configuration from a YAML file and/or environment variables.

    Args:
        path: Path to a YAML config file.  If ``None``, the function tries
            ``./config.yml`` and ``./config.yaml`` as defaults.  If no file
            is found, it falls back to env-only configuration.

    Returns:
        A fully validated :class:`ExporterConfig` instance.

    Raises:
        ConfigError: If the configuration is invalid or incomplete.
    """
    raw: dict[str, Any] = {}

    # Try loading YAML
    if path is not None:
        p = Path(path)
        if not p.exists():
            raise ConfigError(f"Config file not found: {path}")
        try:
            raw = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Failed to parse config file: {exc}") from exc
    else:
        # Try default locations
        for default in ("config.yml", "config.yaml"):
            dp = Path(default)
            if dp.exists():
                try:
                    raw = yaml.safe_load(dp.read_text()) or {}
                except yaml.YAMLError as exc:
                    raise ConfigError(f"Failed to parse {default}: {exc}") from exc
                break

    # Apply env var overrides
    raw = _apply_env_overrides(raw)

    # Check we have at least something
    ms_list = raw.get("miniservers", [])
    if not ms_list:
        raise ConfigError(
            "No configuration found. Provide a config file or set "
            "LOXONE_HOST, LOXONE_USERNAME, LOXONE_PASSWORD environment variables."
        )

    # Remove entries that have no host (e.g. empty dict from env-only fallback with no env set)
    ms_configs = []
    for ms_raw in ms_list:
        if isinstance(ms_raw, dict) and ms_raw.get("host"):
            ms_configs.append(_build_ms_config(ms_raw))

    if not ms_configs:
        raise ConfigError(
            "No valid miniserver configuration found. Each miniserver needs at least a host."
        )

    # Build OTLP configuration
    raw_otlp = raw.get("opentelemetry", {})
    if not isinstance(raw_otlp, dict):
        raw_otlp = {}
    raw_otlp = _apply_otlp_env_overrides(raw_otlp)
    otlp_config = _build_otlp_config(raw_otlp)

    config = ExporterConfig(
        miniservers=tuple(ms_configs),
        listen_port=int(raw.get("listen_port", 9504)),
        listen_address=str(raw.get("listen_address", "0.0.0.0")),
        log_level=str(raw.get("log_level", "info")),
        log_format=str(raw.get("log_format", "json")),
        exclude_rooms=list(raw.get("exclude_rooms", [])),
        exclude_types=list(raw.get("exclude_types", [])),
        exclude_names=list(raw.get("exclude_names", [])),
        include_text_values=bool(raw.get("include_text_values", False)),
        opentelemetry=otlp_config,
    )

    _validate_config(config)

    # Validate OTLP config — fails startup if invalid when enabled
    _validate_otlp_config(config.opentelemetry)

    return config
