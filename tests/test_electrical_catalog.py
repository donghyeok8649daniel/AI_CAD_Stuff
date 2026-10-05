"""The reference library must never turn ratings into unverified loads."""

from urllib.parse import urlsplit

import pytest

from cadstudio.electrical_catalog import (
    CATALOG, catalog_functions, component_prefill, get_catalog_entry,
    has_catalog_function, search_catalog,
)


def test_catalog_ids_and_official_sources_are_stable_and_safe():
    assert len(CATALOG) >= 50
    assert len({entry.catalog_id for entry in CATALOG}) == len(CATALOG)
    for entry in CATALOG:
        assert entry.catalog_id.isascii()
        assert entry.model and entry.manufacturer and entry.category and entry.spec_summary
        parsed = urlsplit(entry.source_url)
        assert parsed.scheme == "https"
        assert parsed.hostname and not parsed.username and not parsed.password
        assert get_catalog_entry(entry.catalog_id) is entry


def test_raspberry_pi_supply_recommendations_are_not_board_load_currents():
    for identifier in ("rpi3bplus", "rpi4b", "rpi5", "rpi_zero2w"):
        entry = get_catalog_entry(identifier)
        assert entry is not None
        assert entry.rated_current_a is None
        values = component_prefill(entry)
        assert values["catalog_id"] == identifier
        assert values["rated_voltage_v"] == 5
        assert "rated_current_a" not in values


def test_reference_only_semiconductor_is_not_inserted_as_a_dc_equivalent():
    for identifier in ("ti_drv8833", "vishay_1n5819", "maxon_666603", "stm32_nucleo_family"):
        entry = get_catalog_entry(identifier)
        assert entry is not None and entry.reference_only
        assert component_prefill(entry) == {}


def test_search_accepts_korean_alias_and_multiword_model_queries():
    assert get_catalog_entry("rpi3bplus") in search_catalog("라즈베리파이 3b+")
    assert get_catalog_entry("rpi4b") in search_catalog("raspberry pi 4")
    assert get_catalog_entry("stm32_nucleo_family") in search_catalog("stm32 nucleo")
    assert get_catalog_entry("ti_drv8833") in search_catalog("h브리지")
    assert get_catalog_entry("b_u585i_iot02a") in search_catalog("stm b")
    assert get_catalog_entry("panasonic_erj6enf1002v") in search_catalog("10k 저항")
    assert get_catalog_entry("littelfuse_218_family") in search_catalog("퓨즈")
    assert search_catalog("제품이없음") == ()


def test_exact_pololu_motor_has_voltage_but_not_fabricated_running_current():
    entry = get_catalog_entry("pololu_4755")
    assert entry is not None
    values = component_prefill(entry)
    assert values["kind"] == "motor"
    assert values["rated_voltage_v"] == 12
    assert "rated_current_a" not in values
    assert "startup_current_a" not in values


def test_exact_resistor_prefills_ohms_without_applying_package_power_as_a_current():
    entry = get_catalog_entry("panasonic_erj6enf1002v")
    assert entry is not None
    values = component_prefill(entry)
    assert values["kind"] == "resistor"
    assert values["resistance_ohm"] == 10000
    assert "rated_current_a" not in values
    assert "max_current_a" not in values


@pytest.mark.parametrize("identifier,capacitance,voltage,polarized", [
    ("kyocera_kgm15br71e104kt", 100e-9, 25, False),
    ("panasonic_eeufr1h101b", 100e-6, 50, True),
])
def test_exact_capacitor_ratings_never_become_a_dc_voltage_source_or_load(
        identifier, capacitance, voltage, polarized):
    entry = get_catalog_entry(identifier)
    assert entry is not None and not entry.reference_only
    values = component_prefill(entry)
    assert values["kind"] == "capacitor"
    assert values["capacitance_f"] == capacitance
    assert values["rated_voltage_v"] == voltage
    assert values["capacitor_polarized"] is polarized
    assert "voltage_v" not in values
    assert "rated_current_a" not in values
    assert "max_current_a" not in values  # Ripple rating is not DC current.


def test_exact_inductor_prefills_dc_winding_resistance_separately_from_inductance():
    entry = get_catalog_entry("wurth_7447713100")
    assert entry is not None and not entry.reference_only
    values = component_prefill(entry)
    assert values["kind"] == "inductor"
    assert values["inductance_h"] == 10e-6
    assert values["winding_resistance_ohm"] == 0.052
    assert "resistance_ohm" not in values
    assert "rated_current_a" not in values
    assert "max_current_a" not in values  # Thermal/saturation conditions differ.


@pytest.mark.parametrize("identifier,voltage", [
    ("robotis_xl330_m288t", 5), ("concentric_lact10p_12v_10", 12),
])
def test_actuator_requires_a_user_operating_current_instead_of_using_stall_rating(identifier, voltage):
    entry = get_catalog_entry(identifier)
    assert entry is not None and not entry.reference_only
    values = component_prefill(entry)
    assert values["kind"] == "actuator"
    assert values["rated_voltage_v"] == voltage
    assert values["analysis_enabled"] is False
    assert "rated_current_a" not in values
    assert "startup_current_a" not in values
    assert "max_current_a" not in values


def test_common_passives_actuators_and_exact_resistor_are_searchable():
    assert get_catalog_entry("kyocera_kgm15br71e104kt") in search_catalog("캐패시터 100nf")
    assert get_catalog_entry("wurth_7447713100") in search_catalog("코일 10uh")
    assert get_catalog_entry("robotis_xl330_m288t") in search_catalog("액추에이터 xl330")
    assert get_catalog_entry("concentric_lact10p_12v_10") in search_catalog("선형 액추에이터")
    entry = get_catalog_entry("panasonic_erj6enf1001v")
    assert entry in search_catalog("1k 저항")
    assert component_prefill(entry)["resistance_ohm"] == 1000


def test_functional_roles_are_independent_of_dc_kind_and_do_not_invent_family_models():
    assert catalog_functions("st_b_g431b_esc1") == ("motor_driver", "controller")
    assert catalog_functions("st_evspin32g4") == ("motor_driver", "controller")
    assert catalog_functions("pololu_2130") == ("motor_driver",)
    assert catalog_functions("pololu_4755") == ("motor", "encoder")
    assert catalog_functions("rpi4b") == ("controller",)
    assert catalog_functions("robotis_xl330_m288t") == ("actuator",)
    assert has_catalog_function("omron_e6b2_cwz6c_1000", "encoder")
    for identifier in ("", "unknown_encoder", "stm32_nucleo_family", "omron_e6b2_family"):
        assert catalog_functions(identifier) == ()
        assert not has_catalog_function(identifier, "encoder")
    for identifier in ("st_b_g431b_esc1", "st_evspin32g4", "omron_e6b2_cwz6c_1000"):
        entry = get_catalog_entry(identifier)
        assert entry.reference_only and component_prefill(entry) == {}
        assert entry.rated_current_a is None and entry.nominal_voltage_v is None


def test_encoder_counts_are_full_quadrature_edges_with_an_explicit_shaft_reference():
    motor = get_catalog_entry("pololu_4755")
    assert motor.encoder_interface == "quadrature"
    assert motor.encoder_counts_per_rev == 64
    assert motor.encoder_reference == "motor_shaft"
    assert motor.motor_gear_ratio == pytest.approx(102.0833333333)
    # The marketing "100:1" name must not turn motor counts into 6400 exact
    # output-shaft counts; the actual gearbox ratio is non-integral.
    assert motor.motor_gear_ratio * motor.encoder_counts_per_rev == pytest.approx(6533.3333333333)
    for identifier in ("omron_e6b2_cwz6c_1000", "omron_e6c2_cwz6c_1000"):
        encoder = get_catalog_entry(identifier)
        assert encoder.encoder_interface == "quadrature"
        assert encoder.encoder_counts_per_rev == 4000
        assert encoder.encoder_reference == "encoder_shaft"
        assert encoder.motor_gear_ratio is None


def test_absolute_angle_encoder_is_not_registered_as_a_quadrature_pulse_source():
    encoder = get_catalog_entry("ams_as5600_asot")
    assert has_catalog_function(encoder.catalog_id, "encoder")
    assert encoder.encoder_interface == "absolute_i2c"
    assert encoder.encoder_counts_per_rev is None
    assert encoder.encoder_reference is None
