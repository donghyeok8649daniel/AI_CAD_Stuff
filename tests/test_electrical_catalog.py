"""The reference library must never turn ratings into unverified loads."""

from urllib.parse import urlsplit

from cadstudio.electrical_catalog import CATALOG, component_prefill, get_catalog_entry, search_catalog


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
