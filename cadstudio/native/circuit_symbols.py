"""Small, movable circuit components with explicit, clickable terminals.

These are electrical symbols and logical connector drawings, not measured PCB
footprints. The DC operating-point terminals ``a``/``b`` stay separate from
manufacturer physical pins: an unassigned pin never inherits a board rail.
Each component is one vector item; only its interactive ports are child items.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsItem, QGraphicsObject

from ..board_pins import board_pinout
from ..electrical import ElectricalComponent
from ..mcu_connections import pin_aliases
from ..product_diagrams import product_diagram


@dataclass(frozen=True, slots=True)
class CircuitPort:
    key: str
    label: str
    node: str | None
    kind: str
    side: str
    physical: bool = False
    connectable: bool = True
    legacy: bool = False
    functions: tuple[str, ...] = ()


INK = QColor("#243346")
MUTED = QColor("#6E7D90")
CONNECTED = QColor("#168779")
SIGNAL = QColor("#507AA2")
POWER = QColor("#BF8722")
SELECTED = QColor("#2675CE")


class _PortItem(QGraphicsEllipseItem):
    """A generous mouse target around a terminal, independent of item dragging."""

    def __init__(self, owner: "CircuitComponentItem", port: CircuitPort, position: QPointF):
        super().__init__(-6, -6, 12, 12, owner)
        self.owner = owner
        self.port = port
        self.setPos(position)
        self.setZValue(4)
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setData(0, port.key)
        self._color = (POWER if port.legacy or port.kind in ("power", "ground")
                       else SIGNAL)
        connected_color = self._color if port.legacy else CONNECTED
        self.setPen(QPen(connected_color if port.node else self._color, 1.8))
        self.setBrush(connected_color if port.node else QColor("#FFFFFF"))
        status = port.node or owner.word("미연결", "Unconnected")
        details = "\n".join(port.functions)
        if not port.connectable:
            details += "\n" + owner.word(
                "물리 전원/참조 핀입니다. DC 전원 단자와 자동 연결되지 않습니다.",
                "Physical power/reference pin. Not automatically tied to the DC power terminals.",
            )
        if port.legacy:
            details += "\n" + owner.word(
                "기존 수동 연결 · 확인 필요. 제조사 물리 핀으로 확인되지 않았습니다.",
                "Legacy manual connection · verification required; not a verified physical pin assignment.",
            )
        self.setToolTip(f"{owner.component.name} · {port.label}\n{status}\n{details}".strip())

    def mousePressEvent(self, event):
        self.owner.setSelected(True)
        self.owner.portClicked.emit(self.owner.component.id, self.port.key)
        event.accept()

    def hoverEnterEvent(self, event):
        self.setPen(QPen(SELECTED, 2.5))
        self.setScale(1.25)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setPen(QPen(self._color if self.port.legacy or not self.port.node else CONNECTED, 1.8))
        self.setScale(1)
        super().hoverLeaveEvent(event)


class CircuitComponentItem(QGraphicsObject):
    """A compact circuit symbol and the ports used by a wiring scene.

    ``ports``/``pin_positions`` describe visible terminals; ``all_ports`` also
    includes hidden reference pins. Compact mode retains every saved mapping,
    with a few real signal pins for discovery. ``show_all_pins`` expands the
    selected item without discarding its position or existing connections.
    Positions in this item are schematic display coordinates only.
    """

    portClicked = Signal(str, str)
    positionChanged = Signal(str, QPointF)
    geometryChanged = Signal(str)
    activated = Signal(str)

    def __init__(self, component: ElectricalComponent | dict, *, english=False,
                 compact=True, parent=None):
        super().__init__(parent)
        self.component = ElectricalComponent.model_validate(
            component.model_dump() if isinstance(component, ElectricalComponent) else component
        ).model_copy(deep=True)
        self.english = english
        self.compact = compact
        self.board = board_pinout(self.component.catalog_id) if self.component.kind == "mcu" else None
        self.product = product_diagram(self.component.catalog_id)
        reference = self.board or self.product
        self.source_url = reference.source_url if reference else self.component.source_url
        self.all_ports = self._ports()
        self.ports: dict[str, CircuitPort] = {}
        self.pin_positions: dict[str, QPointF] = {}
        self.port_items: dict[str, _PortItem] = {}
        self.body_rect = QRectF()
        self._bounds = QRectF()
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                      | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                      | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setZValue(2)
        self.setData(0, self.component.id)
        note = (reference.note_en if english else reference.note) if reference else self.word(
            "사용자 회로 기호입니다. 물리 핀 배치는 확인되지 않았습니다.",
            "Custom circuit symbol; no verified physical pin arrangement.",
        )
        self.setToolTip(f"{self.component.name}\n{self.component.catalog_id}\n{note}\n{self.source_url}".strip())
        self._layout()

    def word(self, ko: str, en: str) -> str:
        return en if self.english else ko

    def _ports(self) -> dict[str, CircuitPort]:
        component = self.component
        a_label, b_label = ("+", "−") if component.kind == "battery" else ("A", "B")
        if component.kind == "mcu":
            a_label, b_label = "DC VCC", "DC GND"
        elif self.product:
            a_label, b_label = "DC A", "DC B"
        result = {
            "a": CircuitPort("a", a_label, component.a, "power", "left"),
            "b": CircuitPort("b", b_label, component.b, "power", "right"),
        }
        known = self.board.pins if self.board else self.product.terminals if self.product else ()
        mappings = component.signal_pins if component.kind == "mcu" else component.terminal_pins
        prefix = "pin:" if component.kind == "mcu" else "port:"
        for pin in known:
            node = mappings.get(pin.key)
            legacy = bool(self.board and pin.kind != "signal" and node is not None)
            if self.board and pin.kind == "signal":
                values = {mappings[alias] for alias in pin_aliases(component, pin.key) if alias in mappings}
                if len(values) == 1:
                    node = next(iter(values))
                elif len(values) > 1:
                    legacy = True
            key = prefix + pin.key
            result[key] = CircuitPort(key, pin.label + (" *" if legacy else ""), node, pin.kind, pin.side,
                                      physical=not legacy, connectable=not self.board or pin.kind == "signal",
                                      legacy=legacy, functions=pin.functions)
        known_keys = {pin.key for pin in known}
        for index, (key, node) in enumerate(mappings.items()):
            if key not in known_keys:
                result[prefix + key] = CircuitPort(prefix + key, key, node, "signal",
                                                   "left" if index % 2 == 0 else "right",
                                                   legacy=bool(known))
        return result

    def _visible_ports(self) -> dict[str, CircuitPort]:
        if not self.compact:
            return dict(self.all_ports)
        # Products generally have a small connector, so show all known ports.
        # Boards can have more than 80 pins: preserve every assigned connector,
        # then expose a few real ports. No decorative/invented GPIOs are added.
        if self.product and not self.board and len(self.all_ports) <= 14:
            return dict(self.all_ports)
        visible = {key: port for key, port in self.all_ports.items()
                   if key in ("a", "b") or port.node is not None}
        if self.board or self.product:
            if self.product:
                examples = [port for port in self.all_ports.values() if port.physical
                            and port.kind in ("power", "ground")]
                examples = [port for port in examples
                            if sum(other.side == port.side and other.kind in ("power", "ground")
                                   for other in examples[:examples.index(port)]) < 3]
                examples += [port for port in self.all_ports.values() if port.physical and port.connectable
                             and any("PWM" in function for function in port.functions)]
            else:
                examples = []
            examples += [port for port in self.all_ports.values()
                        if port.physical and port.connectable
                        and any("I2C" in function or "UART" in function for function in port.functions)]
            examples += [port for port in self.all_ports.values() if port.physical and port.connectable]
            for port in examples:
                if len(visible) >= 10:
                    break
                if sum(item.physical and item.side == port.side for item in visible.values()) >= 4:
                    continue
                visible.setdefault(port.key, port)
        return {key: port for key, port in self.all_ports.items() if key in visible}

    def _layout(self):
        self.prepareGeometryChange()
        for child in self.port_items.values():
            if child.scene() is not None:
                child.scene().removeItem(child)
            child.setParentItem(None)
        self.port_items = {}
        self.ports = self._visible_ports()
        self.pin_positions = {}
        complex_symbol = self.component.kind == "mcu" or self.product is not None or len(self.ports) > 2
        width = 280.0 if complex_symbol else 180.0
        physical = [port for key, port in self.ports.items() if key not in ("a", "b")]
        rows = max(sum(port.side == side for port in physical) for side in ("left", "right"))
        height = max(154.0 if complex_symbol else 126.0, 108 + max(0, rows - 1) * 18 + 38)
        self.body_rect = QRectF(18, 32, width - 36, height - 52)
        self._bounds = QRectF(-9, -3, width + 18, height + 8)
        self.pin_positions.update(a=QPointF(0, 72), b=QPointF(width, 72))
        counters = {"left": 0, "right": 0}
        for port in physical:
            self.pin_positions[port.key] = QPointF(0 if port.side == "left" else width,
                                                   108 + counters[port.side] * 18)
            counters[port.side] += 1
        for key, port in self.ports.items():
            self.port_items[key] = _PortItem(self, port, self.pin_positions[key])
        self.update()

    def show_all_pins(self, show=True):
        compact = not show
        if compact == self.compact:
            return
        self.compact = compact
        self._layout()
        self.geometryChanged.emit(self.component.id)

    @property
    def expanded(self) -> bool:
        return not self.compact

    def port_scene_position(self, key: str) -> QPointF:
        return self.mapToScene(self.pin_positions[key])

    def port_node(self, key: str) -> str | None:
        return self.all_ports[key].node

    def boundingRect(self) -> QRectF:
        return self._bounds

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.positionChanged.emit(self.component.id, QPointF(value))
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        self.activated.emit(self.component.id)
        event.accept()

    def _text(self, painter: QPainter, value: str, rect: QRectF, *, size=8.4,
              color=INK, bold=False, align=Qt.AlignmentFlag.AlignLeft):
        font = QFont("Segoe UI")
        font.setPointSizeF(size)
        font.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(color)
        text = QFontMetricsF(painter.font()).elidedText(value, Qt.TextElideMode.ElideRight, int(rect.width()))
        painter.drawText(rect, align | Qt.AlignmentFlag.AlignVCenter, text)

    def _ratings(self) -> str:
        component = self.component
        if component.kind == "battery":
            return f"{component.voltage_v:g} V · " + ("ON" if component.closed else "OFF")
        if component.kind == "resistor":
            return f"{component.resistance_ohm:g} Ω"
        if component.kind == "wire":
            return f"{component.length_mm:g} mm · {component.cross_section_mm2:g} mm²"
        if component.kind == "switch":
            return self.word("닫힘", "Closed") if component.closed else self.word("열림", "Open")
        if not component.analysis_enabled:
            return self.word("단자 결선 · DC 정격 미설정", "Terminal wiring · DC ratings pending")
        return f"{component.rated_voltage_v:g} V · {component.rated_current_a:g} A"

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self._bounds.width() - 18
        height = self._bounds.height() - 8
        component = self.component
        complex_symbol = component.kind == "mcu" or self.product is not None or len(self.ports) > 2
        painter.setPen(QPen(SELECTED if self.isSelected() else QColor("#A4B4C3"), 2 if self.isSelected() else 1.25))
        painter.setBrush(QColor("#E8F2ED") if component.kind == "mcu" else QColor("#FFFFFF"))
        if complex_symbol:
            painter.drawRoundedRect(self.body_rect, 8, 8)
        elif self.isSelected():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(10, 31, width - 20, 70), 6, 6)
        self._text(painter, component.name, QRectF(8, 0, width - 16, 25), size=10, bold=True)
        reference = self.board or self.product
        if reference:
            self._text(painter, reference.model, QRectF(25, 34, width - 50, 22), size=7.8, color=MUTED)
        painter.setPen(QPen(INK, 1.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cy = 72
        cx = width / 2
        if component.kind == "mcu":
            # A miniature logical board/chip drawing, with explicit DC power
            # stubs. It is not a dimensional board outline or pad placement.
            painter.drawLine(QPointF(0, cy), QPointF(58, cy))
            painter.drawLine(QPointF(width - 58, cy), QPointF(width, cy))
            painter.setBrush(QColor("#49675C"))
            painter.drawRoundedRect(QRectF(cx - 24, 62, 48, 32), 3, 3)
            for offset in (-14, -4, 6, 16):
                painter.drawLine(QPointF(cx + offset, 58), QPointF(cx + offset, 62))
                painter.drawLine(QPointF(cx + offset, 94), QPointF(cx + offset, 98))
            is_mpu = component.catalog_id in ("rpi3bplus", "rpi4b")
            self._text(painter, "MPU" if is_mpu else "MCU", QRectF(cx - 22, 65, 44, 26),
                       size=8, color=QColor("#FFFFFF"), bold=True, align=Qt.AlignmentFlag.AlignCenter)
        elif self.product:
            painter.drawLine(QPointF(0, cy), QPointF(18, cy))
            painter.drawLine(QPointF(width - 18, cy), QPointF(width, cy))
            self._device_symbol(painter, cx, cy)
        else:
            self._simple_symbol(painter, cx, cy, width)
        for key, port in self.ports.items():
            point = self.pin_positions[key]
            left = port.side == "left"
            port_color = POWER if port.legacy else CONNECTED if port.node else POWER if port.kind in ("power", "ground") else SIGNAL
            painter.setPen(QPen(port_color, 1.5))
            if key not in ("a", "b"):
                painter.drawLine(point, QPointF(18 if left else width - 18, point.y()))
            label = port.label
            if key in ("a", "b") and not complex_symbol:
                self._text(painter, label, QRectF(8 if left else width - 36, 47, 28, 19), size=8.5, bold=True)
            else:
                # Connector coordinate and actual pin name stay visible.
                self._text(painter, label, QRectF(25 if left else width / 2 + 3, point.y() - 10,
                                                 width / 2 - 28, 20), size=7.6,
                           color=POWER if port.legacy else CONNECTED if port.node else MUTED,
                           align=Qt.AlignmentFlag.AlignLeft if left else Qt.AlignmentFlag.AlignRight)
        self._text(painter, self._ratings(), QRectF(9, height - 19, width - 18, 18),
                   size=7.8, color=MUTED, align=Qt.AlignmentFlag.AlignCenter)
        hidden = len(self.all_ports) - len(self.ports)
        if hidden:
            self._text(painter, self.word(f"핀 +{hidden}", f"+{hidden} pins"),
                       QRectF(width - 90, 87, 65, 18), size=7, color=MUTED,
                       align=Qt.AlignmentFlag.AlignRight)

    def _simple_symbol(self, painter: QPainter, cx: float, cy: float, width: float):
        kind = self.component.kind
        painter.setPen(QPen(INK, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(QPointF(0, cy), QPointF(cx - 30, cy))
        painter.drawLine(QPointF(cx + 30, cy), QPointF(width, cy))
        if kind == "battery":
            painter.drawLine(QPointF(cx - 30, cy), QPointF(cx - 7, cy))
            painter.drawLine(QPointF(cx + 6, cy), QPointF(cx + 30, cy))
            painter.drawLine(QPointF(cx - 7, cy - 23), QPointF(cx - 7, cy + 23))
            painter.drawLine(QPointF(cx + 6, cy - 12), QPointF(cx + 6, cy + 12))
            if not self.component.closed:
                painter.setPen(QPen(QColor("#C75858"), 2))
                painter.drawLine(QPointF(cx - 16, cy - 25), QPointF(cx + 17, cy + 25))
        elif kind == "resistor":
            painter.drawRect(QRectF(cx - 30, cy - 11, 60, 22))
        elif kind == "wire":
            if self.component.closed:
                painter.drawLine(QPointF(cx - 30, cy), QPointF(cx + 30, cy))
            else:
                painter.drawLine(QPointF(cx - 30, cy), QPointF(cx - 8, cy))
                painter.drawLine(QPointF(cx + 8, cy), QPointF(cx + 30, cy))
                painter.setPen(QPen(QColor("#C75858"), 2))
                painter.drawLine(QPointF(cx - 5, cy + 9), QPointF(cx + 5, cy - 9))
        elif kind == "switch":
            painter.drawEllipse(QPointF(cx - 25, cy), 3, 3)
            painter.drawEllipse(QPointF(cx + 25, cy), 3, 3)
            painter.drawLine(QPointF(cx - 30, cy), QPointF(cx - 25, cy))
            painter.drawLine(QPointF(cx + 25, cy), QPointF(cx + 30, cy))
            painter.drawLine(QPointF(cx - 25, cy), QPointF(cx + 25, cy if self.component.closed else cy - 22))
        elif kind == "motor":
            painter.drawEllipse(QPointF(cx, cy), 28, 28)
            self._text(painter, "M", QRectF(cx - 25, cy - 22, 50, 44), size=18,
                       bold=True, align=Qt.AlignmentFlag.AlignCenter)
        else:
            painter.drawRoundedRect(QRectF(cx - 30, cy - 19, 60, 38), 4, 4)
            self._text(painter, self.word("부하", "LOAD"), QRectF(cx - 26, cy - 17, 52, 34),
                       size=9, bold=True, align=Qt.AlignmentFlag.AlignCenter)

    def _device_symbol(self, painter: QPainter, cx: float, cy: float):
        """Distinct supported product identities without inventing internals."""
        painter.setPen(QPen(INK, 1.6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        catalog = self.component.catalog_id
        if catalog == "vishay_1n5819":
            # Anode left, cathode bar right. Leads are explicit physical ports
            # below; this symbol is not silently tied to abstract DC A/B.
            painter.drawPolygon(QPolygonF([QPointF(cx - 16, cy - 15), QPointF(cx - 16, cy + 15), QPointF(cx + 13, cy)]))
            painter.drawLine(QPointF(cx + 15, cy - 17), QPointF(cx + 15, cy + 17))
        elif catalog == "pololu_4755" or self.component.kind == "motor":
            painter.drawEllipse(QPointF(cx, cy + 4), 19, 19)
            self._text(painter, "M", QRectF(cx - 16, cy - 13, 32, 34), size=12,
                       bold=True, align=Qt.AlignmentFlag.AlignCenter)
            painter.drawRect(QRectF(cx + 19, cy - 5, 23, 18))
            painter.drawLine(QPointF(cx + 42, cy + 4), QPointF(cx + 49, cy + 4))
        else:
            painter.drawRoundedRect(QRectF(cx - 27, cy - 10, 54, 30), 3, 3)
            for offset in (-18, -6, 6, 18):
                painter.drawLine(QPointF(cx + offset, cy - 15), QPointF(cx + offset, cy - 10))
                painter.drawLine(QPointF(cx + offset, cy + 20), QPointF(cx + offset, cy + 25))
            label = "ESC" if catalog == "st_b_g431b_esc1" else "DRV" if catalog == "pololu_2130" else "ENC" if catalog == "ams_as5600_asot" else "IC"
            self._text(painter, label, QRectF(cx - 24, cy - 6, 48, 23), size=9,
                       bold=True, align=Qt.AlignmentFlag.AlignCenter)
