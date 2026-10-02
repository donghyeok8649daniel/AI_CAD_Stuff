"""Lightweight, read-only schematic of the saved electrical netlist.

The diagram is generated from node IDs and component endpoints. It is not a
PCB layout, a routed 3D cable, or a simulation of firmware and signal logic.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QApplication, QDialog, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QVBoxLayout

from ..electrical import ElectricalResult, ElectricalWorkspace
from .widgets import button, label


INK = QColor('#243346')
BUS = QColor('#7C91A6')
LIVE = QColor('#178F83')
OPEN = QColor('#D45757')
SOURCE = QColor('#D79424')
BACKGROUND = QColor('#F7F9FC')


class CircuitView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setBackgroundBrush(QBrush(BACKGROUND))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        event.accept()


class ElectricalSchematicDialog(QDialog):
    """Separate native window showing the actual modeled netlist connections."""

    def __init__(self, parent, workspace: ElectricalWorkspace | dict, result: ElectricalResult | dict | None = None):
        super().__init__(parent)
        self.setWindowTitle('전장 회로도 · 배선 연결 보기')
        self.resize(1050, 690)
        self.workspace = ElectricalWorkspace.model_validate(workspace)
        self.result = ElectricalResult.model_validate(result) if result is not None else None
        language = getattr(QApplication.instance(), 'cad_language', None)
        self.english = getattr(language, 'language', 'ko') == 'en'
        self.scene = QGraphicsScene(self)
        self.view = CircuitView(self.scene, self)
        self.view.setObjectName('electricalSchematicView')
        self.node_positions: dict[str, float] = {}
        self.branch_layout: dict[str, dict] = {}
        self.branch_items: dict[str, list] = {}

        layout = QVBoxLayout(self)
        layout.addWidget(label('읽기 전용 연결도 · 같은 노드 이름만 이어집니다. 교차선은 접점 표시가 있을 때만 연결됩니다.', True))
        controls = QHBoxLayout()
        controls.addWidget(button('전체 맞춤', self.fit_scene))
        controls.addWidget(button('확대', lambda: self.view.scale(1.25, 1.25)))
        controls.addWidget(button('축소', lambda: self.view.scale(.8, .8)))
        controls.addStretch(1)
        controls.addWidget(QLabel('드래그: 이동   휠: 커서 기준 확대/축소'))
        layout.addLayout(controls)
        layout.addWidget(self.view, 1)
        status = 'DC 계산 결과 표시' if self.result is not None else '회로 계산 미완료 · 연결과 입력값만 표시'
        layout.addWidget(label(status + ' · OFF 배터리와 단선된 전선은 전류를 공급하거나 전달하지 않습니다.', True))
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_row.addWidget(button('닫기', self.reject))
        layout.addLayout(close_row)
        self._draw()

    def showEvent(self, event):
        super().showEvent(event)
        self.fit_scene()

    def fit_scene(self):
        rect = self.scene.sceneRect()
        if not rect.isEmpty():
            self.view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def _pen(self, color: QColor, width=2, dashed=False):
        pen = QPen(color, width)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        return pen

    def _line(self, x1, y1, x2, y2, color=INK, width=2, dashed=False, tooltip=''):
        item = self.scene.addLine(x1, y1, x2, y2, self._pen(color, width, dashed))
        if tooltip:
            item.setToolTip(tooltip)
        return item

    def _word(self, korean, english):
        return english if self.english else korean

    def _text(self, text, x, y, color=INK, size=9, bold=False, max_width=None):
        font = QFont('Segoe UI', size, QFont.Weight.Bold if bold else QFont.Weight.Normal)
        shown = QFontMetrics(font).elidedText(str(text), Qt.TextElideMode.ElideRight, max_width) if max_width else str(text)
        item = self.scene.addText(shown, font)
        item.setDefaultTextColor(color)
        item.setPos(x, y)
        if shown != str(text):
            item.setToolTip(str(text))
        return item

    def _endpoint(self, x, y, color=LIVE):
        return self.scene.addEllipse(x - 4, y - 4, 8, 8, self._pen(color, 1), QBrush(color))

    def _symbol(self, component, x, y, color, active, tip, positive_left=True):
        """Draw one branch symbol centered at x, y; return its graphic items."""
        kind = component.kind
        items = []
        if kind == 'wire':
            if active:
                items.append(self._line(x - 25, y, x + 25, y, color, 3, tooltip=tip))
            else:
                items.extend((self._line(x - 25, y, x - 9, y, color, 3, tooltip=tip),
                              self._line(x + 9, y, x + 25, y, color, 3, tooltip=tip),
                              self._line(x - 6, y - 8, x + 6, y + 8, color, 2, tooltip=tip)))
        elif kind == 'switch':
            items.extend((self.scene.addEllipse(x - 27, y - 3, 6, 6, self._pen(color, 2), QBrush(BACKGROUND)),
                          self.scene.addEllipse(x + 21, y - 3, 6, 6, self._pen(color, 2), QBrush(BACKGROUND))))
            items.append(self._line(x - 24, y, x + 24 if active else x + 14, y if active else y - 15,
                                    color, 2, tooltip=tip))
        elif kind == 'battery':
            positive_x = x - 9 if positive_left else x + 9
            negative_x = x + 9 if positive_left else x - 9
            items.extend((self._line(positive_x, y - 19, positive_x, y + 19, color, 3, tooltip=tip),
                          self._line(negative_x, y - 11, negative_x, y + 11, color, 3, tooltip=tip)))
            if not active:
                items.append(self._line(x - 7, y - 15, x + 10, y + 15, OPEN, 2, tooltip=tip))
        elif kind == 'motor':
            items.append(self.scene.addEllipse(x - 23, y - 20, 46, 40, self._pen(color, 2), QBrush(BACKGROUND)))
            items.append(self._text('M', x - 9, y - 15, color, 12, True))
        else:
            width = 55 if kind == 'mcu' else 45
            items.append(self.scene.addRect(x - width / 2, y - 17, width, 34, self._pen(color, 2), QBrush(BACKGROUND)))
            text = {'resistor': 'R', 'mcu': 'MCU', 'load': 'LOAD'}.get(kind, kind.upper())
            items.append(self._text(text, x - (19 if kind in ('mcu', 'load') else 6), y - 12, color, 9, True))
        for item in items:
            item.setToolTip(tip)
        return items

    def _draw(self):
        workspace = self.workspace
        ordered = [name for name in workspace.nodes if name != 'GND'] + ['GND']
        # Components connect only to their named node buses; crossing lines do
        # not merge without an endpoint dot. This is a readable netlist view.
        self.node_positions = {name: 245.0 + index * 230.0 for index, name in enumerate(ordered)}
        width = max(750.0, 245.0 + len(ordered) * 230.0 + 230.0)
        y = 176.0
        rows = {}
        for component in workspace.components:
            rows[component.id] = y
            y += 92.0 + (len(component.signal_pins) * 34.0 if component.kind == 'mcu' else 0.0)
        height = max(360.0, y + 50.0)
        self.scene.setSceneRect(0, 0, width, height)
        self._text(workspace.name, 24, 16, INK, 15, True)
        self._text(self._word('단자/노드', 'Terminals / nodes'), 25, 75, BUS, 9, True)

        volts = self.result.node_voltages_v if self.result else {}
        for name, x in self.node_positions.items():
            self._line(x, 100, x, height - 50, BUS, 1, dashed=True)
            voltage = f'{volts[name]:.4g} V' if name in volts else self._word('전위 미확정', 'Potential unknown')
            self._text(name, x - 48, 63, SOURCE if name == 'GND' else INK, 10, True)
            self._text(voltage, x - 48, 83, BUS, 8)
            self._endpoint(x, 105, SOURCE if name == 'GND' else BUS)

        results = {branch.id: branch for branch in self.result.components} if self.result else {}
        for component in workspace.components:
            y = rows[component.id]
            ax, bx = self.node_positions[component.a], self.node_positions[component.b]
            mid = (ax + bx) / 2
            active = component.kind not in ('wire', 'switch', 'battery') or component.closed
            color = OPEN if not active else SOURCE if component.kind == 'battery' else LIVE
            tip = f'{component.name}\n{component.a} → {component.b}'
            if not active:
                tip += '\n' + (self._word('전원 OFF', 'Power OFF') if component.kind == 'battery' else
                                self._word('단선', 'Open wire') if component.kind == 'wire' else
                                self._word('스위치 열림', 'Switch open'))
            branch = results.get(component.id)
            if branch:
                tip += f"\n{self._word('전류', 'Current')} {branch.current_a:.4g} A"
                if branch.voltage_drop_v is not None:
                    tip += f" · {self._word('전압차', 'Voltage drop')} {branch.voltage_drop_v:.4g} V"
            lead_gap = {'battery': 9, 'motor': 23, 'mcu': 27.5,
                        'wire': 25, 'switch': 24, 'resistor': 22.5, 'load': 22.5}[component.kind]
            left, right = min(ax, bx), max(ax, bx)
            items = [self._line(left, y, mid - lead_gap, y, color, tooltip=tip),
                     self._line(mid + lead_gap, y, right, y, color, tooltip=tip)]
            items.extend(self._symbol(component, mid, y, color, active, tip, positive_left=ax<bx))
            items.extend((self._endpoint(ax, y, color), self._endpoint(bx, y, color)))
            self._text(component.name, 22, y - 20, INK, 9, True, max_width=195)
            self._text(component.kind, 22, y + 2, BUS, 8)
            if component.kind == 'battery':
                self._text('+', ax + 7, y - 25, SOURCE, 12, True)
                self._text('−', bx + 7, y - 25, SOURCE, 12, True)
            state = ('OFF · 0 A' if component.kind == 'battery' and not active else
                     self._word('단선 · 0 A', 'Open · 0 A') if component.kind == 'wire' and not active else
                     self._word('열림 · 0 A', 'Open · 0 A') if component.kind == 'switch' and not active else
                     f'{branch.current_a:.4g} A' if branch else self._word('계산 미완료', 'Not calculated'))
            self._text(state, max(ax, bx) + 22, y - 16, color, 9, True)
            layout = dict(a=component.a, b=component.b, a_x=ax, b_x=bx,
                          row_y=y, kind=component.kind, active=active, signals={})
            if component.kind == 'mcu':
                for index, (pin, node) in enumerate(component.signal_pins.items(), 1):
                    signal_y = y + 23 + index * 31
                    sx = self.node_positions[node]
                    pin_ok = branch.signal_pin_connected.get(pin) if branch else None
                    signal_color = LIVE if pin_ok is True else OPEN if pin_ok is False else BUS
                    items.extend((self._line(mid, y + 17, mid, signal_y, signal_color, 1, dashed=True),
                                  self._line(mid, signal_y, sx, signal_y, signal_color, 2, dashed=True),
                                  self._endpoint(sx, signal_y, signal_color)))
                    signal_status = (self._word('도통 확인', 'Continuity found') if pin_ok is True else
                                     self._word('미연결', 'Disconnected') if pin_ok is False else
                                     self._word('미계산', 'Not calculated'))
                    self._text(f'{pin} → {node} · {signal_status}',
                               max(mid, sx) + 10, signal_y - 15, signal_color, 8)
                    layout['signals'][pin] = dict(node=node, x=sx, y=signal_y, connected=pin_ok)
            self.branch_layout[component.id] = layout
            self.branch_items[component.id] = items
        self._text(self._word('청록: 연결 · 빨강: 단선/열림/OFF · 주황: 전원 · 실제 제작 회로는 별도 검증',
                              'Teal: connected · red: open/OFF · amber: source · check the physical circuit separately'),
                   24, height - 35, BUS, 8)
