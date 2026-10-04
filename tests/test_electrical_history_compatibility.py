"""Legacy circuit snapshots and new registrations retain exact journal values."""

from copy import deepcopy
import json

import pytest

from cadstudio.catalog import preset
from cadstudio.electrical import ElectricalComponent, ElectricalWorkspace
from cadstudio.electrical_registration import register_part, registration_for_part
from cadstudio.models import Design, Project
from cadstudio.native.document import Document, Journal, read_project


INTRODUCED_DEFAULTS = dict(analysis_enabled=True, part_registration=False,
                           terminal_pins={}, pinout_catalog_id="", product_pinout_catalog_id="")


def legacy_circuit(voltage=12):
    workspace = ElectricalWorkspace.model_validate(dict(nodes=["GND", "BAT"], components=[
        dict(id="battery", name="Original battery", kind="battery", a="BAT", b="GND", voltage_v=voltage),
        dict(id="load", name="Original MCU", kind="mcu", a="BAT", b="GND",
             rated_voltage_v=12, rated_current_a=.1, signal_pins={}),
    ])).model_dump()
    for component in workspace["components"]:
        for key in INTRODUCED_DEFAULTS:
            component.pop(key, None)
    return workspace


def entry(identifier, parent, changes):
    return dict(id=identifier, parent=parent, label=identifier,
                created_at="2026-09-30T00:00:00Z", changes=deepcopy(changes))


def legacy_project():
    base = preset("cylinder").model_dump()
    initial, replacement, alternate = legacy_circuit(), legacy_circuit(10), legacy_circuit(9)
    current = deepcopy(base); current["electrical"] = alternate
    entries = [entry("root", None, []),
               entry("add", "root", [dict(path=["electrical"], existed=False, after=initial)]),
               entry("replace", "add", [dict(path=["electrical"], before=initial, after=replacement)]),
               entry("remove", "replace", [dict(path=["electrical"], operation="remove", before=replacement)]),
               entry("branch", "add", [dict(path=["electrical"], before=initial, after=alternate)])]
    return dict(design=current, history=dict(base=base, entries=entries, cursor="branch", head="branch"))


def test_legacy_whole_circuit_add_replace_remove_and_branch_preserve_history(tmp_path):
    raw = legacy_project(); original = deepcopy(raw)
    loaded = Project.model_validate(raw)
    assert raw == original
    assert loaded.design.electrical.components[0].analysis_enabled is True
    assert loaded.history.model_dump()["entries"] == [
        {**row, "source": "manual", "context": {}, "changes": [
            {"operation": "set", "existed": True, "before": None, "after": None, **change}
            for change in row["changes"]]} for row in original["history"]["entries"]]
    document = Document(); document.load(loaded)
    path = tmp_path / "legacy.cad.json"; document.write(path)
    reopened = read_project(path)
    assert reopened.model_dump() == loaded.model_dump()
    journal = Journal(data=reopened.history.model_dump())
    for identifier, voltage in (("add", 12), ("replace", 10), ("branch", 9)):
        state = journal.at(identifier)
        assert Design.model_validate(state).model_dump() == state
        assert state["electrical"]["components"][0]["voltage_v"] == voltage
    assert "electrical" not in journal.at("remove")
    for component in document.design["electrical"]["components"]:
        assert not INTRODUCED_DEFAULTS.keys() & component.keys()


def test_explicit_modern_default_fields_remain_in_snapshots_and_reopen(tmp_path):
    base = preset("cylinder").model_dump(); current = deepcopy(base)
    circuit = legacy_circuit()
    for component in circuit["components"]:
        component.update(deepcopy(INTRODUCED_DEFAULTS))
    current["electrical"] = circuit
    document = Document(); document.commit(Design.model_validate(base), "start")
    document.commit(Design.model_validate(current), "explicit v2.18 circuit")
    before = document.project().model_dump()
    path = tmp_path / "modern.cad.json"; document.write(path)
    after = read_project(path).model_dump()
    assert before == after
    assert after["history"]["entries"][-1]["changes"][0]["after"] == circuit
    for component in after["design"]["electrical"]["components"]:
        assert {key: component[key] for key in INTRODUCED_DEFAULTS} == INTRODUCED_DEFAULTS


def test_nondefault_new_fields_and_mutated_terminal_map_are_never_omitted():
    raw = legacy_circuit()["components"][1]
    model = ElectricalComponent.model_validate(raw)
    assert not INTRODUCED_DEFAULTS.keys() & model.model_dump().keys()
    model.analysis_enabled = False
    assert model.model_dump()["analysis_enabled"] is False
    # In-place map updates do not enter model_fields_set, so value comparison
    # must retain a newly assigned connection as well as explicit empty maps.
    product = ElectricalComponent.model_validate(dict(id="sensor", name="Sensor", kind="load",
                                                      a="BAT", b="GND", analysis_enabled=False))
    assert "terminal_pins" not in product.model_fields_set
    product.terminal_pins["OUT"] = "SIGNAL"
    encoded = json.loads(product.model_dump_json())
    assert encoded["terminal_pins"] == {"OUT": "SIGNAL"}
    assert ElectricalComponent.model_validate(encoded).terminal_pins == product.terminal_pins


@pytest.mark.parametrize("catalog_id", ["rpi4b", "ams_as5600_asot", "pololu_2130", "pololu_4755"])
def test_pending_registration_diagram_provenance_and_unwired_model_edit_roundtrip(catalog_id, tmp_path):
    base = preset("cylinder")
    identifier = base.parts[0].id
    registered = register_part(base, identifier, dict(catalog_id=catalog_id))
    edited = register_part(registered, identifier, dict(name="Renamed physical product"))
    component = registration_for_part(edited, identifier)
    assert component.part_registration is True and component.analysis_enabled is False
    assert component.catalog_id == catalog_id and component.name == "Renamed physical product"
    dumped = component.model_dump()
    assert dumped["part_registration"] is True and dumped["analysis_enabled"] is False
    if catalog_id == "rpi4b":
        assert dumped["pinout_catalog_id"] == catalog_id
    else:
        assert dumped["product_pinout_catalog_id"] == catalog_id
    document = Document(); document.commit(base, "original")
    document.commit(registered, "register"); document.commit(edited, "rename")
    path = tmp_path / "registered.cad.json"; document.write(path)
    reopened = read_project(path)
    assert reopened.model_dump() == document.project().model_dump()
    assert reopened.design.parts[0].geometry == base.parts[0].geometry


@pytest.mark.parametrize("corruption", ["before", "current", "parent", "prototype", "invalid_current", "invalid_history"])
def test_legacy_compatibility_does_not_weaken_history_or_component_validation(corruption):
    raw = legacy_project()
    if corruption == "before":
        raw["history"]["entries"][2]["changes"][0]["before"]["components"][0]["voltage_v"] = 99
    elif corruption == "current":
        raw["design"]["electrical"]["components"][0]["voltage_v"] = 99
    elif corruption == "parent":
        raw["history"]["entries"][2]["parent"] = "future"
    elif corruption == "prototype":
        raw["history"]["entries"][1]["changes"][0]["path"] = ["__proto__", "polluted"]
    elif corruption == "invalid_current":
        raw["design"]["electrical"]["components"][0]["part_registration"] = True
    else:
        # Invalid abandoned history must still be rejected even if the current
        # branch remains valid and loadable in isolation.
        raw["history"]["entries"][2]["changes"][0]["after"]["components"][0]["voltage_v"] = -1
    with pytest.raises(ValueError):
        Project.model_validate(raw)


def test_registered_diagram_provenance_still_rejects_model_tampering():
    base = preset("cylinder"); identifier = base.parts[0].id
    registered = register_part(base, identifier, dict(catalog_id="rpi4b"))
    raw = registered.model_dump()
    raw["electrical"]["components"][0]["pinout_catalog_id"] = "arduino_uno_r3"
    with pytest.raises(ValueError):
        Design.model_validate(raw)
