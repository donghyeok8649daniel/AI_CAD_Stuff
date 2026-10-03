from dataclasses import FrozenInstanceError
import re
from urllib.parse import urlsplit

import pytest

from cadstudio.board_pins import SOURCE_CHECKED_DATE, available_pinouts, board_pinout
from cadstudio.electrical_catalog import get_catalog_entry


def _pins(identifier):
    return {p.key: p for p in board_pinout(identifier).pins}


def test_catalog_models_have_safe_unique_physical_coordinates_and_official_sources():
    pinouts = available_pinouts()
    assert isinstance(pinouts, tuple) and len(pinouts) == 8
    assert len({b.catalog_id for b in pinouts}) == 8
    for board in pinouts:
        assert board_pinout(board.catalog_id) is board
        assert get_catalog_entry(board.catalog_id) is not None
        assert len({p.key for p in board.pins}) == len(board.pins)
        assert len({(p.side, p.position) for p in board.pins}) == len(board.pins)
        host = urlsplit(board.source_url)
        assert host.scheme == "https" and host.hostname in {
            "pip-assets.raspberrypi.com", "docs.arduino.cc", "www.st.com",
            "datasheets.raspberrypi.com",
        }
        assert SOURCE_CHECKED_DATE in board.note
        assert "확인일" in board.note and SOURCE_CHECKED_DATE in board.note_en
        assert "not a dimensioned PCB layout" in board.note_en
        for pin in board.pins:
            assert re.fullmatch(r"[A-Za-z0-9_]{1,40}", pin.key)
            assert pin.kind in ("signal", "power", "ground", "reset", "other")
            assert pin.side in ("left", "right") and pin.position >= 0
            assert pin.label and isinstance(pin.functions, tuple) and pin.functions
        with pytest.raises(FrozenInstanceError):
            board.model = "Changed"
        with pytest.raises(FrozenInstanceError):
            board.pins[0].label = "Changed"


@pytest.mark.parametrize("identifier", ["rpi3bplus", "rpi4b"])
def test_pi_headers_keep_physical_number_distinct_from_gpio_and_logic_voltage(identifier):
    board = board_pinout(identifier)
    pins = _pins(identifier)
    assert board.logic_voltage_v == 3.3
    assert len(pins) == 40
    assert pins["GPIO17"].label == "J8.11 · GPIO17"
    assert pins["GPIO17"].side == "left" and pins["GPIO17"].position == 5
    assert pins["GPIO14"].label == "J8.8 · GPIO14"
    assert "UART TXD" in pins["GPIO14"].functions
    assert pins["GPIO2"].label == "J8.3 · GPIO2"
    assert "I2C SDA" in pins["GPIO2"].functions
    assert pins["GPIO21"].label == "J8.40 · GPIO21"
    assert pins["5V_2"].kind == "power" and pins["GND_6"].kind == "ground"
    assert pins["GPIO0"].kind == pins["GPIO1"].kind == "other"
    assert len([pin for pin in pins.values() if pin.kind == "signal"]) == 26


def test_uno_exact_header_coordinates_and_shared_sda_scl_sockets():
    pins = _pins("arduino_uno_r3")
    assert len(pins) == 32 and board_pinout("arduino_uno_r3").logic_voltage_v == 5.0
    assert pins["D2"].label == "JDIGITAL.3 · D2"
    assert "External interrupt" in pins["D2"].functions
    assert pins["A0"].label == "JANALOG.9 · A0"
    assert pins["D13"].label == "JDIGITAL.14 · D13"
    assert "SPI SCK" in pins["D13"].functions
    assert "PWM" in pins["D3"].functions and "PWM" not in pins["D4"].functions
    assert "SAME_NET:A4" in pins["SDA"].functions
    assert "SAME_NET:A5" in pins["SCL"].functions
    assert pins["IOREF"].kind == pins["AREF"].kind == "other"
    assert pins["RESET"].kind == "reset"


def test_mega_distinguishes_main_edge_and_both_xio_rows():
    pins = _pins("arduino_mega2560_r3")
    assert len(pins) == 86
    assert pins["D2"].label == "JDIGITAL.16 · D2"
    assert pins["D0"].label == "JDIGITAL.18 · D0"
    assert "UART0 RX" in pins["D0"].functions
    assert pins["D21"].label == "JDIGITAL.26 · D21"
    assert "SAME_NET:D21" in pins["SCL"].functions
    assert "SAME_NET:D20" in pins["SDA"].functions
    assert pins["A15"].label == "JANALOG.24 · A15"
    assert pins["D22"].label == "XIO LHS.2 · D22"
    assert pins["D23"].label == "XIO RHS.2 · D23"
    assert pins["D52"].label == "XIO LHS.17 · D52"
    assert pins["D53"].label == "XIO RHS.17 · D53"
    assert "SPI SCK" in pins["D52"].functions
    assert "PWM" in pins["D44"].functions and "PWM" not in pins["D43"].functions


@pytest.mark.parametrize("identifier,table,d11_timer", [
    ("nucleo_f401re", "Table 16", "TIM1_CH1N"),
    ("nucleo_f446re", "Table 19", "TIM14_CH1"),
    ("nucleo_f103rb", "Table 12", "TIM3_CH2"),
])
def test_nucleo_mapping_follows_exact_table_and_default_analog_bridges(identifier, table, d11_timer):
    board = board_pinout(identifier)
    pins = _pins(identifier)
    assert len(pins) == 32 and table in board.note_en and board.logic_voltage_v == 3.3
    assert pins["D2"].label == "CN9.3 · D2 / PA10"
    assert pins["D13"].label == "CN5.6 · D13 / PA5"
    assert "SPI1_SCK" in pins["D13"].functions
    assert d11_timer in pins["D11"].functions
    assert pins["D14"].label == "CN5.9 · D14 / PB9"
    assert pins["D15"].label == "CN5.10 · D15 / PB8"
    assert pins["A4"].label == "CN8.5 · A4 / PC1"
    assert pins["A5"].label == "CN8.6 · A5 / PC0"
    assert "PB9" not in pins["A4"].functions
    assert "solder-bridge" in board.note_en and "Morpho" in board.note
    assert pins["GND_CN6_6"].key != pins["GND_CN6_7"].key


def test_pico_edge_header_excludes_internal_gp_and_non_gpio_control_pins():
    board = board_pinout("rpi_pico")
    pins = _pins("rpi_pico")
    assert len(pins) == 40 and board.logic_voltage_v == 3.3
    assert pins["GP0"].label == "Pin 1 · GP0"
    assert "UART0 TX" in pins["GP0"].functions
    assert pins["GP26"].label == "Pin 31 · GP26"
    assert "ADC0" in pins["GP26"].functions
    assert pins["GP28"].label == "Pin 34 · GP28"
    assert pins["RUN"].kind == "reset" and pins["3V3_EN"].kind == "other"
    assert pins["ADC_VREF"].kind == "other" and pins["VBUS"].kind == "power"
    assert pins["AGND_33"].kind == "ground"
    assert not {"GP23", "GP24", "GP25"} & pins.keys()
    assert len([pin for pin in pins.values() if pin.kind == "signal"]) == 26


def test_duplicate_physical_signals_reference_existing_canonical_signal_keys():
    for board in available_pinouts():
        pins = {p.key: p for p in board.pins}
        for pin in board.pins:
            aliases = [f.removeprefix("SAME_NET:") for f in pin.functions if f.startswith("SAME_NET:")]
            for key in aliases:
                assert key != pin.key and key in pins
                assert pin.kind == pins[key].kind == "signal"


def test_unverified_model_families_and_similar_variants_have_no_guessed_pinout():
    for identifier in ("", "stm32_nucleo_family", "stm32f103c8t6", "blue_pill",
                       "nucleo_g0b1re", "rpi_pico2", "arduino_uno_r4_wifi", "rpi5"):
        assert board_pinout(identifier) is None
