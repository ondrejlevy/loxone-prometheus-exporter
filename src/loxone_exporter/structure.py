"""LoxAPP3.json structure parser.

Parses the Loxone Miniserver structure file into typed dataclasses,
builds the reverse state UUID → (control, state_name) mapping, and
detects text-only controls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Known text-only control types — these have no numeric state values.
_TEXT_ONLY_TYPES = frozenset({
    "TextInput",
    "Webpage",
    "TextState",
})


@dataclass
class Room:
    uuid: str
    name: str


@dataclass
class Category:
    uuid: str
    name: str
    type: str = ""


@dataclass
class StateEntry:
    """A single value-bearing state of a control."""

    state_uuid: str
    state_name: str
    value: float | None = None
    text: str | None = None
    is_digital: bool = False


@dataclass
class StateRef:
    """Reverse mapping entry: state UUID → parent control + state name."""

    control_uuid: str
    state_name: str


@dataclass
class Control:
    uuid: str
    name: str
    type: str
    room_uuid: str | None = None
    cat_uuid: str | None = None
    states: dict[str, StateEntry] = field(default_factory=dict)
    sub_controls: list[Control] = field(default_factory=list)
    is_text_only: bool = False


@dataclass
class MiniserverState:
    """Runtime state for an active Miniserver connection."""

    name: str
    serial: str = ""
    firmware: str = ""
    connected: bool = False
    last_update_ts: float = 0.0
    controls: dict[str, Control] = field(default_factory=dict)
    rooms: dict[str, Room] = field(default_factory=dict)
    categories: dict[str, Category] = field(default_factory=dict)
    state_map: dict[str, StateRef] = field(default_factory=dict)


def _is_text_only(control_type: str, states: dict[str, Any]) -> bool:
    """Determine if a control is text-only (no numeric values expected)."""
    if control_type in _TEXT_ONLY_TYPES:
        return True
    # If all state names suggest text-only content
    text_state_names = {"textAndIcon", "text", "textColor", "textInput"}
    return bool(states and all(name in text_state_names for name in states))


def _parse_control(
    uuid_str: str,
    raw: dict[str, Any],
    state_map: dict[str, StateRef],
) -> Control:
    """Parse a single control dict into a Control dataclass."""
    ctrl_type = str(raw.get("type", ""))
    raw_states = raw.get("states", {})
    is_text = _is_text_only(ctrl_type, raw_states)

    # Digital detection heuristic: Switch, InfoOnlyDigital, etc.
    digital_types = frozenset({
        "Switch", "TimedSwitch", "Pushbutton", "InfoOnlyDigital",
        "PresenceDetector", "SmokeAlarm",
    })
    is_digital_type = ctrl_type in digital_types

    states: dict[str, StateEntry] = {}
    for state_name, state_uuid in raw_states.items():
        state_uuid_str = str(state_uuid)
        is_digital = is_digital_type and state_name in {"active", "value"}
        entry = StateEntry(
            state_uuid=state_uuid_str,
            state_name=state_name,
            is_digital=is_digital,
        )
        states[state_name] = entry
        state_map[state_uuid_str] = StateRef(
            control_uuid=uuid_str, state_name=state_name
        )

    room_uuid = raw.get("room", "") or None
    cat_uuid = raw.get("cat", "") or None

    # Parse sub-controls
    sub_controls: list[Control] = []
    for sub_uuid, sub_raw in raw.get("subControls", {}).items():
        sub_ctrl = _parse_control(str(sub_uuid), sub_raw, state_map)
        sub_ctrl.room_uuid = room_uuid  # Inherit parent's room
        sub_ctrl.cat_uuid = cat_uuid  # Inherit parent's category
        sub_controls.append(sub_ctrl)

    return Control(
        uuid=uuid_str,
        name=str(raw.get("name", "")),
        type=ctrl_type,
        room_uuid=room_uuid,
        cat_uuid=cat_uuid,
        states=states,
        sub_controls=sub_controls,
        is_text_only=is_text,
    )


def parse_structure(
    data: dict[str, Any],
) -> tuple[dict[str, Control], dict[str, Room], dict[str, Category], dict[str, StateRef]]:
    """Parse a LoxAPP3.json structure into typed data structures.

    Args:
        data: Parsed JSON dict from LoxAPP3.json.

    Returns:
        A 4-tuple of ``(controls, rooms, categories, state_map)``.
    """
    rooms: dict[str, Room] = {}
    for uid, raw in data.get("rooms", {}).items():
        rooms[str(uid)] = Room(uuid=str(uid), name=str(raw.get("name", "")))

    categories: dict[str, Category] = {}
    for uid, raw in data.get("cats", {}).items():
        categories[str(uid)] = Category(
            uuid=str(uid),
            name=str(raw.get("name", "")),
            type=str(raw.get("type", "")),
        )

    state_map: dict[str, StateRef] = {}
    controls: dict[str, Control] = {}
    for uid, raw in data.get("controls", {}).items():
        uid_str = str(uid)
        controls[uid_str] = _parse_control(uid_str, raw, state_map)

    return controls, rooms, categories, state_map
