"""ST ESC connector references are not a generic MCU or DC driver simulation."""

import pytest

from cadstudio.board_pins import board_pinout
from cadstudio.electrical import evaluate_electrical
from cadstudio.electrical_catalog import component_prefill, get_catalog_entry, search_catalog
from cadstudio.electrical_registration import register_part, registration_for_part, register_terminal_node
from cadstudio.mcu_connections import connection_endpoints
from cadstudio.models import Design, Project
from cadstudio.product_diagrams import product_diagram


CATALOG = "st_b_g431b_esc1"


def test_exact_st_esc_model_is_discoverable_and_does_not_invent_current_or_gpio():
    entry = get_catalog_entry(CATALOG)
    assert entry in search_catalog("B-G431B-ESC1")
    assert entry in search_catalog("stm32g431")
    assert entry.reference_only and entry.suggested_kind is None
    assert entry.nominal_voltage_v is entry.rated_current_a is None
    assert component_prefill(entry) == {}
    assert "40 A" in entry.spec_summary and "냉각" in entry.spec_summary
    assert board_pinout(CATALOG) is None


def test_st_esc_external_connectors_use_actual_names_and_verified_numbers_only():
    diagram = product_diagram(CATALOG)
    pins = {pin.key: pin for pin in diagram.terminals}
    assert len(pins) == 19
    assert pins["BAT_POS"].label == "J5 · V+"
    assert pins["BAT_NEG"].label == "J6 · V−"
    for number, key in enumerate(("J3_BEC_5V", "J3_UART_TX", "J3_UART_RX", "J3_PWM", "J3_GND"), 1):
        assert pins[key].label.startswith(f"J3.{number} ·")
    assert {key for key in pins if key.startswith("MOTOR_")} == {"MOTOR_U", "MOTOR_V", "MOTOR_W"}
    assert pins["SENSOR_A_H1"].label == "J8 · A+ / H1"
    assert pins["SENSOR_B_H2"].label == "J8 · B+ / H2"
    assert pins["SENSOR_Z_H3"].label == "J8 · Z+ / H3"
    assert all("J1." not in pin.label and "J8." not in pin.label and "J7." not in pin.label for pin in pins.values())
    assert pins["J3_BEC_5V"].kind == pins["SENSOR_5V"].kind == "power"
    assert "daughterboard required" in " ".join(pins["J3_BEC_5V"].functions)
    assert pins["J3_PWM"].signal_level_note and pins["CAN_H"].signal_level_note
    assert "UM2516 Rev 4" in diagram.evidence
    assert "2026-10-05" in diagram.evidence
    assert "not all internal MCU GPIOs" in diagram.note_en
    assert diagram.source_url == get_catalog_entry(CATALOG).source_url


def test_cad_registration_preserves_shape_and_pending_esc_is_not_a_false_dc_load():
    original = Design.model_validate(dict(name="Research frame", parts=[dict(
        id="esc", name="Motor controller carrier", role="structure", color="#F2F2F2",
        geometry=dict(kind="plate", length=41, width=30, thickness=3, hole_count=0),
    )]))
    before = original.model_dump()
    registered = register_part(original, "esc", dict(catalog_id=CATALOG))
    component = registration_for_part(registered, "esc")
    assert original.model_dump() == before
    assert registered.parts[0].geometry == original.parts[0].geometry
    assert component.kind == "load" and component.analysis_enabled is False
    assert component.product_pinout_catalog_id == CATALOG
    assert component.rated_voltage_v == component.rated_current_a == 0
    assert component.signal_pins == {} and component.terminal_pins == {}
    ports = [endpoint for endpoint in connection_endpoints(registered.electrical) if endpoint.terminal.startswith("port:")]
    assert len(ports) == 19 and all(port.node is None for port in ports)
    wired = register_terminal_node(registered, "esc", "J3_PWM", "PWM_COMMAND")
    assert registration_for_part(wired, "esc").terminal_pins == {"J3_PWM": "PWM_COMMAND"}
    assert registration_for_part(registered, "esc").terminal_pins == {}
    restored = Project.model_validate_json(Project(design=wired).model_dump_json()).design
    assert restored == wired
    result = evaluate_electrical(restored.electrical)
    assert result.components[0].analysis_enabled is False
    assert result.components[0].current_a == 0 and result.components[0].voltage_drop_v is None
    with pytest.raises(ValueError, match="동작 회로 모델"):
        register_part(registered, "esc", dict(analysis_enabled=True, rated_voltage_v=12, rated_current_a=.2))
