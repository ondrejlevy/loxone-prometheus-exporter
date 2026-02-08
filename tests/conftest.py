"""Shared test fixtures for loxone_exporter tests."""

from __future__ import annotations

from typing import Any

import pytest

from loxone_exporter.config import ExporterConfig, MiniserverConfig
from loxone_exporter.structure import (
    MiniserverState,
)


@pytest.fixture()
def sample_miniserver_config() -> MiniserverConfig:
    """A single valid MiniserverConfig."""
    return MiniserverConfig(
        name="home",
        host="192.168.1.100",
        port=80,
        username="admin",
        password="secret",
    )


@pytest.fixture()
def sample_exporter_config(sample_miniserver_config: MiniserverConfig) -> ExporterConfig:
    """A valid ExporterConfig with one miniserver."""
    return ExporterConfig(
        miniservers=(sample_miniserver_config,),
        listen_port=9504,
        listen_address="0.0.0.0",
        log_level="info",
        log_format="json",
    )


@pytest.fixture()
def sample_loxapp3() -> dict[str, Any]:
    """A sample LoxAPP3.json structure with diverse controls.

    Contains:
    - 3 top-level controls across 2 rooms and 2 categories
    - 1 IRoomControllerV2 with subControls
    - 1 Switch (digital)
    - 1 InfoOnlyAnalog (analog)
    - 1 TextInput (text-only)
    """
    return {
        "msInfo": {
            "serialNr": "504F94FFFE12AB",
            "msName": "TestMiniserver",
            "miniserverType": 2,
        },
        "softwareVersion": "14.5.12.28",
        "rooms": {
            "aaa00001-0000-0000-ffff000000000000": {
                "name": "Living Room",
                "uuid": "aaa00001-0000-0000-ffff000000000000",
            },
            "aaa00002-0000-0000-ffff000000000000": {
                "name": "Kitchen",
                "uuid": "aaa00002-0000-0000-ffff000000000000",
            },
        },
        "cats": {
            "bbb00001-0000-0000-ffff000000000000": {
                "name": "Lighting",
                "uuid": "bbb00001-0000-0000-ffff000000000000",
                "type": "lights",
            },
            "bbb00002-0000-0000-ffff000000000000": {
                "name": "Temperature",
                "uuid": "bbb00002-0000-0000-ffff000000000000",
                "type": "climate",
            },
        },
        "controls": {
            "ccc00001-0000-0000-ffff000000000000": {
                "name": "Kitchen Light",
                "type": "Switch",
                "room": "aaa00002-0000-0000-ffff000000000000",
                "cat": "bbb00001-0000-0000-ffff000000000000",
                "states": {
                    "active": "ddd00001-0000-0000-ffff000000000000",
                },
            },
            "ccc00002-0000-0000-ffff000000000000": {
                "name": "Living Room Climate",
                "type": "IRoomControllerV2",
                "room": "aaa00001-0000-0000-ffff000000000000",
                "cat": "bbb00002-0000-0000-ffff000000000000",
                "states": {
                    "tempActual": "ddd00002-0000-0000-ffff000000000000",
                    "tempTarget": "ddd00003-0000-0000-ffff000000000000",
                    "mode": "ddd00004-0000-0000-ffff000000000000",
                },
                "subControls": {
                    "ccc00002-0000-0001-ffff000000000000": {
                        "name": "Heating and Cooling",
                        "type": "IRCV2Daytimer",
                        "states": {
                            "value": "ddd00005-0000-0000-ffff000000000000",
                        },
                    },
                },
            },
            "ccc00003-0000-0000-ffff000000000000": {
                "name": "Outside Temperature",
                "type": "InfoOnlyAnalog",
                "room": "aaa00001-0000-0000-ffff000000000000",
                "cat": "bbb00002-0000-0000-ffff000000000000",
                "states": {
                    "value": "ddd00006-0000-0000-ffff000000000000",
                },
            },
            "ccc00004-0000-0000-ffff000000000000": {
                "name": "Status Display",
                "type": "TextInput",
                "room": "aaa00001-0000-0000-ffff000000000000",
                "cat": "bbb00001-0000-0000-ffff000000000000",
                "states": {
                    "textAndIcon": "ddd00007-0000-0000-ffff000000000000",
                },
            },
        },
    }


def _build_miniserver_state(
    config: MiniserverConfig,
    loxapp3: dict[str, Any],
    *,
    connected: bool = True,
    last_update_ts: float = 1738934567.123,
) -> MiniserverState:
    """Build a MiniserverState from config and LoxAPP3 data with initial values."""
    from loxone_exporter.structure import parse_structure

    controls, rooms, categories, state_map = parse_structure(loxapp3)

    ms = MiniserverState(
        name=config.name,
        serial=loxapp3.get("msInfo", {}).get("serialNr", ""),
        firmware=str(loxapp3.get("softwareVersion", "")),
        connected=connected,
        last_update_ts=last_update_ts,
        controls=controls,
        rooms=rooms,
        categories=categories,
        state_map=state_map,
    )
    return ms


@pytest.fixture()
def sample_miniserver_state(
    sample_miniserver_config: MiniserverConfig,
    sample_loxapp3: dict[str, Any],
) -> MiniserverState:
    """A connected MiniserverState with controls populated from sample_loxapp3.

    Sets initial values:
    - Kitchen Light active = 1.0 (digital)
    - Living Room Climate tempActual = 22.5
    - Living Room Climate tempTarget = 21.0
    - Living Room Climate mode = 3.0
    - Outside Temperature value = 5.2
    """
    ms = _build_miniserver_state(
        sample_miniserver_config, sample_loxapp3, connected=True
    )

    # Set initial values for numeric controls
    ms.controls["ccc00001-0000-0000-ffff000000000000"].states["active"].value = 1.0
    ms.controls["ccc00002-0000-0000-ffff000000000000"].states["tempActual"].value = 22.5
    ms.controls["ccc00002-0000-0000-ffff000000000000"].states["tempTarget"].value = 21.0
    ms.controls["ccc00002-0000-0000-ffff000000000000"].states["mode"].value = 3.0
    ms.controls["ccc00003-0000-0000-ffff000000000000"].states["value"].value = 5.2

    # Set text value on the text-only control
    ms.controls["ccc00004-0000-0000-ffff000000000000"].states["textAndIcon"].text = "All OK"

    return ms


@pytest.fixture()
def disconnected_miniserver_state(
    sample_miniserver_config: MiniserverConfig,
    sample_loxapp3: dict[str, Any],
) -> MiniserverState:
    """A disconnected MiniserverState."""
    return _build_miniserver_state(
        sample_miniserver_config, sample_loxapp3, connected=False, last_update_ts=0.0
    )
