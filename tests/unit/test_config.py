"""Tests for config loading, env var overrides, and validation."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
import yaml

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all LOXONE_ environment variables."""
    for key in list(os.environ):
        if key.startswith("LOXONE_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    """Return path to a minimal valid config file."""
    cfg = {
        "miniservers": [
            {
                "name": "home",
                "host": "192.168.1.100",
                "username": "admin",
                "password": "secret",
            }
        ]
    }
    p = tmp_path / "config.yml"
    p.write_text(yaml.dump(cfg))
    return p


@pytest.fixture()
def multi_config_file(tmp_path: Path) -> Path:
    """Return path to a config with two miniservers."""
    cfg = {
        "miniservers": [
            {
                "name": "home",
                "host": "192.168.1.100",
                "username": "admin",
                "password": "secret",
            },
            {
                "name": "office",
                "host": "192.168.1.200",
                "username": "admin",
                "password": "secret2",
            },
        ],
        "listen_port": 9505,
        "log_level": "debug",
        "log_format": "text",
        "exclude_rooms": ["Test Room"],
        "exclude_types": ["Pushbutton"],
        "exclude_names": ["Debug_*"],
        "include_text_values": True,
    }
    p = tmp_path / "config.yml"
    p.write_text(yaml.dump(cfg))
    return p


# ── YAML file loading ──────────────────────────────────────────────────


@pytest.mark.usefixtures("_clean_env")
class TestYAMLLoading:
    def test_load_minimal_config(self, config_file: Path) -> None:
        from loxone_exporter.config import load_config

        config = load_config(str(config_file))
        assert len(config.miniservers) == 1
        ms = config.miniservers[0]
        assert ms.name == "home"
        assert ms.host == "192.168.1.100"
        assert ms.username == "admin"
        assert ms.password == "secret"
        assert ms.port == 80  # default

    def test_load_full_config(self, multi_config_file: Path) -> None:
        from loxone_exporter.config import load_config

        config = load_config(str(multi_config_file))
        assert len(config.miniservers) == 2
        assert config.listen_port == 9505
        assert config.log_level == "debug"
        assert config.log_format == "text"
        assert config.exclude_rooms == ["Test Room"]
        assert config.exclude_types == ["Pushbutton"]
        assert config.exclude_names == ["Debug_*"]
        assert config.include_text_values is True

    def test_defaults_applied(self, config_file: Path) -> None:
        from loxone_exporter.config import load_config

        config = load_config(str(config_file))
        assert config.listen_port == 9504
        assert config.listen_address == "0.0.0.0"
        assert config.log_level == "info"
        assert config.log_format == "json"
        assert config.exclude_rooms == []
        assert config.exclude_types == []
        assert config.exclude_names == []
        assert config.include_text_values is False


# ── Environment variable overrides ─────────────────────────────────────


@pytest.mark.usefixtures("_clean_env")
class TestEnvOverrides:
    def test_env_overrides_yaml(
        self, config_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from loxone_exporter.config import load_config

        monkeypatch.setenv("LOXONE_HOST", "10.0.0.1")
        monkeypatch.setenv("LOXONE_USERNAME", "env_user")
        monkeypatch.setenv("LOXONE_PASSWORD", "env_pass")
        monkeypatch.setenv("LOXONE_PORT", "8080")
        monkeypatch.setenv("LOXONE_LISTEN_PORT", "9999")
        monkeypatch.setenv("LOXONE_LOG_LEVEL", "debug")
        monkeypatch.setenv("LOXONE_NAME", "env_name")

        config = load_config(str(config_file))
        ms = config.miniservers[0]
        assert ms.host == "10.0.0.1"
        assert ms.username == "env_user"
        assert ms.password == "env_pass"
        assert ms.port == 8080
        assert ms.name == "env_name"
        assert config.listen_port == 9999
        assert config.log_level == "debug"

    def test_env_only_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Config file not needed when env vars provide all required fields."""
        from loxone_exporter.config import load_config

        monkeypatch.setenv("LOXONE_HOST", "192.168.1.50")
        monkeypatch.setenv("LOXONE_USERNAME", "prom")
        monkeypatch.setenv("LOXONE_PASSWORD", "pass123")

        config = load_config(None)
        assert len(config.miniservers) == 1
        ms = config.miniservers[0]
        assert ms.host == "192.168.1.50"
        assert ms.username == "prom"
        assert ms.password == "pass123"

    def test_env_only_name_defaults_to_host(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When LOXONE_NAME is not set, name defaults to LOXONE_HOST value."""
        from loxone_exporter.config import load_config

        # Change to temp dir to avoid loading default config.yml
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOXONE_HOST", "192.168.1.50")
        monkeypatch.setenv("LOXONE_USERNAME", "prom")
        monkeypatch.setenv("LOXONE_PASSWORD", "pass123")

        config = load_config(None)
        assert config.miniservers[0].name == "192.168.1.50"

    def test_env_only_name_explicit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When LOXONE_NAME is set, it overrides the default."""
        from loxone_exporter.config import load_config

        monkeypatch.setenv("LOXONE_HOST", "192.168.1.50")
        monkeypatch.setenv("LOXONE_USERNAME", "prom")
        monkeypatch.setenv("LOXONE_PASSWORD", "pass123")
        monkeypatch.setenv("LOXONE_NAME", "my-home")

        config = load_config(None)
        assert config.miniservers[0].name == "my-home"

    def test_env_overrides_only_first_miniserver(
        self, multi_config_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from loxone_exporter.config import load_config

        monkeypatch.setenv("LOXONE_HOST", "10.0.0.1")
        config = load_config(str(multi_config_file))
        assert config.miniservers[0].host == "10.0.0.1"
        assert config.miniservers[1].host == "192.168.1.200"  # unchanged


# ── Validation errors ──────────────────────────────────────────────────


@pytest.mark.usefixtures("_clean_env")
class TestValidation:
    def test_missing_host(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigError, load_config

        cfg = {"miniservers": [{"name": "x", "username": "u", "password": "p"}]}
        p = tmp_path / "bad.yml"
        p.write_text(yaml.dump(cfg))
        with pytest.raises(ConfigError, match=r"(?i)host"):
            load_config(str(p))

    def test_empty_password(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigError, load_config

        cfg = {
            "miniservers": [
                {"name": "x", "host": "1.2.3.4", "username": "u", "password": ""}
            ]
        }
        p = tmp_path / "bad.yml"
        p.write_text(yaml.dump(cfg))
        with pytest.raises(ConfigError, match=r"(?i)password"):
            load_config(str(p))

    def test_duplicate_miniserver_names(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigError, load_config

        cfg = {
            "miniservers": [
                {"name": "dup", "host": "1.2.3.4", "username": "u", "password": "p"},
                {"name": "dup", "host": "5.6.7.8", "username": "u", "password": "p"},
            ]
        }
        p = tmp_path / "bad.yml"
        p.write_text(yaml.dump(cfg))
        with pytest.raises(ConfigError, match=r"(?i)duplicate.*name"):
            load_config(str(p))

    def test_invalid_port_range(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigError, load_config

        cfg = {
            "miniservers": [
                {
                    "name": "x",
                    "host": "1.2.3.4",
                    "username": "u",
                    "password": "p",
                    "port": 99999,
                }
            ]
        }
        p = tmp_path / "bad.yml"
        p.write_text(yaml.dump(cfg))
        with pytest.raises(ConfigError, match=r"(?i)port"):
            load_config(str(p))

    def test_invalid_port_zero(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigError, load_config

        cfg = {
            "miniservers": [
                {
                    "name": "x",
                    "host": "1.2.3.4",
                    "username": "u",
                    "password": "p",
                    "port": 0,
                }
            ]
        }
        p = tmp_path / "bad.yml"
        p.write_text(yaml.dump(cfg))
        with pytest.raises(ConfigError, match=r"(?i)port"):
            load_config(str(p))

    def test_no_miniservers(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigError, load_config

        p = tmp_path / "bad.yml"
        p.write_text(yaml.dump({"miniservers": []}))
        with pytest.raises(ConfigError, match=r"(?i)miniserver"):
            load_config(str(p))

    def test_no_config_no_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigError, load_config

        # Change to temp dir to avoid loading default config.yml
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ConfigError):
            load_config(None)

    def test_invalid_yaml_file(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigError, load_config

        p = tmp_path / "bad.yml"
        p.write_text(": : : invalid yaml [[[")
        with pytest.raises(ConfigError):
            load_config(str(p))

    def test_invalid_log_level(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigError, load_config

        cfg = {
            "miniservers": [
                {"name": "x", "host": "1.2.3.4", "username": "u", "password": "p"}
            ],
            "log_level": "verbose",
        }
        p = tmp_path / "bad.yml"
        p.write_text(yaml.dump(cfg))
        with pytest.raises(ConfigError, match=r"(?i)log_level"):
            load_config(str(p))

    def test_invalid_log_format(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigError, load_config

        cfg = {
            "miniservers": [
                {"name": "x", "host": "1.2.3.4", "username": "u", "password": "p"}
            ],
            "log_format": "xml",
        }
        p = tmp_path / "bad.yml"
        p.write_text(yaml.dump(cfg))
        with pytest.raises(ConfigError, match=r"(?i)log_format"):
            load_config(str(p))

    def test_invalid_listen_port(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigError, load_config

        cfg = {
            "miniservers": [
                {"name": "x", "host": "1.2.3.4", "username": "u", "password": "p"}
            ],
            "listen_port": 70000,
        }
        p = tmp_path / "bad.yml"
        p.write_text(yaml.dump(cfg))
        with pytest.raises(ConfigError, match=r"(?i)listen_port"):
            load_config(str(p))

    def test_config_file_not_found(self) -> None:
        """Test that loading a non-existent config file raises ConfigError."""
        from loxone_exporter.config import ConfigError, load_config

        with pytest.raises(ConfigError, match=r"(?i)not found"):
            load_config("/path/that/does/not/exist.yml")

    def test_default_config_invalid_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that invalid YAML in default config.yml raises ConfigError."""
        from loxone_exporter.config import ConfigError, load_config

        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Create invalid config.yml in current directory
        p = tmp_path / "config.yml"
        p.write_text(": : : invalid yaml [[[")

        with pytest.raises(ConfigError, match=r"(?i)failed to parse config.yml"):
            load_config(None)

    def test_default_config_yaml_loaded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that config.yaml is loaded as default when config.yml doesn't exist."""
        from loxone_exporter.config import load_config

        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Create valid config.yaml (not config.yml)
        cfg = {
            "miniservers": [
                {"name": "test", "host": "192.168.1.1", "username": "admin", "password": "secret"}
            ]
        }
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump(cfg))

        config = load_config(None)
        assert len(config.miniservers) == 1
        assert config.miniservers[0].name == "test"


class TestHostValidation:
    """Tests for host and listen_address validation (Q2, Q3)."""

    @pytest.mark.usefixtures("_clean_env")
    def test_valid_ip_address(self, tmp_path: Path) -> None:
        from loxone_exporter.config import load_config

        cfg = {"miniservers": [{"name": "t", "host": "10.0.0.1", "username": "u", "password": "p"}]}
        p = tmp_path / "config.yml"
        p.write_text(yaml.dump(cfg))
        config = load_config(str(p))
        assert config.miniservers[0].host == "10.0.0.1"

    @pytest.mark.usefixtures("_clean_env")
    def test_valid_hostname(self, tmp_path: Path) -> None:
        from loxone_exporter.config import load_config

        cfg = {
            "miniservers": [
                {"name": "t", "host": "my-server.local", "username": "u", "password": "p"}
            ],
        }
        p = tmp_path / "config.yml"
        p.write_text(yaml.dump(cfg))
        config = load_config(str(p))
        assert config.miniservers[0].host == "my-server.local"

    @pytest.mark.usefixtures("_clean_env")
    def test_invalid_host_rejected(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigError, load_config

        cfg = {
            "miniservers": [
                {"name": "t", "host": "not valid!!", "username": "u", "password": "p"}
            ],
        }
        p = tmp_path / "config.yml"
        p.write_text(yaml.dump(cfg))
        with pytest.raises(ConfigError, match=r"invalid host"):
            load_config(str(p))

    @pytest.mark.usefixtures("_clean_env")
    def test_invalid_listen_address_rejected(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigError, load_config

        cfg = {
            "miniservers": [{"name": "t", "host": "10.0.0.1", "username": "u", "password": "p"}],
            "listen_address": "not-an-ip",
        }
        p = tmp_path / "config.yml"
        p.write_text(yaml.dump(cfg))
        with pytest.raises(ConfigError, match=r"listen_address must be a valid IP"):
            load_config(str(p))

    @pytest.mark.usefixtures("_clean_env")
    def test_valid_listen_address_ipv6(self, tmp_path: Path) -> None:
        from loxone_exporter.config import load_config

        cfg = {
            "miniservers": [{"name": "t", "host": "10.0.0.1", "username": "u", "password": "p"}],
            "listen_address": "::1",
        }
        p = tmp_path / "config.yml"
        p.write_text(yaml.dump(cfg))
        config = load_config(str(p))
        assert config.listen_address == "::1"


class TestSafeIntParsing:
    """Tests for safe int parsing of env variables (Q4)."""

    @pytest.mark.usefixtures("_clean_env")
    def test_invalid_port_env_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from loxone_exporter.config import ConfigError, load_config

        cfg = {"miniservers": [{"name": "t", "host": "10.0.0.1", "username": "u", "password": "p"}]}
        p = tmp_path / "config.yml"
        p.write_text(yaml.dump(cfg))
        monkeypatch.setenv("LOXONE_PORT", "abc")
        with pytest.raises(ConfigError, match=r"LOXONE_PORT must be a valid integer"):
            load_config(str(p))

    @pytest.mark.usefixtures("_clean_env")
    def test_invalid_listen_port_env_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from loxone_exporter.config import ConfigError, load_config

        cfg = {"miniservers": [{"name": "t", "host": "10.0.0.1", "username": "u", "password": "p"}]}
        p = tmp_path / "config.yml"
        p.write_text(yaml.dump(cfg))
        monkeypatch.setenv("LOXONE_LISTEN_PORT", "xyz")
        with pytest.raises(ConfigError, match=r"LOXONE_LISTEN_PORT must be a valid integer"):
            load_config(str(p))


class TestEncryptionOptions:
    """Tests for encryption configuration options."""

    @pytest.mark.usefixtures("_clean_env")
    def test_encryption_defaults_to_false(self, tmp_path: Path) -> None:
        from loxone_exporter.config import load_config

        cfg = {"miniservers": [{"name": "t", "host": "10.0.0.1", "username": "u", "password": "p"}]}
        p = tmp_path / "config.yml"
        p.write_text(yaml.dump(cfg))
        config = load_config(str(p))
        assert config.miniservers[0].use_encryption is False
        assert config.miniservers[0].force_encryption is False

    @pytest.mark.usefixtures("_clean_env")
    def test_use_encryption_enabled(self, tmp_path: Path) -> None:
        from loxone_exporter.config import load_config

        cfg = {
            "miniservers": [
                {
                    "name": "t",
                    "host": "10.0.0.1",
                    "username": "u",
                    "password": "p",
                    "use_encryption": True,
                }
            ]
        }
        p = tmp_path / "config.yml"
        p.write_text(yaml.dump(cfg))
        config = load_config(str(p))
        assert config.miniservers[0].use_encryption is True
        assert config.miniservers[0].force_encryption is False

    @pytest.mark.usefixtures("_clean_env")
    def test_force_encryption_enabled(self, tmp_path: Path) -> None:
        from loxone_exporter.config import load_config

        cfg = {
            "miniservers": [
                {
                    "name": "t",
                    "host": "10.0.0.1",
                    "username": "u",
                    "password": "p",
                    "force_encryption": True,
                }
            ]
        }
        p = tmp_path / "config.yml"
        p.write_text(yaml.dump(cfg))
        config = load_config(str(p))
        assert config.miniservers[0].use_encryption is False
        assert config.miniservers[0].force_encryption is True

    @pytest.mark.usefixtures("_clean_env")
    def test_both_encryption_options_enabled(self, tmp_path: Path) -> None:
        from loxone_exporter.config import load_config

        cfg = {
            "miniservers": [
                {
                    "name": "t",
                    "host": "10.0.0.1",
                    "username": "u",
                    "password": "p",
                    "use_encryption": True,
                    "force_encryption": True,
                }
            ]
        }
        p = tmp_path / "config.yml"
        p.write_text(yaml.dump(cfg))
        config = load_config(str(p))
        assert config.miniservers[0].use_encryption is True
        assert config.miniservers[0].force_encryption is True


# ── OTLP Configuration ────────────────────────────────────────────────


def _make_config_with_otlp(tmp_path: Path, otlp_section: dict[str, Any] | None = None) -> Path:
    """Helper to create a config file with OTLP section."""
    cfg: dict[str, Any] = {
        "miniservers": [
            {"name": "home", "host": "192.168.1.100", "username": "admin", "password": "secret"}
        ],
    }
    if otlp_section is not None:
        cfg["opentelemetry"] = otlp_section
    p = tmp_path / "config.yml"
    p.write_text(yaml.dump(cfg))
    return p


@pytest.mark.usefixtures("_clean_env")
class TestOTLPConfigDisabled:
    """Tests for OTLP config when disabled (default)."""

    def test_default_otlp_disabled(self, config_file: Path) -> None:
        from loxone_exporter.config import load_config

        config = load_config(str(config_file))
        assert config.opentelemetry.enabled is False

    def test_explicit_disabled(self, tmp_path: Path) -> None:
        from loxone_exporter.config import load_config

        p = _make_config_with_otlp(tmp_path, {"enabled": False})
        config = load_config(str(p))
        assert config.opentelemetry.enabled is False
        assert config.opentelemetry.endpoint == ""

    def test_disabled_skips_validation(self, tmp_path: Path) -> None:
        """When disabled, no validation errors even with invalid fields."""
        from loxone_exporter.config import load_config

        p = _make_config_with_otlp(tmp_path, {
            "enabled": False,
            "endpoint": "ftp://bad",  # Invalid but shouldn't matter
        })
        config = load_config(str(p))
        assert config.opentelemetry.enabled is False

    def test_no_otlp_section(self, config_file: Path) -> None:
        """Config without opentelemetry section uses defaults."""
        from loxone_exporter.config import load_config

        config = load_config(str(config_file))
        assert config.opentelemetry.enabled is False
        assert config.opentelemetry.protocol == "grpc"
        assert config.opentelemetry.interval_seconds == 30
        assert config.opentelemetry.timeout_seconds == 15


@pytest.mark.usefixtures("_clean_env")
class TestOTLPConfigEnabled:
    """Tests for OTLP config when enabled=true."""

    def test_minimal_enabled(self, tmp_path: Path) -> None:
        from loxone_exporter.config import load_config

        p = _make_config_with_otlp(tmp_path, {
            "enabled": True,
            "endpoint": "http://localhost:4317",
        })
        config = load_config(str(p))
        assert config.opentelemetry.enabled is True
        assert config.opentelemetry.endpoint == "http://localhost:4317"
        assert config.opentelemetry.protocol == "grpc"
        assert config.opentelemetry.interval_seconds == 30

    def test_full_config(self, tmp_path: Path) -> None:
        from loxone_exporter.config import load_config

        p = _make_config_with_otlp(tmp_path, {
            "enabled": True,
            "endpoint": "https://collector.local:4318",
            "protocol": "http",
            "interval_seconds": 60,
            "timeout_seconds": 30,
            "tls": {"enabled": True, "cert_path": str(tmp_path / "cert.pem")},
            "auth": {"headers": {"Authorization": "Bearer token123"}},
        })
        # Create cert file for validation
        (tmp_path / "cert.pem").write_text("fake cert")
        config = load_config(str(p))
        assert config.opentelemetry.protocol == "http"
        assert config.opentelemetry.interval_seconds == 60
        assert config.opentelemetry.timeout_seconds == 30
        assert config.opentelemetry.tls_config.enabled is True
        assert config.opentelemetry.auth_config.headers == {"Authorization": "Bearer token123"}

    def test_http_protocol(self, tmp_path: Path) -> None:
        from loxone_exporter.config import load_config

        p = _make_config_with_otlp(tmp_path, {
            "enabled": True,
            "endpoint": "http://localhost:4318",
            "protocol": "http",
        })
        config = load_config(str(p))
        assert config.opentelemetry.protocol == "http"


@pytest.mark.usefixtures("_clean_env")
class TestOTLPConfigValidation:
    """Tests for OTLP config validation rules VR-001 through VR-011."""

    def test_vr002_endpoint_required(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigurationError, load_config

        p = _make_config_with_otlp(tmp_path, {"enabled": True})
        with pytest.raises(ConfigurationError, match="endpoint.*required"):
            load_config(str(p))

    def test_vr003_invalid_scheme(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigurationError, load_config

        p = _make_config_with_otlp(tmp_path, {
            "enabled": True,
            "endpoint": "ftp://localhost:4317",
        })
        with pytest.raises(ConfigurationError, match="http:// or https://"):
            load_config(str(p))

    def test_vr003_missing_scheme(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigurationError, load_config

        p = _make_config_with_otlp(tmp_path, {
            "enabled": True,
            "endpoint": "localhost:4317",
        })
        with pytest.raises(ConfigurationError, match="http:// or https://"):
            load_config(str(p))

    def test_vr005_invalid_protocol(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigurationError, load_config

        p = _make_config_with_otlp(tmp_path, {
            "enabled": True,
            "endpoint": "http://localhost:4317",
            "protocol": "TCP",
        })
        with pytest.raises(ConfigurationError, match="'grpc' or 'http'"):
            load_config(str(p))

    def test_vr006_interval_too_low(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigurationError, load_config

        p = _make_config_with_otlp(tmp_path, {
            "enabled": True,
            "endpoint": "http://localhost:4317",
            "interval_seconds": 5,
        })
        with pytest.raises(ConfigurationError, match="interval_seconds.*10 and 300"):
            load_config(str(p))

    def test_vr006_interval_too_high(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigurationError, load_config

        p = _make_config_with_otlp(tmp_path, {
            "enabled": True,
            "endpoint": "http://localhost:4317",
            "interval_seconds": 500,
        })
        with pytest.raises(ConfigurationError, match="interval_seconds.*10 and 300"):
            load_config(str(p))

    def test_vr007_timeout_too_low(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigurationError, load_config

        p = _make_config_with_otlp(tmp_path, {
            "enabled": True,
            "endpoint": "http://localhost:4317",
            "timeout_seconds": 2,
        })
        with pytest.raises(ConfigurationError, match="timeout_seconds.*5 and 60"):
            load_config(str(p))

    def test_vr008_timeout_exceeds_interval(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigurationError, load_config

        p = _make_config_with_otlp(tmp_path, {
            "enabled": True,
            "endpoint": "http://localhost:4317",
            "interval_seconds": 20,
            "timeout_seconds": 25,
        })
        with pytest.raises(ConfigurationError, match="timeout_seconds.*less than interval"):
            load_config(str(p))

    def test_vr009_tls_cert_required(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigurationError, load_config

        p = _make_config_with_otlp(tmp_path, {
            "enabled": True,
            "endpoint": "http://localhost:4317",
            "tls": {"enabled": True},
        })
        with pytest.raises(ConfigurationError, match="cert_path.*required.*TLS"):
            load_config(str(p))

    def test_vr010_cert_file_missing(self, tmp_path: Path) -> None:
        from loxone_exporter.config import ConfigurationError, load_config

        p = _make_config_with_otlp(tmp_path, {
            "enabled": True,
            "endpoint": "http://localhost:4317",
            "tls": {"enabled": True, "cert_path": "/nonexistent/cert.pem"},
        })
        with pytest.raises(ConfigurationError, match="not found or not readable"):
            load_config(str(p))


@pytest.mark.usefixtures("_clean_env")
class TestOTLPEnvOverrides:
    """Tests for LOXONE_OTLP_* environment variable overrides."""

    def test_env_enables_otlp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from loxone_exporter.config import load_config

        p = _make_config_with_otlp(tmp_path, {"enabled": False})
        monkeypatch.setenv("LOXONE_OTLP_ENABLED", "true")
        monkeypatch.setenv("LOXONE_OTLP_ENDPOINT", "http://collector:4317")
        config = load_config(str(p))
        assert config.opentelemetry.enabled is True
        assert config.opentelemetry.endpoint == "http://collector:4317"

    def test_env_overrides_protocol(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from loxone_exporter.config import load_config

        p = _make_config_with_otlp(tmp_path, {
            "enabled": True,
            "endpoint": "http://localhost:4317",
            "protocol": "grpc",
        })
        monkeypatch.setenv("LOXONE_OTLP_PROTOCOL", "http")
        config = load_config(str(p))
        assert config.opentelemetry.protocol == "http"

    def test_env_overrides_interval(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from loxone_exporter.config import load_config

        p = _make_config_with_otlp(tmp_path, {
            "enabled": True,
            "endpoint": "http://localhost:4317",
        })
        monkeypatch.setenv("LOXONE_OTLP_INTERVAL", "60")
        config = load_config(str(p))
        assert config.opentelemetry.interval_seconds == 60

    def test_env_auth_header(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from loxone_exporter.config import load_config

        p = _make_config_with_otlp(tmp_path, {
            "enabled": True,
            "endpoint": "http://localhost:4317",
        })
        monkeypatch.setenv("LOXONE_OTLP_AUTH_HEADER_AUTHORIZATION", "Bearer mytoken")
        config = load_config(str(p))
        assert config.opentelemetry.auth_config.headers is not None
        assert "Authorization" in config.opentelemetry.auth_config.headers

    def test_env_tls_settings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from loxone_exporter.config import load_config

        cert = tmp_path / "ca.crt"
        cert.write_text("fake cert")
        p = _make_config_with_otlp(tmp_path, {
            "enabled": True,
            "endpoint": "http://localhost:4317",
        })
        monkeypatch.setenv("LOXONE_OTLP_TLS_ENABLED", "true")
        monkeypatch.setenv("LOXONE_OTLP_TLS_CERT_PATH", str(cert))
        config = load_config(str(p))
        assert config.opentelemetry.tls_config.enabled is True
        assert config.opentelemetry.tls_config.cert_path == str(cert)
