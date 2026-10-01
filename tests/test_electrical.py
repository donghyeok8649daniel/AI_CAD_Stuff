"""DC wiring calculations behind the native electrical workspace."""

import pytest
from pydantic import ValidationError

from cadstudio.electrical import ElectricalWorkspace, evaluate_electrical
from cadstudio.models import Design, Project


def branch(result, identifier):
    return next(item for item in result.components if item.id == identifier)


def test_battery_wire_and_motor_include_source_and_wire_voltage_loss():
    workspace = ElectricalWorkspace(nodes=["GND", "BAT", "MOTOR"], components=[
        dict(id="cell", name="6 V battery", kind="battery", a="BAT", b="GND", voltage_v=6,
             internal_resistance_ohm=0.1, max_current_a=2, part_id="battery_body"),
        dict(id="cable", name="1 m copper", kind="wire", a="BAT", b="MOTOR", length_mm=1000,
             cross_section_mm2=1),
        dict(id="motor", name="DC motor", kind="motor", a="MOTOR", b="GND", rated_voltage_v=6,
             rated_current_a=1, part_id="motor_body"),
    ])
    result = evaluate_electrical(workspace)
    expected_current = 6 / (6 + .1 + .01724)
    assert branch(result, "cell").current_a == pytest.approx(expected_current)
    assert branch(result, "cable").current_a == pytest.approx(expected_current)
    assert branch(result, "motor").current_a == pytest.approx(expected_current)
    assert branch(result, "cable").voltage_drop_v == pytest.approx(expected_current * .01724)
    assert result.node_voltages_v["MOTOR"] == pytest.approx(expected_current * 6)
    assert result.source_power_w == pytest.approx(result.absorbed_power_w)
    assert branch(result, "motor").part_id == "motor_body"
    assert branch(result, "cell").current_direction == "b_to_a"
    assert branch(result, "cable").current_direction == "a_to_b"
    assert ElectricalWorkspace.model_validate_json(workspace.model_dump_json()) == workspace


def test_parallel_loads_sum_and_battery_current_limit_warns():
    workspace = dict(nodes=["GND", "BAT"], components=[
        dict(id="b", name="Small cell", kind="battery", a="BAT", b="GND", voltage_v=12,
             internal_resistance_ohm=1, max_current_a=1),
        dict(id="l1", name="A", kind="load", a="BAT", b="GND", rated_voltage_v=12, rated_current_a=1),
        dict(id="l2", name="B", kind="load", a="BAT", b="GND", rated_voltage_v=12, rated_current_a=1),
    ])
    result = evaluate_electrical(workspace)
    assert result.node_voltages_v["BAT"] == pytest.approx(72 / 7)
    assert branch(result, "b").current_a == pytest.approx(12 / 7)
    assert branch(result, "b").current_a == pytest.approx(branch(result, "l1").current_a + branch(result, "l2").current_a)
    assert any("Small cell" in warning and "초과" in warning for warning in result.warnings)


def test_open_switch_has_zero_current_and_does_not_fake_voltage_on_isolated_node():
    workspace = dict(nodes=["GND", "BAT", "SW", "FLOAT"], components=[
        dict(id="b", name="Battery", kind="battery", a="BAT", b="GND", voltage_v=9),
        dict(id="sw", name="Open", kind="switch", a="BAT", b="SW", closed=False),
        dict(id="r", name="Return load", kind="resistor", a="SW", b="GND", resistance_ohm=100),
        dict(id="unused", name="Unused switch", kind="switch", a="BAT", b="FLOAT", closed=False),
    ])
    result = evaluate_electrical(workspace)
    assert branch(result, "sw").current_a == 0
    assert branch(result, "sw").voltage_drop_v == pytest.approx(9)
    assert result.node_voltages_v["SW"] == pytest.approx(0)
    assert branch(result, "unused").voltage_drop_v is None
    assert "FLOAT" not in result.node_voltages_v


def test_explicit_motor_start_current_creates_distinct_peak_case_and_warnings():
    workspace = dict(nodes=["GND", "BAT"], components=[
        dict(id="b", name="Battery", kind="battery", a="BAT", b="GND", voltage_v=12,
             internal_resistance_ohm=.2, max_current_a=3),
        dict(id="m", name="Motor", kind="motor", a="BAT", b="GND", rated_voltage_v=12,
             rated_current_a=1, startup_current_a=6),
    ])
    result = evaluate_electrical(workspace)
    assert result.startup is not None
    assert branch(result, "m").current_a == pytest.approx(12 / 12.2)
    assert branch(result.startup, "m").current_a == pytest.approx(12 / 2.2)
    assert not result.warnings
    assert any("Battery" in warning and "초과" in warning for warning in result.startup.warnings)


def test_mcu_polarity_and_low_voltage_are_reported_as_review_warnings():
    workspace = dict(nodes=["GND", "BAT", "MCU"], components=[
        dict(id="b", name="Cell", kind="battery", a="BAT", b="GND", voltage_v=5,
             internal_resistance_ohm=1),
        dict(id="w", name="Lead", kind="wire", a="BAT", b="MCU", length_mm=1000,
             cross_section_mm2=.01),
        dict(id="m", name="MCU", kind="mcu", a="MCU", b="GND", rated_voltage_v=5,
             rated_current_a=1),
    ])
    result = evaluate_electrical(workspace)
    assert branch(result, "m").voltage_drop_v < 4.5
    assert any("최소 동작 전압" in warning for warning in result.warnings)
    reversed_mcu = dict(nodes=["GND", "BAT"], components=[
        dict(id="b", name="Cell", kind="battery", a="BAT", b="GND", voltage_v=5),
        dict(id="m", name="MCU", kind="mcu", a="GND", b="BAT", rated_voltage_v=5,
             rated_current_a=.1),
    ])
    assert any("극성" in warning for warning in evaluate_electrical(reversed_mcu).warnings)


def test_netlist_round_trips_through_a_cad_project():
    workspace = ElectricalWorkspace(nodes=["GND", "VPLUS"], components=[
        dict(id="battery", name="전원", kind="battery", a="VPLUS", b="GND", voltage_v=9),
        dict(id="resistor", name="저항", kind="resistor", a="VPLUS", b="GND", resistance_ohm=90),
    ])
    project = Project(design=Design(electrical=workspace))
    reopened = Project.model_validate_json(project.model_dump_json())
    assert reopened.design.electrical == workspace
    assert evaluate_electrical(reopened.design.electrical).components[0].current_a == pytest.approx(.1)


@pytest.mark.parametrize("bad", [
    dict(nodes=["BAT"], components=[]),
    dict(nodes=["GND", "BAT", "BAT"], components=[]),
    dict(nodes=["GND", "BAT"], components=[dict(id="x", name="x", kind="battery", a="BAT", b="OTHER", voltage_v=5)]),
    dict(nodes=["GND", "BAT"], components=[dict(id="x", name="x", kind="battery", a="BAT", b="GND", voltage_v=0)]),
    dict(nodes=["GND", "BAT"], components=[dict(id="x", name="x", kind="wire", a="BAT", b="GND", length_mm=10)]),
    dict(
        nodes=["GND", "BAT"],
        components=[dict(id="x", name="x", kind="motor", a="BAT", b="GND",
                         rated_voltage_v=12, rated_current_a=1, startup_current_a=float("inf"))],
    ),
])
def test_invalid_netlists_are_rejected_before_a_study(bad):
    with pytest.raises(ValidationError):
        ElectricalWorkspace.model_validate(bad)


def test_floating_passive_branch_warns_without_inventing_a_node_voltage_and_conflicting_sources_fail():
    floating = dict(nodes=["GND", "A", "B"], components=[
        dict(id="r", name="floating", kind="resistor", a="A", b="B", resistance_ohm=10),
    ])
    result = evaluate_electrical(floating)
    assert result.node_voltages_v == {"GND": 0}
    assert branch(result, "r").current_a == 0
    assert any("무전원 회로" in warning and "GND" in warning for warning in result.warnings)
    conflicting = dict(nodes=["GND", "A"], components=[
        dict(id="b1", name="b1", kind="battery", a="A", b="GND", voltage_v=5),
        dict(id="b2", name="b2", kind="battery", a="A", b="GND", voltage_v=9),
    ])
    with pytest.raises(ValueError, match="회로를 계산"):
        evaluate_electrical(conflicting)


def test_unpowered_load_is_explicitly_unverified():
    result = evaluate_electrical(dict(nodes=['GND', 'LOAD'], components=[
        dict(id='m', name='unpowered motor', kind='motor', a='LOAD', b='GND',
             rated_voltage_v=12, rated_current_a=1),
        dict(id='r', name='return', kind='resistor', a='LOAD', b='GND', resistance_ohm=10),
    ]))
    assert result.node_voltages_v['LOAD'] == 0
    assert any('전원이 없어' in warning for warning in result.warnings)


def test_open_series_wire_reports_unpowered_mcu_supply_and_no_false_current():
    result = evaluate_electrical(dict(nodes=["GND", "BAT", "VCC"], components=[
        dict(id="battery", name="Cell", kind="battery", a="BAT", b="GND", voltage_v=5),
        dict(id="wire", name="Power lead", kind="wire", a="BAT", b="VCC", closed=False,
             length_mm=100, cross_section_mm2=.5),
        dict(id="mcu", name="Controller", kind="mcu", a="VCC", b="GND",
             rated_voltage_v=5, rated_current_a=.1),
    ]))
    assert branch(result, "wire").current_a == 0
    assert branch(result, "wire").voltage_drop_v == pytest.approx(5)
    assert branch(result, "mcu").current_a == 0
    assert branch(result, "mcu").supply_connected is False
    assert branch(result, "mcu").return_connected is True
    assert any("Power lead" in warning and "단선" in warning for warning in result.warnings)
    assert any("Controller" in warning and "VCC" in warning for warning in result.warnings)


def test_disconnected_mcu_return_warns_even_when_the_solver_sees_both_nodes():
    result = evaluate_electrical(dict(nodes=["GND", "BAT", "RET"], components=[
        dict(id="battery", name="Cell", kind="battery", a="BAT", b="GND", voltage_v=5),
        dict(id="mcu", name="Controller", kind="mcu", a="BAT", b="RET",
             rated_voltage_v=5, rated_current_a=.1),
        dict(id="return", name="Return lead", kind="wire", a="RET", b="GND", closed=False,
             length_mm=100, cross_section_mm2=.5),
    ]))
    assert result.node_voltages_v["RET"] == pytest.approx(5)
    assert branch(result, "mcu").voltage_drop_v == pytest.approx(0)
    assert branch(result, "mcu").current_a == pytest.approx(0)
    assert branch(result, "mcu").supply_connected is True
    assert branch(result, "mcu").return_connected is False
    assert any("Controller" in warning and "리턴" in warning for warning in result.warnings)


def test_parallel_mcu_branch_stays_powered_when_another_branch_wire_breaks():
    result = evaluate_electrical(dict(nodes=["GND", "BAT", "VCC2"], components=[
        dict(id="battery", name="Cell", kind="battery", a="BAT", b="GND", voltage_v=5),
        dict(id="healthy", name="Healthy MCU", kind="mcu", a="BAT", b="GND",
             rated_voltage_v=5, rated_current_a=.1),
        dict(id="lead", name="Broken lead", kind="wire", a="BAT", b="VCC2", closed=False,
             length_mm=100, cross_section_mm2=.5),
        dict(id="lost", name="Isolated MCU", kind="mcu", a="VCC2", b="GND",
             rated_voltage_v=5, rated_current_a=.1),
    ]))
    assert branch(result, "healthy").current_a == pytest.approx(.1)
    assert branch(result, "battery").current_a == pytest.approx(.1)
    assert branch(result, "healthy").supply_connected is True
    assert branch(result, "healthy").return_connected is True
    assert branch(result, "lost").current_a == 0
    assert branch(result, "lost").supply_connected is False


def test_unpowered_mcu_and_open_battery_output_are_explicit():
    no_source = evaluate_electrical(dict(nodes=["GND", "VCC"], components=[
        dict(id="mcu", name="Board", kind="mcu", a="VCC", b="GND",
             rated_voltage_v=3.3, rated_current_a=.08),
    ]))
    assert branch(no_source, "mcu").supply_connected is False
    assert branch(no_source, "mcu").return_connected is False
    assert any("전원이 없어" in warning for warning in no_source.warnings)
    open_battery = evaluate_electrical(dict(nodes=["GND", "BAT"], components=[
        dict(id="battery", name="Cell", kind="battery", a="BAT", b="GND", voltage_v=5),
    ]))
    assert branch(open_battery, "battery").current_a == 0
    assert any("Cell" in warning and "개방 회로" in warning for warning in open_battery.warnings)


def test_floating_battery_loop_calculates_relative_drop_without_fake_ground_reference():
    result = evaluate_electrical(dict(nodes=["GND", "PLUS", "MINUS"], components=[
        dict(id="battery", name="Floating supply", kind="battery", a="PLUS", b="MINUS", voltage_v=5),
        dict(id="mcu", name="Controller", kind="mcu", a="PLUS", b="MINUS",
             rated_voltage_v=5, rated_current_a=.1),
    ]))
    assert result.node_voltages_v == {"GND": 0}
    assert branch(result, "mcu").voltage_drop_v == pytest.approx(5)
    assert branch(result, "mcu").current_a == pytest.approx(.1)
    assert branch(result, "mcu").supply_connected is True
    assert branch(result, "mcu").return_connected is True
    assert any("절대 노드 전위는 미정" in warning for warning in result.warnings)


def test_mcu_signal_pins_report_passive_continuity_separately_from_power():
    base = dict(nodes=["GND", "BAT", "SIG", "REMOTE", "FLOAT"], components=[
        dict(id="battery", name="Cell", kind="battery", a="BAT", b="GND", voltage_v=3.3),
        dict(id="mcu", name="Board", kind="mcu", a="BAT", b="GND",
             rated_voltage_v=3.3, rated_current_a=.1,
             signal_pins={"GPIO1": "SIG", "GPIO2": "FLOAT"}),
        dict(id="lead", name="Signal lead", kind="wire", a="SIG", b="REMOTE",
             length_mm=100, cross_section_mm2=.5),
        dict(id="pull", name="Pull resistor", kind="resistor", a="REMOTE", b="GND", resistance_ohm=1000),
    ])
    connected = evaluate_electrical(base)
    assert branch(connected, "mcu").signal_pin_connected == {"GPIO1": True, "GPIO2": False}
    assert branch(connected, "mcu").supply_connected is True
    assert branch(connected, "mcu").return_connected is True
    broken = dict(base, components=[dict(c) for c in base["components"]])
    broken["components"][2]["closed"] = False
    disconnected = evaluate_electrical(broken)
    assert branch(disconnected, "mcu").signal_pin_connected == {"GPIO1": False, "GPIO2": False}
    assert branch(disconnected, "mcu").current_a == pytest.approx(.1)
    assert any("GPIO1" in warning and "단선" in warning for warning in disconnected.warnings)
    alias = dict(base, components=[dict(c) for c in base["components"]])
    alias["components"][1]["signal_pins"] = {"a": "FLOAT"}
    assert branch(evaluate_electrical(alias), "mcu").signal_pin_connected == {"a": False}


def test_optional_catalog_and_signal_fields_round_trip_without_changing_v1_defaults():
    old = ElectricalWorkspace.model_validate(dict(nodes=["GND", "BAT"], components=[
        dict(id="mcu", name="Board", kind="mcu", a="BAT", b="GND",
             rated_voltage_v=3.3, rated_current_a=.1),
    ]))
    assert old.components[0].signal_pins == {}
    assert old.components[0].catalog_id == ""
    assert old.components[0].source_url == ""
    new = old.model_copy(deep=True)
    new.components[0].signal_pins = {"GPIO0": "BAT"}
    new.components[0].catalog_id = "vendor:board-123"
    new.components[0].source_url = "https://example.org/board-123"
    assert ElectricalWorkspace.model_validate_json(new.model_dump_json()) == new
    with pytest.raises(ValidationError, match="HTTPS"):
        ElectricalWorkspace.model_validate(dict(nodes=["GND", "BAT"], components=[
            dict(id="mcu", name="Board", kind="mcu", a="BAT", b="GND",
                 rated_voltage_v=3.3, rated_current_a=.1, source_url="http://example.org/board"),
        ]))
    with pytest.raises(ValidationError, match="등록된 노드"):
        ElectricalWorkspace.model_validate(dict(nodes=["GND", "BAT"], components=[
            dict(id="mcu", name="Board", kind="mcu", a="BAT", b="GND",
                 rated_voltage_v=3.3, rated_current_a=.1, signal_pins={"GPIO0": "MISSING"}),
        ]))


def test_extreme_wire_values_fail_cleanly_instead_of_producing_nonfinite_dc_results():
    circuit = dict(nodes=["GND", "BAT", "VCC"], components=[
        dict(id="battery", name="Cell", kind="battery", a="BAT", b="GND", voltage_v=5),
        dict(id="wire", name="Tiny lead", kind="wire", a="BAT", b="VCC",
             length_mm=1e-300, cross_section_mm2=1e5),
        dict(id="mcu", name="Board", kind="mcu", a="VCC", b="GND",
             rated_voltage_v=5, rated_current_a=.1),
    ])
    with pytest.raises(ValueError, match="Tiny lead.*저항값"):
        evaluate_electrical(circuit)
