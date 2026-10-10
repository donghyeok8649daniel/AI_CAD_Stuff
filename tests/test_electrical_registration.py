"""Physical CAD registrations keep pending ratings and passive wiring honest."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from cadstudio.electrical import ElectricalWorkspace, evaluate_electrical
from cadstudio.electrical_registration import (
    connect_registered_pin, connect_registered_terminal, connected_pins_for_part,
    register_part, register_terminal_node, registration_for_part, unregister_part,
)
from cadstudio.mcu_connections import connection_endpoints, topology_warnings
from cadstudio.models import Design, Project
from cadstudio.part_operations import delete_parts, part_clipboard, paste_parts


def original():
    return Design.model_validate(dict(name="Keep this research assembly", parts=[
        dict(id="board", name="Controller enclosure", geometry=dict(kind="plate", length=60, width=40, thickness=2, hole_count=0),
             color="#345678", role="structure", fixed=True),
        dict(id="encoder", name="Motor encoder assembly", geometry=dict(kind="cylinder", diameter=12, height=30),
             transform=dict(x=90), color="#112233", role="transmission"),
        dict(id="supply", name="Physical battery", geometry=dict(kind="plate", length=50, width=30, thickness=15, hole_count=0),
             transform=dict(x=150), color="#AA5500"),
    ], part_groups=[dict(id="assembly", name="Retain selection group", part_ids=["board", "encoder"])],
        parameters={"wall": "2 mm"}, electrical=dict(name="Original power circuit", nodes=["GND", "BAT", "UNUSED"], components=[
            dict(id="battery", name="Verified 5 V", kind="battery", a="BAT", b="GND", voltage_v=5,
                 internal_resistance_ohm=.1, max_current_a=2),
            dict(id="old_load", name="Preserved resistor", kind="resistor", a="BAT", b="GND", resistance_ohm=100),
        ])))


def _branch(result, identifier):
    return next(branch for branch in result.components if branch.id == identifier)


def test_pending_exact_mcu_registration_changes_no_geometry_or_custom_color_and_persists():
    old = original(); before = old.model_dump()
    args = dict(catalog_id="rpi4b"); args_before = deepcopy(args)
    registered = register_part(old, "board", args)
    assert old.model_dump() == before and args == args_before
    part = next(part for part in registered.parts if part.id == "board")
    oldpart = next(part for part in old.parts if part.id == "board")
    assert part.geometry == oldpart.geometry and part.transform == oldpart.transform
    assert part.features == oldpart.features and part.fixed is oldpart.fixed
    assert part.color == "#345678" and part.role == "electrical"
    assert registered.part_groups == old.part_groups and registered.parameters == old.parameters
    component = registration_for_part(registered, "board")
    assert component.part_registration is True and component.analysis_enabled is False
    assert component.part_id == "board" and component.catalog_id == component.pinout_catalog_id == "rpi4b"
    assert component.rated_current_a == 0 and component.rated_voltage_v == 5  # Official voltage only.
    assert component.a not in old.electrical.nodes and component.b not in old.electrical.nodes
    assert component.a != component.b and component.b != "GND"  # No unrequested rail connection.
    assert component.signal_pins == {}
    assert registered.electrical.components[:2] == old.electrical.components
    assert registered.electrical.nodes[:3] == old.electrical.nodes
    before_result = evaluate_electrical(old.electrical)
    result = evaluate_electrical(registered.electrical)
    pending = _branch(result, component.id)
    assert pending.analysis_enabled is False and pending.resistance_ohm is pending.voltage_drop_v is None
    assert pending.current_a == 0 and result.source_power_w == pytest.approx(before_result.source_power_w)
    assert any("0 A는 확인된 소비전류가 아닙니다" in warning for warning in result.warnings)
    reopened = Project.model_validate_json(Project(design=registered).model_dump_json())
    assert reopened.design == registered and registration_for_part(reopened.design, "board") == component
    # Inspector callers receive a copy, not mutable design state.
    component.signal_pins["GPIO17"] = "BAT"
    assert registration_for_part(registered, "board").signal_pins == {}


def test_repeated_registration_updates_one_feature_and_color_change_is_explicit():
    design = register_part(original(), "board", dict(catalog_id="rpi4b"))
    first = registration_for_part(design, "board")
    renamed = register_part(design, "board", dict(name="Main controller"))
    second = registration_for_part(renamed, "board")
    assert second.id == first.id and second.name == "Main controller"
    assert (second.a, second.b, second.catalog_id) == (first.a, first.b, first.catalog_id)
    assert len(renamed.electrical.components) == len(design.electrical.components)
    assert renamed.parts[0].name == design.parts[0].name  # Electrical label is separate.
    colored = register_part(renamed, "board", dict(apply_default_color=True))
    assert colored.parts[0].color == "#FFD400" and renamed.parts[0].color == "#345678"


def test_enabling_mcu_dc_requires_operating_current_and_preserves_prior_active_circuit():
    design = register_part(original(), "board", dict(catalog_id="rpi4b"))
    before = design.model_dump()
    with pytest.raises(ValueError, match="전류"):
        register_part(design, "board", dict(analysis_enabled=True, a="BAT", b="GND"))
    assert design.model_dump() == before
    active = register_part(design, "board", dict(analysis_enabled=True, a="BAT", b="GND", rated_current_a=.1))
    component = registration_for_part(active, "board")
    assert component.analysis_enabled is True and component.rated_current_a == .1
    result = evaluate_electrical(active.electrical)
    assert _branch(result, component.id).current_a > 0 and _branch(result, component.id).analysis_enabled is True
    assert result.absorbed_power_w == pytest.approx(result.source_power_w)
    edited = register_part(active, "board", dict(name="Only a metadata edit"))
    assert registration_for_part(edited, "board").analysis_enabled is True
    assert registration_for_part(edited, "board").rated_current_a == .1


@pytest.mark.parametrize("catalog_id", ["ams_as5600_asot", "pololu_2130", "vishay_1n5819"])
def test_exact_reference_products_have_verified_diagrams_but_no_fictional_dc_model(catalog_id):
    design = register_part(original(), "encoder", dict(catalog_id=catalog_id))
    component = registration_for_part(design, "encoder")
    assert component.product_pinout_catalog_id == catalog_id
    assert component.analysis_enabled is False and component.terminal_pins == {}
    assert component.rated_current_a == component.rated_voltage_v == 0
    endpoints = [endpoint for endpoint in connection_endpoints(design.electrical) if endpoint.component_id == component.id]
    assert any(endpoint.terminal.startswith("port:") for endpoint in endpoints)
    assert all(endpoint.node is None for endpoint in endpoints if endpoint.terminal.startswith("port:"))
    before = design.model_dump()
    with pytest.raises(ValueError, match="動作|동작 회로 모델"):
        register_part(design, "encoder", dict(analysis_enabled=True, rated_voltage_v=5, rated_current_a=.01))
    assert design.model_dump() == before


@pytest.mark.parametrize("args", [
    {"catalog_id": "invented_chip"}, {"catalog_id": "stm32_nucleo_family"},
    {"catalog_id": "rpi4b", "kind": "motor"}, {"catalog_id": "rpi4b", "signal_pins": {"GPIO999": "BAT"}},
    {"catalog_id": "pololu_2130", "terminal_pins": {"PWM999": "BAT"}},
])
def test_unverified_or_wrong_exact_model_and_physical_keys_fail_without_mutation(args):
    old = original(); before = old.model_dump()
    with pytest.raises(ValueError):
        register_part(old, "board", args)
    assert old.model_dump() == before
    with pytest.raises(ValueError, match="실제 CAD"):
        register_part(old, "missing", dict(catalog_id="rpi4b"))


def test_manual_registration_requires_no_model_or_invented_current_and_can_add_explicit_port():
    design = register_part(original(), "encoder", dict(kind="load", name="Custom encoder housing"))
    component = registration_for_part(design, "encoder")
    assert component.catalog_id == component.product_pinout_catalog_id == component.pinout_catalog_id == ""
    assert component.analysis_enabled is False and component.rated_current_a == 0
    connected = register_terminal_node(design, "encoder", "OUT_A", "MY_SIGNAL")
    assert registration_for_part(connected, "encoder").terminal_pins == {"OUT_A": "MY_SIGNAL"}
    assert "MY_SIGNAL" in connected.electrical.nodes
    with pytest.raises(ValueError, match="단자 이름"):
        register_terminal_node(design, "encoder", "bad terminal", "MY_SIGNAL")


def test_pending_mcu_and_exact_encoder_connect_by_actual_body_ids_and_named_signal():
    design = register_part(original(), "board", dict(catalog_id="rpi4b"))
    design = register_part(design, "encoder", dict(catalog_id="pololu_4755"))
    before = design.model_dump()
    connected = connect_registered_pin(design, "board", "GPIO17", "encoder", "port:ENCODER_A")
    mcu = registration_for_part(connected, "board")
    motor = registration_for_part(connected, "encoder")
    assert mcu.signal_pins["GPIO17"] == motor.terminal_pins["ENCODER_A"]
    assert motor.terminal_pins.keys() == {"ENCODER_A"}
    assert motor.a != motor.terminal_pins["ENCODER_A"] and motor.b != motor.terminal_pins["ENCODER_A"]
    assert design.model_dump() == before
    result = evaluate_electrical(connected.electrical)
    assert _branch(result, mcu.id).signal_pin_connected == {"GPIO17": True}
    assert _branch(result, mcu.id).analysis_enabled is False and _branch(result, motor.id).analysis_enabled is False
    assert result.startup is None
    assert result.source_power_w == pytest.approx(evaluate_electrical(design.electrical).source_power_w)
    assert any(endpoint.component_id == motor.id and endpoint.terminal == "port:ENCODER_A"
               for endpoint in connected_pins_for_part(connected, "board"))
    with pytest.raises(ValueError, match="먼저 전장"):
        connect_registered_pin(design, "board", "GPIO17", "supply", "a")


def test_product_to_mcu_join_and_explicit_power_mapping_never_auto_bridge_encoder_and_motor_rails():
    design = register_part(original(), "board", dict(catalog_id="rpi4b"))
    design = register_part(design, "encoder", dict(catalog_id="pololu_4755"))
    design = register_part(design, "supply", dict(kind="battery", voltage_v=5, analysis_enabled=True, a="BAT", b="GND"))
    connected = connect_registered_terminal(design, "encoder", "ENCODER_A", "board", "pin:GPIO17")
    mcu = registration_for_part(connected, "board")
    motor = registration_for_part(connected, "encoder")
    assert motor.terminal_pins["ENCODER_A"] == mcu.signal_pins["GPIO17"]
    powered = connect_registered_terminal(connected, "encoder", "ENCODER_VCC", "supply", "a")
    motor = registration_for_part(powered, "encoder")
    assert motor.terminal_pins["ENCODER_VCC"] == "BAT"
    assert "MOTOR_RED" not in motor.terminal_pins and motor.a != "BAT"
    result = evaluate_electrical(powered.electrical)
    assert _branch(result, motor.id).voltage_drop_v is None and _branch(result, motor.id).resistance_ohm is None
    assert result.source_power_w == pytest.approx(evaluate_electrical(connected.electrical).source_power_w)
    risky = connect_registered_pin(powered, "board", "GPIO18", "encoder", "port:ENCODER_VCC")
    assert any("물리 전원·GND 단자" in warning for warning in topology_warnings(risky.electrical))


def test_product_to_product_named_signal_join_is_unique_and_preserves_other_signal_users():
    design = register_part(original(), "board", dict(catalog_id="pololu_2130"))
    design = register_part(design, "encoder", dict(catalog_id="pololu_4755"))
    joined = connect_registered_terminal(design, "encoder", "ENCODER_A", "board", "port:AIN1")
    driver = registration_for_part(joined, "board")
    motor = registration_for_part(joined, "encoder")
    shared = driver.terminal_pins["AIN1"]
    assert shared == motor.terminal_pins["ENCODER_A"] and shared.startswith("MCUNET_")
    changed = register_terminal_node(joined, "encoder", "ENCODER_B", "SECOND_NET")
    assert registration_for_part(changed, "encoder").terminal_pins["ENCODER_A"] == shared
    assert registration_for_part(changed, "board").terminal_pins["AIN1"] == shared
    before = changed.model_dump()
    for terminal in ("BAD_PIN", "port:BAD_PIN"):
        with pytest.raises(ValueError, match="물리 단자 목록"):
            connect_registered_terminal(changed, "encoder", terminal, "board", "port:AIN1")
    assert changed.model_dump() == before


def test_model_change_requires_pin_disconnection_confirmation_and_clears_stale_operating_data():
    design = register_part(original(), "board", dict(catalog_id="rpi4b", analysis_enabled=True,
        rated_current_a=.1, a="BAT", b="GND", signal_pins={"GPIO17": "OLD_SIGNAL"}))
    before = design.model_dump()
    with pytest.raises(ValueError, match="명시적으로 확인"):
        register_part(design, "board", dict(catalog_id="arduino_uno_r3"))
    assert design.model_dump() == before
    changed = register_part(design, "board", dict(catalog_id="arduino_uno_r3", allow_drop_connections=True))
    prior, new = registration_for_part(design, "board"), registration_for_part(changed, "board")
    assert new.id == prior.id and new.signal_pins == {}
    assert new.analysis_enabled is False and new.rated_current_a == 0
    assert (new.a, new.b) == (prior.a, prior.b) and "OLD_SIGNAL" in changed.electrical.nodes
    assert changed.parts[0].color == design.parts[0].color


def test_registration_reference_validation_is_opt_in_and_old_loose_links_still_load():
    raw = original().model_dump()
    raw["electrical"]["components"][0]["part_id"] = "old_missing_body"
    assert Design.model_validate(raw).electrical.components[0].part_id == "old_missing_body"
    raw["electrical"]["components"][0]["part_registration"] = True
    with pytest.raises(ValidationError, match="존재하지 않는 CAD"):
        Design.model_validate(raw)
    raw = register_part(original(), "board", dict(catalog_id="rpi4b")).model_dump()
    duplicate = deepcopy(raw["electrical"]["components"][-1]); duplicate["id"] = "another"
    duplicate["part_registration"] = False
    raw["electrical"]["components"].append(duplicate)
    with pytest.raises(ValidationError, match="한 번만"):
        Design.model_validate(raw)


def test_unregister_or_delete_removes_only_the_owned_feature_and_preserves_remaining_pin_nets():
    design = register_part(original(), "board", dict(catalog_id="rpi4b"))
    design = register_part(design, "encoder", dict(catalog_id="pololu_4755"))
    design = connect_registered_pin(design, "board", "GPIO17", "encoder", "port:ENCODER_A")
    original_state = design.model_dump()
    mcu = registration_for_part(design, "board")
    removed = unregister_part(design, "encoder")
    assert registration_for_part(removed, "encoder") is None and removed.parts == design.parts
    assert removed.electrical.nodes == design.electrical.nodes
    assert registration_for_part(removed, "board").signal_pins == mcu.signal_pins
    assert _branch(evaluate_electrical(removed.electrical), mcu.id).signal_pin_connected == {"GPIO17": False}
    deleted = Design.model_validate(delete_parts(design.model_dump(), ["encoder"]))
    assert "encoder" not in {part.id for part in deleted.parts}
    assert all(component.part_id != "encoder" for component in deleted.electrical.components)
    assert deleted.electrical.nodes == design.electrical.nodes
    assert registration_for_part(deleted, "board").signal_pins == mcu.signal_pins
    assert design.model_dump() == original_state


def test_clipboard_copy_does_not_duplicate_original_physical_registration_or_reuse_part_association():
    design = register_part(original(), "board", dict(catalog_id="rpi4b"))
    payload = part_clipboard(design.model_dump(), ["board"])
    assert payload.get("electrical") is None
    pasted, ids = paste_parts(design.model_dump(), payload)
    pasted = Design.model_validate(pasted)
    assert len(ids) == 1 and ids[0] != "board"
    assert registration_for_part(pasted, ids[0]) is None
    assert registration_for_part(pasted, "board") == registration_for_part(design, "board")


def test_pending_all_kinds_skip_bad_zero_resistance_and_large_board_nodes_remain_guarded():
    workspace = ElectricalWorkspace.model_validate(dict(nodes=["GND", "A", "B"], components=[
        dict(id=kind, name=kind, kind=kind, a="A", b="B", analysis_enabled=False)
        for kind in ("battery", "wire", "resistor", "load", "motor", "mcu", "switch")]))
    result = evaluate_electrical(workspace)
    assert result.source_power_w == result.absorbed_power_w == 0 and result.startup is None
    assert all(not branch.analysis_enabled and branch.voltage_drop_v is None and branch.resistance_ohm is None
               for branch in result.components)
    design = register_part(original(), "board", dict(catalog_id="rpi4b"))
    raw = design.model_dump()
    raw["electrical"]["nodes"].extend(f"NET_{index}" for index in range(512 - len(raw["electrical"]["nodes"])))
    saturated = Design.model_validate(raw); before = saturated.model_dump()
    with pytest.raises(ValueError):
        register_part(saturated, "encoder", dict(catalog_id="pololu_4755"))
    assert saturated.model_dump() == before


def test_new_registration_rails_never_join_an_unrelated_existing_node_with_same_prefix():
    raw = original().model_dump()
    raw["electrical"]["nodes"].extend(["ereg_001_A", "ereg_002_B"])
    design = Design.model_validate(raw)
    registered = register_part(design, "board", dict(catalog_id="rpi4b"))
    component = registration_for_part(registered, "board")
    assert component.id == "ereg_003" and (component.a, component.b) == ("ereg_003_A", "ereg_003_B")
    assert registered.electrical.components[:2] == design.electrical.components


def test_strict_physical_registration_prevents_kind_or_pinout_provenance_tampering():
    raw = register_part(original(), "board", dict(catalog_id="rpi4b")).model_dump()
    wrong_kind = deepcopy(raw); wrong_kind["electrical"]["components"][-1]["kind"] = "motor"
    wrong_kind["electrical"]["components"][-1]["pinout_catalog_id"] = ""
    with pytest.raises(ValidationError, match="종류가 일치"):
        Design.model_validate(wrong_kind)
    missing_board = deepcopy(raw); missing_board["electrical"]["components"][-1]["pinout_catalog_id"] = ""
    with pytest.raises(ValidationError, match="모식도 연결"):
        Design.model_validate(missing_board)
    raw = register_part(original(), "encoder", dict(catalog_id="pololu_4755")).model_dump()
    raw["electrical"]["components"][-1]["product_pinout_catalog_id"] = ""
    with pytest.raises(ValidationError, match="모식도 연결"):
        Design.model_validate(raw)


def test_pending_closed_wires_keep_passive_supply_path_but_never_imply_known_dc_power():
    workspace = ElectricalWorkspace.model_validate(dict(nodes=["GND", "BAT", "VCC"], components=[
        dict(id="battery", name="Known source", kind="battery", a="BAT", b="GND", voltage_v=5),
        dict(id="wire", name="Unknown wire ratings", kind="wire", a="BAT", b="VCC", analysis_enabled=False),
        dict(id="mcu", name="Pending board", kind="mcu", a="VCC", b="GND", analysis_enabled=False),
    ]))
    result = evaluate_electrical(workspace); pending = _branch(result, "mcu")
    assert pending.supply_connected and pending.return_connected
    assert pending.voltage_drop_v is None and result.source_power_w == 0
    raw = workspace.model_dump(); raw["components"][1]["closed"] = False
    assert not _branch(evaluate_electrical(raw), "mcu").supply_connected


def test_adopting_legacy_known_model_discards_only_invalid_pins_with_explicit_consent():
    raw = original().model_dump()
    raw["electrical"]["nodes"].extend(["VALID", "OLD_POWER_LABEL"])
    raw["electrical"]["components"].append(dict(id="legacy", name="Existing board", kind="mcu",
        part_id="board", catalog_id="rpi4b", a="BAT", b="GND", rated_voltage_v=5, rated_current_a=.1,
        signal_pins={"GPIO17": "VALID", "5V_2": "OLD_POWER_LABEL"}))
    design = Design.model_validate(raw); before = design.model_dump()
    with pytest.raises(ValueError, match="명시적으로 확인"):
        register_part(design, "board", dict(catalog_id="rpi4b"))
    adopted = register_part(design, "board", dict(catalog_id="rpi4b", allow_drop_connections=True))
    assert registration_for_part(adopted, "board").signal_pins == {"GPIO17": "VALID"}
    assert "OLD_POWER_LABEL" in adopted.electrical.nodes and design.model_dump() == before
