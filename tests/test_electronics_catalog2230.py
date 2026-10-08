"""Source-linked catalog additions remain usable without inventing models."""

from dataclasses import FrozenInstanceError
from urllib.parse import urlsplit

import pytest

from cadstudio.board_pins import board_pinout
from cadstudio.electrical import ElectricalWorkspace, evaluate_electrical
from cadstudio.electrical_catalog import (
    CATALOG, catalog_counts, catalog_support, component_prefill,
    get_catalog_entry, search_catalog,
)
from cadstudio.electrical_catalog_data import (
    DYNAMIXEL_ROWS, EXPANDED_CATALOG_IDS, FUSE_ROWS, NUCLEO_MODELS,
    SOURCE_CHECKED_DATE,
)
from cadstudio.electrical_registration import (
    register_part, register_terminal_node, registration_for_part,
)
from cadstudio.electrical_safety import evaluate_electrical_safety
from cadstudio.models import Design, Project
from cadstudio.product_diagrams import product_diagram


NEW_ENTRIES = tuple(get_catalog_entry(identifier) for identifier in EXPANDED_CATALOG_IDS)
REGISTERABLE = tuple(entry.catalog_id for entry in NEW_ENTRIES if not entry.reference_only)
REFERENCE_ONLY = tuple(entry.catalog_id for entry in NEW_ENTRIES if entry.reference_only)


def assembly():
    return Design.model_validate(dict(name="User assembly", parameters={"wall": "2 mm"}, parts=[
        dict(id="body", name="User colored carrier", role="structure", color="#345678",
             fixed=True, transform=dict(x=60, y=10, rz=25),
             geometry=dict(kind="plate", length=60, width=40, thickness=2, hole_count=0)),
        dict(id="other", name="Keep other component", color="#AABBCC",
             geometry=dict(kind="cylinder", diameter=10, height=20)),
    ], part_groups=[dict(id="keep", name="Keep group", part_ids=["body", "other"])],
        electrical=dict(nodes=["GND", "BAT"], components=[
            dict(id="source", name="User source", kind="battery", a="BAT", b="GND",
                 voltage_v=12, internal_resistance_ohm=.1),
            dict(id="load", name="Existing load", kind="resistor", a="BAT", b="GND", resistance_ohm=120),
        ])))


def circuit_with(identifier, load_resistance=5, voltage=12):
    entry = get_catalog_entry(identifier)
    prefill = component_prefill(entry)
    return ElectricalWorkspace.model_validate(dict(nodes=["GND", "BAT", "OUT"], components=[
        dict(id="supply", name="Source", kind="battery", a="BAT", b="GND",
             voltage_v=voltage, internal_resistance_ohm=.1),
        dict(**prefill, id="selected", a="BAT", b="OUT", analysis_enabled=True),
        dict(id="load", name="Load", kind="resistor", a="OUT", b="GND", resistance_ohm=load_resistance),
    ]))


def test_expansion_has_unique_exact_identity_sources_and_explicit_support_counts():
    counts = catalog_counts()
    assert counts["total"] >= 235 and counts["registerable"] >= 164
    assert counts["product_diagrams"] >= 49 and counts["board_pinouts"] >= 11
    assert len(EXPANDED_CATALOG_IDS) == 125 and len(REGISTERABLE) == 96
    assert len({entry.catalog_id for entry in CATALOG}) == len(CATALOG)
    for entry in NEW_ENTRIES:
        assert entry.source_checked_date == SOURCE_CHECKED_DATE
        assert entry.evidence and entry.spec_summary and entry.model
        url = urlsplit(entry.source_url)
        assert url.scheme == "https" and url.hostname in {
            "www.st.com", "docs.arduino.cc", "docs.espressif.com", "www.raspberrypi.com",
            "www.pjrc.com", "www.beagleboard.org", "www.ti.com", "www.analog.com",
            "www.bosch-sensortec.com", "emanual.robotis.com", "www.littelfuse.com",
            "industrial.panasonic.com", "www.bourns.com",
        }
        assert url.username is None and url.password is None
        assert entry.rated_current_a is None  # Supply/rating/stall currents are not consumption.
        assert entry in search_catalog(entry.model, limit=300)
        with pytest.raises(FrozenInstanceError):
            entry.model = "Generic family"


@pytest.mark.parametrize("identifier", REGISTERABLE)
def test_each_new_registerable_product_attaches_and_roundtrips_without_changing_user_assembly(identifier):
    old = assembly()
    before = old.model_dump()
    mapped = register_part(old, "body", dict(catalog_id=identifier))
    registered = registration_for_part(mapped, "body")
    entry = get_catalog_entry(identifier)
    assert old.model_dump() == before
    assert registered.catalog_id == identifier and registered.source_url == entry.source_url
    assert registered.kind == entry.suggested_kind and registered.analysis_enabled is False
    assert registered.rated_current_a == 0 and registered.part_id == "body"
    assert mapped.parts[0].geometry == old.parts[0].geometry
    assert mapped.parts[0].transform == old.parts[0].transform and mapped.parts[0].fixed
    assert mapped.parts[0].color == old.parts[0].color
    assert mapped.parts[1] == old.parts[1]
    assert mapped.part_groups == old.part_groups and mapped.parameters == old.parameters
    assert mapped.electrical.components[:2] == old.electrical.components
    reopened = Project.model_validate_json(Project(design=mapped).model_dump_json()).design
    assert reopened == mapped
    assert evaluate_electrical(mapped.electrical).source_power_w == pytest.approx(
        evaluate_electrical(old.electrical).source_power_w)


@pytest.mark.parametrize("identifier", REFERENCE_ONLY)
def test_product_discovery_does_not_invent_package_pinouts_or_dc_behavior(identifier):
    entry = get_catalog_entry(identifier)
    assert catalog_support(identifier) == "reference"
    assert component_prefill(entry) == {} and entry.suggested_kind is None
    assert product_diagram(identifier) is None and board_pinout(identifier) is None
    original = assembly()
    before = original.model_dump()
    with pytest.raises(ValueError, match="특정 제품 모델"):
        register_part(original, "body", dict(catalog_id=identifier))
    assert original.model_dump() == before


def test_new_nucleo_board_identity_keeps_unverified_header_and_current_unset():
    assert len(NUCLEO_MODELS) == 24
    for model, chip, size in NUCLEO_MODELS:
        identifier = "st_" + model.lower().replace("-", "_")
        entry = get_catalog_entry(identifier)
        assert entry.model == model and chip in entry.spec_summary
        assert f"Nucleo-{size}" in entry.series
        assert entry in search_catalog(chip, limit=300)
        assert catalog_support(identifier) == "manual"
        assert board_pinout(identifier) is None and product_diagram(identifier) is None
        assert "rated_current_a" not in component_prefill(entry)
    assert "End of Life" in get_catalog_entry("arduino_nano_rp2040_connect").spec_summary


@pytest.mark.parametrize("row", FUSE_ROWS)
def test_exact_fuse_rating_prefill_preserves_ac_dc_and_two_contact_topology(row):
    model, series, current, voltage, voltage_type, cold_r, source = row
    identifier = "littelfuse_" + model.lower().replace(".", "_")
    entry = get_catalog_entry(identifier)
    values = component_prefill(entry)
    assert entry.model == model and entry.series == series
    assert entry.fuse_current_a == current and entry.contact_resistance_ohm == cold_r
    assert entry.voltage_rating_type == voltage_type
    assert values["kind"] == "switch" and values["contact_resistance_ohm"] == cold_r
    assert values["safety"]["fuse_current_a"] == current
    assert values["safety"]["source_url"] == source
    if voltage_type == "ac":
        assert "max_voltage_v" not in values["safety"]
    else:
        assert values["safety"]["max_voltage_v"] == voltage
    assert "voltage_v" not in values and "rated_voltage_v" not in values
    assert "rated_current_a" not in values and "max_current_a" not in values
    assert product_diagram(identifier) is None and catalog_support(identifier) == "manual"
    registered = registration_for_part(register_part(assembly(), "body", dict(catalog_id=identifier)), "body")
    assert registered.terminal_pins == {} and registered.signal_pins == {}


def test_fuse_overcurrent_is_reported_but_does_not_fake_trip_or_modify_circuit():
    workspace = circuit_with("littelfuse_0451001_mrl")
    before = workspace.model_dump()
    result = evaluate_electrical(workspace)
    report = evaluate_electrical_safety(workspace)
    selected = next(item for item in result.components if item.id == "selected")
    assert abs(selected.current_a) == pytest.approx(12 / (5 + .1 + .078))
    assert selected.current_a != 0
    assert "fuse_rating_exceeded" in {issue.code for issue in report.issues}
    assert "fuse_trip_not_modelled" in {issue.code for issue in report.issues}
    assert workspace.components[1].closed is True and workspace.model_dump() == before
    ac_report = evaluate_electrical_safety(circuit_with("littelfuse_0218001_mxp"))
    assert "fuse_dc_voltage_unknown" in {issue.code for issue in ac_report.issues}
    assert "fuse_supply_voltage_exceeded" not in {issue.code for issue in ac_report.issues}
    overvoltage = evaluate_electrical_safety(circuit_with("littelfuse_0287002_u", voltage=48))
    assert "fuse_supply_voltage_exceeded" in {issue.code for issue in overvoltage.issues}


@pytest.mark.parametrize("row", DYNAMIXEL_ROWS)
def test_new_dynamixel_variants_keep_exact_connector_bus_and_real_saved_nets(row):
    identifier, model, slug, voltage, voltage_range, bus, xl330, rs485 = row
    diagram = product_diagram(identifier)
    pins = {pin.key: pin for pin in diagram.terminals}
    assert get_catalog_entry(identifier).nominal_voltage_v == voltage
    assert diagram.source_url.endswith("/" + slug + "/") and SOURCE_CHECKED_DATE in diagram.evidence
    assert pins["GND"].label == "1 · GND" and pins["VDD"].label == "2 · VDD"
    if rs485:
        assert set(pins) == {"GND", "VDD", "DATA_POS", "DATA_NEG"}
        assert pins["DATA_POS"].label == "3 · DATA+" and pins["DATA_NEG"].label == "4 · DATA−"
        assert pins["DATA_POS"].signal_voltage_reference == "external_rs485_transceiver"
    else:
        assert set(pins) == {"GND", "VDD", "DATA"}
        assert pins["DATA"].signal_voltage_reference == ("ttl_3v3" if xl330 else "ttl_5v")
    assert "ENCODER_A" not in pins and "PWM" not in pins
    mapped = register_part(assembly(), "body", dict(catalog_id=identifier))
    for pin in pins:
        mapped = register_terminal_node(mapped, "body", pin, "NET_" + pin)
    reopened = Project.model_validate_json(Project(design=mapped).model_dump_json()).design
    assert registration_for_part(reopened, "body").terminal_pins == {pin: "NET_" + pin for pin in pins}
    assert registration_for_part(reopened, "body").analysis_enabled is False
    if identifier.startswith("robotis_xm540"):
        assert "External Port and Dual Joint" in diagram.note_en


def test_exact_passive_values_keep_rated_power_capacitance_and_rdc_semantics():
    resistor = get_catalog_entry("panasonic_erj6enf2200v")
    assert component_prefill(resistor)["safety"]["rated_power_w"] == .125
    circuit = circuit_with(resistor.catalog_id, load_resistance=1)
    report = evaluate_electrical_safety(circuit)
    assert any(issue.code == "dissipation_rating_exceeded" and "selected" in issue.component_ids for issue in report.issues)
    capacitor = component_prefill(get_catalog_entry("panasonic_eeufr1e101b"))
    assert capacitor["capacitance_f"] == pytest.approx(100e-6)
    assert capacitor["rated_voltage_v"] == 25 and capacitor["capacitor_polarized"]
    assert "voltage_v" not in capacitor and "rated_current_a" not in capacitor
    inductor = get_catalog_entry("bourns_srr1260_100m")
    values = component_prefill(inductor)
    assert values["inductance_h"] == pytest.approx(10e-6) and values["winding_resistance_ohm"] == .020
    assert "RDC 최대" in inductor.spec_summary and "RDC maximum" in inductor.evidence
    assert "max_current_a" not in values and "thermal_resistance_k_per_w" not in values
