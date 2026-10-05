"""Circuit symbols preserve real terminal identity while remaining interactive."""

import hashlib

import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsView

from cadstudio.electrical import ElectricalComponent
from cadstudio.native.circuit_symbols import CircuitComponentItem, CONNECTED, POWER


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    yield instance
    instance.processEvents()


def board(**fields):
    return ElectricalComponent.model_validate(dict(
        id="controller", name="Raspberry Pi 4 control board", kind="mcu",
        a="VCC", b="GND", rated_voltage_v=5, rated_current_a=.2,
        catalog_id="rpi4b", **fields,
    ))


def test_compact_board_keeps_saved_pins_and_does_not_infer_power_rails(app):
    component = board(signal_pins={"GPIO21": "REMOTE", "GPIO2": "SDA"})
    before = component.model_dump()
    item = CircuitComponentItem(component)
    assert item.ports["pin:GPIO21"].node == "REMOTE"
    assert item.ports["pin:GPIO2"].node == "SDA"
    assert item.ports["a"].node == "VCC" and item.ports["b"].node == "GND"
    assert item.all_ports["pin:5V_2"].node is None
    assert item.all_ports["pin:GND_6"].node is None
    assert item.all_ports["pin:5V_2"].connectable is False
    assert item.all_ports["pin:GPIO2"].physical is True
    assert "J8.3" in item.all_ports["pin:GPIO2"].label
    assert "raspberrypi.com" in item.source_url
    assert len(item.ports) < len(item.all_ports) == 42
    assert item.boundingRect().height() < 260
    assert component.model_dump() == before


def test_expand_reference_reuses_position_and_preserves_all_connections(app):
    item = CircuitComponentItem(board(signal_pins={"GPIO21": "REMOTE"}))
    scene = QGraphicsScene()
    scene.addItem(item)
    item.setPos(73, 42)
    changed = []
    item.geometryChanged.connect(changed.append)
    item.show_all_pins(True)
    assert item.pos() == QPointF(73, 42)
    assert len(item.ports) == 42
    assert item.port_node("pin:GPIO21") == "REMOTE"
    assert item.port_node("pin:5V_2") is None
    assert item.port_scene_position("pin:GPIO21") == item.mapToScene(item.pin_positions["pin:GPIO21"])
    item.show_all_pins(False)
    assert "pin:GPIO21" in item.ports
    assert changed == ["controller", "controller"]
    assert len(scene.items()) == 1 + len(item.ports)


def test_legacy_power_assignment_is_warned_not_painted_as_verified(app):
    item = CircuitComponentItem(board(signal_pins={"3V3_1": "WRONG_LEGACY"}))
    port = item.ports["pin:3V3_1"]
    assert port.node == "WRONG_LEGACY"  # Preserve, never silently disconnect.
    assert port.legacy and not port.physical and not port.connectable
    assert port.label.endswith(" *")
    assert "기존 수동 연결 · 확인 필요" in item.port_items[port.key].toolTip()
    assert item.port_items[port.key].brush().color() == POWER
    assert item.port_items[port.key].brush().color() != CONNECTED


def test_contradictory_same_gpio_aliases_are_preserved_and_warned(app):
    component = ElectricalComponent.model_validate(dict(
        id="legacy_uno", name="Old UNO", kind="mcu", catalog_id="arduino_uno_r3",
        a="VCC", b="GND", rated_voltage_v=5, rated_current_a=.1,
        signal_pins={"A4": "FIRST_NET", "SDA": "OTHER_NET"},
    ))
    item = CircuitComponentItem(component)
    for key, node in (("A4", "FIRST_NET"), ("SDA", "OTHER_NET")):
        port = item.ports[f"pin:{key}"]
        assert port.node == node
        assert port.legacy and not port.physical
        assert port.connectable  # User can repair the alias assignment.
        assert port.label.endswith(" *")
        assert item.port_items[port.key].brush().color() == POWER


def test_terminal_click_and_drag_emit_component_and_real_terminal(app):
    item = CircuitComponentItem(board(signal_pins={"GPIO2": "SDA"}))
    scene = QGraphicsScene()
    scene.addItem(item)
    scene.setSceneRect(-40, -40, 400, 330)
    view = QGraphicsView(scene)
    view.resize(450, 350)
    view.show()
    app.processEvents()
    clicks = []
    moves = []
    item.portClicked.connect(lambda component, terminal: clicks.append((component, terminal)))
    item.positionChanged.connect(lambda component, point: moves.append((component, point)))
    point = view.mapFromScene(item.port_scene_position("pin:GPIO2"))
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert clicks == [("controller", "pin:GPIO2")]
    item.setPos(10, 20)
    assert moves[-1] == ("controller", QPointF(10, 20))
    assert item.port_scene_position("pin:GPIO2") == item.pin_positions["pin:GPIO2"] + QPointF(10, 20)
    assert item.isSelected()
    view.close()


@pytest.mark.parametrize("catalog,key,node", [
    ("pololu_2130", "VIN", "MOTOR_POWER"),
    ("ams_as5600_asot", "SDA", "I2C_DATA"),
    ("pololu_4755", "ENCODER_A", "ENCODER_NET"),
    ("vishay_1n5819", "CATHODE", "RECTIFIER_K"),
])
def test_exact_products_expose_real_terminal_without_dc_short(app, catalog, key, node):
    component = ElectricalComponent.model_validate(dict(
        id="device", name="Exact product", kind="motor" if catalog == "pololu_4755" else "load",
        a="DC_A", b="DC_B", catalog_id=catalog, analysis_enabled=False,
        terminal_pins={key: node},
    ))
    item = CircuitComponentItem(component)
    assert item.product.catalog_id == catalog
    assert item.ports[f"port:{key}"].node == node
    assert item.port_scene_position(f"port:{key}") != item.port_scene_position("a")
    assert item.port_node("a") == "DC_A"
    assert item.port_node("b") == "DC_B"
    assert any(port.node is None for terminal, port in item.ports.items() if terminal.startswith("port:") and terminal != f"port:{key}")
    assert item.source_url.startswith("https://")


def test_unknown_board_keeps_manual_ports_without_invented_physical_pinout(app):
    component = ElectricalComponent.model_validate(dict(
        id="custom", name="Custom board", kind="mcu", a="VCC", b="GND",
        rated_voltage_v=5, rated_current_a=.1, signal_pins={"USER_TX": "SERIAL"},
    ))
    item = CircuitComponentItem(component)
    assert item.board is None
    assert set(item.ports) == {"a", "b", "pin:USER_TX"}
    assert not item.ports["pin:USER_TX"].physical
    assert item.ports["pin:USER_TX"].node == "SERIAL"
    assert not item.source_url


def test_symbols_draw_distinct_native_vectors_for_supported_circuit_kinds(app):
    hashes = set()
    for kind in ("battery", "resistor", "switch", "motor", "load", "wire"):
        component = ElectricalComponent.model_validate(dict(
            id="part", name="Circuit part", kind=kind, a="A_NET", b="B_NET",
            voltage_v=12, resistance_ohm=470, rated_voltage_v=12, rated_current_a=.2,
            length_mm=100, cross_section_mm2=.5,
        ))
        item = CircuitComponentItem(component)
        image = QImage(220, 150, QImage.Format.Format_ARGB32)
        image.fill(0xffffffff)
        painter = QPainter(image)
        scene = QGraphicsScene()
        scene.addItem(item)
        scene.render(painter, QRectF(0, 0, 220, 150), scene.itemsBoundingRect())
        painter.end()
        data = bytes(image.constBits())
        assert len(set(data)) > 30
        hashes.add(hashlib.sha256(data).digest())
    assert len(hashes) == 6
