"""Rendered independent signal pads must not imply a GPIO short or fake rail."""

import pytest
from PySide6.QtWidgets import QApplication, QGraphicsEllipseItem, QGraphicsLineItem

from cadstudio.electrical import ElectricalWorkspace, evaluate_electrical
from cadstudio.native.electrical_schematic import ElectricalSchematicDialog, LIVE


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    yield instance
    instance.processEvents()


def _two_signals(kind):
    component = dict(id="device", name="Two independent signals", kind=kind, a="POWER", b="GND",
                     rated_voltage_v=5, rated_current_a=.05)
    if kind == "mcu":
        component.update(catalog_id="rpi4b", signal_pins={"GPIO17": "SIG_A", "GPIO18": "SIG_B"})
    else:
        component["terminal_pins"] = {"OUT_A": "SIG_A", "PWM": "SIG_B"}
    return ElectricalWorkspace.model_validate(dict(nodes=["GND", "POWER", "SIG_A", "SIG_B"], components=[
        dict(id="source", name="Supply", kind="battery", a="POWER", b="GND", voltage_v=5),
        component,
        dict(id="pull_a", name="Input A", kind="resistor", a="SIG_A", b="GND", resistance_ohm=1000),
        dict(id="pull_b", name="Input B", kind="resistor", a="SIG_B", b="GND", resistance_ohm=2000),
    ]))


@pytest.mark.parametrize("kind", ["mcu", "load"])
def test_independent_gpio_or_driver_ports_have_distinct_drawn_pads_and_no_common_conductor(app, kind):
    workspace = _two_signals(kind)
    schematic = ElectricalSchematicDialog(None, workspace, evaluate_electrical(workspace))
    try:
        signals = tuple(schematic.branch_layout["device"]["signals"].values())
        assert len(signals) == 2 and signals[0]["node"] != signals[1]["node"]
        pad_positions = {(signal["origin_x"], signal["origin_y"]) for signal in signals}
        assert len(pad_positions) == 2
        items = schematic.branch_items["device"]
        pads = {(item.rect().center().x(), item.rect().center().y())
                for item in items if isinstance(item, QGraphicsEllipseItem)}
        assert pad_positions <= pads
        lines = [item.line() for item in items if isinstance(item, QGraphicsLineItem)]
        for signal in signals:
            assert any(line.x1() == signal["origin_x"] and line.y1() == signal["origin_y"]
                       and line.x2() == signal["x"] and line.y2() == signal["y"] for line in lines)
        # A vertical shared conductor would join two independent net rows even
        # if colors and the stored node names differ. Inspect rendered lines.
        net_rows = sorted(signal["y"] for signal in signals)
        assert not any(line.x1() == line.x2() and
                       min(line.y1(), line.y2()) <= net_rows[0] and
                       max(line.y1(), line.y2()) >= net_rows[1] for line in lines)
        # Independent horizontal conductors have no positive shared segment.
        signal_lines = [line for line in lines if line.y1() == line.y2() and line.y1() in net_rows]
        assert len(signal_lines) == 2
        assert signal_lines[0].y1() != signal_lines[1].y1()
        assert workspace == _two_signals(kind)
    finally:
        schematic.reject()


def test_legacy_supply_label_is_preserved_but_not_rendered_as_verified_physical_rail(app):
    raw = _two_signals("mcu").model_dump()
    device = next(component for component in raw["components"] if component["id"] == "device")
    # Old files permitted free labels, including a key now used by a 3.3 V pad.
    # A 5 V net assignment must not be upgraded into a verified 3.3 V rail.
    device["signal_pins"] = {"3V3_1": "POWER"}
    workspace = ElectricalWorkspace.model_validate(raw)
    result = evaluate_electrical(workspace)
    assert next(branch for branch in result.components if branch.id == "device").signal_pin_connected["3V3_1"] is True
    schematic = ElectricalSchematicDialog(None, workspace, result)
    try:
        layout = schematic.branch_layout["device"]["signals"]["3V3_1"]
        assert layout["legacy"] is True
        lines = [item for item in schematic.branch_items["device"] if isinstance(item, QGraphicsLineItem)
                 and item.line().y1() == item.line().y2() == layout["y"]]
        assert lines and all(item.pen().color() != LIVE for item in lines)
        text = " ".join(item.toPlainText() for item in schematic.scene.items() if hasattr(item, "toPlainText"))
        assert "3V3 *" in text
        assert "기존 수동 연결 · 확인 필요" in text or "Legacy manual mapping · check required" in text
        assert workspace.components[1].signal_pins == {"3V3_1": "POWER"}
    finally:
        schematic.reject()
