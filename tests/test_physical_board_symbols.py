"""Physical illustrations expose verified pads without inventing nets."""

import hashlib

import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsView

from cadstudio.board_pins import board_pinout
from cadstudio.electrical import ElectricalComponent
from cadstudio.native.physical_board_symbols import PhysicalComponentItem


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    yield instance
    instance.processEvents()


def board(catalog_id="rpi4b", **fields):
    return ElectricalComponent.model_validate(dict(
        id="controller", name="Control board", kind="mcu", a="DC_POWER", b="DC_GND",
        catalog_id=catalog_id, analysis_enabled=False, **fields,
    ))


@pytest.mark.parametrize("catalog", ["rpi3bplus", "rpi4b"])
def test_all_forty_header_pads_keep_authoritative_two_column_order(app, catalog):
    item = PhysicalComponentItem(board(catalog))
    assert len(item.ports) == 42
    assert item.board.catalog_id == catalog
    for pin in board_pinout(catalog).pins:
        key = ("supply:" if pin.kind in ("power", "ground") else "pin:") + pin.key
        point = item.pin_positions[key]
        assert point.x() == (228 if pin.side == "left" else 250)
        assert point.y() == 94 + 18 * pin.position
        assert item.ports[key].label == pin.label
        assert item.ports[key].physical
    before = dict(item.pin_positions)
    item.show_all_pins(True)
    assert item.expanded and len(item.ports) == 42
    assert item.pin_positions == before
    item.show_all_pins(False)
    assert not item.expanded and item.pin_positions == before
    assert "공식 자료" in item.toolTip()


def test_supply_assignment_is_explicit_and_dc_terminals_do_not_assign_pads(app):
    original = board(board_supply_pins={"5V_2": "REAL_POWER"},
                     supply_pinout_catalog_id="rpi4b", signal_pins={"GPIO2": "DATA"})
    before = original.model_dump()
    item = PhysicalComponentItem(original)
    assert item.port_node("a") == "DC_POWER" and item.port_node("b") == "DC_GND"
    assert item.port_node("supply:5V_2") == "REAL_POWER"
    assert item.port_node("supply:5V_4") is None
    assert item.port_node("supply:GND_6") is None
    assert item.port_node("pin:GPIO2") == "DATA"
    assert item.ports["supply:5V_2"].connectable
    assert item.ports["supply:GND_6"].connectable
    assert not item.ports["pin:GPIO0"].connectable  # HAT EEPROM reference.
    assert item.pin_positions["a"].y() < item.body_rect.top()
    assert original.model_dump() == before


def test_legacy_power_signal_is_preserved_separately_from_real_power_pad(app):
    item = PhysicalComponentItem(board(signal_pins={"3V3_1": "OLD_MANUAL"}))
    legacy = item.ports["pin:3V3_1"]
    assert legacy.legacy and not legacy.physical and not legacy.connectable
    assert legacy.node == "OLD_MANUAL"
    assert item.ports["supply:3V3_1"].node is None
    assert item.ports["supply:3V3_1"].physical
    assert item.pin_positions["pin:3V3_1"].y() > item.body_rect.bottom()
    assert "기존 수동 연결 · 확인 필요" in item.port_items["pin:3V3_1"].toolTip()


def test_body_click_activates_but_pin_click_and_drag_do_not(app):
    item = PhysicalComponentItem(board())
    scene = QGraphicsScene()
    scene.addItem(item)
    view = QGraphicsView(scene)
    view.setSceneRect(-60, -40, 490, 630)
    view.resize(620, 720)
    view.show()
    app.processEvents()
    activated, clicked, moved = [], [], []
    item.activated.connect(activated.append)
    item.portClicked.connect(lambda *args: clicked.append(args))
    item.positionChanged.connect(lambda *args: moved.append(args))
    body_point = view.mapFromScene(item.mapToScene(QPointF(80, 180)))
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=body_point)
    assert activated == ["controller"]
    activated.clear()
    pin = view.mapFromScene(item.port_scene_position("supply:5V_2"))
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=pin)
    assert clicked == [("controller", "supply:5V_2")]
    assert activated == []
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=body_point)
    for offset in (QPoint(15, 8), QPoint(34, 17), QPoint(54, 24)):
        QTest.mouseMove(view.viewport(), body_point + offset, delay=15)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=body_point + QPoint(54, 24))
    assert moved
    assert item.pos() != QPointF()
    assert activated == []
    item.setPos(17, 29)
    assert item.port_scene_position("pin:GPIO2") == item.pin_positions["pin:GPIO2"] + QPointF(17, 29)
    view.close()


def test_exact_esc_has_named_connectors_and_manual_fallback_has_no_fake_pads(app):
    component = ElectricalComponent.model_validate(dict(
        id="esc", name="ESC", kind="load", a="DC_A", b="DC_B",
        catalog_id="st_b_g431b_esc1", analysis_enabled=False,
        terminal_pins={"MOTOR_U": "PHASE_U"},
    ))
    item = PhysicalComponentItem(component)
    assert len(item.ports) == 21
    assert item.product.catalog_id == "st_b_g431b_esc1"
    assert item.ports["port:MOTOR_U"].label == "J7 · U"
    assert item.port_node("port:MOTOR_U") == "PHASE_U"
    assert "미검증 모식 배치" in item.toolTip()
    custom = PhysicalComponentItem(board("custom_board", signal_pins={"CUSTOM_IN": "USER_NET"}))
    assert custom.board is None
    assert set(custom.ports) == {"a", "b", "pin:CUSTOM_IN"}
    assert not custom.ports["pin:CUSTOM_IN"].physical


def test_pi_models_render_distinct_vectors_with_header_and_no_external_assets(app):
    hashes = []
    for catalog in ("rpi3bplus", "rpi4b"):
        item = PhysicalComponentItem(board(catalog))
        scene = QGraphicsScene()
        scene.addItem(item)
        assert len(scene.items()) == 43  # One vector object and 42 terminals.
        image = QImage(400, 530, QImage.Format.Format_ARGB32)
        image.fill(0xffffffff)
        painter = QPainter(image)
        scene.render(painter, QRectF(0, 0, 400, 530), item.boundingRect())
        painter.end()
        pixels = bytes(image.constBits())
        assert len(set(pixels)) > 50
        hashes.append(hashlib.sha256(pixels).digest())
    assert hashes[0] != hashes[1]
