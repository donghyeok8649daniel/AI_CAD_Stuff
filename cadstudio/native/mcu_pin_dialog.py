"""Native board selection, connector pin diagram and explicit net assignments.

All edits stay in a private electrical workspace until accepted. A header
diagram shows connector labels, not dimensional board geometry or firmware.
"""
from copy import deepcopy
from uuid import uuid4

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont, QPainter, QPen
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget)

from ..electrical import ElectricalComponent, ElectricalWorkspace
from .widgets import button, number


def english():
    return getattr(getattr(QApplication.instance(), 'cad_language', None), 'language', 'ko') == 'en'


def word(ko, en):
    return en if english() else ko


class McuBoardDialog(QDialog):
    """Choose an exact connector map, leaving unknown operating data blank."""
    def __init__(self, parent, workspace, parts=(), existing=None):
        super().__init__(parent)
        from ..board_pins import available_pinouts
        self.setWindowTitle(word('MCU 모델 / 전원 설정', 'MCU model / power settings'))
        self.resize(590, 490)
        self.old = deepcopy(existing.model_dump() if hasattr(existing, 'model_dump') else existing or {})
        self.workspace = ElectricalWorkspace.model_validate(workspace)
        self.dropped_confirmed = False
        self.component = None
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.model_combo = QComboBox()
        self.model_combo.setObjectName('mcuModelChoice')
        for pinout in available_pinouts():
            self.model_combo.addItem(pinout.model, pinout.catalog_id)
        current_id = self.old.get('catalog_id', '')
        if self.old and self.model_combo.findData(current_id) < 0:
            self.model_combo.addItem(word('사용자 보드 / 기존 모델', 'Custom board / existing model'), current_id)
        if self.old:
            self.model_combo.setCurrentIndex(max(0, self.model_combo.findData(current_id)))
        form.addRow(word('MCU / 보드 모델', 'MCU / board model'), self.model_combo)
        self.name = QLineEdit(self.old.get('name', ''))
        self.name.setObjectName('mcuBoardName')
        form.addRow(word('회로에서 사용할 이름', 'Name in the circuit'), self.name)
        self.a = QComboBox(); self.b = QComboBox()
        for field in (self.a, self.b):
            field.setEditable(True); field.addItems(self.workspace.nodes)
        self.a.setCurrentText(self.old.get('a', 'MCU_POWER'))
        self.b.setCurrentText(self.old.get('b', 'GND'))
        form.addRow(word('VCC 공급 노드', 'VCC supply node'), self.a)
        form.addRow(word('GND / 리턴 노드', 'GND / return node'), self.b)
        self.voltage = number(self.old.get('rated_voltage_v', 0), 0, 1000, ' V', decimals=4)
        self.current = number(self.old.get('rated_current_a', 0), 0, 10000, ' A', decimals=6)
        form.addRow(word('실제 공급 전압', 'Actual supply voltage'), self.voltage)
        form.addRow(word('확인한 동작 전류', 'Verified operating current'), self.current)
        from PySide6.QtWidgets import QCheckBox
        self.analysis_enabled=QCheckBox(word('정격 입력 완료 · DC 계산에 포함','Ratings entered · include in DC analysis'));self.analysis_enabled.setChecked(self.old.get('analysis_enabled',True));form.addRow(self.analysis_enabled)
        self.part = QComboBox(); self.part.addItem(word('CAD 부품 연결 없음', 'No linked CAD part'), '')
        for item in parts: self.part.addItem(item['name'] + ' · ' + item['id'], item['id'])
        prior = self.old.get('part_id', '')
        if prior and self.part.findData(prior) < 0: self.part.addItem(prior, prior)
        self.part.setCurrentIndex(max(0, self.part.findData(prior)))
        form.addRow(word('연결할 CAD 부품', 'Linked CAD part'), self.part)
        if self.old.get('part_registration'):
            self.model_combo.setEnabled(False);self.part.setEnabled(False)
        layout.addLayout(form)
        self.notes = QLabel(); self.notes.setWordWrap(True)
        layout.addWidget(self.notes, 1)
        source = button(word('공식 핀 자료 열기', 'Open official pin reference'), self.open_source)
        layout.addWidget(source)
        hint = QLabel(word('공급기 최대 전류를 보드 소비전류로 넣지 마세요. 전원 입력 경로와 각 전압 레일은 공식 자료로 확인합니다. 모델을 바꾸면 기존 핀 연결을 확인 후 해제합니다.',
                          'Do not use a power adapter maximum as board consumption. Check the power input path and each voltage rail against the reference. Changing models requires confirmation to remove previous pin assignments.'))
        hint.setWordWrap(True); layout.addWidget(hint)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(self.accept); controls.rejected.connect(self.reject)
        layout.addWidget(controls)
        self.identifier = self.old.get('id') or 'mcu-' + uuid4().hex[:12]
        self.model_combo.currentIndexChanged.connect(self.model_changed)
        self.model_changed()

    def model_changed(self):
        from ..board_pins import board_pinout
        pinout = board_pinout(self.model_combo.currentData())
        self.notes.setText((pinout.note_en if english() else pinout.note) if pinout else word('등록된 핀 배치 없음 · 기존 사용자 핀 이름을 유지합니다.', 'No registered pinout · existing custom pin names are retained.'))
        if not self.old: self.name.setText(self.model_combo.currentText())

    def open_source(self):
        from ..board_pins import board_pinout
        pinout = board_pinout(self.model_combo.currentData())
        if pinout: QDesktopServices.openUrl(QUrl(pinout.source_url))

    def assignments_to_drop(self):
        from ..board_pins import board_pinout
        pins = self.old.get('signal_pins') or {}
        catalog_id = self.model_combo.currentData()
        if catalog_id != self.old.get('catalog_id', ''):
            return {**pins,**{'supply:'+key:node for key,node in (self.old.get('board_supply_pins') or {}).items()}}
        pinout = board_pinout(catalog_id)
        allowed = {pin.key for pin in pinout.pins if pin.kind == 'signal'} if pinout else set(pins)
        return {key: node for key, node in pins.items() if key not in allowed}

    def candidate(self):
        from ..board_pins import board_pinout
        dropped = self.assignments_to_drop()
        if dropped and not self.dropped_confirmed:
            raise ValueError(word('모델 변경으로 해제될 핀 연결을 먼저 확인하세요.', 'Confirm the pin assignments removed by this model change.'))
        data = deepcopy(self.old)
        model_id = self.model_combo.currentData()
        pinout = board_pinout(model_id)
        data.update(id=self.identifier, kind='mcu', name=self.name.text().strip() or self.model_combo.currentText(),
                    a=self.a.currentText().strip(), b=self.b.currentText().strip(),
                    rated_voltage_v=self.voltage.value(), rated_current_a=self.current.value(),analysis_enabled=self.analysis_enabled.isChecked(),
                    part_id=self.part.currentData(), catalog_id=model_id,
                    pinout_catalog_id=model_id if pinout else '',
                    source_url=pinout.source_url if pinout else data.get('source_url', ''),
                    signal_pins={key: node for key, node in (data.get('signal_pins') or {}).items() if key not in dropped})
        if model_id!=self.old.get('catalog_id','') and ('board_supply_pins' in data or 'supply_pinout_catalog_id' in data):
            data['board_supply_pins']={};data['supply_pinout_catalog_id']=''
        return ElectricalComponent.model_validate(data)

    def accept(self):
        dropped = self.assignments_to_drop()
        if dropped and not self.dropped_confirmed:
            answer = QMessageBox.question(self, word('핀 연결 해제 확인', 'Confirm pin disconnection'),
                word('모델의 핀 배치가 달라 다음 연결을 해제합니다. 다른 부품의 연결은 유지합니다. 계속할까요?\n',
                     'The model pinout changes, so these assignments will be removed. Other components keep their connections. Continue?\n')
                + '\n'.join(f'{pin} → {node}' for pin, node in dropped.items()))
            if answer != QMessageBox.StandardButton.Yes: return
            self.dropped_confirmed = True
        try: self.component = self.candidate()
        except ValueError as exc:
            QMessageBox.warning(self, word('MCU 입력 확인', 'Check MCU inputs'), str(exc)[:1200]); return
        super().accept()


class PinDiagramView(QGraphicsView):
    pin_clicked = Signal(str)

    def __init__(self, parent=None):
        scene = QGraphicsScene(parent)
        super().__init__(scene, parent)
        self.setObjectName('mcuPinDiagram')
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setBackgroundBrush(QBrush(QColor('#F7F9FC')))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.pin_items = {}; self.pin_positions = {}

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item is not None and item.data(0):
            self.pin_clicked.emit(str(item.data(0))); event.accept(); return
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        self.scale(1.12 if event.angleDelta().y() > 0 else 1 / 1.12, 1.12 if event.angleDelta().y() > 0 else 1 / 1.12)
        event.accept()

    def fit(self):
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def draw(self, component, connections, selected='', diagram=None):
        from ..board_pins import board_pinout
        scene = self.scene(); scene.clear(); self.pin_items = {}; self.pin_positions = {}
        def text(value, x, y, color='#243346', bold=False, pin=''):
            item = scene.addText(value, QFont('Segoe UI', 9, QFont.Weight.Bold if bold else QFont.Weight.Normal))
            item.setDefaultTextColor(QColor(color)); item.setPos(x, y)
            if pin: item.setData(0, pin)
            return item
        if component is None:
            text(word('MCU를 추가하거나 선택하세요.', 'Add or select an MCU.'), 20, 20)
            scene.setSceneRect(0, 0, 600, 350); self.fit(); return
        pinout = diagram or board_pinout(component.catalog_id)
        physical_pins = getattr(pinout,'terminals',getattr(pinout,'pins',()))
        position = {pin.key: (pin.side, pin.position) for pin in physical_pins} if pinout else {}
        legacy = [pin for pin in connections if pin.key not in position]
        next_slot = max((slot for side, slot in position.values() if side == 'right'), default=-1) + 1
        for index, pin in enumerate(legacy): position[pin.key] = ('right', next_slot + index)
        height = max(270, 120 + max((slot for _, slot in position.values()), default=0) * 34)
        scene.addRect(285, 72, 330, height - 90, QPen(QColor('#A9B6C6'), 2), QBrush(QColor('#E9EFF7')))
        text(component.name, 292, 14, bold=True)
        text(pinout.model if pinout else component.catalog_id or ('Custom MCU' if component.kind=='mcu' else 'Custom electronic component'), 292, 36)
        text(('VCC: ' if component.kind=='mcu' else 'A: ') + component.a + ('   GND: ' if component.kind=='mcu' else '   B: ') + component.b, 292, 57, '#566B84')
        for pin in connections:
            side, slot = position[pin.key]; y = 94 + slot * 34
            x = 285 if side == 'left' else 615
            connected = pin.node is not None
            color = '#B28328' if pin.legacy else '#178F83' if connected else '#657A95' if pin.kind == 'signal' else '#B28328'
            if pin.key == selected: color = '#3A71C9'
            rect = scene.addRect(x - 6, y - 5, 12, 12, QPen(QColor(color), 2), QBrush(QColor(color)))
            rect.setData(0, pin.key); rect.setToolTip(pin.label + '\n' + ' · '.join(pin.functions))
            self.pin_items[pin.key] = rect; self.pin_positions[pin.key] = (x, y)
            caption = text(pin.label, x + 12 if side == 'left' else x - 157, y - 11, color, selected == pin.key, pin.key)
            caption.setToolTip(pin.label + '\n' + ' · '.join(pin.functions))
            if connected:
                outside = x - 28 if side == 'left' else x + 28
                scene.addLine(x, y, outside, y, QPen(QColor(color), 2))
                targets = ', '.join(target.label for target in pin.targets)
                caption = pin.node + (' · ' + targets if targets else '')
                short = caption if len(caption) <= 31 else caption[:28] + '…'
                tag = text(short, 10 if side == 'left' else 654, y - 11, color)
                tag.setToolTip(caption)
        text(word('핀 배치 모식도 · 치수 도면 아님 · 전압 레일은 자동 연결하지 않음',
                  'Connector schematic · not dimensional · voltage rails are not auto-connected'), 22, height + 18, '#566B84')
        scene.setSceneRect(0, 0, 930, height + 55)


class McuPinDialog(QDialog):
    """Select MCU, click a physical header pin and connect a named endpoint."""
    def __init__(self, parent, workspace, parts=(), mcu_id=None):
        super().__init__(parent)
        self.setWindowTitle(word('MCU · 핀 연결 / 모식도', 'MCU · pin connections / diagram'))
        self.resize(1200, 820)
        self.original = ElectricalWorkspace.model_validate(workspace).model_copy(deep=True)
        self.workspace = self.original.model_copy(deep=True)
        self.parts = tuple(parts); self.accepted_workspace = None
        self.selected_pin = ''; self.connections = (); self._refreshing = False; self.custom_allowed = False
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(QLabel(word('MCU 선택', 'Select MCU')))
        self.mcu_combo = QComboBox(); self.mcu_combo.setObjectName('mcuBoardSelection')
        header.addWidget(self.mcu_combo, 1)
        self.add_button = button(word('MCU 추가…', 'Add MCU…'), self.add_board)
        self.add_button.setObjectName('mcuAddBoard'); header.addWidget(self.add_button)
        self.edit_button = button(word('모델 / 전원 편집…', 'Edit model / power…'), self.edit_board)
        self.edit_button.setObjectName('mcuEditBoard'); header.addWidget(self.edit_button)
        header.addWidget(button(word('공식 핀 자료', 'Official pin reference'), self.open_source))
        layout.addLayout(header)
        self.board_note = QLabel(); self.board_note.setWordWrap(True); layout.addWidget(self.board_note)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.pin_view = PinDiagramView(self); splitter.addWidget(self.pin_view)
        table_box = QWidget(); table_layout = QVBoxLayout(table_box); table_layout.setContentsMargins(0, 0, 0, 0)
        self.pin_table = QTableWidget(0, 4); self.pin_table.setObjectName('mcuPinTable')
        self.pin_table.setHorizontalHeaderLabels([word('핀 / 헤더 위치', 'Pin / header'), word('기능', 'Functions'), word('노드', 'Net'), word('연결 대상', 'Connected to')])
        self.pin_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.pin_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.pin_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.pin_table.horizontalHeader().setStretchLastSection(True)
        table_layout.addWidget(self.pin_table, 1)
        table_layout.addWidget(button(word('모식도 전체 맞춤', 'Fit pin diagram'), self.pin_view.fit))
        splitter.addWidget(table_box); splitter.setSizes([620, 480]); layout.addWidget(splitter, 1)
        self.pin_caption = QLabel(); self.pin_caption.setWordWrap(True); layout.addWidget(self.pin_caption)
        row = QHBoxLayout()
        row.addWidget(QLabel(word('연결할 부품 · 단자', 'Target component · terminal')))
        self.target_combo = QComboBox(); self.target_combo.setObjectName('mcuConnectionTarget'); self.target_combo.setMinimumContentsLength(28)
        self.target_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(self.target_combo, 1)
        self.connect_button = button(word('선택 핀 연결', 'Connect selected pin'), self.connect_selected, True)
        self.connect_button.setObjectName('mcuConnectPin'); row.addWidget(self.connect_button)
        self.disconnect_button = button(word('핀 연결 해제', 'Disconnect pin'), self.disconnect_selected)
        self.disconnect_button.setObjectName('mcuDisconnectPin'); row.addWidget(self.disconnect_button)
        layout.addLayout(row)
        advanced = QHBoxLayout()
        advanced.addWidget(QLabel(word('직접 노드 지정', 'Assign a net directly')))
        self.node_combo = QComboBox(); self.node_combo.setEditable(True); self.node_combo.setObjectName('mcuPinNode')
        advanced.addWidget(self.node_combo, 1)
        self.custom_pin = QLineEdit(); self.custom_pin.setPlaceholderText(word('사용자 보드 핀 이름', 'Custom board pin name'))
        self.custom_pin.setObjectName('mcuCustomPin'); advanced.addWidget(self.custom_pin)
        self.node_button = button(word('노드에 연결', 'Connect to net'), self.connect_node)
        self.node_button.setObjectName('mcuConnectNode'); advanced.addWidget(self.node_button)
        layout.addLayout(advanced)
        self.status = QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.warnings = QPlainTextEdit(); self.warnings.setReadOnly(True); self.warnings.setMaximumHeight(86)
        self.warnings.setObjectName('mcuPinWarnings'); layout.addWidget(self.warnings)
        bottom = QHBoxLayout()
        hint = QLabel(word('같은 노드는 연결됩니다. GPIO로 모터·배터리를 직접 구동하지 마세요. 핀 도통은 코드 실행이나 전압 호환성 검증이 아닙니다.',
                          'Equal net names connect. Do not drive motors or batteries directly from GPIO. Pin continuity does not verify firmware or voltage compatibility.'))
        hint.setWordWrap(True); bottom.addWidget(hint, 1)
        self.apply_button = button(word('핀 연결 저장', 'Save pin connections'), self.accept, True)
        self.apply_button.setObjectName('mcuPinApply'); bottom.addWidget(self.apply_button)
        bottom.addWidget(button(word('취소', 'Cancel'), self.reject)); layout.addLayout(bottom)
        self.mcu_combo.currentIndexChanged.connect(self.refresh_pins)
        self.pin_table.itemSelectionChanged.connect(self.table_selected)
        self.pin_view.pin_clicked.connect(self.select_pin)
        self.refresh(mcu_id)

    def current_mcu(self):
        return next((component for component in self.workspace.components if component.id == self.mcu_combo.currentData() and component.kind == 'mcu'), None)

    def refresh(self, mcu_id=None):
        self._refreshing = True
        self.mcu_combo.blockSignals(True); self.mcu_combo.clear()
        for component in self.workspace.components:
            if component.kind == 'mcu': self.mcu_combo.addItem(component.name, component.id)
        if mcu_id: self.mcu_combo.setCurrentIndex(max(0, self.mcu_combo.findData(mcu_id)))
        self.mcu_combo.blockSignals(False); self._refreshing = False
        self.refresh_pins(); self.pin_view.fit()

    def refresh_pins(self, *_):
        from ..board_pins import board_pinout
        from ..mcu_connections import connection_endpoints, pin_connections, topology_warnings
        if self._refreshing: return
        component = self.current_mcu(); self.edit_button.setEnabled(component is not None)
        self.connections = pin_connections(self.workspace, component.id) if component else ()
        self._refreshing = True; self.pin_table.setRowCount(len(self.connections))
        for row, pin in enumerate(self.connections):
            values = (pin.label + (' *' if pin.legacy else ''), ' · '.join(pin.functions), pin.node or '—', ', '.join(target.label for target in pin.targets))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value); item.setData(Qt.ItemDataRole.UserRole, pin.key)
                if pin.kind != 'signal': item.setForeground(QColor('#977830'))
                self.pin_table.setItem(row, column, item)
        self.pin_table.resizeColumnsToContents()
        self.target_combo.clear()
        self.target_combo.addItem(word('연결할 단자를 선택하세요', 'Choose a target terminal'), None)
        if component:
            for endpoint in connection_endpoints(self.workspace, exclude_mcu_id=component.id):
                self.target_combo.addItem(endpoint.label + (' · ' + endpoint.node if endpoint.node else ''), (endpoint.component_id, endpoint.terminal))
        previous_node = self.node_combo.currentText(); self.node_combo.clear(); self.node_combo.addItems(self.workspace.nodes)
        self.node_combo.setCurrentText(previous_node)
        pinout = board_pinout(component.catalog_id) if component else None
        self.board_note.setText((pinout.model + ' · ' + (pinout.note_en if english() else pinout.note)) if pinout else word('핀 배치 미등록 · 사용자 핀 이름은 *로 표시합니다.', 'No registered pinout · custom pin names are marked *.'))
        self.custom_allowed = component is not None and not pinout
        self.custom_pin.setVisible(self.custom_allowed)
        diagnostics = topology_warnings(self.workspace, language='en' if english() else 'ko')
        self.warnings.setPlainText('\n'.join(diagnostics) if diagnostics else word('연결 위험 경고 없음 · 실제 전압·드라이버·코드는 별도 확인', 'No topology warnings · verify actual voltage, drivers and firmware separately'))
        self._refreshing = False
        if self.selected_pin not in {pin.key for pin in self.connections}: self.selected_pin = ''
        self.select_pin(self.selected_pin)
        self.apply_button.setEnabled(component is not None or self.workspace != self.original)

    def table_selected(self):
        if self._refreshing: return
        item = self.pin_table.item(self.pin_table.currentRow(), 0)
        if item: self.select_pin(item.data(Qt.ItemDataRole.UserRole))

    def select_pin(self, key):
        self.selected_pin = key
        pin = next((pin for pin in self.connections if pin.key == key), None)
        component = self.current_mcu()
        enabled = pin is not None and pin.kind == 'signal'
        self.connect_button.setEnabled(enabled); self.disconnect_button.setEnabled(pin is not None and pin.node is not None)
        self.node_button.setEnabled(enabled or self.custom_allowed)
        if pin:
            self.pin_caption.setText(pin.label + ' · ' + ' / '.join(pin.functions) + (' · ' + pin.node if pin.node else ''))
            self.node_combo.setCurrentText(pin.node or '')
            if not enabled:
                self.status.setText(word('전원·GND·리셋 핀은 신호 연결 대상으로 사용하지 않습니다. VCC/GND 전원 노드는 모델 / 전원 편집에서 지정하고 각 레일은 공식 자료를 확인하세요.',
                                         'Power, ground and reset pins are not signal endpoints. Set abstract VCC/GND nodes in Edit model / power and check each physical rail against the reference.'))
            else: self.status.clear()
            row = next(index for index, value in enumerate(self.connections) if value.key == key)
            self._refreshing = True; self.pin_table.selectRow(row); self._refreshing = False
        else: self.pin_caption.setText(word('모식도 또는 표에서 신호 핀을 클릭하세요.', 'Click a signal pin in the diagram or table.'))
        self.pin_view.draw(component, self.connections, key)

    def _change(self, function, *args):
        try: self.workspace = function(self.workspace, *args)
        except (ValueError, TypeError) as exc:
            self.status.setText(str(exc)[:1000]); return False
        self.refresh_pins(); return True

    def connect_selected(self):
        from ..mcu_connections import assign_pin
        component = self.current_mcu(); target = self.target_combo.currentData()
        if not component or not self.selected_pin or not target:
            self.status.setText(word('핀과 연결할 단자를 먼저 선택하세요.', 'Select a pin and target terminal first.')); return
        self._change(assign_pin, component.id, self.selected_pin, *target)

    def connect_node(self):
        from ..mcu_connections import assign_pin_node
        component = self.current_mcu()
        if not component: return
        key = self.custom_pin.text().strip() if self.custom_allowed and self.custom_pin.text().strip() else self.selected_pin
        if self._change(assign_pin_node, component.id, key, self.node_combo.currentText().strip()):
            self.selected_pin = key; self.custom_pin.clear(); self.refresh_pins()

    def disconnect_selected(self):
        from ..mcu_connections import disconnect_pin
        component = self.current_mcu()
        if component and self.selected_pin: self._change(disconnect_pin, component.id, self.selected_pin)

    def open_source(self):
        from ..board_pins import board_pinout
        component = self.current_mcu(); pinout = board_pinout(component.catalog_id) if component else None
        if pinout: QDesktopServices.openUrl(QUrl(pinout.source_url))

    def _edit_board(self, component=None):
        dialog = McuBoardDialog(self, self.workspace, self.parts, component)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.component is None: return
        data = self.workspace.model_dump(); changed = dialog.component.model_dump()
        for index, existing in enumerate(data['components']):
            if existing['id'] == changed['id']: data['components'][index] = changed; break
        else: data['components'].append(changed)
        data['nodes'] = sorted(set(data['nodes']) | {changed['a'], changed['b']} | set(changed['signal_pins'].values()))
        try: self.workspace = ElectricalWorkspace.model_validate(data)
        except ValueError as exc:
            self.status.setText(str(exc)[:1000]); return
        self.refresh(changed['id'])

    def add_board(self): self._edit_board()
    def edit_board(self):
        component = self.current_mcu()
        if component: self._edit_board(component)

    def accept(self):
        try: self.accepted_workspace = ElectricalWorkspace.model_validate(self.workspace.model_dump())
        except ValueError as exc:
            self.status.setText(str(exc)[:1000]); return
        super().accept()

    def showEvent(self, event):
        super().showEvent(event); self.pin_view.fit()
