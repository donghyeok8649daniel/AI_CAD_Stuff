"""Exact references must support registration without approving device behaviour."""

import pytest

from cadstudio.board_pins import board_pinout
from cadstudio.electrical import evaluate_electrical
from cadstudio.electrical_catalog import (
    CATALOG, catalog_counts, catalog_functions, catalog_model_candidates,
    catalog_support, component_prefill, get_catalog_entry, search_catalog,
)
from cadstudio.electrical_registration import (
    connect_registered_pin, register_part, register_terminal_node, registration_for_part,
)
from cadstudio.models import Design, Project
from cadstudio.product_diagrams import product_diagram


NEW_PRODUCTS = (
    "ti_ref5025aid", "meanwell_hdr60_5", "meanwell_lrs600_24",
    "adafruit_904", "adafruit_4226", "adafruit_1085", "adafruit_5346",
    "adafruit_815", "adafruit_3190", "adafruit_2857", "adafruit_2652", "adafruit_6357",
)


def assembly():
    return Design.model_validate(dict(
        name="Existing user's assembly", parameters={"wall": "2 mm"},
        parts=[
            dict(id="controller", name="Custom controller enclosure", fixed=True,
                 color="#345678", role="structure", transform=dict(x=12, ry=15),
                 geometry=dict(kind="plate", length=60, width=40, thickness=2, hole_count=0)),
            dict(id="module", name="Custom module envelope", color="#123456", role="electrical",
                 transform=dict(x=90, rz=25), geometry=dict(kind="cylinder", diameter=12, height=30)),
        ], part_groups=[dict(id="selection", name="Keep group", part_ids=["controller", "module"])],
        electrical=dict(nodes=["GND", "BAT", "SPARE"], components=[
            dict(id="battery", name="Existing source", kind="battery", a="BAT", b="GND",
                 voltage_v=5, internal_resistance_ohm=.1, max_current_a=2),
            dict(id="old_load", name="Existing resistor", kind="resistor", a="BAT", b="GND", resistance_ohm=100),
        ])))


@pytest.mark.parametrize("catalog_id", NEW_PRODUCTS)
def test_exact_modules_register_connect_all_verified_terminals_and_reopen_without_changing_body(catalog_id):
    old = assembly()
    old_data = old.model_dump()
    diagram = product_diagram(catalog_id)
    entry = get_catalog_entry(catalog_id)
    registered = register_part(old, "module", dict(catalog_id=catalog_id))
    component = registration_for_part(registered, "module")
    assert old.model_dump() == old_data
    assert component.kind == "load" and component.analysis_enabled is False
    assert component.catalog_id == component.product_pinout_catalog_id == catalog_id
    assert component.source_url == entry.source_url == diagram.source_url
    assert component.rated_current_a == 0  # Pending sentinel, never a documented operating point.
    assert entry.rated_current_a is entry.nominal_voltage_v is None
    assert entry.reference_only and component_prefill(entry) == {}
    assert registered.parts == old.parts and registered.part_groups == old.part_groups
    assert registered.parameters == old.parameters
    assert registered.electrical.components[:2] == old.electrical.components
    # Actual persisted terminal connectivity must survive a project round trip.
    for index, terminal in enumerate(diagram.terminals):
        registered = register_terminal_node(registered, "module", terminal.key, f"REF_NET_{index}")
    reopened = Project.model_validate_json(Project(design=registered).model_dump_json()).design
    restored = registration_for_part(reopened, "module")
    assert restored.terminal_pins == {pin.key: f"REF_NET_{i}" for i, pin in enumerate(diagram.terminals)}
    assert restored == registration_for_part(registered, "module")
    assert reopened.parts == old.parts
    assert evaluate_electrical(reopened.electrical).source_power_w == pytest.approx(
        evaluate_electrical(old.electrical).source_power_w)
    with pytest.raises(ValueError, match="물리 단자 목록"):
        register_terminal_node(reopened, "module", "GUESSED_PIN", "SPARE")


def test_support_counts_distinguish_registerable_maps_manual_items_and_discovery():
    counts = catalog_counts()
    assert counts["total"] == len(CATALOG) >= 98
    assert counts["registerable"] >= 55
    assert counts["total"] == counts["registerable"] + counts["reference"]
    assert counts["registerable"] == counts["board_pinouts"] + counts["product_diagrams"] + counts["manual"]
    assert catalog_support("rpi_pico2") == catalog_support("rpi_zero2w") == "board_pins"
    assert all(catalog_support(identifier) == "terminals" for identifier in NEW_PRODUCTS)
    assert catalog_support("robotis_xl330_m288t") == "manual"
    assert catalog_support("stm32_nucleo_family") == catalog_support("not_known") == "reference"
    counts["total"] = -1
    assert catalog_counts()["total"] == len(CATALOG)


def test_named_psus_use_verified_numbers_distinct_mains_earth_and_pending_dc_outputs():
    hdr = {pin.key: pin for pin in product_diagram("meanwell_hdr60_5").terminals}
    lrs = {pin.key: pin for pin in product_diagram("meanwell_lrs600_24").terminals}
    assert hdr["AC_L"].label == "5 · AC/L" and hdr["AC_N"].label == "6 · AC/N"
    assert hdr["DC_NEG"].label.startswith("1,2") and hdr["DC_POS"].label.startswith("3,4")
    assert "FG" not in hdr
    assert lrs["AC_L"].label.startswith("1 ·") and lrs["AC_N"].label.startswith("2 ·")
    assert lrs["FG"].label.startswith("3 ·") and lrs["FG"].kind == "other"
    assert lrs["DC_NEG"].label.startswith("4–6") and lrs["DC_POS"].label.startswith("7–9")
    assert all(pins[key].kind == "other" for pins in (hdr, lrs) for key in ("AC_L", "AC_N"))
    assert "32.5 W" in get_catalog_entry("meanwell_hdr60_5").spec_summary
    assert "regenerative" in product_diagram("meanwell_lrs600_24").note_en


def test_ref5025aid_is_an_exact_chip_without_remote_sense_or_enhanced_grade_pins():
    diagram = product_diagram("ti_ref5025aid")
    pins = {pin.key: pin for pin in diagram.terminals}
    assert len(pins) == 8 and pins["OUT"].label == "6 · VOUT"
    assert pins["VIN"].label == "2 · VIN" and pins["GND"].label == "4 · GND"
    assert pins["DNC_1"].kind == pins["DNC_8"].kind == pins["NC_7"].kind == "other"
    assert not {"EN", "SENSE_POS", "SENSE_NEG"} & pins.keys()
    assert "No remote SENSE" in diagram.note_en and "carrier" in diagram.note_en


@pytest.mark.parametrize("maker,model,expected", [
    ("MEANWELL", "HDR-60-5", "meanwell_hdr60_5"),
    ("Mean Well", "LRS-600-24", "meanwell_lrs600_24"),
    ("Texas Instruments", "REF5025AID SOIC8", "ti_ref5025aid"),
    ("TI", "REF5025AID", "ti_ref5025aid"),
])
def test_exact_metadata_candidates_are_explicit_suggestions(maker, model, expected):
    before = assembly().model_dump()
    assert [entry.catalog_id for entry in catalog_model_candidates(maker, model)] == [expected]
    assert assembly().model_dump() == before


@pytest.mark.parametrize("maker,model", [
    ("", "LRS-600-24"), ("Unknown vendor", "LRS-600-24"), ("MEAN WELL", "LRS-600"),
    ("MEAN WELL", "LRS-600-48"), ("TI", "REF5025EID"), ("TI", "REF5025"),
    ("TI", "REF5025AID carrier with remote sense"), ("Adafruit", "AS5600"),
])
def test_unknown_variants_and_carriers_do_not_match_chip_or_catalog_search_aliases(maker, model):
    assert catalog_model_candidates(maker, model) == ()


def test_selecting_ref_chip_does_not_silently_replace_a_carriers_custom_sense_connections():
    custom = register_part(assembly(), "module", dict(kind="load",
        terminal_pins={"OUT": "EXC_OUT", "GND": "EXC_GND", "SENSE_POS": "REMOTE_POS", "SENSE_NEG": "REMOTE_NEG"}))
    before = custom.model_dump()
    assert catalog_model_candidates("TI", "REF5025AID SOIC8")
    with pytest.raises(ValueError, match="기존 핀·단자 연결"):
        register_part(custom, "module", dict(catalog_id="ti_ref5025aid"))
    assert custom.model_dump() == before


def test_board_modules_distinguish_analog_supply_outputs_digital_address_straps_and_pwm():
    adc = {pin.key: pin for pin in product_diagram("adafruit_1085").terminals}
    assert adc["APLUS"].kind == "power" and adc["AMINUS"].kind == "ground"
    assert all(adc[f"A{i}"].kind == "signal" for i in range(4)) and "ADDR" not in adc
    expander = {pin.key: pin for pin in product_diagram("adafruit_5346").terminals}
    assert all(expander[f"D{i}"].kind == "other" for i in range(3))
    assert all("output only" in " ".join(expander[key].functions) for key in ("A7", "B7"))
    assert "analog" in " ".join(expander["A0"].functions)
    servo = {pin.key: pin for pin in product_diagram("adafruit_815").terminals}
    assert servo["VCC"].key != servo["VPLUS"].key
    assert len([pin for pin in servo.values() if pin.key.startswith("PWM")]) == 16
    assert all(servo[f"PWM{i}"].signal_voltage_reference == "VCC" for i in range(16))
    driver = {pin.key: pin for pin in product_diagram("adafruit_3190").terminals}
    assert "VCC" not in driver and driver["OUT2"].kind == "power"
    assert catalog_functions("adafruit_3190") == ("motor_driver",)


def test_exact_encoder_board_and_i2c_rails_do_not_inherit_chip_or_motor_assumptions():
    board = get_catalog_entry("adafruit_6357")
    pins = {pin.key: pin for pin in product_diagram(board.catalog_id).terminals}
    assert board.encoder_interface == "absolute_i2c" and board.encoder_counts_per_rev is None
    assert pins["SDA"].signal_voltage_reference == "VIN" and pins["OUT"].signal_voltage_reference == ""
    assert "VDD, not Vin" in " ".join(pins["OUT"].functions)
    assert not {"ENCODER_A", "ENCODER_B", "DIR", "VDD5V"} & pins.keys()
    assert get_catalog_entry("adafruit_6357") in search_catalog("엔코더 as5600")
    assert get_catalog_entry("adafruit_3190") in search_catalog("모터 drv8871")
    sensor = {pin.key: pin for pin in product_diagram("adafruit_904").terminals}
    assert sensor["VIN_NEG"].kind == "power" and sensor["GND"].kind == "ground"
    assert sensor["SDA"].signal_voltage_min_v == 2.7 and sensor["SDA"].signal_voltage_max_v == 5.5


@pytest.mark.parametrize("board_id,pin_key,label", [
    ("rpi_pico2", "GP4", "Pin 6 · GP4"),
    ("rpi_zero2w", "GPIO2", "J8.3 · GPIO2"),
])
def test_new_verified_board_headers_connect_and_persist_exact_i2c_pins(board_id, pin_key, label):
    pins = {pin.key: pin for pin in board_pinout(board_id).pins}
    assert len(pins) == 40 and pins[pin_key].label == label
    assert board_pinout(board_id).logic_voltage_v == 3.3
    design = register_part(assembly(), "controller", dict(catalog_id=board_id))
    design = register_part(design, "module", dict(catalog_id="adafruit_904"))
    connected = connect_registered_pin(design, "controller", pin_key, "module", "port:SDA")
    restored = Project.model_validate_json(Project(design=connected).model_dump_json()).design
    assert registration_for_part(restored, "controller").signal_pins[pin_key] == registration_for_part(restored, "module").terminal_pins["SDA"]
    assert registration_for_part(restored, "controller").analysis_enabled is False
    if board_id == "rpi_pico2":
        assert not {"GP23", "GP24", "GP25", "GP29"} & pins.keys()
        assert pins["VBUS"].label == "Pin 40 · VBUS" and pins["ADC_VREF"].kind == "other"
    else:
        assert pins["GPIO0"].kind == pins["GPIO1"].kind == "other"
        assert "DNF" in board_pinout(board_id).note_en
