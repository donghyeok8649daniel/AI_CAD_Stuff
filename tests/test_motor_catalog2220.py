"""Motor choices preserve real terminal identities and never certify a drive."""

import pytest

from cadstudio.electrical import evaluate_electrical
from cadstudio.electrical_catalog import (
    MOTOR_CATALOG_IDS, catalog_counts, catalog_functions, catalog_support,
    component_prefill, get_catalog_entry, search_catalog,
)
from cadstudio.electrical_registration import (
    connect_registered_pin, register_part, register_terminal_node, registration_for_part,
)
from cadstudio.models import Design, Project
from cadstudio.product_diagrams import MOTOR_DIAGRAM_IDS, product_diagram


def assembly():
    return Design.model_validate(dict(name="Original machine", parameters={"wall": "2 mm"}, parts=[
        dict(id="controller", name="Controller carrier", role="electrical", color="#224466",
             geometry=dict(kind="plate", length=60, width=40, thickness=2, hole_count=0)),
        dict(id="motor", name="Existing motor envelope", role="transmission", color="#998877",
             transform=dict(x=70, rz=15), fixed=True,
             geometry=dict(kind="cylinder", diameter=40, height=70)),
    ], part_groups=[dict(id="keep", name="Keep assembly", part_ids=["controller", "motor"])],
        electrical=dict(nodes=["GND", "BAT"], components=[
            dict(id="source", name="Existing 12 V source", kind="battery", a="BAT", b="GND",
                 voltage_v=12, internal_resistance_ohm=.1, max_current_a=2),
            dict(id="resistor", name="Existing load", kind="resistor", a="BAT", b="GND", resistance_ohm=100),
        ])))


def terminals(identifier):
    return {pin.key: pin for pin in product_diagram(identifier).terminals}


@pytest.mark.parametrize("catalog_id", MOTOR_DIAGRAM_IDS)
def test_motor_reference_attaches_to_existing_body_and_persists_real_connections(catalog_id):
    old = assembly()
    before = old.model_dump()
    entry = get_catalog_entry(catalog_id)
    mapped = register_part(old, "motor", dict(catalog_id=catalog_id))
    registered = registration_for_part(mapped, "motor")
    assert old.model_dump() == before
    assert registered.kind == (entry.suggested_kind or "load")
    assert registered.part_id == "motor" and registered.product_pinout_catalog_id == catalog_id
    assert registered.analysis_enabled is False and registered.rated_current_a == 0
    assert registered.terminal_pins == {} and registered.source_url == entry.source_url
    assert product_diagram(catalog_id).source_url == entry.source_url
    assert mapped.parts[1].geometry == old.parts[1].geometry
    assert mapped.parts[1].transform == old.parts[1].transform
    assert mapped.parts[1].color == old.parts[1].color and mapped.parts[1].fixed
    assert mapped.parts[0] == old.parts[0]
    assert mapped.part_groups == old.part_groups and mapped.parameters == old.parameters
    assert mapped.electrical.components[:2] == old.electrical.components
    # Persist every usable terminal without inventing a connection for NC cavities.
    usable = [pin for pin in product_diagram(catalog_id).terminals if not pin.key.endswith("NC")]
    for i, pin in enumerate(usable):
        mapped = register_terminal_node(mapped, "motor", pin.key, f"MOTOR_NET_{i}")
    reopened = Project.model_validate_json(Project(design=mapped).model_dump_json()).design
    assert registration_for_part(reopened, "motor").terminal_pins == {
        pin.key: f"MOTOR_NET_{i}" for i, pin in enumerate(usable)}
    assert reopened == mapped
    assert evaluate_electrical(mapped.electrical).source_power_w == pytest.approx(
        evaluate_electrical(old.electrical).source_power_w)
    with pytest.raises(ValueError, match="물리 단자 목록"):
        register_terminal_node(mapped, "motor", "GUESSED_PIN", "BAT")


def test_motor_expansion_is_searchable_by_exact_model_without_fake_family_coverage():
    assert len(MOTOR_CATALOG_IDS) == 12 and len(MOTOR_DIAGRAM_IDS) == 15
    counts = catalog_counts()
    assert counts["total"] >= 110 and counts["registerable"] >= 68
    assert all(catalog_support(identifier) == "terminals" for identifier in MOTOR_DIAGRAM_IDS)
    for identifier in MOTOR_CATALOG_IDS:
        entry = get_catalog_entry(identifier)
        assert entry in search_catalog(entry.model)
        assert entry.rated_current_a is None  # No arbitrary DC operating consumption.
        assert set(catalog_functions(identifier)) & {"motor", "actuator"}
        assert entry.source_url.startswith("https://")
    assert product_diagram("stepperonline_17he19_2004s") is None
    assert product_diagram("robotis_xm430_family") is None
    assert product_diagram("pololu_5724") is None


@pytest.mark.parametrize("identifier,voltage,counts,ratio", [
    ("pololu_4845", 12, 48, (22**4 * 24) / (12 * 10**4)),
    ("pololu_4847", 12, 48, (22**5 * 23) / (12 * 10**5)),
    ("pololu_5725", 24, 48, (22**4 * 24) / (12 * 10**4)),
    ("pololu_4753", 12, 64, 50),
])
def test_dc_gearmotor_voltage_and_motor_shaft_encoder_counts_remain_separate(identifier, voltage, counts, ratio):
    entry = get_catalog_entry(identifier)
    pins = terminals(identifier)
    assert entry.nominal_voltage_v == voltage and entry.encoder_counts_per_rev == counts
    assert entry.encoder_reference == "motor_shaft" and entry.motor_gear_ratio == pytest.approx(ratio)
    assert entry.encoder_interface == "quadrature"
    assert pins["MOTOR_BLACK"].kind == "power" and pins["ENCODER_GND"].kind == "ground"
    assert "Black" in pins["MOTOR_BLACK"].label and "Green" in pins["ENCODER_GND"].label
    assert "Blue" in pins["ENCODER_VCC"].label and "Yellow" in pins["ENCODER_A"].label
    assert "White" in pins["ENCODER_B"].label
    for signal in ("ENCODER_A", "ENCODER_B"):
        assert pins[signal].signal_voltage_reference == "encoder_vcc"
        assert (pins[signal].signal_voltage_min_v, pins[signal].signal_voltage_max_v) == (3.5, 20)
    prefill = component_prefill(entry)
    assert prefill["rated_voltage_v"] == voltage and prefill["analysis_enabled"] is False
    assert "rated_current_a" not in prefill


@pytest.mark.parametrize("identifier", ["stepperonline_17hs16_2004s1", "stepperonline_17hs19_2004s1", "stepperonline_23hs22_2804s", "maxon_ec_i40_496655"])
def test_multiphase_motor_registration_cannot_be_promoted_to_a_fictional_dc_load(identifier):
    entry = get_catalog_entry(identifier)
    assert entry.reference_only and entry.suggested_kind is None and component_prefill(entry) == {}
    registered = register_part(assembly(), "motor", dict(catalog_id=identifier))
    before = registered.model_dump()
    with pytest.raises(ValueError, match="동작 회로 모델"):
        register_part(registered, "motor", dict(analysis_enabled=True, rated_voltage_v=24, rated_current_a=2))
    assert registered.model_dump() == before
    with pytest.raises(ValueError, match="종류"):
        register_part(assembly(), "motor", dict(catalog_id=identifier, kind="motor"))


def test_stepper_two_windings_have_no_ground_or_voltage_source_pins():
    for identifier in ("stepperonline_17hs16_2004s1", "stepperonline_17hs19_2004s1", "stepperonline_23hs22_2804s"):
        pins = terminals(identifier)
        assert set(pins) == {"A_POS", "A_NEG", "B_POS", "B_NEG"}
        assert all(pin.kind == "power" for pin in pins.values())
        assert [(pins[key].label.split(" · ")[1]) for key in ("A_POS", "A_NEG", "B_POS", "B_NEG")] == ["Black", "Green", "Red", "Blue"]
        assert "Phase current is not DC" in product_diagram(identifier).note_en
    assert "1.3 Ω" in get_catalog_entry("stepperonline_17hs16_2004s1").spec_summary
    assert "1.20 N·m" in get_catalog_entry("stepperonline_23hs22_2804s").spec_summary


def test_dynamixel_ttl_and_rs485_variants_preserve_different_actual_connector_interfaces():
    ttl = terminals("robotis_xm430_w350t")
    differential = terminals("robotis_xm430_w350r")
    assert set(ttl) == {"GND", "VDD", "DATA"}
    assert set(differential) == {"GND", "VDD", "DATA_POS", "DATA_NEG"}
    assert ttl["GND"].label == "1 · GND" and ttl["VDD"].label == "2 · VDD"
    assert ttl["DATA"].label == "3 · DATA"
    assert differential["DATA_POS"].label == "3 · DATA+" and differential["DATA_NEG"].label == "4 · DATA−"
    assert ttl["DATA"].signal_voltage_reference == "ttl_5v"
    assert terminals("robotis_xl330_m288t")["DATA"].signal_voltage_reference == "ttl_3v3"
    assert "5 V compatibility" in product_diagram("robotis_xl330_m288t").note_en
    assert differential["DATA_POS"].signal_voltage_reference == "external_rs485_transceiver"
    assert all(not ({"ENCODER_A", "ENCODER_B", "PWM", "TX", "RX"} & terminals(identifier).keys())
               for identifier in ("robotis_xm430_w350t", "robotis_xm430_w350r", "robotis_xl430_w250t", "robotis_xl330_m288t"))


def test_dynamixel_model_change_requires_explicit_connection_removal_and_keeps_the_body():
    ttl = register_part(assembly(), "motor", dict(catalog_id="robotis_xm430_w350t"))
    ttl = register_terminal_node(ttl, "motor", "DATA", "HALF_DUPLEX")
    before = ttl.model_dump()
    with pytest.raises(ValueError, match="既存|기존 핀·단자 연결"):
        register_part(ttl, "motor", dict(catalog_id="robotis_xm430_w350r"))
    assert ttl.model_dump() == before
    switched = register_part(ttl, "motor", dict(catalog_id="robotis_xm430_w350r", allow_drop_connections=True))
    assert switched.parts == ttl.parts and switched.part_groups == ttl.part_groups
    assert registration_for_part(switched, "motor").terminal_pins == {}
    assert "HALF_DUPLEX" in switched.electrical.nodes


def test_feedback_linear_p_variant_retains_potentiometer_wiper_and_connector_numbers():
    for identifier in ("concentric_lact6p_12v_10", "concentric_lact8p_12v_10", "concentric_lact10p_12v_10"):
        pins = terminals(identifier)
        assert pins["MOTOR_BLACK"].label == "Power 1 · Black"
        assert pins["MOTOR_RED"].label == "Power 2 · Red"
        assert pins["MOTOR_BLACK"].kind == pins["MOTOR_RED"].kind == "power"
        assert pins["POT_WIPER"].label == "Feedback 1 · Blue" and pins["POT_WIPER"].kind == "signal"
        assert pins["POT_EXC_NEG"].label == "Feedback 2 · White · EXC−"
        assert pins["POT_NC"].label == "Feedback 3 · N.C."
        assert pins["POT_EXC_POS"].label == "Feedback 4 · Yellow · EXC+"
        assert "retracts with red positive" in product_diagram(identifier).note_en
        assert "Rev.20201208" in product_diagram(identifier).evidence


def test_maxon_hall_commutation_is_not_a_quadrature_encoder_or_a_motor_ground():
    entry = get_catalog_entry("maxon_ec_i40_496655")
    pins = terminals(entry.catalog_id)
    assert entry.nominal_voltage_v == 36 and entry.encoder_interface is None
    assert entry.functional_roles == ("motor",)
    assert all(pins[key].kind == "power" for key in ("WINDING_1", "WINDING_2", "WINDING_3"))
    assert pins["WINDING_2"].label == "Motor 2 · Black · winding 2"
    assert pins["HALL_GND"].label == "Sensor 4 · Blue · GND"
    assert pins["HALL_VCC"].label == "Sensor 5 · Green · VHall"
    assert "4.5–24" in " ".join(pins["HALL_VCC"].functions)
    assert not {"ENCODER_A", "ENCODER_B", "ENCODER_Z"} & pins.keys()
    assert "max. continuous" not in " ".join(pins["HALL_VCC"].functions)
    assert "2.74 A" in entry.spec_summary and "61.8 A" in entry.spec_summary
    assert "March 2025" in product_diagram(entry.catalog_id).evidence


def test_new_motor_encoder_pin_can_share_a_controller_net_without_sharing_motor_power():
    design = register_part(assembly(), "controller", dict(catalog_id="rpi4b"))
    design = register_part(design, "motor", dict(catalog_id="pololu_5725"))
    connected = connect_registered_pin(design, "controller", "GPIO17", "motor", "port:ENCODER_A")
    motor = registration_for_part(connected, "motor")
    controller = registration_for_part(connected, "controller")
    assert motor.terminal_pins["ENCODER_A"] == controller.signal_pins["GPIO17"]
    assert "MOTOR_RED" not in motor.terminal_pins and "ENCODER_VCC" not in motor.terminal_pins
    assert motor.a != motor.terminal_pins["ENCODER_A"] and motor.b != motor.terminal_pins["ENCODER_A"]
    assert motor.analysis_enabled is False and controller.analysis_enabled is False
    # Storing connectivity makes no electrical-level compatibility claim.
    assert "3.3 V GPIO" in product_diagram("pololu_5725").note_en
