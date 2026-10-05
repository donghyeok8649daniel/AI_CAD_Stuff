"""Component-oriented circuit editor; geometry is schematic, never a PCB layout."""
from __future__ import annotations

from collections import defaultdict
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QGraphicsScene,
    QGraphicsView, QHBoxLayout, QLabel, QSplitter, QVBoxLayout, QWidget, QMessageBox)

from ..electrical import ElectricalResult, ElectricalWorkspace, ElectricalSchematicPosition
from .widgets import button, label

INK = QColor('#243346')
BUS = QColor('#7C91A6')
LIVE = QColor('#178F83')
OPEN = QColor('#D45757')
SOURCE = QColor('#D79424')
BACKGROUND = QColor('#F7F9FC')
NET_ROLE = 101
TERMINAL_ROLE = 102


class CircuitView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.editor_owner = parent
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setBackgroundBrush(QBrush(BACKGROUND))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        if .12 <= self.transform().m11() * factor <= 4:
            self.scale(factor, factor)
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.editor_owner.cancel_connection()
            event.accept()
        else:
            super().keyPressEvent(event)


class ElectricalSchematicDialog(QDialog):
    """Private draft with movable symbols and explicit, editable port connections."""
    editRequested = Signal()
    focusRequested = Signal()
    partActivated = Signal(str)

    def __init__(self, parent, workspace, result=None, parts=(), *, editable=True, view_mode='physical'):
        super().__init__(parent)
        self.editable = editable
        self.view_mode=view_mode if view_mode in ('physical','symbols') else 'physical'
        language = getattr(QApplication.instance(), 'cad_language', None)
        self.english = getattr(language, 'language', 'ko') == 'en'
        self.setWindowTitle(self._word('전장 회로도 · 부품 / 핀 / 배선', 'Circuit schematic · components / pins / wiring'))
        self.resize(1240, 820)
        self.workspace = ElectricalWorkspace.model_validate(workspace).model_copy(deep=True)
        self.parts = tuple(parts)
        self.workspace_changed = False
        self.accepted_workspace = None
        self.result = ElectricalResult.model_validate(result) if result is not None else None
        self.component_items = {}
        self.node_positions = {}
        self.branch_layout = {}
        self.branch_items = {}
        self.endpoint_coordinates = {}
        self.net_segments = {}
        self.junction_items = []
        self._route_items = []
        self._drawing = False
        self.pending_terminal = None
        self.selected_terminal = None
        self.scene = QGraphicsScene(self)
        self.view = CircuitView(self.scene, self)
        self.view.setObjectName('electricalSchematicView')
        self.route_timer = QTimer(self)
        self.route_timer.setSingleShot(True)
        self.route_timer.timeout.connect(self._route)

        layout = QVBoxLayout(self)
        layout.addWidget(label(self._word(
            '부품 드래그: 배치 · 시작/대상 핀 클릭: 연결 · 선택 편집: 모델/정격 변경 · 실물 몸체 클릭: 확대/CAD 보기.' if editable else
            '저장된 회로를 메인 화면에서 확인합니다. 회로 편집에서 부품·핀·배선을 변경하고 저장하세요.',
            'Drag: arrange · source/target pins: wire · Edit selected: model/ratings · click physical body: focus/CAD.' if editable else
            'Inspect the saved circuit in the main workspace. Use Edit circuit to change and save components, pins and wires.'), True))
        controls = QHBoxLayout()
        self.kind_combo = QComboBox()
        self.kind_combo.setObjectName('schematicAddKind')
        for key, ko, en in [('mcu','MCU / MPU 보드','MCU / MPU board'), ('battery','배터리 / 전원','Battery / supply'),
                ('motor','모터 / 액추에이터','Motor / actuator'), ('load','센서 / 드라이버 / 전자제품','Sensor / driver / device'),
                ('resistor','저항','Resistor'), ('switch','스위치','Switch'), ('wire','전선','Wire')]:
            self.kind_combo.addItem(self._word(ko, en), key)
        controls.addWidget(self.kind_combo)
        self.add_button = button(self._word('부품 추가…', 'Add component…'), self.add_component, True)
        self.add_button.setObjectName('schematicAddComponent')
        controls.addWidget(self.add_button)
        self.wire_button = button(self._word('핀 연결', 'Wire pins'), self.cancel_connection)
        self.wire_button.setCheckable(True)
        self.wire_button.setObjectName('schematicWireMode')
        controls.addWidget(self.wire_button)
        self.edit_button = button(self._word('선택 편집…', 'Edit selected…'), self.edit_selected)
        self.edit_button.setObjectName('schematicEditSelected')
        controls.addWidget(self.edit_button)
        self.expand_button = button(self._word('선택 보드 전체 핀', 'Selected board: all pins'), self.expand_selected)
        self.expand_button.setObjectName('schematicExpandPins')
        controls.addWidget(self.expand_button)
        self.cad_button=button(self._word('CAD 부품 보기','Show CAD part'),self.show_linked_part)
        self.cad_button.setObjectName('schematicShowCadPart');controls.addWidget(self.cad_button)
        if not editable:
            controls.addWidget(button(self._word('회로도 크게 보기 / 패널 복원', 'Focus circuit / restore panels'), self.focusRequested.emit))
        controls.addStretch(1)
        layout.addLayout(controls)

        navigation = QHBoxLayout()
        self.mode_picker=QComboBox();self.mode_picker.setObjectName('schematicViewMode')
        self.mode_picker.addItem(self._word('실물 배선','Board wiring'),'physical');self.mode_picker.addItem(self._word('회로 기호','Circuit symbols'),'symbols')
        self.mode_picker.setCurrentIndex(self.mode_picker.findData(self.view_mode));navigation.addWidget(self.mode_picker)
        self.mode_picker.currentIndexChanged.connect(self.change_view_mode)
        navigation.addWidget(button(self._word('자동 배치', 'Auto arrange'), self.auto_arrange))
        navigation.addWidget(button(self._word('전체 맞춤', 'Fit all'), self.fit_scene))
        navigation.addWidget(button('+', lambda: self.view.scale(1.25, 1.25)))
        navigation.addWidget(button('−', lambda: self.view.scale(.8, .8)))
        self.disconnect_button=button(self._word('선택 핀 연결 해제','Disconnect selected pin'),self.disconnect_selected_pin)
        self.disconnect_button.setObjectName('schematicDisconnectPin');self.disconnect_button.setEnabled(False);navigation.addWidget(self.disconnect_button)
        self.pin_button = button(self._word('MCU 핀 연결 상세…', 'MCU pin connection details…'), self.edit_mcu_pins)
        self.pin_button.setObjectName('schematicMcuPins')
        navigation.addWidget(self.pin_button)
        navigation.addWidget(button(self._word('보드 핀 상세 보기', 'Board pin reference'), self.show_pin_details))
        navigation.addStretch(1)
        if editable:
            navigation.addWidget(QLabel(self._word('휠: 확대 / 축소 · Esc: 연결 취소', 'Wheel: zoom · Esc: cancel wire')))
        layout.addLayout(navigation)

        from .mcu_pin_dialog import PinDiagramView
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.view)
        self.pin_panel = QWidget()
        pins = QVBoxLayout(self.pin_panel)
        self.mcu_combo = QComboBox()
        self.mcu_combo.setObjectName('schematicMcuSelection')
        pins.addWidget(self.mcu_combo)
        self.pin_view = PinDiagramView(self)
        self.pin_view.setObjectName('schematicMcuDiagram')
        pins.addWidget(self.pin_view, 1)
        pins.addWidget(button(self._word('핀 상세 닫기', 'Hide pin reference'), self.pin_panel.hide))
        self.splitter.addWidget(self.pin_panel)
        self.pin_panel.hide()
        layout.addWidget(self.splitter, 1)
        self.mcu_combo.currentIndexChanged.connect(self.refresh_pin_diagram)
        self.pin_view.pin_clicked.connect(lambda key: self.edit_mcu_pins(pin=key))
        self.scene.selectionChanged.connect(self._selection_changed)
        self.inspector = QLabel()
        self.inspector.setWordWrap(True)
        self.inspector.setObjectName('schematicSelectionDetails')
        layout.addWidget(self.inspector)
        self.supply_warnings=QLabel();self.supply_warnings.setObjectName('schematicSupplyWarnings');self.supply_warnings.setWordWrap(True)
        self.supply_warnings.setStyleSheet('color:#e8b85b;');self.supply_warnings.hide();layout.addWidget(self.supply_warnings)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName('schematicStatus')
        layout.addWidget(self.status)
        layout.addWidget(label(self._word(
            '같은 노드 이름이 같은 전선입니다. 접점 없는 교차선은 별개입니다. 보드 외형은 배선 안내도이며 제작 치수가 아닙니다. DC 단자와 실제 전원 핀은 별도로 지정합니다.',
            'Matching net names are connected. Crossings without dots are separate. Board artwork guides wiring, not fabrication dimensions. Assign DC terminals and physical power pins separately.'), True))
        close = QHBoxLayout()
        close.addStretch(1)
        self.apply_button = button(self._word('회로도 변경 저장', 'Save circuit changes'), self.accept, True)
        self.apply_button.setObjectName('schematicApply')
        self.apply_button.setEnabled(False)
        close.addWidget(self.apply_button)
        self.close_button = button(self._word('닫기', 'Close'), self.reject)
        close.addWidget(self.close_button)
        layout.addLayout(close)
        if not editable:
            self.kind_combo.hide()
            self.add_button.hide()
            self.wire_button.hide()
            self.edit_button.setText(self._word('회로 편집…', 'Edit circuit…'))
            self.pin_button.hide()
            self.disconnect_button.hide()
            self.apply_button.hide()
            self.close_button.hide()
            self.inspector.setToolTip(self._word('메인 화면에서는 저장된 회로를 표시합니다. 회로 편집에서 변경하고 저장하세요.',
                'The main workspace displays the saved circuit. Use Edit circuit to make and save changes.'))
        self._draw()
        self.refresh_mcu_list()
        self._selection_changed()

    def _word(self, korean, english):
        return english if self.english else korean

    def change_view_mode(self):
        selected=self._selected_id();self.view_mode=self.mode_picker.currentData();self.pending_terminal=None
        self._draw()
        if selected:self.component_items[selected].setSelected(True)
        self.fit_scene()

    def _changed(self):
        self.workspace_changed = True
        self.apply_button.setEnabled(True)

    def _component(self, identifier):
        return next(c for c in self.workspace.components if c.id == identifier)

    def _selected_id(self):
        return next((key for key, item in self.component_items.items() if item.isSelected()), None)

    def _selection_changed(self):
        if self._drawing:return
        identifier = self._selected_id()
        if self.selected_terminal and self.selected_terminal[0]!=identifier:
            self.selected_terminal=None;self.disconnect_button.setEnabled(False)
        self.edit_button.setEnabled(bool(identifier) or not self.editable)
        self.expand_button.setEnabled(bool(identifier and self._component(identifier).kind in ('mcu','load','motor')))
        self.cad_button.setEnabled(bool(identifier and self._component(identifier).part_id))
        if identifier:
            c = self._component(identifier)
            self.inspector.setText(f'{c.name} · {c.catalog_id or c.kind} · {c.a} / {c.b}' +
                (f' · CAD: {c.part_id}' if c.part_id else ''))
            if c.kind == 'mcu':
                self.mcu_combo.setCurrentIndex(self.mcu_combo.findData(identifier))
        else:
            self.inspector.setText(self._word('부품을 선택하면 이름·모델·CAD 연결을 확인하고 편집할 수 있습니다.',
                'Select a component to inspect its name, model and linked CAD part.'))

    def show_pin_details(self):
        self.pin_panel.show()
        self.splitter.setSizes([850, 350])
        self.pin_view.fit()

    def focus_component(self, identifier):
        item=self.component_items.get(identifier)
        if item is None:return False
        self.scene.clearSelection();item.setSelected(True)
        self.view.fitInView(item.mapRectToScene(item.boundingRect()).adjusted(-45,-45,45,45),Qt.AspectRatioMode.KeepAspectRatio)
        if self.view.transform().m11()>2:self.view.resetTransform();self.view.scale(2,2);self.view.centerOn(item)
        return True

    def show_linked_part(self):
        identifier=self._selected_id()
        if identifier:
            part_id=self._component(identifier).part_id
            if part_id:self.partActivated.emit(part_id)

    def activate_component(self, identifier):
        self.selected_terminal=None;self.disconnect_button.setEnabled(False)
        self.focus_component(identifier)
        part_id=self._component(identifier).part_id
        if part_id:self.partActivated.emit(part_id)

    def refresh_mcu_list(self, selected_id=None):
        selected_id = selected_id or self.mcu_combo.currentData()
        self.mcu_combo.blockSignals(True)
        self.mcu_combo.clear()
        for c in self.workspace.components:
            if c.kind == 'mcu': self.mcu_combo.addItem(c.name, c.id)
        if selected_id: self.mcu_combo.setCurrentIndex(max(0, self.mcu_combo.findData(selected_id)))
        self.mcu_combo.blockSignals(False)
        self.refresh_pin_diagram()

    def refresh_pin_diagram(self, *_):
        from ..mcu_connections import pin_connections
        c = next((c for c in self.workspace.components if c.id == self.mcu_combo.currentData()), None)
        self.pin_view.draw(c, pin_connections(self.workspace, c.id) if c else ())
        self.pin_view.fit()

    def edit_mcu_pins(self, *_args, pin=None):
        if not self.editable:self.editRequested.emit();return
        from .mcu_pin_dialog import McuPinDialog
        dialog = McuPinDialog(self, self.workspace, self.parts, self.mcu_combo.currentData())
        if pin: dialog.select_pin(pin)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.accepted_workspace is not None:
            self._adopt(dialog.accepted_workspace)

    def _adopt(self, workspace):
        from ..electrical import evaluate_electrical
        self.workspace = ElectricalWorkspace.model_validate(workspace).model_copy(deep=True)
        self._changed()
        self.pending_terminal = None
        try: self.result = evaluate_electrical(self.workspace)
        except (ValueError, TypeError): self.result = None
        self._draw()
        self.refresh_mcu_list()

    def disconnect_selected_pin(self):
        if not self.editable or self.selected_terminal is None:return
        identifier,key=self.selected_terminal
        from ..circuit_connections import disconnect_schematic_terminal
        try:
            self._adopt(disconnect_schematic_terminal(self.workspace,identifier,key))
            self.status.setText(self._word('선택한 핀 연결을 해제했습니다. 저장하면 반영됩니다.','Selected pin disconnected. Save to apply.'))
        except ValueError as exc:self.status.setText(str(exc))

    def add_component(self):
        if not self.editable: self.editRequested.emit(); return
        from .electrical_dialog import ComponentDialog
        dialog = ComponentDialog(self, self.parts)
        dialog.kind.setCurrentIndex(dialog.kind.findData(self.kind_combo.currentData()))
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        self._replace_component(dialog.candidate())
        self.fit_scene()

    def edit_selected(self):
        if not self.editable: self.editRequested.emit(); return
        identifier = self._selected_id()
        if identifier: self.edit_component(identifier)

    def edit_component(self, identifier):
        if not self.editable: self.editRequested.emit(); return
        from .electrical_dialog import ComponentDialog
        dialog = ComponentDialog(self, self.parts, self._component(identifier).model_dump())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._replace_component(dialog.candidate())

    def _replace_component(self, candidate):
        raw = self.workspace.model_dump()
        replaced = False
        for index, old in enumerate(raw['components']):
            if old['id'] == candidate['id']:
                raw['components'][index] = candidate
                replaced = True
                break
        if not replaced: raw['components'].append(candidate)
        raw['nodes'] = list(dict.fromkeys([*raw['nodes'], candidate['a'], candidate['b'],
            *candidate.get('signal_pins', {}).values(), *candidate.get('terminal_pins', {}).values(), *candidate.get('board_supply_pins',{}).values()]))
        try: self._adopt(ElectricalWorkspace.model_validate(raw))
        except ValueError as exc: QMessageBox.warning(self, self._word('부품 입력 확인', 'Check component'), str(exc)[:800])

    def expand_selected(self):
        identifier = self._selected_id()
        if identifier:
            item = self.component_items[identifier]
            item.show_all_pins(not getattr(item, 'expanded', False))
            self._route()

    def cancel_connection(self, *_):
        self.pending_terminal = None
        if not self.editable:
            self.status.setText(self._word('회로 편집: 부품 추가 · 핀 연결 · 배치 저장 | 휠: 확대 / 축소',
                'Edit circuit: add components, wire pins and save placement | Wheel: zoom'))
            return
        self.status.setText(self._word('핀 연결 모드: 시작 단자와 대상 단자를 클릭하세요.',
            'Wire mode: click the source and target terminals.') if self.wire_button.isChecked() else
            self._word('부품 드래그: 배치 · 선택 편집: 모델 변경 · 핀 연결 버튼으로 배선',
            'Drag: arrange · Edit selected: change model · Wire pins: connect'))

    def _port_clicked(self, identifier, terminal):
        item = self.component_items[identifier]
        item.setSelected(True)
        port = item.all_ports[terminal]
        self.selected_terminal=(identifier,terminal)
        self.disconnect_button.setEnabled(self.editable and port.connectable and port.node is not None)
        if not port.connectable:
            self.status.setText(self._word('이 패드는 공식 핀 참고 표시입니다. DC 전원은 별도 A/B 단자에서 설정하세요.',
                'This pad is a physical pin reference. Set modeled DC power at the separate A/B terminals.'))
            return
        if not self.editable or not self.wire_button.isChecked():
            self.status.setText(f'{self._component(identifier).name} · {port.label} · {port.node or self._word("미연결", "Unconnected")}' +
                (self._word(' — 핀 연결 모드를 켜고 시작·대상 핀을 클릭하세요.', ' — enable Wire pins, then click source and target.') if self.editable else
                 self._word(' — 회로 편집에서 핀과 배선을 변경하세요.', ' — use Edit circuit to change pins and wiring.')))
            return
        if self.pending_terminal is None:
            self.pending_terminal = (identifier, terminal)
            self.status.setText(self._word('대상 단자를 클릭하세요 · Esc로 취소', 'Click target terminal · Esc to cancel') + f' · {port.label}')
            return
        source = self.pending_terminal
        self.pending_terminal = None
        if source == (identifier, terminal):
            self.cancel_connection()
            return
        source_port = self.component_items[source[0]].all_ports[source[1]]
        if source_port.node and source_port.node != port.node:
            answer = QMessageBox.question(self, self._word('단자 연결 변경', 'Reassign terminal'), self._word(
                '선택한 시작 단자만 대상 노드로 옮깁니다. 기존 노드에 연결된 다른 부품은 그대로 유지합니다. 계속할까요?',
                'Move only the source terminal to the target net. Other devices on its old net stay unchanged. Continue?'))
            if answer != QMessageBox.StandardButton.Yes: return
        # The clicked graphics child is still handling mousePressEvent. Rebuild
        # after that event returns, so Qt never deletes the active event target.
        self.pending_terminal=None
        QTimer.singleShot(0,lambda:self.connect_terminals(*source,identifier,terminal))

    def connect_terminals(self, source_id, source_terminal, target_id, target_terminal):
        if not self.editable:return False
        from ..circuit_connections import connect_schematic_terminals
        try:
            self._adopt(connect_schematic_terminals(self.workspace, source_id, source_terminal, target_id, target_terminal))
            self.status.setText(self._word('핀 연결을 변경했습니다. 저장하면 설계에 반영됩니다.', 'Connection updated. Save to apply to the design.'))
            return True
        except ValueError as exc:
            self.status.setText(str(exc))
            return False

    def _moved(self, identifier, point):
        if self._drawing or not self.editable: return
        x,y=max(-100000,min(100000,point.x())),max(-100000,min(100000,point.y()))
        if x!=point.x() or y!=point.y():
            self._drawing=True
            self.component_items[identifier].setPos(x,y)
            self._drawing=False
        self.workspace.schematic_positions[identifier] = ElectricalSchematicPosition(x=x, y=y)
        self._changed()
        self.route_timer.start(100)

    def _draw(self):
        from .circuit_symbols import CircuitComponentItem
        if self.view_mode=='physical':
            from .physical_board_symbols import PhysicalComponentItem
            factory=PhysicalComponentItem
        else:factory=CircuitComponentItem
        self._drawing = True
        self.route_timer.stop()
        self.component_items.clear()
        self.selected_terminal=None;self.disconnect_button.setEnabled(False)
        self.scene.clear()
        self._route_items.clear()
        for c in self.workspace.components:
            item = factory(c, english=self.english)
            self.scene.addItem(item)
            item.setZValue(10)
            item.portClicked.connect(self._port_clicked)
            item.positionChanged.connect(self._moved)
            if self.view_mode=='physical':
                item.activated.connect(self.activate_component)
            else:
                # Accepting the component editor redraws/deletes these items.
                # Let the originating mouseDoubleClickEvent return first.
                item.activated.connect(self.edit_component,Qt.ConnectionType.QueuedConnection)
            item.geometryChanged.connect(lambda *_: self._route())
            self.component_items[c.id] = item
            if not self.editable:
                from PySide6.QtWidgets import QGraphicsItem
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self._arrange(save=False)
        self._drawing = False
        self._route()
        self.cancel_connection()

    def _arrange(self, save):
        groups = [[], [], [], []]
        for c in self.workspace.components:
            column = 0 if c.kind == 'battery' else 1 if c.kind in ('wire','switch','resistor') else 2 if c.kind == 'mcu' else 3
            groups[column].append(c)
        y = 70.0
        rows = max((len(g) for g in groups), default=0)
        for row in range(rows):
            height = max(self.component_items[g[row].id].boundingRect().height() for g in groups if row < len(g))
            for column, group in enumerate(groups):
                if row >= len(group): continue
                c = group[row]
                pos = self.workspace.schematic_positions.get(c.id) if not save else None
                point = QPointF(pos.x, pos.y) if pos else QPointF(90 + column * 420, y)
                self.component_items[c.id].setPos(point)
                if save: self.workspace.schematic_positions[c.id] = ElectricalSchematicPosition(x=point.x(), y=point.y())
            y += height + 150

    def auto_arrange(self):
        self._drawing = True
        self._arrange(save=True)
        self._drawing = False
        if self.editable: self._changed()
        self._route()
        self.fit_scene()

    def _line(self, a, b, color, node, terminal=None, dashed=False):
        pen = QPen(color, 3.0 if self.view_mode=='physical' else 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap);pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if dashed: pen.setStyle(Qt.PenStyle.DashLine)
        item = self.scene.addLine(a.x(), a.y(), b.x(), b.y(), pen)
        item.setZValue(12 if self.view_mode=='physical' else -2)
        item.setData(NET_ROLE, node)
        item.setData(TERMINAL_ROLE, terminal)
        item.setToolTip(node)
        self._route_items.append(item)
        self.net_segments.setdefault(node, []).append(item)
        return item

    def _text(self, text, point, color=BUS, size=9):
        item = self.scene.addText(text, QFont('Segoe UI', size))
        item.setDefaultTextColor(color)
        item.setPos(point)
        item.setZValue(-1)
        self._route_items.append(item)
        return item

    def _route(self):
        if self._drawing: return
        for item in self._route_items: self.scene.removeItem(item)
        self._route_items.clear()
        self.net_segments.clear()
        self.junction_items.clear()
        self.branch_layout.clear()
        self.branch_items.clear()
        self.endpoint_coordinates.clear()
        nets = defaultdict(list)
        rectangles = [item.sceneBoundingRect() for item in self.component_items.values()]
        results = {b.id: b for b in self.result.components} if self.result else {}
        for c in self.workspace.components:
            item = self.component_items[c.id]
            active = c.kind not in ('wire','switch','battery') or c.closed
            ax, bx = item.port_scene_position('a'), item.port_scene_position('b')
            layout = dict(a=c.a, b=c.b, a_x=ax.x(), b_x=bx.x(), row_y=ax.y(), kind=c.kind, active=active, signals={})
            self.branch_items[c.id] = [item, *item.childItems()]
            for key, port in item.ports.items():
                point = item.port_scene_position(key)
                self.endpoint_coordinates[(c.id, key)] = point
                if port.node:
                    nets[port.node].append((c.id, key, point, port))
                if key.startswith(('pin:', 'port:', 'supply:')) and port.node:
                    branch = results.get(c.id)
                    short = key.partition(':')[2]
                    connected = branch.signal_pin_connected.get(short) if branch else None
                    layout['signals'][short] = dict(node=port.node, x=point.x(), y=point.y(), origin_x=point.x(),
                        origin_y=point.y(), connected=connected, legacy=port.legacy)
            self.branch_layout[c.id] = layout
            state = self._word('정격 입력 전 · DC 계산 제외', 'Ratings pending · excluded from DC') if not c.analysis_enabled else \
                ('OFF · 0 A' if c.kind == 'battery' and not active else self._word('단선 · 0 A','Open · 0 A') if c.kind == 'wire' and not active else
                 self._word('열림 · 0 A','Open · 0 A') if c.kind == 'switch' and not active else
                 f'{results[c.id].current_a:.4g} A' if c.id in results else self._word('계산 미완료','Not calculated'))
            self._text(state, QPointF(item.sceneBoundingRect().left()+5, item.sceneBoundingRect().bottom()+3), OPEN if not active else BUS, 8)
        from .circuit_routing import route_nets
        bodies = [item.mapRectToScene(item.body_rect) for item in self.component_items.values()]
        unassigned = [item.port_scene_position(key) for item in self.component_items.values()
                      for key, port in item.ports.items() if port.node is None]
        if self.view_mode=='physical':
            from .pictorial_wiring import physical_routes
            routed=physical_routes(nets,self.component_items)
        else:routed = route_nets(nets, bodies, reserved_points=unassigned)
        self.unrouted_terminals = routed.unrouted
        self.node_positions = {node: float(index) for index, node in enumerate(self.workspace.nodes)}
        for node, endpoints in nets.items():
            color = SOURCE if any(port.legacy for _,_,_,port in endpoints) else BUS if node == 'GND' else LIVE
            if self.view_mode=='physical':
                from .pictorial_wiring import wire_color
                color=wire_color(node,endpoints)
            for start, end in routed.segments[node]:
                self._line(start, end, color, node)
            for point in routed.junctions[node]:
                dot = self.scene.addEllipse(point.x()-3, point.y()-3, 6, 6, QPen(color), QBrush(color))
                dot.setData(NET_ROLE, node)
                dot.setZValue(13 if self.view_mode=='physical' else -1)
                self._route_items.append(dot)
                self.junction_items.append(dot)
            volts = self.result.node_voltages_v if self.result else {}
            text = node + (f' · {volts[node]:.4g} V' if node in volts else '')
            # Net labels are standard off-page connections when a dense/overlaid
            # arrangement cannot be routed within the bounded interactive budget.
            labels = {(endpoints[0][0], endpoints[0][1])}
            labels.update((identifier,key) for name,identifier,key in routed.unrouted if name == node)
            for identifier, key, point, port in endpoints:
                self.branch_items[identifier].extend(self.net_segments.get(node, []))
                if (identifier,key) in labels:
                    offset = -115 if port.side == 'left' else 12
                    self._text(text, QPointF(point.x()+offset, point.y()-27), color, 8)
        if routed.unrouted:
            self.routing_note = self._word(
                f'{len(routed.unrouted)}개 단자를 같은 노드 라벨로 연결 표시합니다. 자동 배치나 부품 이동으로 배선을 정리할 수 있습니다.',
                f'{len(routed.unrouted)} terminals use matching net labels. Auto arrange or move components to simplify wiring.')
            self._text(self.routing_note, QPointF(self.scene.itemsBoundingRect().left(), self.scene.itemsBoundingRect().bottom()+35), BUS, 9)
        else:
            self.routing_note = ''
        if not rectangles:
            self._text(self._word('회로가 비어 있습니다. 위에서 보드·배터리·모터·저항·스위치를 추가하세요.',
                'Empty circuit. Add a board, battery, motor, resistor or switch above.'), QPointF(40,80), INK, 13)
        from ..board_supply import board_supply_warnings
        warnings=board_supply_warnings(self.workspace,self.result,language='en' if self.english else 'ko')
        visible=list(warnings[:4])
        if len(warnings)>4:visible.append(self._word(f'그 외 {len(warnings)-4}개 · 마우스를 올려 상세 확인',f'{len(warnings)-4} more · hover for details'))
        self.supply_warnings.setText('\n'.join(visible));self.supply_warnings.setToolTip('\n'.join(warnings)[:12000]);self.supply_warnings.setVisible(bool(warnings))
        bounds = self.scene.itemsBoundingRect().adjusted(-35,-35,35,35)
        self.scene.setSceneRect(bounds)

    def fit_scene(self):
        self.route_timer.stop()
        self._route()
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def showEvent(self, event):
        super().showEvent(event)
        self.fit_scene()

    def accept(self):
        if not self.editable: return
        self.route_timer.stop()
        self.accepted_workspace = ElectricalWorkspace.model_validate(self.workspace.model_dump()).model_copy(deep=True)
        super().accept()

    def reject(self):
        self.route_timer.stop()
        super().reject()
