"""Tests for LoxAPP3.json structure parser."""

from __future__ import annotations


def _sample_structure() -> dict:
    """Return a minimal LoxAPP3.json-style dict with realistic data."""
    return {
        "msInfo": {"serialNr": "504F9412345", "msName": "TestMS"},
        "softwareVersion": "14.5.12.7",
        "rooms": {
            "13efd3e5-019d-8ad2-ffff-403fb0c34b9e": {
                "name": "Living Room",
                "uuid": "13efd3e5-019d-8ad2-ffff-403fb0c34b9e",
            },
            "14abc123-019d-8ad2-ffff-403fb0c34b9e": {
                "name": "Kitchen",
                "uuid": "14abc123-019d-8ad2-ffff-403fb0c34b9e",
            },
        },
        "cats": {
            "152c22de-0338-94b5-ffff-403fb0c34b9e": {
                "name": "Temperature",
                "uuid": "152c22de-0338-94b5-ffff-403fb0c34b9e",
                "type": "undefined",
            },
            "163d33ef-0338-94b5-ffff-403fb0c34b9e": {
                "name": "Lighting",
                "uuid": "163d33ef-0338-94b5-ffff-403fb0c34b9e",
                "type": "undefined",
            },
        },
        "controls": {
            # Simple switch in Kitchen
            "0b47c5b3-002f-0f3e-ffff-403fb0c34b9e": {
                "name": "Kitchen Light",
                "type": "Switch",
                "uuidAction": "0b47c5b3-002f-0f3e-ffff-403fb0c34b9e",
                "room": "14abc123-019d-8ad2-ffff-403fb0c34b9e",
                "cat": "163d33ef-0338-94b5-ffff-403fb0c34b9e",
                "states": {
                    "active": "0b47c5b3-002f-0f3e-ffff-403fb0c34b00",
                },
            },
            # IRoomControllerV2 with subControls
            "15beed5b-01ab-d81f-ffff-403fb0c34b9e": {
                "name": "Living Room Climate",
                "type": "IRoomControllerV2",
                "uuidAction": "15beed5b-01ab-d81f-ffff-403fb0c34b9e",
                "room": "13efd3e5-019d-8ad2-ffff-403fb0c34b9e",
                "cat": "152c22de-0338-94b5-ffff-403fb0c34b9e",
                "states": {
                    "tempActual": "15beed5b-01ab-d81f-ffff-403fb0c3aa01",
                    "tempTarget": "15beed5b-01ab-d81f-ffff-403fb0c3aa02",
                    "mode": "15beed5b-01ab-d81f-ffff-403fb0c3aa03",
                },
                "subControls": {
                    "15beed5b-01ab-d7eb-ffff-403fb0c34b9e": {
                        "name": "Heating and Cooling",
                        "type": "IRCV2Daytimer",
                        "states": {
                            "value": "15beed5b-01ab-d7eb-ffff-403fb0c3bb01",
                        },
                    }
                },
            },
            # InfoOnlyAnalog — no room/category
            "aaa11111-0000-0000-ffff-403fb0c34b9e": {
                "name": "Outdoor Temp",
                "type": "InfoOnlyAnalog",
                "uuidAction": "aaa11111-0000-0000-ffff-403fb0c34b9e",
                "states": {
                    "value": "aaa11111-0000-0000-ffff-403fb0c3cc01",
                },
            },
            # Text-only control (TextInput)
            "bbb22222-0000-0000-ffff-403fb0c34b9e": {
                "name": "Status Display",
                "type": "TextInput",
                "uuidAction": "bbb22222-0000-0000-ffff-403fb0c34b9e",
                "room": "13efd3e5-019d-8ad2-ffff-403fb0c34b9e",
                "cat": "152c22de-0338-94b5-ffff-403fb0c34b9e",
                "states": {
                    "textAndIcon": "bbb22222-0000-0000-ffff-403fb0c3dd01",
                },
            },
        },
    }


class TestParseRooms:
    def test_rooms_parsed(self) -> None:
        from loxone_exporter.structure import parse_structure

        _controls, rooms, _cats, _state_map = parse_structure(_sample_structure())
        assert len(rooms) == 2
        assert rooms["13efd3e5-019d-8ad2-ffff-403fb0c34b9e"].name == "Living Room"
        assert rooms["14abc123-019d-8ad2-ffff-403fb0c34b9e"].name == "Kitchen"


class TestParseCategories:
    def test_categories_parsed(self) -> None:
        from loxone_exporter.structure import parse_structure

        _controls, _rooms, cats, _state_map = parse_structure(_sample_structure())
        assert len(cats) == 2
        assert cats["152c22de-0338-94b5-ffff-403fb0c34b9e"].name == "Temperature"


class TestParseControls:
    def test_simple_switch(self) -> None:
        from loxone_exporter.structure import parse_structure

        controls, _rooms, _cats, _state_map = parse_structure(_sample_structure())
        ctrl = controls["0b47c5b3-002f-0f3e-ffff-403fb0c34b9e"]
        assert ctrl.name == "Kitchen Light"
        assert ctrl.type == "Switch"
        assert "active" in ctrl.states
        assert ctrl.room_uuid == "14abc123-019d-8ad2-ffff-403fb0c34b9e"
        assert ctrl.cat_uuid == "163d33ef-0338-94b5-ffff-403fb0c34b9e"

    def test_ircv2_with_subcontrols(self) -> None:
        from loxone_exporter.structure import parse_structure

        controls, _rooms, _cats, _state_map = parse_structure(_sample_structure())
        ctrl = controls["15beed5b-01ab-d81f-ffff-403fb0c34b9e"]
        assert ctrl.type == "IRoomControllerV2"
        assert len(ctrl.states) == 3
        assert "tempActual" in ctrl.states
        assert "tempTarget" in ctrl.states
        assert "mode" in ctrl.states
        assert len(ctrl.sub_controls) >= 1

    def test_subcontrol_states_in_state_map(self) -> None:
        from loxone_exporter.structure import parse_structure

        _controls, _rooms, _cats, state_map = parse_structure(_sample_structure())
        # Sub-control state UUID should be in the state map
        assert "15beed5b-01ab-d7eb-ffff-403fb0c3bb01" in state_map

    def test_control_missing_room_category(self) -> None:
        from loxone_exporter.structure import parse_structure

        controls, _rooms, _cats, _state_map = parse_structure(_sample_structure())
        ctrl = controls["aaa11111-0000-0000-ffff-403fb0c34b9e"]
        assert ctrl.room_uuid is None or ctrl.room_uuid == ""
        assert ctrl.cat_uuid is None or ctrl.cat_uuid == ""


class TestStateMap:
    def test_state_map_built(self) -> None:
        from loxone_exporter.structure import parse_structure

        _controls, _rooms, _cats, state_map = parse_structure(_sample_structure())
        # Switch active state
        ref = state_map["0b47c5b3-002f-0f3e-ffff-403fb0c34b00"]
        assert ref.control_uuid == "0b47c5b3-002f-0f3e-ffff-403fb0c34b9e"
        assert ref.state_name == "active"
        # IRCV2 tempActual state
        ref2 = state_map["15beed5b-01ab-d81f-ffff-403fb0c3aa01"]
        assert ref2.control_uuid == "15beed5b-01ab-d81f-ffff-403fb0c34b9e"
        assert ref2.state_name == "tempActual"


class TestTextOnlyDetection:
    def test_text_only_control_detected(self) -> None:
        from loxone_exporter.structure import parse_structure

        controls, _rooms, _cats, _state_map = parse_structure(_sample_structure())
        ctrl = controls["bbb22222-0000-0000-ffff-403fb0c34b9e"]
        assert ctrl.is_text_only is True

    def test_numeric_control_not_text_only(self) -> None:
        from loxone_exporter.structure import parse_structure

        controls, _rooms, _cats, _state_map = parse_structure(_sample_structure())
        ctrl = controls["0b47c5b3-002f-0f3e-ffff-403fb0c34b9e"]
        assert ctrl.is_text_only is False


class TestEmptyStructure:
    def test_empty_structure(self) -> None:
        from loxone_exporter.structure import parse_structure

        data = {"rooms": {}, "cats": {}, "controls": {}}
        controls, rooms, cats, state_map = parse_structure(data)
        assert len(controls) == 0
        assert len(rooms) == 0
        assert len(cats) == 0
        assert len(state_map) == 0
