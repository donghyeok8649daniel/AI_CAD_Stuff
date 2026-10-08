"""Fault review never changes stored wiring or fabricates thermal ratings."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from cadstudio.electrical import ElectricalComponent, ElectricalWorkspace, evaluate_electrical
from cadstudio.electrical_safety import evaluate_electrical_safety


def source(**kwargs):
    return dict(id="cell", name="Cell", kind="battery", a="BAT", b="GND", voltage_v=12,
                internal_resistance_ohm=.1, max_current_a=2, **kwargs)


def resistor(**kwargs):
    return dict(id="load", name="Resistor", kind="resistor", a="BAT", b="GND",
                resistance_ohm=120, **kwargs)


def workspace(*components, nodes=("GND", "BAT")):
    return dict(nodes=list(nodes), components=list(components))


def codes(report):
    return {issue.code for issue in report.issues}


def branch(report, identifier="load"):
    return next(item for item in report.branches if item.id == identifier)


def test_closed_conductor_supply_bypass_is_short_even_if_dimensions_are_pending():
    raw = workspace(source(), dict(id="short", name="Short", kind="wire", a="BAT", b="GND", analysis_enabled=False))
    before = deepcopy(raw)
    report = evaluate_electrical_safety(raw)
    assert raw == before and report.status == "fault"
    issue = next(item for item in report.issues if item.code == "source_short_circuit")
    assert issue.component_ids == ["cell", "short"] and issue.scenario == "topology"
    assert branch(report, "short").current_a is None
    assert branch(report, "short").estimated_temperature_c is None


@pytest.mark.parametrize("closed,enabled", [(False, True), (True, False)])
def test_disabled_source_or_open_wire_has_no_false_short(closed, enabled):
    cell = source(); cell["analysis_enabled"] = enabled
    report = evaluate_electrical_safety(workspace(cell,
        dict(id="wire", name="Wire", kind="wire", a="BAT", b="GND", closed=closed,
             length_mm=100, cross_section_mm2=1)))
    assert "source_short_circuit" not in codes(report)


def test_direct_parallel_source_conflict_is_reported_when_ideal_solver_fails():
    cell = source(); cell["internal_resistance_ohm"] = 0
    other = dict(cell, id="other", name="Other", voltage_v=5)
    report = evaluate_electrical_safety(workspace(cell, other))
    assert {"conflicting_sources", "dc_not_solved"} <= codes(report)
    assert report.status == "fault" and not report.dc_solved
    assert all(item.current_a is None and item.estimated_temperature_c is None for item in report.branches)


def test_identical_or_disabled_parallel_sources_do_not_claim_voltage_conflict():
    cell = source(); other = dict(cell, id="other", name="Other")
    assert "conflicting_sources" not in codes(evaluate_electrical_safety(workspace(cell, other, resistor())))
    other.update(voltage_v=5, closed=False)
    assert "conflicting_sources" not in codes(evaluate_electrical_safety(workspace(cell, other, resistor())))


def test_resistor_power_and_current_limits_are_actual_calculated_faults():
    cell = source(); cell["max_current_a"] = .05
    report = evaluate_electrical_safety(workspace(cell, resistor(safety=dict(rated_power_w=.25))))
    assert {"current_limit_exceeded", "dissipation_rating_exceeded"} <= codes(report)
    assert report.status == "fault"
    assert branch(report).dissipated_power_w == pytest.approx(120 * (12 / 120.1) ** 2)
    assert branch(report).estimated_temperature_c is None


def test_motor_input_power_is_not_assumed_to_be_heat():
    motor = dict(id="motor", name="Motor", kind="motor", a="BAT", b="GND",
        rated_voltage_v=12, rated_current_a=1, startup_current_a=4,
        safety=dict(thermal_resistance_k_per_w=5, ambient_temperature_c=25,
                    duty_cycle=1, max_temperature_c=80))
    report = evaluate_electrical_safety(workspace(source(), motor))
    row = branch(report, "motor")
    assert row.current_a > .9 and row.startup_current_a > 3.8
    assert row.heat_basis == "unknown" and row.dissipated_power_w is None
    assert row.estimated_temperature_c is None and "heat_loss_unknown" in codes(report)


def test_declared_motor_loss_fraction_allows_explicit_steady_temperature_only():
    motor = dict(id="motor", name="Motor", kind="motor", a="BAT", b="GND",
        rated_voltage_v=12, rated_current_a=1, startup_current_a=4,
        safety=dict(heat_loss_fraction=.2, thermal_resistance_k_per_w=5,
                    ambient_temperature_c=25, duty_cycle=.5, max_temperature_c=26))
    report = evaluate_electrical_safety(workspace(source(), motor))
    row = branch(report, "motor")
    assert row.heat_basis == "declared_loss_fraction"
    assert row.estimated_temperature_c == pytest.approx(25 + row.dissipated_power_w * .5 * 5)
    assert row.startup_dissipated_power_w > row.dissipated_power_w
    assert "temperature_limit_exceeded" in codes(report)


@pytest.mark.parametrize("missing", ["thermal_resistance_k_per_w", "ambient_temperature_c", "duty_cycle"])
def test_thermal_resistance_environment_and_duty_are_each_required(missing):
    safety = dict(rated_power_w=2, thermal_resistance_k_per_w=10, ambient_temperature_c=25,
                  duty_cycle=1, max_temperature_c=100)
    del safety[missing]
    report = evaluate_electrical_safety(workspace(source(), resistor(safety=safety)))
    assert branch(report).estimated_temperature_c is None
    assert "thermal_conditions_missing" in codes(report)


def test_battery_heat_is_internal_i_squared_r_not_delivered_terminal_power():
    report = evaluate_electrical_safety(workspace(source(), resistor()))
    cell = branch(report, "cell")
    assert cell.dissipated_power_w == pytest.approx(cell.current_a ** 2 * .1)
    assert cell.dissipated_power_w < .01


def test_capacitor_dc_open_does_not_establish_zero_heat_or_false_short():
    cap = dict(id="cap", name="Capacitor", kind="capacitor", a="BAT", b="GND",
               capacitance_f=470e-6, rated_voltage_v=10, capacitor_polarized=True)
    report = evaluate_electrical_safety(workspace(source(), cap))
    assert "source_short_circuit" not in codes(report)
    assert "voltage_limit_exceeded" in codes(report)
    assert branch(report, "cap").current_a == 0
    assert branch(report, "cap").dissipated_power_w is None
    assert branch(report, "cap").estimated_temperature_c is None
    cap.update(a="GND", b="BAT")
    assert "reverse_capacitor" in codes(evaluate_electrical_safety(workspace(source(), cap)))


def test_fuse_overrating_warns_without_manufacturing_a_trip_time_or_opening():
    fuse = dict(id="fuse", name="Fuse", kind="switch", a="BAT", b="LOAD",
                safety=dict(fuse_current_a=.05, max_voltage_v=32))
    load = resistor(); load["a"] = "LOAD"
    raw = workspace(source(), fuse, load, nodes=("GND", "BAT", "LOAD")); before = deepcopy(raw)
    report = evaluate_electrical_safety(raw)
    assert raw == before and fuse.get("closed", True)
    assert {"fuse_rating_exceeded", "fuse_trip_not_modelled"} <= codes(report)
    assert branch(report, "fuse").current_a > .05


def test_fuse_voltage_is_supply_stress_not_small_closed_contact_drop():
    cell = source(); cell["voltage_v"] = 60
    fuse = dict(id="fuse", name="Fuse", kind="switch", a="BAT", b="LOAD",
                safety=dict(fuse_current_a=2, max_voltage_v=32))
    load = resistor(); load["a"] = "LOAD"
    report = evaluate_electrical_safety(workspace(cell, fuse, load, nodes=("GND", "BAT", "LOAD")))
    assert "fuse_supply_voltage_exceeded" in codes(report)
    issue = next(item for item in report.issues if item.code == "fuse_supply_voltage_exceeded")
    assert issue.measured_value == 60 and issue.limit == 32


def test_common_ground_does_not_attribute_an_unrelated_60v_source_to_12v_fuse():
    low = source(); high = dict(low, id="high", a="HV", voltage_v=60)
    fuse = dict(id="fuse", name="Fuse", kind="switch", a="RETURN", b="GND",
                safety=dict(fuse_current_a=2, max_voltage_v=32))
    load = resistor(); load["b"] = "RETURN"
    high_load = dict(resistor(), id="highload", a="HV", resistance_ohm=1000)
    report = evaluate_electrical_safety(workspace(low, high, fuse, load, high_load, nodes=("GND", "BAT", "RETURN", "HV")))
    assert "fuse_supply_voltage_exceeded" not in codes(report)


def test_starting_current_has_separate_limit_issue_and_no_peak_temperature_claim():
    motor = dict(id="motor", name="Motor", kind="motor", a="BAT", b="GND",
                 rated_voltage_v=12, rated_current_a=1, startup_current_a=4)
    report = evaluate_electrical_safety(workspace(source(), motor))
    issues = [item for item in report.issues if item.code == "current_limit_exceeded"]
    assert len(issues) == 1 and issues[0].scenario == "startup"


def test_explicit_zero_duty_is_distinct_from_missing_environment():
    report = evaluate_electrical_safety(workspace(source(), resistor(safety=dict(
        rated_power_w=2, thermal_resistance_k_per_w=10, ambient_temperature_c=-10,
        duty_cycle=0, max_temperature_c=-9))))
    assert branch(report).estimated_temperature_c == -10
    assert "temperature_limit_exceeded" not in codes(report)


def test_legacy_absent_default_and_explicit_safety_none_round_trip_exactly():
    old = ElectricalComponent.model_validate(resistor()).model_dump()
    assert "safety" not in old
    assert ElectricalComponent.model_validate(old).model_dump() == old
    explicit = ElectricalComponent.model_validate({**old, "safety": None}).model_dump()
    assert "safety" in explicit and explicit["safety"] is None
    with_spec = ElectricalComponent.model_validate({**old, "safety": dict(rated_power_w=.25)})
    assert ElectricalComponent.model_validate_json(with_spec.model_dump_json()).model_dump() == with_spec.model_dump()


@pytest.mark.parametrize("safety", [dict(rated_power_w=0), dict(fuse_current_a=1),
    dict(heat_loss_fraction=.5), dict(duty_cycle=1.1), dict(ambient_temperature_c=float("nan")),
    dict(thermal_resistance_k_per_w=0), dict(source_url="http://example.com/spec")])
def test_invalid_or_wrong_kind_safety_values_are_rejected(safety):
    with pytest.raises(ValidationError):
        ElectricalComponent.model_validate(resistor(safety=safety))


def test_solved_result_is_reused_but_other_topology_is_rejected():
    raw = workspace(source(), resistor())
    result = evaluate_electrical(raw)
    report = evaluate_electrical_safety(raw, result=result, language="en")
    assert report.dc_solved and "thermal_conditions_missing" in codes(report)
    assert "safety certification" in report.scope
    other = deepcopy(raw); other["components"][1]["id"] = "other"
    with pytest.raises(ValueError, match="does not match"):
        evaluate_electrical_safety(other, result=result)
