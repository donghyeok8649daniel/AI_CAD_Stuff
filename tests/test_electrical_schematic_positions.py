"""Circuit canvas placement is bounded, cosmetic, and journal compatible."""

from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from cadstudio.catalog import preset
from cadstudio.electrical import ElectricalSchematicPosition, ElectricalWorkspace, evaluate_electrical
from cadstudio.electrical_registration import register_part, registration_for_part, unregister_part
from cadstudio.models import Design
from cadstudio.native.document import Document, Journal, read_project
from cadstudio.part_operations import delete_parts


def circuit():
    return dict(nodes=["GND", "BAT"], components=[
        dict(id="battery", name="Battery", kind="battery", a="BAT", b="GND", voltage_v=12),
        dict(id="load", name="Board", kind="mcu", a="BAT", b="GND", rated_voltage_v=12,
             rated_current_a=.1),
    ])


def test_absent_legacy_layout_is_not_added_by_load_dump_copy_or_json():
    workspace = ElectricalWorkspace.model_validate(circuit())
    assert workspace.schematic_positions == {}
    assert "schematic_positions" not in workspace.model_fields_set
    for serialized in (workspace.model_dump(), workspace.model_copy(deep=True).model_dump(),
                       json.loads(workspace.model_dump_json())):
        assert "schematic_positions" not in serialized
        assert ElectricalWorkspace.model_validate(serialized).model_dump() == serialized


def test_explicit_empty_and_mutated_nonempty_layout_are_preserved():
    raw = circuit(); raw["schematic_positions"] = {}
    explicit = ElectricalWorkspace.model_validate(raw)
    assert explicit.model_dump()["schematic_positions"] == {}
    legacy = ElectricalWorkspace.model_validate(circuit())
    legacy.schematic_positions["battery"] = ElectricalSchematicPosition(x=-37.5, y=912.25)
    assert "schematic_positions" not in legacy.model_fields_set
    encoded = json.loads(legacy.model_dump_json())
    assert encoded["schematic_positions"] == {"battery": dict(x=-37.5, y=912.25)}
    assert ElectricalWorkspace.model_validate(encoded).model_dump() == encoded


def test_layout_roundtrip_does_not_change_electrical_calculation_or_netlist():
    raw = circuit(); baseline = ElectricalWorkspace.model_validate(raw)
    moved_raw = deepcopy(raw)
    moved_raw["schematic_positions"] = {"battery": dict(x=-100000, y=100000),
                                       "load": dict(x=420.5, y=37.75)}
    moved = ElectricalWorkspace.model_validate(moved_raw)
    assert evaluate_electrical(moved).model_dump() == evaluate_electrical(baseline).model_dump()
    assert moved.nodes == baseline.nodes and moved.components == baseline.components
    assert ElectricalWorkspace.model_validate_json(moved.model_dump_json()) == moved


@pytest.mark.parametrize("position", [dict(x=float("nan"), y=0), dict(x=0, y=float("inf")),
                                      dict(x=-float("inf"), y=0), dict(x=-100000.1, y=0),
                                      dict(x=0, y=100000.1), dict(x=0),
                                      dict(x=0, y=0, rotation=90)])
def test_layout_coordinates_are_finite_bounded_complete_and_known(position):
    raw = circuit(); raw["schematic_positions"] = {"battery": position}
    with pytest.raises(ValidationError):
        ElectricalWorkspace.model_validate(raw)


@pytest.mark.parametrize("identifier", ["missing", "../battery", "__proto__", "", "battery "])
def test_layout_can_only_reference_existing_component_ids(identifier):
    raw = circuit(); raw["schematic_positions"] = {identifier: dict(x=0, y=0)}
    with pytest.raises(ValidationError):
        ElectricalWorkspace.model_validate(raw)


def test_layout_count_matches_the_bounded_component_collection():
    raw = dict(nodes=["GND", "BAT"], components=[
        dict(id=f"part{index}", name=f"Board {index}", kind="mcu", a="BAT", b="GND",
             analysis_enabled=False) for index in range(256)],
        schematic_positions={f"part{index}": dict(x=index * 300, y=-index * 20) for index in range(256)})
    assert len(ElectricalWorkspace.model_validate(raw).schematic_positions) == 256
    raw["schematic_positions"]["extra"] = dict(x=0, y=0)
    with pytest.raises(ValidationError):
        ElectricalWorkspace.model_validate(raw)


def test_legacy_add_move_reset_and_branch_save_reopen_keep_exact_history(tmp_path):
    base = preset("cylinder").model_dump()
    legacy = deepcopy(base); legacy["electrical"] = ElectricalWorkspace.model_validate(circuit()).model_dump()
    moved = deepcopy(legacy)
    moved["electrical"]["schematic_positions"] = {"battery": dict(x=120.5, y=-38.25)}
    reset = deepcopy(legacy); reset["electrical"]["schematic_positions"] = {}
    document = Document(); document.commit(Design.model_validate(base), "base")
    document.commit(Design.model_validate(legacy), "legacy circuit")
    legacy_id = document.journal.data["cursor"]
    document.commit(Design.model_validate(moved), "move battery")
    moved_id = document.journal.data["cursor"]
    document.commit(Design.model_validate(reset), "reset placement")
    reset_id = document.journal.data["cursor"]
    path = tmp_path / "schematic.cad.json"; document.write(path)
    reopened = read_project(path)
    assert reopened.model_dump() == document.project().model_dump()
    journal = Journal(data=reopened.history.model_dump())
    for identifier, expected in ((legacy_id, legacy), (moved_id, moved), (reset_id, reset)):
        state = journal.at(identifier)
        assert state == expected
        assert Design.model_validate(state).model_dump() == state
    assert "schematic_positions" not in journal.at(legacy_id)["electrical"]


def test_layout_history_tampering_still_rejects_project(tmp_path):
    base = preset("cylinder").model_dump(); current = deepcopy(base)
    current["electrical"] = ElectricalWorkspace.model_validate(circuit()).model_dump()
    current["electrical"]["schematic_positions"] = {"battery": dict(x=10, y=20)}
    document = Document(); document.commit(Design.model_validate(base), "base")
    document.commit(Design.model_validate(current), "canvas")
    raw = document.project().model_dump()
    raw["design"]["electrical"]["schematic_positions"]["battery"]["x"] = 11
    from cadstudio.models import Project

    with pytest.raises(ValueError):
        Project.model_validate(raw)


def registered_layout():
    base = Design.model_validate(dict(parts=[
        dict(id="board", name="Controller", geometry=dict(kind="plate", length=60, width=40, thickness=2, hole_count=0)),
        dict(id="driver", name="Driver", geometry=dict(kind="plate", length=30, width=20, thickness=2, hole_count=0),
             transform=dict(x=90)),
    ]))
    registered = register_part(base, "board", dict(catalog_id="rpi4b"))
    registered = register_part(registered, "driver", dict(catalog_id="pololu_2130"))
    first = registration_for_part(registered, "board").id
    second = registration_for_part(registered, "driver").id
    raw = registered.model_dump()
    raw["electrical"]["schematic_positions"] = {first: dict(x=110, y=250), second: dict(x=420, y=250)}
    return Design.model_validate(raw), first, second


@pytest.mark.parametrize("operation", ["unregister", "delete"])
def test_removing_physical_registration_prunes_only_its_diagram_position(operation, tmp_path):
    registered, first, second = registered_layout(); before = registered.model_dump()
    removed = (unregister_part(registered, "driver") if operation == "unregister"
               else Design.model_validate(delete_parts(registered.model_dump(), ["driver"])))
    assert second not in {item.id for item in removed.electrical.components}
    assert removed.electrical.schematic_positions == {first: ElectricalSchematicPosition(x=110, y=250)}
    assert removed.electrical.nodes == registered.electrical.nodes
    assert registration_for_part(removed, "board") == registration_for_part(registered, "board")
    assert registered.model_dump() == before
    document = Document(); document.commit(registered, "registered arrangement")
    document.commit(removed, "remove registration")
    path = tmp_path / "pruned.cad.json"; document.write(path)
    reopened = read_project(path)
    assert reopened.model_dump() == document.project().model_dump()


def test_unregister_without_new_layout_never_adds_legacy_empty_field():
    registered, _, _ = registered_layout()
    raw = registered.model_dump(); raw["electrical"].pop("schematic_positions")
    removed = unregister_part(raw, "driver")
    assert "schematic_positions" not in removed.electrical.model_dump()
    deleted = Design.model_validate(delete_parts(raw, ["driver"]))
    assert "schematic_positions" not in deleted.electrical.model_dump()
