"""Physical MCU pin editing preserves nets and has no fictional GPIO solver."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from cadstudio.board_pins import board_pinout
from cadstudio.electrical import ElectricalWorkspace, evaluate_electrical
from cadstudio.mcu_connections import (
    assign_pin, assign_pin_node, change_mcu_model, connection_endpoints,
    disconnect_pin, pin_connections, topology_warnings,
)


def circuit():
    return ElectricalWorkspace.model_validate(dict(
        nodes=["GND", "BAT", "SIG_A", "SIG_B", "UNUSED", "MCUNET_001"],
        components=[
            dict(id="bat", name="5 V supply", kind="battery", a="BAT", b="GND", voltage_v=5),
            dict(id="pi", name="Controller", kind="mcu", catalog_id="rpi4b", a="BAT", b="GND",
                 rated_voltage_v=5, rated_current_a=.1, part_id="controller_body"),
            dict(id="uno", name="Remote controller", kind="mcu", catalog_id="arduino_uno_r3",
                 a="BAT", b="GND", rated_voltage_v=5, rated_current_a=.15),
            dict(id="sense", name="Encoder / driver", kind="load", a="BAT", b="GND",
                 rated_voltage_v=5, rated_current_a=.02, terminal_pins={"OUT_A": "SIG_A", "PWM": "SIG_B"}),
            dict(id="pull", name="Pull resistor", kind="resistor", a="SIG_A", b="GND", resistance_ohm=10000),
        ]))


def part(workspace, identifier):
    return next(component for component in workspace.components if component.id == identifier)


def branch(result, identifier):
    return next(component for component in result.components if component.id == identifier)


def test_pinout_physical_labels_and_supply_pins_are_not_implicitly_connected():
    workspace = circuit()
    before = workspace.model_dump()
    rows = {row.key: row for row in pin_connections(workspace, "pi")}
    assert "11" in rows["GPIO17"].label
    assert rows["GPIO17"].kind == "signal" and rows["GPIO17"].node is None
    assert all(row.node is None for row in rows.values() if row.kind in ("power", "ground"))
    assert workspace.model_dump() == before
    endpoints = connection_endpoints(workspace, exclude_mcu_id="pi")
    assert not any(endpoint.component_id == "pi" for endpoint in endpoints)
    assert any(endpoint.component_id == "sense" and endpoint.terminal == "port:OUT_A"
               and endpoint.node == "SIG_A" for endpoint in endpoints)
    assert any(endpoint.component_id == "uno" and endpoint.terminal == "pin:D2"
               and endpoint.node is None for endpoint in endpoints)


def test_assignment_to_declared_encoder_signal_is_passive_and_round_trips():
    workspace = circuit()
    before = workspace.model_dump()
    result_before = evaluate_electrical(workspace)
    assigned = assign_pin(workspace, "pi", "GPIO17", "sense", "port:OUT_A")
    assert workspace.model_dump() == before
    assert part(assigned, "pi").signal_pins == {"GPIO17": "SIG_A"}
    assert part(assigned, "pi").pinout_catalog_id == "rpi4b"
    assert part(assigned, "pi").part_id == "controller_body"
    assert assigned.nodes == workspace.nodes  # Including deliberately unused named nets.
    result = evaluate_electrical(assigned)
    assert branch(result, "pi").signal_pin_connected == {"GPIO17": True}
    assert branch(result, "pi").current_a == pytest.approx(branch(result_before, "pi").current_a)
    assert result.source_power_w == pytest.approx(result_before.source_power_w)
    assert ElectricalWorkspace.model_validate_json(assigned.model_dump_json()) == assigned
    row = next(row for row in pin_connections(assigned, "pi") if row.key == "GPIO17")
    assert any(endpoint.component_id == "sense" and endpoint.terminal == "port:OUT_A" for endpoint in row.targets)


def test_unassigned_other_mcu_signal_creates_unique_net_and_voltage_warning():
    workspace = circuit()
    assigned = assign_pin(workspace, "pi", "GPIO17", "uno", "pin:D2")
    assert part(assigned, "pi").signal_pins == {"GPIO17": "MCUNET_002"}
    assert part(assigned, "uno").signal_pins == {"D2": "MCUNET_002"}
    assert assigned.nodes[-1] == "MCUNET_002"
    assert not part(workspace, "pi").signal_pins
    result = evaluate_electrical(assigned)
    assert branch(result, "pi").signal_pin_connected == {"GPIO17": True}
    assert branch(result, "uno").signal_pin_connected == {"D2": True}
    assert any("3.3 V / 5 V" in warning for warning in topology_warnings(assigned))
    assert any("Different logic references" in warning for warning in topology_warnings(assigned, language="en"))
    assert any("레벨 변환" in warning for warning in result.warnings)
    # Passive pin maps never acquire absolute node voltage or source current.
    assert "MCUNET_002" not in result.node_voltages_v
    assert branch(result, "pi").current_a == pytest.approx(.1)


def test_reassigning_one_gpio_does_not_move_another_gpio_or_target_net():
    workspace = assign_pin_node(circuit(), "pi", "GPIO17", "SIG_A")
    workspace = assign_pin_node(workspace, "pi", "GPIO18", "SIG_A")
    workspace = assign_pin_node(workspace, "uno", "D2", "SIG_A")
    before = workspace.model_dump()
    moved = assign_pin(workspace, "pi", "GPIO17", "sense", "port:PWM")
    assert part(moved, "pi").signal_pins == {"GPIO17": "SIG_B", "GPIO18": "SIG_A"}
    assert part(moved, "uno").signal_pins["D2"] == "SIG_A"
    assert part(moved, "sense").terminal_pins == {"OUT_A": "SIG_A", "PWM": "SIG_B"}
    assert part(moved, "pull").a == "SIG_A"
    assert workspace.model_dump() == before
    disconnected = disconnect_pin(moved, "pi", "GPIO17")
    assert part(disconnected, "pi").signal_pins == {"GPIO18": "SIG_A"}
    assert disconnected.nodes == moved.nodes
    assert part(disconnected, "sense").terminal_pins == part(moved, "sense").terminal_pins


def test_duplicate_gpio_connector_aliases_cannot_be_split_and_unassign_together():
    workspace = assign_pin_node(circuit(), "uno", "A4", "SIG_A")
    workspace = assign_pin_node(workspace, "uno", "SDA", "SIG_A")
    moved = assign_pin_node(workspace, "uno", "SDA", "SIG_B")
    assert part(moved, "uno").signal_pins == {"A4": "SIG_B", "SDA": "SIG_B"}
    rows = {row.key: row for row in pin_connections(moved, "uno")}
    assert rows["A4"].node == rows["SDA"].node == "SIG_B"
    assert all(not endpoint.terminal.startswith("pin:") for endpoint in rows["A4"].targets
               if endpoint.component_id == "uno")
    raw = moved.model_dump()
    next(component for component in raw["components"] if component["id"] == "uno")["signal_pins"]["SDA"] = "SIG_A"
    with pytest.raises(ValidationError, match="동일 GPIO"):
        ElectricalWorkspace.model_validate(raw)
    removed = disconnect_pin(moved, "uno", "A4")
    assert part(removed, "uno").signal_pins == {}


def test_alias_only_attachments_do_not_claim_a_connected_signal_partner():
    workspace = assign_pin_node(circuit(), "uno", "A4", "FLOAT")
    workspace = assign_pin_node(workspace, "uno", "SDA", "FLOAT")
    result = evaluate_electrical(workspace)
    assert branch(result, "uno").signal_pin_connected == {"A4": False, "SDA": False}
    # Distinct GPIOs on one MCU are real distinct net endpoints.
    workspace = assign_pin_node(workspace, "uno", "D2", "FLOAT")
    result = evaluate_electrical(workspace)
    assert branch(result, "uno").signal_pin_connected == {"A4": True, "SDA": True, "D2": True}


def test_bound_physical_pin_keys_reject_fake_signal_and_supply_aliases():
    workspace = assign_pin_node(circuit(), "pi", "GPIO17", "SIG_A")
    for key in ("GPIO999", next(pin.key for pin in board_pinout("rpi4b").pins if pin.kind == "power")):
        raw = workspace.model_dump()
        next(component for component in raw["components"] if component["id"] == "pi")["signal_pins"] = {key: "SIG_A"}
        with pytest.raises(ValidationError, match="信号|신호 핀"):
            ElectricalWorkspace.model_validate(raw)
    power_key = next(pin.key for pin in board_pinout("rpi4b").pins if pin.kind == "power")
    with pytest.raises(ValueError, match="별도 전원"):
        assign_pin(circuit(), "pi", power_key, "bat", "a")
    raw = workspace.model_dump()
    next(component for component in raw["components"] if component["id"] == "pi")["catalog_id"] = "rpi3bplus"
    with pytest.raises(ValidationError, match="모델이 변경"):
        ElectricalWorkspace.model_validate(raw)


def test_legacy_unknown_pin_is_preserved_visible_and_warned_until_confirmed_binding():
    workspace = circuit()
    part(workspace, "pi").signal_pins = {"OldLabel": "SIG_A"}
    workspace = ElectricalWorkspace.model_validate(workspace.model_dump())
    changed = assign_pin_node(workspace, "pi", "GPIO17", "SIG_B")
    assert part(changed, "pi").signal_pins == {"OldLabel": "SIG_A", "GPIO17": "SIG_B"}
    assert part(changed, "pi").pinout_catalog_id == ""
    assert any(row.key == "OldLabel" and row.legacy for row in pin_connections(changed, "pi"))
    assert any("OldLabel" in warning and "연결을 보존" in warning for warning in topology_warnings(changed))
    with pytest.raises(ValueError, match="명시적으로 확인"):
        change_mcu_model(changed, "pi", "rpi4b")
    rebound, dropped = change_mcu_model(changed, "pi", "rpi4b", allow_drop=True)
    assert dropped == {"OldLabel": "SIG_A"}
    assert part(rebound, "pi").signal_pins == {"GPIO17": "SIG_B"}
    assert part(rebound, "pi").pinout_catalog_id == "rpi4b"


def test_changing_board_requires_confirmation_even_if_gpio_label_also_exists():
    original = assign_pin_node(circuit(), "pi", "GPIO17", "SIG_A")
    before = original.model_dump()
    with pytest.raises(ValueError, match="명시적으로 확인"):
        change_mcu_model(original, "pi", "rpi3bplus")
    changed, dropped = change_mcu_model(original, "pi", "rpi3bplus", allow_drop=True)
    assert dropped == {"GPIO17": "SIG_A"}
    assert part(changed, "pi").signal_pins == {}
    assert part(changed, "pi").rated_voltage_v == 5 and part(changed, "pi").rated_current_a == .1
    assert changed.nodes == original.nodes and original.model_dump() == before
    # A stale manually edited model is not silently accepted as a valid map.
    part(original, "pi").catalog_id = "arduino_uno_r3"
    with pytest.raises(ValidationError, match="モデル|모델이 변경"):
        connection_endpoints(original)


def test_gpio_direct_battery_and_motor_power_have_warnings_not_fake_drive_current():
    workspace = circuit()
    raw = workspace.model_dump()
    raw["components"].append(dict(id="motor", name="Motor", kind="motor", a="BAT", b="GND",
                                  rated_voltage_v=5, rated_current_a=.2))
    workspace = ElectricalWorkspace.model_validate(raw)
    before = evaluate_electrical(workspace)
    connected = assign_pin(workspace, "pi", "GPIO17", "motor", "a")
    warnings = topology_warnings(connected)
    assert any("배터리 전원 단자" in warning for warning in warnings)
    assert any("별도 드라이버" in warning for warning in warnings)
    assert any("부하·센서·드라이버의 전력 단자" in warning for warning in warnings)
    after = evaluate_electrical(connected)
    assert branch(after, "motor").current_a == branch(before, "motor").current_a
    assert branch(after, "pi").current_a == branch(before, "pi").current_a


def test_signal_wire_break_is_detected_without_changing_board_power():
    raw = circuit().model_dump()
    raw["nodes"].append("REMOTE")
    raw["components"] = [component for component in raw["components"] if component["id"] != "pull"]
    next(component for component in raw["components"] if component["id"] == "sense")["terminal_pins"] = {"OUT_A": "REMOTE"}
    raw["components"].append(dict(id="wire", name="Signal wire", kind="wire", a="SIG_A", b="REMOTE",
                                  length_mm=100, cross_section_mm2=.5))
    workspace = assign_pin(raw, "pi", "GPIO17", "wire", "a")
    healthy = evaluate_electrical(workspace)
    assert branch(healthy, "pi").signal_pin_connected["GPIO17"] is True
    part(workspace, "wire").closed = False
    broken = evaluate_electrical(workspace)
    assert branch(broken, "pi").signal_pin_connected["GPIO17"] is False
    assert branch(broken, "pi").current_a == branch(healthy, "pi").current_a
    assert any("GPIO17" in warning and "단선" in warning for warning in broken.warnings)


def test_declared_signal_ports_and_node_ids_are_strict_and_not_solver_branches():
    raw = circuit().model_dump()
    for alteration in ({"bad label": "SIG_A"}, {"GOOD": "wrong node"}, {"GOOD": "MISSING"}):
        changed = deepcopy(raw)
        next(component for component in changed["components"] if component["id"] == "sense")["terminal_pins"] = alteration
        with pytest.raises(ValidationError):
            ElectricalWorkspace.model_validate(changed)
    changed = deepcopy(raw)
    next(component for component in changed["components"] if component["id"] == "bat")["terminal_pins"] = {"OUT": "SIG_A"}
    with pytest.raises(ValidationError, match="추가 신호 단자"):
        ElectricalWorkspace.model_validate(changed)
    # Both signal ports of this sensor have no DC current edges.
    result = evaluate_electrical(raw)
    assert "SIG_B" not in result.node_voltages_v


def test_custom_mcu_free_pin_labels_and_new_named_nodes_remain_supported():
    raw = circuit().model_dump()
    controller = next(component for component in raw["components"] if component["id"] == "pi")
    controller["catalog_id"] = "custom_board"
    workspace = assign_pin_node(raw, "pi", "GPIO_CUSTOM_42", "USER_NET")
    assert part(workspace, "pi").signal_pins == {"GPIO_CUSTOM_42": "USER_NET"}
    assert part(workspace, "pi").pinout_catalog_id == ""
    assert any(row.legacy for row in pin_connections(workspace, "pi"))
    assert any("수동 연결" in warning for warning in topology_warnings(workspace))
    with pytest.raises(ValueError, match="노드 ID"):
        assign_pin_node(raw, "pi", "GPIO_CUSTOM_42", "bad node")
    with pytest.raises(ValueError, match="핀 이름"):
        assign_pin_node(raw, "pi", "bad pin", "USER_NET")


def test_large_board_exceeds_legacy_32pin_limit_and_node_creation_stays_guarded():
    raw = circuit().model_dump()
    controller = next(component for component in raw["components"] if component["id"] == "pi")
    controller.update(catalog_id="arduino_mega2560_r3", pinout_catalog_id="arduino_mega2560_r3",
                      signal_pins={pin.key: "SIG_A" for pin in board_pinout("arduino_mega2560_r3").pins if pin.kind == "signal"})
    workspace = ElectricalWorkspace.model_validate(raw)
    assert len(part(workspace, "pi").signal_pins) > 32
    assert ElectricalWorkspace.model_validate_json(workspace.model_dump_json()) == workspace
    raw["nodes"].extend(f"NET_{index}" for index in range(512 - len(raw["nodes"])))
    saturated = ElectricalWorkspace.model_validate(raw)
    with pytest.raises(ValueError, match="512"):
        assign_pin_node(saturated, "pi", "D2", "NEW_NET")
    # Existing nets are still editable at the size bound.
    assert part(assign_pin_node(saturated, "pi", "D2", "SIG_B"), "pi").signal_pins["D2"] == "SIG_B"


def test_passive_pin_map_size_is_bounded_even_for_custom_boards():
    raw = circuit().model_dump()
    controller = next(component for component in raw["components"] if component["id"] == "pi")
    controller.update(catalog_id="custom_board", signal_pins={f"GPIO_{index}": "SIG_A" for index in range(144)})
    workspace = ElectricalWorkspace.model_validate(raw)
    assert len(part(workspace, "pi").signal_pins) == 144
    controller["signal_pins"]["GPIO_144"] = "SIG_A"
    with pytest.raises(ValidationError, match="144"):
        ElectricalWorkspace.model_validate(raw)


def test_invalid_endpoint_and_self_gpio_reject_without_input_mutation():
    workspace = circuit()
    before = workspace.model_dump()
    for target, terminal in (("missing", "a"), ("sense", "port:missing"), ("sense", "pin:D2"), ("pi", "pin:GPIO17")):
        with pytest.raises(ValueError):
            assign_pin(workspace, "pi", "GPIO17", target, terminal)
    assert workspace.model_dump() == before
