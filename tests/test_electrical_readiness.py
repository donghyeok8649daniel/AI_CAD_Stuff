"""Workbench coverage must not turn net labels into device operation approval."""
from copy import deepcopy

import pytest

from cadstudio.board_supply import assign_board_supply_node
from cadstudio.circuit_connections import add_schematic_wire, delete_schematic_wire
from cadstudio.electrical import ElectricalWorkspace
from cadstudio.electrical_readiness import build_electrical_readiness
from cadstudio.electrical_registration import register_part
from cadstudio.models import Design


def design(*, role="electrical", color="#123456", circuit=None):
    raw = dict(name="Coverage without guesses", parts=[dict(id="body", name="Motor battery MCU", role=role,
        color=color, geometry=dict(kind="plate", length=40, width=30, thickness=2, hole_count=0))])
    if circuit is not None:
        raw["electrical"] = circuit
    return Design.model_validate(raw)


def row(report, identifier):
    return next(item for item in report.components if item.component_id == identifier)


def codes(report):
    return {item.code for item in report.issues}


def powered_board():
    original = design(circuit=dict(nodes=["GND", "SOURCE"], components=[dict(id="source", name="5 V", kind="battery",
        a="SOURCE", b="GND", voltage_v=5)]))
    registered = register_part(original, "body", dict(catalog_id="rpi4b"))
    board_id = next(item.id for item in registered.electrical.components if item.part_id == "body")
    wired = add_schematic_wire(registered.electrical, "source", "a", board_id, "supply:5V_2",
        name="Supply", length_mm=150, cross_section_mm2=.5)
    wired = add_schematic_wire(wired, "source", "b", board_id, "supply:GND_6",
        name="Return", length_mm=150, cross_section_mm2=.5)
    registered.electrical = wired
    return registered, board_id


def test_empty_design_is_distinct_from_unregistered_electrical_bodies():
    empty = build_electrical_readiness(Design(name="Empty"))
    assert empty.status == "empty" and not empty.issues
    report = build_electrical_readiness(design())
    assert report.status == "needs_attention"
    assert report.counts["electrical_parts"] == report.counts["unregistered_parts"] == 1
    assert report.counts["components"] == 0
    assert report.parts[0].registration_status == "unregistered"
    assert codes(report) == {"cad_registration_missing"}


@pytest.mark.parametrize("role", ["unspecified", "structure", "transmission", "specimen"])
def test_yellow_color_and_product_name_do_not_infer_electrical_role(role):
    report = build_electrical_readiness(design(role=role, color="#FFD400"))
    assert report.status == "empty" and report.counts["electrical_parts"] == 0


def test_exact_registration_is_not_rated_or_physically_powered_by_catalog_voltage():
    registered = register_part(design(), "body", dict(catalog_id="rpi4b"))
    report = build_electrical_readiness(registered)
    component = report.components[0]
    assert component.model_status == "exact" and component.registration_status == "registered"
    assert component.diagram_available and component.power_status == "missing"
    assert component.assigned_terminals == component.isolated_terminals == 0
    assert component.unassigned_terminals == component.available_terminals > 0
    assert {"physical_supply_missing", "physical_return_missing", "dc_model_excluded", "operating_values_missing"} <= codes(report)
    assert "isolated_terminal" not in codes(report)  # Unused GPIOs are not faults.
    assert report.counts["registered_electrical_parts"] == 1


def test_abstract_dc_power_does_not_fill_real_board_power_pads():
    raw = design(circuit=dict(nodes=["GND", "SOURCE"], components=[dict(id="legacy", name="Pi", kind="mcu",
        part_id="body", catalog_id="rpi4b", a="SOURCE", b="GND", rated_voltage_v=5, rated_current_a=.1),
        dict(id="source", name="Supply", kind="battery", a="SOURCE", b="GND", voltage_v=5)])).model_dump()
    report = build_electrical_readiness(raw)
    component = row(report, "legacy")
    assert component.analysis_enabled and component.power_status == "missing"
    assert component.supply_path_connected is component.return_path_connected is None
    assert component.registration_status == report.parts[0].registration_status == "legacy"
    assert report.counts["unregistered_parts"] == 1 and report.counts["registered_parts"] == 0


def test_closed_physical_supply_and_return_have_passive_paths_but_no_hardware_approval():
    original, identifier = powered_board()
    before = original.model_dump()
    report = build_electrical_readiness(original)
    component = row(report, identifier)
    assert component.power_status == "documented"
    assert component.supply_path_connected is component.return_path_connected is True
    assert component.assigned_terminals == 2 and component.isolated_terminals == 0
    assert "physical_supply_missing" not in codes(report)
    assert report.counts["wires"] == 2 and report.counts["undocumented_wires"] == 0
    assert not report.hardware_execution_supported and not report.firmware_execution_supported
    assert not report.dc_calculation_performed and report.status == "needs_attention"
    assert original.model_dump() == before


@pytest.mark.parametrize("fault", ["delete", "open"])
def test_removing_or_opening_supply_preserves_pad_but_reports_missing_external_path(fault):
    original, identifier = powered_board()
    if fault == "delete":
        original.electrical = delete_schematic_wire(original.electrical, "WIRE_001")
    else:
        next(item for item in original.electrical.components if item.id == "WIRE_001").closed = False
    component = row(build_electrical_readiness(original), identifier)
    assert component.power_status == "isolated" and component.isolated_terminals == 1
    assert component.supply_path_connected is False and component.return_path_connected is True
    assert {item.code for item in component.issues} >= {"isolated_terminal", "supply_source_unresolved"}


def test_internal_load_is_not_used_as_a_wire_to_complete_supply_or_return():
    original = register_part(design(), "body", dict(catalog_id="rpi4b"))
    identifier = original.electrical.components[0].id
    circuit = original.electrical.model_dump()
    circuit["nodes"] += ["SOURCE", "ISOLATED_SUPPLY", "ISOLATED_RETURN"]
    circuit["components"] += [dict(id="source", name="Supply", kind="battery", a="SOURCE", b="GND", voltage_v=5),
        dict(id="bridge", name="Other board DC load", kind="mcu", a="SOURCE", b="ISOLATED_SUPPLY", rated_voltage_v=5, rated_current_a=.1),
        dict(id="return_load", name="Other DC load", kind="load", a="GND", b="ISOLATED_RETURN", rated_voltage_v=5, rated_current_a=.1)]
    workspace = assign_board_supply_node(circuit, identifier, "5V_2", "ISOLATED_SUPPLY")
    workspace = assign_board_supply_node(workspace, identifier, "GND_6", "ISOLATED_RETURN")
    original.electrical = workspace
    component = row(build_electrical_readiness(original), identifier)
    assert component.power_status == "documented"  # Stored external endpoint, not an approved source path.
    assert component.supply_path_connected is component.return_path_connected is False
    assert {item.code for item in component.issues} >= {"supply_source_unresolved", "return_source_unresolved"}


@pytest.mark.parametrize("catalog_id, expected", [("", "custom"), ("missing_product", "unknown"),
    ("stm32g4_family", "family"), ("rpi4b", "exact")])
def test_manual_unknown_family_and_exact_labels_are_not_conflated(catalog_id, expected):
    original = design(circuit=dict(nodes=["GND", "POWER"], components=[dict(id="entry", name="Manual", kind="mcu",
        part_id="body", catalog_id=catalog_id, a="POWER", b="GND", analysis_enabled=False,
        signal_pins={"USER_PIN": "POWER"})]))
    report = build_electrical_readiness(original)
    component = report.components[0]
    assert component.model_status == expected and component.registration_status == "legacy"
    assert component.undocumented_pins == ("pin:USER_PIN",)
    assert "undocumented_pin_labels" in codes(report)
    if expected in ("unknown", "family"):
        assert "exact_model_missing" in codes(report)


def test_custom_part_registration_is_distinct_from_exact_manufacturer_registration():
    original = register_part(design(), "body", dict(kind="load"))
    report = build_electrical_readiness(original)
    component = report.components[0]
    assert component.registration_status == "registered" and component.model_status == "custom"
    assert component.power_status == "undocumented" and not component.diagram_available
    assert report.counts["registered_parts"] == report.counts["custom_components"] == 1
    assert report.counts["exact_models"] == 0


def test_custom_named_pads_do_not_make_unused_abstract_dc_placeholders_into_faults():
    original = design(circuit=dict(nodes=["GND", "POWER", "ABSTRACT_A", "ABSTRACT_B"], components=[
        dict(id="source", name="Source", kind="battery", a="POWER", b="GND", voltage_v=5),
        dict(id="custom", name="Custom oscillator", kind="load", a="ABSTRACT_A", b="ABSTRACT_B", analysis_enabled=False,
             terminal_pins={"VCC": "POWER", "GND": "GND"})]))
    component = row(build_electrical_readiness(original), "custom")
    assert component.available_terminals == component.assigned_terminals == 2
    assert component.isolated_terminals == 0 and component.power_status == "undocumented"
    assert "isolated_terminal" not in {item.code for item in component.issues}
    assert component.undocumented_pins == ("port:GND", "port:VCC")


def test_exact_reference_driver_has_pin_coverage_without_a_fictional_dc_model():
    original = register_part(design(), "body", dict(catalog_id="st_b_g431b_esc1"))
    report = build_electrical_readiness(original)
    component = report.components[0]
    assert component.model_status == "exact" and component.diagram_available
    assert component.power_status == "missing" and not component.analysis_enabled
    assert not report.hardware_execution_supported


def test_legacy_duplicate_and_dangling_cad_links_remain_visible_without_mutation():
    original = design(circuit=dict(nodes=["GND", "POWER"], components=[dict(id=identifier, name=identifier,
        kind="resistor", part_id=part, a="POWER", b="GND", resistance_ohm=100)
        for identifier, part in (("first", "body"), ("second", "body"), ("stale", "deleted_body"))]))
    before = original.model_dump()
    report = build_electrical_readiness(original)
    assert report.parts[0].registration_status == "duplicate"
    assert row(report, "first").registration_status == row(report, "second").registration_status == "duplicate"
    assert report.counts["blocked_components"] == 3
    assert {"duplicate_cad_link", "missing_cad_body"} <= codes(report)
    assert original.model_dump() == before


def test_linked_non_electrical_body_is_exposed_without_guessing_its_role():
    original = design(role="structure", circuit=dict(nodes=["GND", "POWER"], components=[dict(id="linked", name="Circuit",
        kind="resistor", part_id="body", a="POWER", b="GND", resistance_ohm=100)]))
    report = build_electrical_readiness(original)
    assert report.counts["electrical_parts"] == report.counts["unregistered_parts"] == 0
    assert report.counts["candidate_parts"] == report.counts["role_mismatch_parts"] == 1
    assert report.parts[0].role == "structure" and "cad_role_mismatch" in codes(report)


def test_wire_without_physical_endpoint_metadata_is_counted_as_undocumented():
    original = design(circuit=dict(nodes=["GND", "POWER"], components=[dict(id="wire", name="Old wire", kind="wire",
        a="POWER", b="GND", length_mm=20, cross_section_mm2=.5)]))
    report = build_electrical_readiness(original)
    assert report.counts["wires"] == report.counts["undocumented_wires"] == 1
    assert "wire_endpoints_undocumented" in codes(report)


@pytest.mark.parametrize("fault", ["missing_component", "missing_terminal", "changed_net"])
def test_stale_physical_wire_metadata_is_reported_as_blocked(fault):
    original, identifier = powered_board()
    circuit = original.electrical.model_dump()
    wire = next(item for item in circuit["components"] if item["id"] == "WIRE_001")
    if fault == "missing_component":
        wire["wire_endpoints"][0]["component_id"] = "deleted_source"
    elif fault == "missing_terminal":
        wire["wire_endpoints"][1]["terminal"] = "supply:UNKNOWN"
    else:
        circuit["nodes"].append("CHANGED_SOURCE")
        wire["a"] = "CHANGED_SOURCE"
    original.electrical = ElectricalWorkspace.model_validate(circuit)
    report = build_electrical_readiness(original)
    expected = "wire_endpoint_net_mismatch" if fault == "changed_net" else "wire_endpoint_missing"
    assert any(problem.code == expected and problem.severity == "blocked" for problem in row(report, "WIRE_001").issues)
    assert report.counts["invalid_wire_endpoints"] == report.counts["blocked_components"] == 1


def test_builder_does_not_copy_design_or_run_dc_and_preserves_absent_legacy_fields(monkeypatch):
    import cadstudio.electrical as electrical
    original = design(circuit=dict(nodes=["GND", "POWER"], components=[dict(id="entry", name="Entry", kind="resistor",
        a="POWER", b="GND", resistance_ohm=100)]))
    before = original.model_dump()

    def forbidden(*args, **kwargs):
        raise AssertionError("Workbench refresh must not copy assets or solve DC")

    with monkeypatch.context() as context:
        context.setattr(Design, "model_dump", forbidden)
        context.setattr(electrical, "evaluate_electrical", forbidden)
        report = build_electrical_readiness(original)
        assert report.counts["components"] == 1
    assert original.model_dump() == before
    assert "schematic_positions" not in original.electrical.model_dump()
    assert "part_registration" not in original.electrical.components[0].model_dump()


def test_raw_input_is_not_mutated_and_report_is_json_serializable():
    original = design().model_dump()
    before = deepcopy(original)
    report = build_electrical_readiness(original)
    assert original == before
    assert report.model_validate_json(report.model_dump_json()) == report
    assert all(item.code and item.next_action for item in report.issues)


def test_localization_keeps_machine_codes_and_counts_stable():
    original = design()
    korean = build_electrical_readiness(original)
    english = build_electrical_readiness(original, "en")
    assert korean.counts == english.counts and codes(korean) == codes(english)
    assert korean.issues[0].message != english.issues[0].message
    assert "physical product registration" in english.issues[0].message
    assert "firmware" in english.scope_note
