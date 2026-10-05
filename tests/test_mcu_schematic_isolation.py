"""Rendered independent signal pads must not imply a GPIO short or fake rail."""

import pytest
from PySide6.QtWidgets import QApplication

from cadstudio.electrical import ElectricalWorkspace, evaluate_electrical
from cadstudio.mcu_connections import connection_endpoints, pin_connections
from cadstudio.native.electrical_schematic import ElectricalSchematicDialog


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
    schematic = ElectricalSchematicDialog(None, workspace, evaluate_electrical(workspace), view_mode='symbols')
    try:
        signals = tuple(schematic.branch_layout["device"]["signals"].values())
        assert len(signals) == 2 and signals[0]["node"] != signals[1]["node"]
        pad_positions = {(signal["origin_x"], signal["origin_y"]) for signal in signals}
        assert len(pad_positions) == 2
        prefix="pin:" if kind=="mcu" else "port:"
        keys=("GPIO17","GPIO18") if kind=="mcu" else ("OUT_A","PWM")
        assert pad_positions=={(schematic.endpoint_coordinates[("device",prefix+key)].x(),
                               schematic.endpoint_coordinates[("device",prefix+key)].y()) for key in keys}
        a_lines=[item.line() for item in schematic.net_segments["SIG_A"]]
        b_lines=[item.line() for item in schematic.net_segments["SIG_B"]]
        assert a_lines and b_lines
        # Actual routed nets must remain geometrically distinct; a shared
        # conductor would imply a short even when their labels differ.
        assert not any(_shared_segment(a,b) for a in a_lines for b in b_lines)
        for key,node in zip(keys,("SIG_A","SIG_B")):
            point=schematic.endpoint_coordinates[("device",prefix+key)]
            assert any(_on_line(point,item.line()) for item in schematic.net_segments[node])
        assert workspace == _two_signals(kind)
    finally:
        schematic.reject()


def _on_line(point,line):
    epsilon=1e-5
    return ((abs(line.y1()-line.y2())<epsilon and abs(point.y()-line.y1())<epsilon
             and min(line.x1(),line.x2())-epsilon<=point.x()<=max(line.x1(),line.x2())+epsilon)
            or (abs(line.x1()-line.x2())<epsilon and abs(point.x()-line.x1())<epsilon
                and min(line.y1(),line.y2())-epsilon<=point.y()<=max(line.y1(),line.y2())+epsilon))


def _shared_segment(a,b):
    epsilon=1e-5
    horizontal=(abs(a.y1()-a.y2())<epsilon and abs(b.y1()-b.y2())<epsilon
                and abs(a.y1()-b.y1())<epsilon)
    vertical=(abs(a.x1()-a.x2())<epsilon and abs(b.x1()-b.x2())<epsilon
              and abs(a.x1()-b.x1())<epsilon)
    if horizontal:
        return min(max(a.x1(),a.x2()),max(b.x1(),b.x2()))-max(min(a.x1(),a.x2()),min(b.x1(),b.x2()))>epsilon
    if vertical:
        return min(max(a.y1(),a.y2()),max(b.y1(),b.y2()))-max(min(a.y1(),a.y2()),min(b.y1(),b.y2()))>epsilon
    return False


def test_legacy_supply_label_is_preserved_but_not_rendered_as_verified_physical_rail(app):
    raw = _two_signals("mcu").model_dump()
    device = next(component for component in raw["components"] if component["id"] == "device")
    # Old files permitted free labels, including a key now used by a 3.3 V pad.
    # A 5 V net assignment must not be upgraded into a verified 3.3 V rail.
    device["signal_pins"] = {"3V3_1": "POWER"}
    workspace = ElectricalWorkspace.model_validate(raw)
    result = evaluate_electrical(workspace)
    assert next(branch for branch in result.components if branch.id == "device").signal_pin_connected["3V3_1"] is True
    schematic = ElectricalSchematicDialog(None, workspace, result, view_mode='symbols')
    try:
        layout = schematic.branch_layout["device"]["signals"]["3V3_1"]
        assert layout["legacy"] is True
        # A preserved legacy rail label is deliberately not promoted into a
        # verified physical power pad or a live supply indication.
        assert ('device','pin:3V3_1') in schematic.endpoint_coordinates
        assert not any(endpoint.terminal=='pin:3V3_1' and endpoint.node=='POWER'
                       for endpoint in connection_endpoints(workspace))
        rail=next(pin for pin in pin_connections(workspace,'device') if pin.key=='3V3_1')
        assert rail.legacy and rail.kind!='signal'
        item=schematic.component_items['device']
        port=item.ports['pin:3V3_1']
        assert port.legacy and not port.physical and not port.connectable
        from cadstudio.native.circuit_symbols import CONNECTED
        assert item.port_items['pin:3V3_1'].brush().color()!=CONNECTED
        text = " ".join([*(value.toPlainText() for value in schematic.scene.items() if hasattr(value, "toPlainText")),
                         *(value.label for value in item.ports.values()),
                         *(value.toolTip() for value in item.port_items.values())])
        assert "3V3 *" in text
        assert "기존 수동 연결 · 확인 필요" in text or "Legacy manual connection · verification required" in text
        assert workspace.components[1].signal_pins == {"3V3_1": "POWER"}
    finally:
        schematic.reject()
