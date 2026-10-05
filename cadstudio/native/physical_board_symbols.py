"""Source-backed board wiring illustrations, separate from schematic symbols.

The Raspberry Pi header keeps its actual 40 socket identities and two-column
order. The vector board outline is an illustration, not a dimensional footprint.
Other boards/products keep verified connector names but explicitly use logical
placement. No pictured chip, connector or touching wire creates a net.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication

from .circuit_symbols import (
    CircuitComponentItem, CircuitPort, _PortItem,
    CONNECTED, INK, MUTED, POWER, SELECTED, SIGNAL,
)


class PhysicalComponentItem(CircuitComponentItem):
    """Movable native vector illustration with clickable source-backed pins.

    ``supply:KEY`` is an explicitly assigned manufacturer supply socket;
    ``pin:KEY`` is a GPIO/reference or a preserved legacy manual mapping.
    Abstract DC ``a``/``b`` stay visibly separate. All 40 Raspberry Pi sockets
    remain visible in compact mode; expansion adds function labels only.
    """

    PI_MODELS = frozenset(("rpi3bplus", "rpi4b"))

    def __init__(self, component, english=False, compact=True, parent=None):
        self._press_screen = None
        self._press_position = None
        self._body_dragged = False
        super().__init__(component, english=english, compact=compact, parent=parent)
        if self.board and self.component.catalog_id in self.PI_MODELS:
            note = self.word(
                "J8 40핀 번호·홀짝 열은 공식 자료 기준입니다. 보드 그림의 치수와 커넥터 외형은 설명용입니다.",
                "Official J8 40-pin numbers and odd/even columns; board dimensions and connector artwork are illustrative.",
            )
        else:
            note = self.word(
                "단자 이름은 확인된 자료를 사용하며, 그림상의 커넥터 위치는 미검증 모식 배치입니다.",
                "Verified terminal names where available; connector positions are an unverified logical arrangement.",
            )
        self.setToolTip(self.toolTip() + "\n" + note)

    def _ports(self):
        ports = super()._ports()
        if not self.board:
            return ports
        for pin in self.board.pins:
            if pin.kind not in ("power", "ground"):
                continue
            old_key = "pin:" + pin.key
            old = ports.pop(old_key)
            # Preserve an old manual signal-map entry as a warning. It does
            # not become an assignment of the newly editable physical pad.
            if old.node is not None:
                ports[old_key] = old
            key = "supply:" + pin.key
            ports[key] = CircuitPort(
                key, pin.label, self.component.board_supply_pins.get(pin.key),
                pin.kind, pin.side, physical=True, connectable=True,
                functions=pin.functions,
            )
        return ports

    def _visible_ports(self):
        # Hiding an unassigned socket would make physical wiring misleading.
        # Logical fallbacks also retain every verified or saved terminal.
        return dict(self.all_ports)

    def _layout(self):
        if not self.board or self.component.catalog_id not in self.PI_MODELS:
            super()._layout()
            self._logical_note_y = self._bounds.height() - 27
            self._bounds.setHeight(self._bounds.height() + 17)
            return
        self.prepareGeometryChange()
        for child in self.port_items.values():
            if child.scene() is not None:
                child.scene().removeItem(child)
            child.setParentItem(None)
        self.port_items = {}
        self.ports = self._visible_ports()
        self.pin_positions = {"a": QPointF(0, 37), "b": QPointF(350, 37)}
        self.body_rect = QRectF(18, 62, 314, 410)
        self._bounds = QRectF(-10, -4, 370, 503)
        actual_keys = {"a", "b"}
        for pin in self.board.pins:
            prefix = "supply:" if pin.kind in ("power", "ground") else "pin:"
            key = prefix + pin.key
            # The data record supplies the physical odd/even column and row.
            self.pin_positions[key] = QPointF(228 if pin.side == "left" else 250,
                                               94 + pin.position * 18)
            actual_keys.add(key)
        extra = [key for key in self.ports if key not in actual_keys]
        for index, key in enumerate(extra):
            port = self.ports[key]
            row = index // 2
            self.pin_positions[key] = QPointF(0 if port.side == "left" else 350,
                                               514 + row * 22)
        if extra:
            self._bounds.setBottom(538 + ((len(extra) - 1) // 2) * 22)
        for key, port in self.ports.items():
            self.port_items[key] = _PortItem(self, port, self.pin_positions[key])
        self.update()

    def mousePressEvent(self, event):
        self._press_screen = event.screenPos() if event.button() == Qt.MouseButton.LeftButton else None
        self._press_position = QPointF(self.pos())
        self._body_dragged = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_screen is not None:
            delta = event.screenPos() - self._press_screen
            if delta.manhattanLength() >= QApplication.startDragDistance():
                self._body_dragged = True
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        clicked = (
            event.button() == Qt.MouseButton.LeftButton
            and self._press_screen is not None
            and not self._body_dragged
            and self._press_position == self.pos()
        )
        super().mouseReleaseEvent(event)
        self._press_screen = None
        if clicked:
            self.activated.emit(self.component.id)

    def mouseDoubleClickEvent(self, event):
        # A stationary first click already activates the physical component.
        event.accept()

    def _pin_label(self, key):
        port = self.ports[key]
        if self.compact:
            return port.label.replace("J8.", "").replace(" · ", " ")
        functions = [value for value in port.functions
                     if value not in ("GPIO", "GND") and not value.endswith("rail")]
        suffix = functions[0].replace(" (HAT EEPROM)", "") if functions else ""
        return port.label.replace("J8.", "").replace(" · ", " ") + (" " + suffix if suffix else "")

    def paint(self, painter: QPainter, option, widget=None):
        if not self.board or self.component.catalog_id not in self.PI_MODELS:
            super().paint(painter, option, widget)
            # Source-backed terminals do not imply source-backed artwork.
            self._text(painter, self.word("단자 배치 모식도", "Logical connector placement"),
                       QRectF(20, self._logical_note_y, self.body_rect.width() - 4, 16),
                       size=6.5, color=MUTED, align=Qt.AlignmentFlag.AlignCenter)
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._text(painter, self.component.name, QRectF(8, 0, 334, 24), size=10, bold=True)
        painter.setPen(QPen(SELECTED if self.isSelected() else QColor("#195E43"),
                            2.6 if self.isSelected() else 1.5))
        painter.setBrush(QColor("#23764F"))
        painter.drawRoundedRect(self.body_rect, 9, 9)
        self._text(painter, self.board.model, QRectF(29, 65, 291, 19), size=8.2,
                   color=QColor("#F6FFF7"), bold=True)
        # Illustrative holes and packages carry no electrical identity.
        painter.setPen(QPen(QColor("#D0DCB9"), 1))
        painter.setBrush(QColor("#122D25"))
        for point in (QPointF(31, 91), QPointF(319, 91), QPointF(31, 458), QPointF(319, 458)):
            painter.drawEllipse(point, 4, 4)
        self._chip(painter, QRectF(49, 217, 58, 76), "MPU")
        self._chip(painter, QRectF(47, 345, 54, 38), "RAM", size=7)
        # Physical pin locations and order are represented independently of
        # the approximate decorative PCB connector drawings.
        painter.setPen(QPen(QColor("#242A24"), 1.2))
        painter.setBrush(QColor("#232A23"))
        painter.drawRoundedRect(QRectF(217, 85, 44, 362), 3, 3)
        self._text(painter, "J8", QRectF(217, 448, 45, 18), size=7.2,
                   color=QColor("#EAF3D8"), bold=True, align=Qt.AlignmentFlag.AlignCenter)
        is_four = self.component.catalog_id == "rpi4b"
        self._connector(painter, QRectF(43, 428, 48, 37), "USB", "#367CBA" if is_four else "#384147")
        self._connector(painter, QRectF(97, 428, 48, 37), "USB", "#384147")
        self._connector(painter, QRectF(157, 427, 52, 38), "ETH", "#58616B")
        self._connector(painter, QRectF(19, 135, 20, 28), "PWR", "#68747A", size=5.3)
        self._connector(painter, QRectF(19, 176, 20, 18 if is_four else 33), "HDMI", "#68747A", size=5.0)
        if is_four:
            self._connector(painter, QRectF(19, 199, 20, 18), "HDMI", "#68747A", size=5.0)
        painter.setPen(QPen(QColor("#AFD59E"), 1.1))
        painter.setBrush(QColor("#D5DCBD"))
        painter.drawRect(QRectF(44, 397, 61, 13))
        self._text(painter, self.word("외형 설명용", "Illustration"), QRectF(40, 94, 78, 18),
                   size=6.3, color=QColor("#D6ECD9"))
        for key, port in self.ports.items():
            point = self.pin_positions[key]
            color = POWER if port.legacy or port.kind in ("power", "ground") else CONNECTED if port.node else SIGNAL
            if key in ("a", "b"):
                painter.setPen(QPen(color, 1.5, Qt.PenStyle.DashLine))
                painter.drawLine(point, QPointF(48 if key == "a" else 302, 37))
                self._text(painter, port.label, QRectF(54 if key == "a" else 198, 42, 98, 16),
                           size=7.1, color=POWER,
                           align=Qt.AlignmentFlag.AlignLeft if key == "a" else Qt.AlignmentFlag.AlignRight)
            elif point.y() < 500:
                left = port.side == "left"
                # Route leads leave horizontally at the pad center. Keep all
                # labels above that line so mixed assigned/unassigned rows do
                # not overlap each other or have wires drawn through the text.
                rect = QRectF(120 if left else 260, point.y() - 16, 98 if left else 66, 12)
                self._text(painter, self._pin_label(key), rect, size=6.8 if self.compact else 6.1,
                           color=QColor("#FFF6BA") if port.kind in ("power", "ground") else QColor("#F4FFF7"),
                           align=Qt.AlignmentFlag.AlignRight if left else Qt.AlignmentFlag.AlignLeft)
            else:
                self._text(painter, port.label, QRectF(12 if port.side == "left" else 179,
                                                       point.y() - 9, 159, 18), size=7, color=color,
                           align=Qt.AlignmentFlag.AlignLeft if port.side == "left" else Qt.AlignmentFlag.AlignRight)
        self._text(painter, self._ratings(), QRectF(15, 475, 320, 18), size=7.5, color=MUTED,
                   align=Qt.AlignmentFlag.AlignCenter)

    def _chip(self, painter, rect, label, size=9):
        painter.setPen(QPen(QColor("#1B2822"), 1.2))
        painter.setBrush(QColor("#25312C"))
        painter.drawRoundedRect(rect, 3, 3)
        for offset in range(8, int(rect.height()) - 4, 8):
            painter.setPen(QPen(QColor("#B2BBAF"), 1.4))
            painter.drawLine(QPointF(rect.left() - 4, rect.top() + offset), QPointF(rect.left(), rect.top() + offset))
            painter.drawLine(QPointF(rect.right(), rect.top() + offset), QPointF(rect.right() + 4, rect.top() + offset))
        self._text(painter, label, rect.adjusted(3, 3, -3, -3), size=size, bold=True,
                   color=QColor("#D4DDD0"), align=Qt.AlignmentFlag.AlignCenter)

    def _connector(self, painter, rect, label, fill, size=6.5):
        painter.setPen(QPen(QColor("#C3CBD0"), 1.2))
        painter.setBrush(QColor(fill))
        painter.drawRect(rect)
        self._text(painter, label, rect.adjusted(1, 1, -1, -1), size=size,
                   color=QColor("#F0F5F7"), bold=True, align=Qt.AlignmentFlag.AlignCenter)
