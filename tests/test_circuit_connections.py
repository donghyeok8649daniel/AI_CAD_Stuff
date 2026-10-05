"""Canvas wiring changes only the selected endpoint and verified aliases."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from cadstudio.board_pins import board_pinout
from cadstudio.circuit_connections import (assign_schematic_node, connect_schematic_terminals,
                                           disconnect_schematic_terminal)
from cadstudio.electrical import ElectricalWorkspace, evaluate_electrical


def circuit():
    return ElectricalWorkspace.model_validate(dict(nodes=["GND", "BAT", "SIG_A", "SIG_B"], components=[
        dict(id="battery", name="Battery", kind="battery", a="BAT", b="GND", voltage_v=5),
        dict(id="pi", name="Pi", kind="mcu", catalog_id="rpi4b", pinout_catalog_id="rpi4b",
             a="BAT", b="GND", rated_voltage_v=5, rated_current_a=.1,
             signal_pins={"GPIO17": "SIG_A", "GPIO18": "SIG_A"}),
        dict(id="uno", name="UNO", kind="mcu", catalog_id="arduino_uno_r3", pinout_catalog_id="arduino_uno_r3",
             a="BAT", b="GND", rated_voltage_v=5, rated_current_a=.1,
             signal_pins={"A4": "SIG_A", "SDA": "SIG_A", "D2": "SIG_A"}),
        dict(id="sensor", name="Manual sensor", kind="load", a="BAT", b="GND", rated_voltage_v=5,
             rated_current_a=.02, terminal_pins={"OUT_A": "SIG_A", "PWM": "SIG_B"}),
        dict(id="pull", name="Pull resistor", kind="resistor", a="SIG_A", b="GND", resistance_ohm=10000),
        dict(id="driver", name="DRV8833", kind="load", a="BAT", b="GND", catalog_id="pololu_2130",
             analysis_enabled=False, part_registration=True, part_id="driver_body",
             product_pinout_catalog_id="pololu_2130"),
    ], schematic_positions={"pi": dict(x=520, y=240)}))


def component(workspace, identifier):
    return next(item for item in workspace.components if item.id == identifier)


def test_reassigning_power_endpoint_does_not_merge_old_shared_net_or_mutate_input():
    workspace = circuit(); original = workspace.model_dump()
    moved = connect_schematic_terminals(workspace, "pull", "a", "sensor", "port:PWM")
    assert component(moved, "pull").a == "SIG_B"
    assert component(moved, "pi").signal_pins == original["components"][1]["signal_pins"]
    assert component(moved, "sensor").terminal_pins == {"OUT_A": "SIG_A", "PWM": "SIG_B"}
    assert moved.schematic_positions == workspace.schematic_positions
    assert workspace.model_dump() == original


def test_source_mcu_signal_aliases_move_together_without_moving_other_gpio_users():
    workspace = circuit(); original = workspace.model_dump()
    moved = connect_schematic_terminals(workspace, "uno", "pin:SDA", "sensor", "port:PWM")
    assert component(moved, "uno").signal_pins == {"A4": "SIG_B", "SDA": "SIG_B", "D2": "SIG_A"}
    assert component(moved, "pi").signal_pins == {"GPIO17": "SIG_A", "GPIO18": "SIG_A"}
    assert component(moved, "pull").a == "SIG_A"
    assert component(moved, "uno").pinout_catalog_id == "arduino_uno_r3"
    assert workspace.model_dump() == original


def test_unassigned_target_board_signal_gets_a_new_net_and_existing_gpio_alias_semantics():
    workspace = circuit(); original = workspace.model_dump()
    linked = connect_schematic_terminals(workspace, "sensor", "port:OUT_A", "pi", "pin:GPIO19")
    node = component(linked, "pi").signal_pins["GPIO19"]
    assert node not in workspace.nodes and node == linked.nodes[-1]
    assert component(linked, "sensor").terminal_pins["OUT_A"] == node
    assert component(linked, "sensor").terminal_pins["PWM"] == "SIG_B"
    assert component(linked, "pull").a == "SIG_A"
    assert workspace.model_dump() == original


def test_pending_real_product_terminal_connects_without_forging_dc_load_or_pin_provenance():
    workspace = circuit(); result_before = evaluate_electrical(workspace)
    linked = connect_schematic_terminals(workspace, "pi", "pin:GPIO17", "driver", "port:AIN1")
    driver = component(linked, "driver")
    assert driver.terminal_pins == {"AIN1": component(linked, "pi").signal_pins["GPIO17"]}
    assert driver.product_pinout_catalog_id == "pololu_2130"
    assert driver.part_id == "driver_body" and driver.part_registration is True
    assert driver.analysis_enabled is False and driver.rated_current_a == 0
    assert result_before.source_power_w == evaluate_electrical(linked).source_power_w
    assert ElectricalWorkspace.model_validate_json(linked.model_dump_json()) == linked


def test_product_to_product_unassigned_target_allocates_net_and_binds_verified_ports():
    workspace = circuit()
    linked = connect_schematic_terminals(workspace, "sensor", "port:PWM", "driver", "port:BIN1")
    node = component(linked, "driver").terminal_pins["BIN1"]
    assert node in linked.nodes and node not in workspace.nodes
    assert component(linked, "sensor").terminal_pins["PWM"] == node
    assert component(linked, "driver").product_pinout_catalog_id == "pololu_2130"
    assert component(workspace, "driver").terminal_pins == {}


@pytest.mark.parametrize("source,target", [("a", "b"), ("pin:SDA", "pin:A4"), ("pin:D2", "pin:D2")])
def test_self_component_wiring_is_rejected_atomically(source, target):
    workspace = circuit(); original = workspace.model_dump()
    with pytest.raises(ValueError, match="같은 부품"):
        connect_schematic_terminals(workspace, "uno", source, "uno", target)
    assert workspace.model_dump() == original


def test_other_component_connection_that_shorts_source_supply_pair_is_rejected():
    workspace = circuit(); original = workspace.model_dump()
    with pytest.raises(ValidationError, match="서로 다른"):
        connect_schematic_terminals(workspace, "battery", "a", "sensor", "b")
    assert workspace.model_dump() == original


@pytest.mark.parametrize("source_id,source_terminal,target_id,target_terminal", [
    ("missing", "a", "battery", "a"), ("pull", "pin:FAKE", "battery", "a"),
    ("sensor", "port:UNDECLARED", "pi", "pin:GPIO17"), ("sensor", "a", "driver", "port:FAKE"),
    ("pi", "pin:GPIO999", "sensor", "a"), ("pi", "a", "uno", "pin:POWER")])
def test_unregistered_or_wrong_endpoint_is_rejected(source_id, source_terminal, target_id, target_terminal):
    workspace = circuit(); original = workspace.model_dump()
    with pytest.raises(ValueError):
        connect_schematic_terminals(workspace, source_id, source_terminal, target_id, target_terminal)
    assert workspace.model_dump() == original


def test_physical_board_power_pad_never_becomes_signal_or_implicit_dc_supply():
    workspace = circuit(); original = workspace.model_dump()
    power_key = next(pin.key for pin in board_pinout("rpi4b").pins if pin.kind == "power")
    with pytest.raises(ValueError):
        connect_schematic_terminals(workspace, "battery", "a", "pi", f"pin:{power_key}")
    assert workspace.model_dump() == original


def test_disconnect_a_b_and_product_ports_affects_selected_terminal_only():
    workspace = circuit(); original = workspace.model_dump()
    disconnected = disconnect_schematic_terminal(workspace, "pull", "a")
    assert component(disconnected, "pull").a == disconnected.nodes[-1]
    assert disconnected.nodes[-1] not in workspace.nodes
    assert component(disconnected, "pull").b == "GND"
    assert component(disconnected, "pi").signal_pins == component(workspace, "pi").signal_pins
    removed = disconnect_schematic_terminal(disconnected, "sensor", "port:OUT_A")
    assert component(removed, "sensor").terminal_pins == {"PWM": "SIG_B"}
    assert removed.nodes == disconnected.nodes  # Previously named nets remain usable.
    assert workspace.model_dump() == original


def test_disconnect_mcu_pad_clears_only_that_gpio_alias_group():
    workspace = circuit(); disconnected = disconnect_schematic_terminal(workspace, "uno", "pin:SDA")
    assert component(disconnected, "uno").signal_pins == {"D2": "SIG_A"}
    assert component(disconnected, "pi").signal_pins == {"GPIO17": "SIG_A", "GPIO18": "SIG_A"}
    assert disconnected.nodes == workspace.nodes


def test_explicit_net_assignment_preserves_named_nodes_layout_and_unrelated_endpoints():
    workspace = circuit(); original = workspace.model_dump()
    assigned = assign_schematic_node(workspace, "driver", "port:AIN1", "USER_PWM")
    assert component(assigned, "driver").terminal_pins == {"AIN1": "USER_PWM"}
    assert assigned.nodes == workspace.nodes + ["USER_PWM"]
    assert assigned.schematic_positions == workspace.schematic_positions
    assert component(assigned, "driver").product_pinout_catalog_id == "pololu_2130"
    assert workspace.model_dump() == original
    with pytest.raises(ValueError, match="노드 ID"):
        assign_schematic_node(workspace, "sensor", "port:PWM", "invalid node")


def test_fresh_node_limit_rejects_disconnect_or_unassigned_target_without_partial_edits():
    raw = circuit().model_dump()
    raw["nodes"].extend(f"NET_{index}" for index in range(128 - len(raw["nodes"])))
    workspace = ElectricalWorkspace.model_validate(raw); original = workspace.model_dump()
    for operation in (
        lambda: disconnect_schematic_terminal(workspace, "battery", "a"),
        lambda: connect_schematic_terminals(workspace, "sensor", "port:PWM", "driver", "port:AIN1"),
        lambda: connect_schematic_terminals(workspace, "pi", "pin:GPIO17", "driver", "port:AIN1"),
        lambda: assign_schematic_node(workspace, "sensor", "port:PWM", "NEW_NODE"),
    ):
        with pytest.raises(ValueError, match="128"):
            operation()
        assert workspace.model_dump() == original


def test_stale_pin_provenance_is_revalidated_before_any_endpoint_edit():
    raw = circuit().model_dump()
    next(item for item in raw["components"] if item["id"] == "driver")["catalog_id"] = "pololu_4755"
    original = deepcopy(raw)
    with pytest.raises(ValueError, match="모델이 변경"):
        connect_schematic_terminals(raw, "battery", "a", "sensor", "a")
    assert raw == original
