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


_VALID_LOG_LEVELS = {"debug", "info", "warning", "error"}
_VALID_LOG_FORMATS = {"json", "text"}
_HOSTNAME_RE = re.compile(
    r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)


@dataclass(frozen=True)
class MiniserverConfig:
    """Configuration for a single Loxone Miniserver connection.
    
    Encryption options:
    - use_encryption: Manually enable wss:// encrypted connections.
    - force_encryption: Require encryption and enable it from the start.
      Setting force_encryption=True implies use_encryption=True.
    - Auto-detection: When neither option is set, encryption is automatically
      enabled when Miniserver 2 (Gen2) is detected.
    """

    name: str
    host: str
    port: int = 80
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
        if ms.name in names:
            raise ConfigError(f"Duplicate miniserver name {ms.name!r}")
        names.add(ms.name)


def _build_ms_config(raw: dict[str, Any]) -> MiniserverConfig:
    """Build a MiniserverConfig from a raw dict."""
    return MiniserverConfig(
        name=str(raw.get("name", "")),
        host=str(raw.get("host", "")),
        port=int(raw.get("port", 80)),
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
    )

    _validate_config(config)
    return config
