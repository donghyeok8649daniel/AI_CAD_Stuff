"""512 named nets preserve real cable endpoints and documented board pins."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from cadstudio.board_pins import board_pinout
from cadstudio.board_supply import assign_board_supply_node
from cadstudio.circuit_connections import (
    add_schematic_wire, assign_schematic_node, connect_schematic_terminals,
    delete_schematic_wire, disconnect_schematic_terminal, update_schematic_wire,
)
from cadstudio.electrical import ElectricalWorkspace
from cadstudio.mcu_connections import assign_pin, assign_pin_node, connection_endpoints


def circuit(node_count=512):
    """Manual terminal banks are not fictional product pinouts or GPIOs.

    At 129 nodes every name has an actual terminal/pin use. Larger fixtures
    retain 262 used terminal nets and 130 physical cables, then reserved nets.
    Each bank remains below 144 terminals and the circuit below 256 devices.
    """
    cable_count = 63 if node_count == 129 else 130
    left = [f"LEFT_{index:03d}" for index in range(1, cable_count + 1)]
    right = [f"RIGHT_{index:03d}" for index in range(1, cable_count + 1)]
    nodes = ["GND", "POWER", *left, *right]
    nodes.extend(f"NET_{index:03d}" for index in range(len(nodes) + 1, node_count + 1))
    components = [
        dict(id="source", name="Five volt source", kind="battery", a="POWER", b="GND", voltage_v=5),
        dict(id="bank_left", name="Manual terminal bank A", kind="load", a="POWER", b="GND",
             analysis_enabled=False, terminal_pins={**{f"T{i:03d}": node for i, node in enumerate(left, 1)},
                                                     "SPARE": "POWER"}),
        dict(id="bank_right", name="Manual terminal bank B", kind="load", a="POWER", b="GND",
             analysis_enabled=False, terminal_pins={**{f"T{i:03d}": node for i, node in enumerate(right, 1)},
                                                     "SPARE": "GND"}),
        dict(id="pi", name="Pi 4 controller", kind="mcu", a="POWER", b="GND", analysis_enabled=False,
             catalog_id="rpi4b", pinout_catalog_id="rpi4b", source_url=board_pinout("rpi4b").source_url,
             signal_pins={"GPIO17": left[-1], "GPIO18": nodes[-1]},
             board_supply_pins={"5V_2": "POWER", "GND_6": "GND"}, supply_pinout_catalog_id="rpi4b"),
        dict(id="driver", name="Documented pending driver", kind="load", a="POWER", b="GND",
             analysis_enabled=False, catalog_id="pololu_2130", product_pinout_catalog_id="pololu_2130"),
    ]
    for index, (a, b) in enumerate(zip(left, right), 1):
        source_id, terminal = ("pi", "pin:GPIO17") if index == cable_count else ("bank_left", f"port:T{index:03d}")
        components.append(dict(id=f"WIRE_{index:03d}", name=f"Terminal cable {index}", kind="wire", a=a, b=b,
                               length_mm=250 + index, cross_section_mm2=.25, analysis_enabled=False,
                               wire_color="#123456", wire_endpoints=[
                                   dict(component_id=source_id, terminal=terminal),
                                   dict(component_id="bank_right", terminal=f"port:T{index:03d}"),
                               ]))
    return ElectricalWorkspace.model_validate(dict(nodes=nodes, components=components, schematic_positions={
        "pi": dict(x=750, y=150), "bank_right": dict(x=1200, y=300),
        f"WIRE_{cable_count:03d}": dict(x=975, y=225),
    }))


def component(workspace, identifier):
    return next(item for item in workspace.components if item.id == identifier)


def snapshot(raw):
    return deepcopy(raw.model_dump() if isinstance(raw, ElectricalWorkspace) else raw)


def as_input(workspace, input_kind):
    return workspace if input_kind == "model" else workspace.model_dump()


def wires(workspace):
    return [item.model_dump() for item in workspace.components if item.kind == "wire"]


def assert_wire_ownership(workspace):
    endpoints = {(item.component_id, item.terminal): item.node for item in connection_endpoints(workspace)}
    for wire in (item for item in workspace.components if item.kind == "wire"):
        assert len(wire.wire_endpoints) == 2
        assert endpoints[(wire.wire_endpoints[0].component_id, wire.wire_endpoints[0].terminal)] == wire.a
        assert endpoints[(wire.wire_endpoints[1].component_id, wire.wire_endpoints[1].terminal)] == wire.b


def assert_existing_cables_and_supply(before, after):
    assert wires(after) == wires(before)
    assert_wire_ownership(after)
    assert after.nodes.count("GND") == 1
    assert [item.id for item in after.components] == [item.id for item in before.components]
    assert after.schematic_positions == before.schematic_positions
    old_pi, pi = component(before, "pi"), component(after, "pi")
    assert pi.signal_pins["GPIO17"] == old_pi.signal_pins["GPIO17"]
    assert pi.board_supply_pins == old_pi.board_supply_pins == {"5V_2": "POWER", "GND_6": "GND"}
    assert pi.pinout_catalog_id == pi.supply_pinout_catalog_id == "rpi4b"
    assert pi.source_url == old_pi.source_url


@pytest.mark.parametrize("node_count", [129, 511, 512])
def test_expanded_schema_round_trips_used_terminal_nets_and_physical_pi_cables(node_count):
    workspace = circuit(node_count)
    assert len(workspace.nodes) == node_count
    assert len(wires(workspace)) == (63 if node_count == 129 else 130)
    used = {node for item in workspace.components for node in
            (item.a, item.b, *item.terminal_pins.values(), *item.signal_pins.values(), *item.board_supply_pins.values())}
    assert len(used) >= 129
    assert all(len(item.terminal_pins) <= 144 for item in workspace.components)
    assert len(workspace.components) < 256
    assert_wire_ownership(workspace)
    restored = ElectricalWorkspace.model_validate_json(workspace.model_dump_json())
    assert restored.model_dump() == workspace.model_dump()
    assert ElectricalWorkspace.model_json_schema()["properties"]["nodes"]["maxItems"] == 512


def test_513th_schema_node_is_rejected_without_changing_input():
    raw = circuit().model_dump()
    raw["nodes"].append("NET_513")
    before = deepcopy(raw)
    with pytest.raises(ValidationError) as caught:
        ElectricalWorkspace.model_validate(raw)
    assert any(error["loc"] == ("nodes",) and error["type"] == "too_long" for error in caught.value.errors())
    assert raw == before


CREATE_OPERATIONS = [
    pytest.param(lambda raw: assign_schematic_node(raw, "bank_left", "port:SPARE", "NEW_512"), id="schematic-assign"),
    pytest.param(lambda raw: assign_pin_node(raw, "pi", "GPIO19", "NEW_512"), id="gpio-assign"),
    pytest.param(lambda raw: connect_schematic_terminals(raw, "bank_left", "port:SPARE", "driver", "port:AIN1"), id="schematic-connect"),
    pytest.param(lambda raw: assign_pin(raw, "pi", "GPIO19", "driver", "port:BIN1"), id="gpio-connect"),
    pytest.param(lambda raw: disconnect_schematic_terminal(raw, "bank_left", "a"), id="disconnect-required-terminal"),
]


@pytest.mark.parametrize("input_kind", ["model", "dict"])
@pytest.mark.parametrize("operation", CREATE_OPERATIONS)
def test_511_to_512_creation_preserves_existing_cables_supply_and_input(input_kind, operation):
    workspace = circuit(511)
    raw = as_input(workspace, input_kind)
    before = snapshot(raw)
    result = operation(raw)
    assert result.nodes[:-1] == workspace.nodes
    assert len(result.nodes) == 512 and result.nodes[-1] not in workspace.nodes
    assert_existing_cables_and_supply(workspace, result)
    assert snapshot(raw) == before
    # A successful operation must bind the new node, rather than append a label only.
    assert any(result.nodes[-1] in (item.a, item.b, *item.terminal_pins.values(), *item.signal_pins.values())
               for item in result.components if item.kind != "wire")


EXISTING_OPERATIONS = [
    pytest.param(lambda raw: assign_schematic_node(raw, "bank_left", "port:SPARE", "NET_510"), id="schematic-late-net"),
    pytest.param(lambda raw: assign_pin_node(raw, "pi", "GPIO18", "NET_510"), id="gpio-late-net"),
    pytest.param(lambda raw: assign_pin(raw, "pi", "GPIO19", "bank_right", "port:T130"), id="gpio-existing-terminal"),
    pytest.param(lambda raw: connect_schematic_terminals(raw, "bank_left", "port:SPARE", "pi", "pin:GPIO18"), id="connect-existing-gpio"),
]


@pytest.mark.parametrize("input_kind", ["model", "dict"])
@pytest.mark.parametrize("operation", EXISTING_OPERATIONS)
def test_existing_net_reassignment_succeeds_at_512_without_moving_saved_cables(input_kind, operation):
    workspace = circuit()
    raw = as_input(workspace, input_kind)
    before = snapshot(raw)
    result = operation(raw)
    assert result.nodes == workspace.nodes
    assert result.model_dump() != before
    assert_existing_cables_and_supply(workspace, result)
    assert snapshot(raw) == before


REJECTED_OPERATIONS = [
    pytest.param(lambda raw: assign_schematic_node(raw, "bank_left", "port:SPARE", "NEW_513"), id="schematic-assign"),
    pytest.param(lambda raw: assign_pin_node(raw, "pi", "GPIO19", "NEW_513"), id="gpio-assign"),
    pytest.param(lambda raw: assign_board_supply_node(raw, "pi", "5V_2", "NEW_513"), id="board-supply-assign"),
    pytest.param(lambda raw: connect_schematic_terminals(raw, "bank_left", "port:SPARE", "driver", "port:AIN1"), id="schematic-connect"),
    pytest.param(lambda raw: connect_schematic_terminals(raw, "pi", "pin:GPIO19", "driver", "port:AIN1"), id="schematic-gpio-connect"),
    pytest.param(lambda raw: assign_pin(raw, "pi", "GPIO19", "driver", "port:BIN1"), id="gpio-connect"),
    pytest.param(lambda raw: disconnect_schematic_terminal(raw, "bank_left", "a"), id="disconnect-required-terminal"),
    pytest.param(lambda raw: add_schematic_wire(raw, "pi", "pin:GPIO19", "driver", "port:AIN1",
                                             name="Pending GPIO lead", length_mm=300, cross_section_mm2=.25), id="wire-new-pads"),
]


@pytest.mark.parametrize("input_kind", ["model", "dict"])
@pytest.mark.parametrize("operation", REJECTED_OPERATIONS)
def test_513th_assign_connect_disconnect_or_wire_is_rejected_atomically(input_kind, operation):
    workspace = circuit()
    raw = as_input(workspace, input_kind)
    before = snapshot(raw)
    with pytest.raises(ValueError, match="512"):
        operation(raw)
    assert snapshot(raw) == before
    assert_wire_ownership(ElectricalWorkspace.model_validate(snapshot(raw)))


@pytest.mark.parametrize("input_kind", ["model", "dict"])
def test_saturated_wire_edit_delete_and_add_keep_late_gpio_and_endpoint_identity(input_kind):
    workspace = circuit()
    raw = as_input(workspace, input_kind)
    before = snapshot(raw)
    original = component(workspace, "WIRE_130")
    edited = update_schematic_wire(raw, original.id, source_id="bank_left", source_terminal="port:SPARE",
                                   target_id="bank_right", target_terminal="port:SPARE", length_mm=975)
    cable = component(edited, original.id)
    assert cable.id == original.id and cable.length_mm == 975
    assert (cable.a, cable.b) == ("POWER", "GND")
    assert [(ref.component_id, ref.terminal) for ref in cable.wire_endpoints] == [
        ("bank_left", "port:SPARE"), ("bank_right", "port:SPARE")]
    assert cable.wire_color == original.wire_color and cable.cross_section_mm2 == original.cross_section_mm2
    assert edited.nodes == workspace.nodes and edited.schematic_positions == workspace.schematic_positions
    assert component(edited, "pi") == component(workspace, "pi")
    assert wires(edited)[:-1] == wires(workspace)[:-1]
    assert_wire_ownership(edited)
    deleted = delete_schematic_wire(edited, original.id)
    assert deleted.nodes == workspace.nodes and original.id not in {item.id for item in deleted.components}
    assert original.id not in deleted.schematic_positions
    assert component(deleted, "bank_left").terminal_pins == component(workspace, "bank_left").terminal_pins
    assert component(deleted, "bank_right").terminal_pins == component(workspace, "bank_right").terminal_pins
    added = add_schematic_wire(deleted, "pi", "pin:GPIO17", "bank_right", "port:T130",
                               name="Restored documented GPIO cable", length_mm=380, cross_section_mm2=.25)
    assert added.nodes == workspace.nodes and len(wires(added)) == 130
    assert component(added, "pi") == component(workspace, "pi")
    assert [(ref.component_id, ref.terminal) for ref in added.components[-1].wire_endpoints] == [
        ("pi", "pin:GPIO17"), ("bank_right", "port:T130")]
    assert_wire_ownership(added)
    assert snapshot(raw) == before


@pytest.mark.parametrize("input_kind", ["model", "dict"])
def test_existing_cable_blocks_gpio_reassignment_even_to_existing_late_net(input_kind):
    raw = as_input(circuit(), input_kind)
    before = snapshot(raw)
    with pytest.raises(ValueError, match="electrical_wire_edit"):
        assign_pin_node(raw, "pi", "GPIO17", "NET_510")
    assert snapshot(raw) == before


@pytest.mark.parametrize("input_kind", ["model", "dict"])
@pytest.mark.parametrize("bad_pin", ["5V_2", "GND_6", "GPIO999"])
def test_capacity_change_does_not_turn_supply_or_unknown_pads_into_gpio(input_kind, bad_pin):
    raw = as_input(circuit(), input_kind)
    before = snapshot(raw)
    with pytest.raises(ValueError):
        assign_pin_node(raw, "pi", bad_pin, "NET_510")
    assert snapshot(raw) == before


@pytest.mark.parametrize("input_kind", ["model", "dict"])
@pytest.mark.parametrize("source_id,source_terminal,target_id,target_terminal", [
    ("bank_left", "port:GPIO17", "bank_right", "port:T130"),
    ("pi", "port:T130", "bank_right", "port:T130"),
    ("pi", "pin:GPIO17", "missing", "port:T130"),
])
def test_expanded_capacity_does_not_relax_physical_wire_endpoint_ownership(
        input_kind, source_id, source_terminal, target_id, target_terminal):
    raw = as_input(circuit(), input_kind)
    before = snapshot(raw)
    with pytest.raises(ValueError):
        add_schematic_wire(raw, source_id, source_terminal, target_id, target_terminal,
                           name="Invalid cable", length_mm=300, cross_section_mm2=.25)
    assert snapshot(raw) == before


@pytest.mark.parametrize("corruption", ["no_ground", "duplicate", "unsafe", "missing_terminal_net", "missing_gpio_net", "missing_supply_net"])
def test_512_schema_keeps_ground_identifiers_and_endpoint_membership_strict(corruption):
    raw = circuit().model_dump()
    if corruption == "no_ground":
        raw["nodes"][0] = "OTHER_GROUND"
    elif corruption == "duplicate":
        raw["nodes"][-1] = raw["nodes"][-2]
    elif corruption == "unsafe":
        raw["nodes"][-1] = "unsafe net"
    else:
        item = next(row for row in raw["components"] if row["id"] == ("bank_left" if corruption == "missing_terminal_net" else "pi"))
        field, key = {"missing_terminal_net": ("terminal_pins", "SPARE"),
                      "missing_gpio_net": ("signal_pins", "GPIO18"),
                      "missing_supply_net": ("board_supply_pins", "5V_2")}[corruption]
        item[field][key] = "MISSING_NET"
    before = deepcopy(raw)
    with pytest.raises(ValidationError):
        ElectricalWorkspace.model_validate(raw)
    assert raw == before
