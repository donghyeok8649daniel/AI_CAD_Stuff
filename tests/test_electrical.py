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


def test_floating_active_branch_and_conflicting_ideal_sources_fail_clearly():
    floating = dict(nodes=["GND", "A", "B"], components=[
        dict(id="r", name="floating", kind="resistor", a="A", b="B", resistance_ohm=10),
    ])
    with pytest.raises(ValueError, match="GND"):
        evaluate_electrical(floating)
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
