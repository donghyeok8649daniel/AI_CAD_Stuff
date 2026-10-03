"""Known product signals require voltage review independently of motor ratings."""

import pytest

from cadstudio.electrical import ElectricalWorkspace
from cadstudio.mcu_connections import assign_pin, topology_warnings


def _workspace(board="rpi4b", *, motor_voltage=12.0):
    return ElectricalWorkspace.model_validate({
        "nodes": ["GND", "MCU_POWER", "MOTOR_A", "MOTOR_B", "SIGNAL_A", "SIGNAL_B"],
        "components": [
            {"id": "board", "name": "Test board", "kind": "mcu", "a": "MCU_POWER", "b": "GND",
             "analysis_enabled": False, "catalog_id": board, "pinout_catalog_id": board},
            {"id": "motor", "name": "Pololu #4755", "kind": "motor", "a": "MOTOR_A", "b": "MOTOR_B",
             "rated_voltage_v": motor_voltage, "analysis_enabled": False, "catalog_id": "pololu_4755",
             "product_pinout_catalog_id": "pololu_4755"},
        ],
    })


@pytest.mark.parametrize("board,pin", [("rpi4b", "GPIO17"), ("arduino_uno_r3", "D2")])
def test_encoder_output_is_not_unconditionally_approved_for_a_gpio(board, pin):
    workspace = assign_pin(_workspace(board), "board", pin, "motor", "port:ENCODER_A")
    messages = "\n".join(topology_warnings(workspace, language="en"))
    assert "encoder" in messages.casefold()
    assert "3.5" in messages and "20" in messages
    assert "MCU" in messages
    assert "motor rating" in messages


def test_signal_review_follows_closed_wires_but_not_an_open_wire():
    workspace = _workspace()
    workspace.components[0].signal_pins = {"GPIO17": "SIGNAL_A"}
    workspace.components[1].terminal_pins = {"ENCODER_B": "SIGNAL_B"}
    raw = workspace.model_dump()
    raw["components"].append({"id": "signal_wire", "name": "Signal cable", "kind": "wire",
                              "a": "SIGNAL_A", "b": "SIGNAL_B", "closed": True,
                              "analysis_enabled": False})
    assert "encoder" in "\n".join(topology_warnings(raw, language="en")).casefold()
    raw["components"][-1]["closed"] = False
    assert not any("encoder" in text.casefold() for text in topology_warnings(raw, language="en"))


def test_changing_motor_operating_voltage_does_not_erase_separate_encoder_warning():
    for motor_voltage in (3.3, 12.0):
        workspace = assign_pin(_workspace(motor_voltage=motor_voltage), "board", "GPIO17",
                               "motor", "port:ENCODER_A")
        messages = "\n".join(topology_warnings(workspace, language="en"))
        assert "3.5" in messages and "motor rating" in messages


def test_unassigned_encoder_signal_adds_no_false_connection_warning():
    assert not any("encoder" in text.casefold()
                   for text in topology_warnings(_workspace(), language="en"))
