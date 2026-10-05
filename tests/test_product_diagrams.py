from dataclasses import FrozenInstanceError
import re
from urllib.parse import urlsplit

import pytest

from cadstudio.electrical_catalog import component_prefill, get_catalog_entry, search_catalog
from cadstudio.product_diagrams import SOURCE_CHECKED_DATE, available_product_diagrams, product_diagram


def _terminals(identifier):
    return {p.key: p for p in product_diagram(identifier).terminals}


def test_exact_product_diagrams_are_immutable_unique_and_source_linked():
    diagrams = available_product_diagrams()
    assert isinstance(diagrams, tuple) and len(diagrams) == 5
    assert len({diagram.catalog_id for diagram in diagrams}) == len(diagrams)
    for diagram in diagrams:
        assert product_diagram(diagram.catalog_id) is diagram
        entry = get_catalog_entry(diagram.catalog_id)
        assert entry is not None and entry.source_url == diagram.source_url
        assert len({pin.key for pin in diagram.terminals}) == len(diagram.terminals)
        assert len({(pin.side, pin.position) for pin in diagram.terminals}) == len(diagram.terminals)
        assert SOURCE_CHECKED_DATE in diagram.note and SOURCE_CHECKED_DATE in diagram.note_en
        assert diagram.evidence and "시뮬레이션" in diagram.note
        host = urlsplit(diagram.source_url)
        assert host.scheme == "https" and host.hostname in {
            "look.ams-osram.com", "www.pololu.com", "www.vishay.com", "www.st.com",
        }
        assert "Not a dimensioned PCB/footprint" in diagram.note_en
        for terminal in diagram.terminals:
            assert re.fullmatch(r"[A-Za-z0-9_]{1,40}", terminal.key)
            assert terminal.label and terminal.functions
            assert terminal.kind in ("signal", "power", "ground", "other")
            assert terminal.side in ("left", "right") and terminal.position >= 0
        with pytest.raises(FrozenInstanceError):
            diagram.model = "Generic"
        with pytest.raises(FrozenInstanceError):
            diagram.terminals[0].key = "Wrong"


def test_as5600_is_exact_soic8_ic_pin_numbers_not_a_guessed_module_connector():
    diagram = product_diagram("ams_as5600_asot")
    pins = _terminals("ams_as5600_asot")
    assert "AS5600-ASOT" in diagram.model and "SOIC-8 IC" in diagram.model
    assert len(pins) == 8
    for number, key in enumerate(("VDD5V", "VDD3V3", "OUT", "GND", "PGO", "SDA", "SCL", "DIR"), 1):
        assert pins[key].label == f"{number} · {key}"
    assert pins["VDD5V"].kind == pins["VDD3V3"].kind == "power"
    assert "5 V mode regulator bypass" in " ".join(pins["VDD3V3"].functions)
    assert pins["GND"].kind == "ground"
    assert {pin.key for pin in pins.values() if pin.kind == "signal"} == {"OUT", "PGO", "SDA", "SCL", "DIR"}
    assert "not the header layout of an unknown" in diagram.note_en
    assert "Figure 45" in diagram.evidence


def test_pololu_driver_distinguishes_control_and_switched_motor_power_terminals():
    diagram = product_diagram("pololu_2130")
    pins = _terminals("pololu_2130")
    assert len(pins) == 15
    assert {p.key for p in pins.values() if p.kind == "signal"} == {
        "AIN1", "AIN2", "BIN1", "BIN2", "nSLEEP", "nFAULT",
    }
    assert pins["VIN"].kind == pins["VMM"].kind == "power"
    assert pins["AOUT1"].kind == pins["AOUT2"].kind == "power"
    assert "Open-drain" in " ".join(pins["nFAULT"].functions)
    assert "Board pull-up" in pins["nSLEEP"].functions
    assert pins["AISEN"].kind == pins["BISEN"].kind == "other"
    assert "Grounded by default" in pins["AISEN"].functions
    assert "not a claim about the physical order/numbers" in diagram.note_en
    assert "sixteen header pads" in diagram.note_en


def test_pololu_motor_retains_wire_colors_separate_encoder_rails_and_bidirectional_motor():
    diagram = product_diagram("pololu_4755")
    pins = _terminals("pololu_4755")
    assert len(pins) == 6
    assert pins["MOTOR_RED"].label == "Red · motor terminal"
    assert pins["MOTOR_BLACK"].label == "Black · motor terminal"
    assert pins["ENCODER_GND"].label == "Green · encoder GND"
    assert pins["ENCODER_VCC"].label == "Blue · encoder Vcc"
    assert pins["ENCODER_A"].label == "Yellow · encoder A"
    assert pins["ENCODER_B"].label == "White · encoder B"
    assert pins["MOTOR_BLACK"].kind == "power"  # It is not the encoder ground.
    assert pins["ENCODER_GND"].kind == "ground"
    assert "Output swings 0 to encoder Vcc" in pins["ENCODER_A"].functions
    assert "3.3 V MCU compatibility is not assumed" in diagram.note_en
    assert "connector pin numbers and physical lead order are not inferred" in diagram.note_en


def test_supply_dependent_signal_bounds_do_not_reuse_motor_voltage_or_approve_gpio():
    pins = _terminals("pololu_4755")
    for key in ("ENCODER_A", "ENCODER_B"):
        pin = pins[key]
        assert pin.signal_voltage_reference == "encoder_vcc"
        assert (pin.signal_voltage_min_v, pin.signal_voltage_max_v) == (3.5, 20.0)
        assert "Do not infer it from the motor rating" in pin.signal_level_note_en
        assert "엔코더" in pin.signal_level_note
    # The DC motor model is nominally 12 V, whereas encoder Vcc is independent.
    assert get_catalog_entry("pololu_4755").nominal_voltage_v == 12.0
    assert all(not pins[key].signal_voltage_reference for key in ("MOTOR_RED", "MOTOR_BLACK"))
    for identifier, keys in (("ams_as5600_asot", ("OUT", "SCL", "SDA")),
                             ("pololu_2130", ("nFAULT",))):
        others = _terminals(identifier)
        for key in keys:
            assert others[key].signal_level_note and others[key].signal_level_note_en
            assert others[key].signal_voltage_min_v is None
            assert others[key].signal_voltage_max_v is None


def test_diode_uses_verified_cathode_band_without_invented_numbered_leads():
    diagram = product_diagram("vishay_1n5819")
    pins = _terminals("vishay_1n5819")
    assert set(pins) == {"ANODE", "CATHODE"}
    assert pins["CATHODE"].label == "K · cathode (band)"
    assert all(pin.kind == "other" for pin in pins.values())
    assert "No invented pin 1/2 numbering" in diagram.note_en
    assert "color band denotes cathode" in diagram.evidence


def test_new_reference_products_do_not_invent_dc_operating_current_or_supply_defaults():
    for identifier in ("ams_as5600_asot", "pololu_2130"):
        entry = get_catalog_entry(identifier)
        assert entry.reference_only and component_prefill(entry) == {}
        assert entry.nominal_voltage_v is None and entry.rated_current_a is None
    assert get_catalog_entry("ams_as5600_asot") in search_catalog("as5600")
    assert get_catalog_entry("pololu_2130") in search_catalog("pololu 2130")
    # Existing motor remains a DC-equivalent option with user's operating point.
    motor = component_prefill(get_catalog_entry("pololu_4755"))
    assert motor["kind"] == "motor" and motor["rated_voltage_v"] == 12.0
    assert "rated_current_a" not in motor and "startup_current_a" not in motor


def test_unverified_family_clone_and_similar_ic_ids_do_not_inherit_a_physical_map():
    for identifier in ("", "as5600_module", "as5600", "ams_as5600l", "ti_drv8833",
                       "pololu_2135", "omron_e6b2_family", "jst_ph_family", "rpi4b"):
        assert product_diagram(identifier) is None
