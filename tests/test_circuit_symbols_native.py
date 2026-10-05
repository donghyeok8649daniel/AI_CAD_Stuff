"""Circuit symbols preserve real terminal identity while remaining interactive."""

import hashlib

import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsView

from cadstudio.electrical import ElectricalComponent
from cadstudio.native.circuit_symbols import CircuitComponentItem, CONNECTED, POWER, _engineering_value
from cadstudio.native.physical_board_symbols import PhysicalComponentItem


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
    for kind in ("battery", "resistor", "capacitor", "inductor", "switch", "motor", "actuator", "load", "wire"):
        component = ElectricalComponent.model_validate(dict(
            id="part", name="Circuit part", kind=kind, a="A_NET", b="B_NET",
            voltage_v=12, resistance_ohm=470, rated_voltage_v=12, rated_current_a=.2,
            length_mm=100, cross_section_mm2=.5,
            capacitance_f=100e-6 if kind == "capacitor" else 0,
            inductance_h=10e-3 if kind == "inductor" else 0,
            winding_resistance_ohm=2 if kind == "inductor" else 0,
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
    assert len(hashes) == 9


@pytest.mark.parametrize("item_type", [CircuitComponentItem, PhysicalComponentItem])
def test_passive_and_actuator_symbols_are_distinct_at_the_actual_wiring_anchors(app, item_type):
    symbol_hashes = {}
    for kind in ("capacitor", "inductor", "actuator", "resistor", "motor", "load"):
        component = ElectricalComponent.model_validate(dict(
            id="device", name="Same device", kind=kind, a="POSITIVE", b="RETURN",
            capacitance_f=100e-6 if kind == "capacitor" else 0,
            inductance_h=10e-3 if kind == "inductor" else 0,
            winding_resistance_ohm=2 if kind == "inductor" else 0,
            resistance_ohm=470, rated_voltage_v=12, rated_current_a=.8,
        ))
        before = component.model_dump()
        item = item_type(component)
        scene = QGraphicsScene()
        scene.addItem(item)
        assert item.port_scene_position("a") == QPointF(0, 72)
        assert item.port_scene_position("b") == QPointF(180, 72)
        assert set(item.ports) == {"a", "b"}
        assert item.ports["a"].node == "POSITIVE" and item.ports["b"].node == "RETURN"
        for key in ("a", "b"):
            assert item.port_items[key].pos() == item.pin_positions[key]
            assert item.boundingRect().contains(item.pin_positions[key])
        image = QImage(220, 200, QImage.Format.Format_ARGB32)
        image.fill(0xffffffff)
        painter = QPainter(image)
        item.paint(painter, None)
        painter.end()
        # Crop only the symbol, excluding the name and numeric rating so the
        # assertion verifies distinctive electrical artwork rather than text.
        body = image.copy(45, 43, 92, 58)
        symbol_hashes[kind] = hashlib.sha256(bytes(body.constBits())).hexdigest()
        item.setPos(23, 37)
        assert item.port_scene_position("a") == QPointF(23, 109)
        assert item.port_scene_position("b") == QPointF(203, 109)
        assert component.model_dump() == before
    assert len(set(symbol_hashes.values())) == 6


@pytest.mark.parametrize("item_type", [CircuitComponentItem, PhysicalComponentItem])
def test_polarized_capacitor_displays_real_polarity_without_claiming_a_supply(app, item_type):
    component = ElectricalComponent.model_validate(dict(
        id="capacitor", name="Filter capacitor", kind="capacitor", a="FILTER", b="GND",
        capacitance_f=100e-6, capacitor_polarized=True,
    ))
    item = item_type(component)
    assert item.ports["a"].label == "+" and item.ports["b"].label == "−"
    assert item.ports["a"].kind == "passive"
    assert item.ports["b"].kind == "passive"
    assert item._ratings() == "100 µF · DC 정상상태 개방"
    english = item_type(component, english=True)
    assert english._ratings() == "100 µF · DC steady-state open"
    image_hashes = []
    for polarized in (False, True):
        symbol = item_type(component.model_copy(update={"capacitor_polarized": polarized}))
        image = QImage(200, 150, QImage.Format.Format_ARGB32)
        image.fill(0xffffffff)
        painter = QPainter(image)
        symbol.paint(painter, None)
        painter.end()
        image_hashes.append(hashlib.sha256(bytes(image.copy(45, 43, 92, 58).constBits())).hexdigest())
    assert image_hashes[0] != image_hashes[1]


@pytest.mark.parametrize("value,unit,expected", [
    (100e-12, "F", "100 pF"), (22e-9, "F", "22 nF"), (4.7e-6, "F", "4.7 µF"),
    (2200e-6, "F", "2.2 mF"), (47e-6, "H", "47 µH"), (10e-3, "H", "10 mH"),
    (1.5, "H", "1.5 H"), (4700, "Ω", "4.7 kΩ"), (0.25, "Ω", "250 mΩ"),
])
def test_passive_engineering_units_remain_readable_without_zero_rounding(value, unit, expected):
    assert _engineering_value(value, unit) == expected
