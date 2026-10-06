"""Component-oriented circuit editor; geometry is schematic, never a PCB layout."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPainterPath, QPainterPathStroker
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QGraphicsScene,
    QGraphicsView, QHBoxLayout, QLabel, QSplitter, QVBoxLayout, QWidget, QMessageBox, QGraphicsItem, QGraphicsPathItem, QInputDialog)

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
WIRE_ROLE = 103


class SelectableWirePath(QGraphicsPathItem):
    def shape(self):
        stroke=QPainterPathStroker();stroke.setWidth(12)
        return stroke.createStroke(self.path())


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
        elif event.key() == Qt.Key.Key_Delete and self.editor_owner.delete_wire_button.isEnabled():
            self.editor_owner.delete_selected_wire()
            event.accept()
        else:
            super().keyPressEvent(event)


class ElectricalSchematicDialog(QDialog):
    """Private draft with movable symbols and explicit, editable port connections."""
    editRequested = Signal()
    focusRequested = Signal()
    partActivated = Signal(str)
    simulationRequested = Signal()
    wireActionRequested = Signal(str,object)
    componentSelected = Signal(str)
    linkRequested = Signal(object)
    aiRequested = Signal(object)

    def __init__(self, parent, workspace, result=None, parts=(), *, editable=True, view_mode='physical', inspection_only=False, design=None):
        super().__init__(parent)
        self.inspection_only = inspection_only
        self.editable = editable and not inspection_only
        editable = self.editable
        self.view_mode=view_mode if view_mode in ('physical','symbols') else 'physical'
        language = getattr(QApplication.instance(), 'cad_language', None)
        self.english = getattr(language, 'language', 'ko') == 'en'
        self.setWindowTitle(self._word('전장 회로도 · 부품 / 핀 / 배선', 'Circuit schematic · components / pins / wiring'))
        self.resize(1240, 820)
        self.workspace = ElectricalWorkspace.model_validate(workspace).model_copy(deep=True)
        self.parts = tuple(deepcopy(parts))
        self.design_reference = design
        self.workspace_changed = False
        self.accepted_workspace = None
        self.accepted_parts = None
        self.ai_request = None
        self._selection_emitting = True
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
        self.fit_timer = QTimer(self)
        self.fit_timer.setSingleShot(True)
        self.fit_timer.timeout.connect(self._fit_view)

        # Qt owns the unused editor widgets as one hidden subtree in previews.
        # Keeping removed QLayoutItems in Python creates competing ownership
        # during cyclic collection and can also make a later warning orphaned.
        self.editor_controls = QWidget(self) if inspection_only else self
        layout = QVBoxLayout(self.editor_controls)
        layout.addWidget(label(self._word(
            '부품 드래그: 배치 · 시작/대상 핀 클릭: 연결 · 선택 편집: 모델/정격 변경 · 실물 몸체 클릭: 확대/CAD 보기.' if editable else
            '저장된 회로를 메인 화면에서 확인합니다. 회로 편집에서 부품·핀·배선을 변경하고 저장하세요.',
            'Drag: arrange · source/target pins: wire · Edit selected: model/ratings · click physical body: focus/CAD.' if editable else
            'Inspect the saved circuit in the main workspace. Use Edit circuit to change and save components, pins and wires.'), True))
        controls = QHBoxLayout()
        self.kind_combo = QComboBox()
        self.kind_combo.setObjectName('schematicAddKind')
        for key, ko, en in [('mcu','MCU / MPU 보드','MCU / MPU board'), ('battery','배터리 / 전원','Battery / supply'),
                ('motor','모터','Motor'), ('actuator','액추에이터','Actuator'), ('load','센서 / 드라이버 / 전자제품','Sensor / driver / device'),
                ('resistor','저항','Resistor'), ('capacitor','커패시터 / 콘덴서','Capacitor'), ('inductor','코일 / 인덕터','Coil / inductor'),
                ('switch','스위치','Switch'), ('wire','전선','Wire')]:
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

        wires=QHBoxLayout()
        self.add_wire_button=button(self._word('전선 추가…','Add wire…'),self.add_wire,True)
        self.add_wire_button.setObjectName('schematicAddWire');wires.addWidget(self.add_wire_button)
        self.delete_wire_button=button(self._word('선택 전선 삭제 · Delete','Delete selected wire · Delete'),self.delete_selected_wire)
        self.delete_wire_button.setObjectName('schematicDeleteWire');self.delete_wire_button.setEnabled(False)
        wires.addWidget(self.delete_wire_button)
        wires.addWidget(label(self._word('전선 경로·몸체를 클릭해 선택한 뒤 삭제합니다. 기존 노드 연결은 회로 편집에서 핀 선택 → 연결 해제로 분리합니다.',
            'Click a wire path/body to select and delete it. Existing net connections: Edit circuit → select pin → Disconnect pin.'),True),1)
        layout.addLayout(wires)

        correspondence = QHBoxLayout()
        self.link_button = button(self._word('CAD 대응 설정…', 'Link CAD body…'), self.edit_cad_link)
        self.link_button.setObjectName('schematicLinkCad'); correspondence.addWidget(self.link_button)
        self.ai_button = button(self._word('AI 배선 요청…', 'Prepare AI wiring…'), self.prepare_ai_request)
        self.ai_button.setObjectName('schematicAiRequest'); correspondence.addWidget(self.ai_button)
        correspondence.addWidget(label(self._word('CAD 보기: 실제 부품 찾기 · 대응 설정: 기존 회로 부품을 CAD에 연결',
            'Show CAD: locate the body · Link CAD: associate an existing circuit component'), True), 1)
        layout.addLayout(correspondence)

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
        self.simulation_button=button(self._word('구동 시뮬레이션…','Drive simulation…'),self.open_simulation)
        self.simulation_button.setObjectName('schematicDriveSimulation');close.addWidget(self.simulation_button)
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
        if inspection_only:
            # Preview panes are much shorter than the standalone editor. Keep
            # their actual circuit canvas, rather than eight rows of editor UI.
            layout.removeWidget(self.splitter)
            preview_layout = QVBoxLayout(self)
            compact = QHBoxLayout()
            navigation.removeWidget(self.mode_picker); self.mode_picker.show(); compact.addWidget(self.mode_picker)
            compact.addWidget(button(self._word('전체 맞춤', 'Fit all'), self.fit_scene))
            compact.addWidget(button('+', lambda: self.view.scale(1.25, 1.25)))
            compact.addWidget(button('−', lambda: self.view.scale(.8, .8)))
            controls.removeWidget(self.expand_button); self.expand_button.show(); compact.addWidget(self.expand_button)
            self.preview_warnings = QLabel()
            self.preview_warnings.setObjectName('schematicPreviewWarnings')
            self.preview_warnings.setStyleSheet('color:#c48718;')
            compact.addWidget(self.preview_warnings)
            compact.addStretch(1)
            preview_layout.addLayout(compact); preview_layout.addWidget(self.splitter, 1); self.splitter.show()
            preview_layout.setContentsMargins(4, 4, 4, 4); preview_layout.setSpacing(4)
            self.editor_controls.hide()
            for widget in self.editor_controls.findChildren(QWidget): widget.hide()
        self._draw()
        self.refresh_mcu_list()
        self._selection_changed()

    def _word(self, korean, english):
        return english if self.english else korean

    def open_simulation(self):
        if self.inspection_only: return
        if not self.editable:
            self.simulationRequested.emit();return
        from .drive_simulation_dialog import DriveSimulationDialog
        dialog=DriveSimulationDialog(self,dict(name=self.workspace.name,parts=list(self.parts),electrical=self.workspace.model_dump()))
        dialog.exec()
        dialog.deleteLater()

    def change_view_mode(self):
        selected=self._selected_id();self.view_mode=self.mode_picker.currentData();self.pending_terminal=None
        self._draw()
        if selected:self.component_items[selected].setSelected(True)
        self.fit_scene()

    def _changed(self):
        if self.inspection_only: return
        self.workspace_changed = True
        self.apply_button.setEnabled(True)

    def _component(self, identifier):
        return next(c for c in self.workspace.components if c.id == identifier)

    def _selected_id(self):
        wire=next((item.data(WIRE_ROLE) for item in self.scene.selectedItems() if item.data(WIRE_ROLE)),None)
        if wire:return wire
        return next((key for key, item in self.component_items.items() if item.isSelected()), None)

    def _selection_changed(self):
        if self._drawing:return
        identifier = self._selected_id()
        if self.selected_terminal and self.selected_terminal[0]!=identifier:
            self.selected_terminal=None;self.disconnect_button.setEnabled(False)
        self.edit_button.setEnabled(bool(identifier) or not self.editable)
        self.delete_wire_button.setEnabled(bool(identifier and self._component(identifier).kind=='wire'))
        self.expand_button.setEnabled(bool(identifier and self._component(identifier).kind in ('mcu','load','motor','actuator')))
        self.cad_button.setEnabled(bool(identifier and self._component(identifier).part_id))
        self.link_button.setEnabled(bool(identifier and self.parts))
        if identifier:
            c = self._component(identifier)
            part = next((p for p in self.parts if p['id'] == c.part_id), None)
            state = self._word('등록됨', 'Registered') if c.part_registration else self._word('기존 대응 · 등록 확인 필요', 'Legacy link · registration pending')
            linked = f"{part['name']} [{part['id']}] · {state}" if part else (
                self._word('없는 CAD 부품: ', 'Missing CAD body: ') + c.part_id if c.part_id else self._word('CAD 대응 없음 · 대응 설정에서 연결하세요.', 'No CAD association · use Link CAD body.'))
            self.inspector.setText(f'{c.name} [{c.id}] · {c.catalog_id or c.kind} · {c.a} / {c.b} · CAD: {linked}')
            if c.kind == 'mcu':
                self.mcu_combo.setCurrentIndex(self.mcu_combo.findData(identifier))
        else:
            self.inspector.setText(self._word('부품을 선택하면 이름·모델·CAD 연결을 확인하고 편집할 수 있습니다.',
                'Select a component to inspect its name, model and linked CAD part.'))
        if self._selection_emitting: self.componentSelected.emit(identifier or '')

    def show_pin_details(self):
        self.pin_panel.show()
        self.splitter.setSizes([850, 350])
        self.pin_view.fit()

    def focus_component(self, identifier, *, notify=True, zoom=True):
        item=self.component_items.get(identifier)
        if item is None:return False
        old = self._selection_emitting; self._selection_emitting = notify
        try:
            self.scene.blockSignals(True); self.scene.clearSelection(); item.setSelected(True); self.scene.blockSignals(False)
            self._selection_changed()
            if zoom:
                self.view.fitInView(item.mapRectToScene(item.boundingRect()).adjusted(-45,-45,45,45),Qt.AspectRatioMode.KeepAspectRatio)
                if self.view.transform().m11()>2:self.view.resetTransform();self.view.scale(2,2);self.view.centerOn(item)
        finally: self._selection_emitting = old
        return True

    def focus_part(self, part_id, *, zoom=True):
        identifier = next((c.id for c in self.workspace.components if c.part_id == part_id), None)
        return self.focus_component(identifier, notify=False, zoom=zoom) if identifier else False

    def edit_cad_link(self):
        if self.inspection_only: return
        identifier = self._selected_id()
        if not identifier: return
        if not self.editable: self.linkRequested.emit(identifier); return
        from .electrical_part_dialog import ElectricalCadLinkDialog, circuit_link_design
        try: dialog = ElectricalCadLinkDialog(self, circuit_link_design(self.parts, self.workspace, self.design_reference), identifier)
        except (ValueError, TypeError) as exc: self.status.setText(str(exc)[:1200]); return
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.checked is not None:
                self.parts = tuple(p.model_dump(mode='json') for p in dialog.checked.parts)
                self._adopt(dialog.checked.electrical)
                self.focus_component(identifier)
                self.status.setText(self._word('CAD 대응 초안을 변경했습니다. 회로도 변경 저장으로 반영하세요.', 'CAD association draft updated. Save circuit changes to apply.'))
        finally: dialog.deleteLater()

    def prepare_ai_request(self):
        if self.inspection_only: return
        prompt, ok = QInputDialog.getMultiLineText(self, self._word('AI 배선 요청 준비', 'Prepare AI wiring request'),
            self._word('원하는 부품·핀·전선 변경을 입력하세요. 메인 AI 입력창에 준비한 뒤 초안 생성 버튼으로 실행합니다.',
                       'Describe component, pin or wire changes. The request is prepared in the main AI panel; Generate draft starts it.'))
        if not ok or not prompt.strip(): return
        identifier = self._selected_id()
        component = next((c for c in self.workspace.components if c.id == identifier), None)
        request = dict(prompt=prompt.strip(), component_id=identifier or '', part_id=component.part_id if component else '',
                       terminal=self.selected_terminal[1] if self.selected_terminal and self.selected_terminal[0] == identifier else '')
        if not self.editable: self.aiRequested.emit(request); return
        self.ai_request = request
        self.apply_button.setText(self._word('전장 변경 저장 · AI 요청 준비', 'Save electrical changes · prepare AI'))
        self.apply_button.setEnabled(True)
        self.status.setText(self._word('AI 요청을 대기시켰습니다. 저장하면 메인 AI 입력창으로 전달되며, 취소하면 폐기됩니다.',
            'AI request queued. Save transfers it to the main AI input; cancel discards it.'))

    def show_linked_part(self):
        if self.inspection_only: return
        identifier=self._selected_id()
        if identifier:
            part_id=self._component(identifier).part_id
            if part_id:self.partActivated.emit(part_id)

    def activate_component(self, identifier):
        self.selected_terminal=None;self.disconnect_button.setEnabled(False)
        self.focus_component(identifier)
        part_id=self._component(identifier).part_id
        if part_id and not self.inspection_only:self.partActivated.emit(part_id)

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
        if self.inspection_only: return
        if not self.editable:self.editRequested.emit();return
        from .mcu_pin_dialog import McuPinDialog
        dialog = McuPinDialog(self, self.workspace, self.parts, self.mcu_combo.currentData())
        if pin: dialog.select_pin(pin)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.accepted_workspace is not None:
                self._adopt(dialog.accepted_workspace)
        finally: dialog.deleteLater()

    def _adopt(self, workspace):
        if self.inspection_only: return
        from ..electrical import evaluate_electrical
        self.workspace = ElectricalWorkspace.model_validate(workspace).model_copy(deep=True)
        self._changed()
        self.pending_terminal = None
        try: self.result = evaluate_electrical(self.workspace)
        except (ValueError, TypeError): self.result = None
        self._draw()
        self.refresh_mcu_list()
        self._selection_changed()

    def disconnect_selected_pin(self):
        if not self.editable or self.selected_terminal is None:return
        identifier,key=self.selected_terminal
        from ..circuit_connections import disconnect_schematic_terminal
        try:
            self._adopt(disconnect_schematic_terminal(self.workspace,identifier,key))
            self.status.setText(self._word('선택한 핀 연결을 해제했습니다. 저장하면 반영됩니다.','Selected pin disconnected. Save to apply.'))
        except ValueError as exc:self.status.setText(str(exc))

    def add_wire(self):
        if self.inspection_only: return
        if not self.editable:self.wireActionRequested.emit('add',self.selected_terminal);return
        from .wire_connection_dialog import WireConnectionDialog
        dialog=WireConnectionDialog(self,self.workspace,english=self.english,selected_terminal=self.selected_terminal)
        try:
            if dialog.exec()==QDialog.DialogCode.Accepted and dialog.checked is not None:
                self._adopt(dialog.checked)
                self.fit_scene()
                self.wire_paths.get(dialog.wire_id,self.component_items[dialog.wire_id]).setSelected(True)
                self.status.setText(self._word('전선을 추가했습니다. 회로도 변경 저장으로 설계와 작업 기록에 반영하세요.',
                    'Wire added. Save circuit changes to update the design and history.'))
        finally:dialog.deleteLater()

    def delete_selected_wire(self):
        if self.inspection_only: return
        identifier=self._selected_id()
        if not identifier:return
        if not self.editable:self.wireActionRequested.emit('delete',identifier);return
        from ..circuit_connections import delete_schematic_wire
        try:
            self._adopt(delete_schematic_wire(self.workspace,identifier))
            self.status.setText(self._word('선택 전선만 삭제했습니다. 다른 부품·핀·노드는 유지됩니다. 저장하면 반영됩니다.',
                'Only the selected wire was deleted. Other components, pins and nets remain. Save to apply.'))
        except ValueError as exc:self.status.setText(str(exc))

    def add_component(self):
        if self.inspection_only: return
        if not self.editable: self.editRequested.emit(); return
        from .electrical_dialog import ComponentDialog
        dialog = ComponentDialog(self, self.parts)
        dialog.kind.setCurrentIndex(dialog.kind.findData(self.kind_combo.currentData()))
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted: return
            self._replace_component(dialog.candidate()); self.fit_scene()
        finally: dialog.deleteLater()

    def edit_selected(self):
        if self.inspection_only: return
        if not self.editable: self.editRequested.emit(); return
        identifier = self._selected_id()
        if identifier: self.edit_component(identifier)

    def edit_component(self, identifier):
        if self.inspection_only: return
        if not self.editable: self.editRequested.emit(); return
        from .electrical_dialog import ComponentDialog
        dialog = ComponentDialog(self, self.parts, self._component(identifier).model_dump())
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._replace_component(dialog.candidate())
        finally: dialog.deleteLater()

    def _replace_component(self, candidate):
        if self.inspection_only: return
        old = next((c for c in self.workspace.components if c.id == candidate['id']), None)
        previous_part_id = old.part_id if old else ''
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
        try:
            from .electrical_part_dialog import validate_circuit_cad_assignment
            parts, workspace = validate_circuit_cad_assignment(self.parts, ElectricalWorkspace.model_validate(raw), candidate['id'], previous_part_id, self.design_reference)
            self.parts = parts; self._adopt(workspace)
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
            column = 0 if c.kind == 'battery' else 1 if c.kind in ('wire','switch','resistor','capacitor','inductor') else 2 if c.kind == 'mcu' else 3
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
        if self.inspection_only: return
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
        selected=self._selected_id()
        blocked=self.scene.blockSignals(True)
        notify=self._selection_emitting
        self._selection_emitting=False
        try:
            self._route_body()
            if selected:
                for item in self._route_items:
                    if item.data(WIRE_ROLE)==selected:item.setSelected(True);break
            # Rerouting updates inspectors and restores a selected wire; it is
            # not a user selection. Do not reopen CAD panels on Fit or resize.
            self._selection_changed()
        finally:
            self._selection_emitting=notify
            self.scene.blockSignals(blocked)

    def _route_body(self):
        for item in self._route_items: self.scene.removeItem(item)
        self._route_items.clear()
        self.net_segments.clear()
        self.junction_items.clear()
        self.branch_layout.clear()
        self.branch_items.clear()
        self.endpoint_coordinates.clear()
        self.wire_paths={}
        direct={}
        if self.view_mode=='physical':
            for c in self.workspace.components:
                if c.kind!='wire' or len(c.wire_endpoints)!=2:continue
                rows=[]
                for reference,node in zip(c.wire_endpoints,(c.a,c.b)):
                    endpoint=self.component_items.get(reference.component_id)
                    # Wire-to-wire references have no stable physical pad when
                    # the referenced branch itself is drawn as a direct path.
                    # Preserve their conductive A/B nodes using the ordinary
                    # symbol/net view; never resolve recursive/self anchors.
                    if endpoint is None or endpoint.component.kind=='wire' or reference.terminal not in endpoint.ports:break
                    port=endpoint.ports[reference.terminal]
                    if port.node!=node:break
                    rows.append((reference.component_id,reference.terminal,endpoint.port_scene_position(reference.terminal),port))
                if len(rows)==2:direct[c.id]=rows
        nets = defaultdict(list)
        rectangles = [item.sceneBoundingRect() for item in self.component_items.values()]
        results = {b.id: b for b in self.result.components} if self.result else {}
        for c in self.workspace.components:
            item = self.component_items[c.id]
            item.setVisible(c.id not in direct)
            active = c.kind not in ('wire','switch','battery') or c.closed
            ax, bx = item.port_scene_position('a'), item.port_scene_position('b')
            layout = dict(a=c.a, b=c.b, a_x=ax.x(), b_x=bx.x(), row_y=ax.y(), kind=c.kind, active=active, signals={})
            self.branch_items[c.id] = [item, *item.childItems()]
            for key, port in item.ports.items():
                point = item.port_scene_position(key)
                self.endpoint_coordinates[(c.id, key)] = point
                if port.node and c.id not in direct:
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
            if c.id not in direct:self._text(state, QPointF(item.sceneBoundingRect().left()+5, item.sceneBoundingRect().bottom()+3), OPEN if not active else BUS, 8)
        from .circuit_routing import route_nets
        visible_items={key:item for key,item in self.component_items.items() if key not in direct}
        bodies = [item.mapRectToScene(item.body_rect) for item in visible_items.values()]
        unassigned = [item.port_scene_position(key) for item in visible_items.values()
                      for key, port in item.ports.items() if port.node is None]
        if self.view_mode=='physical':
            from .pictorial_wiring import physical_routes
            routed=physical_routes(nets,visible_items)
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
        # A saved resistive wire is a distinct branch between two real terminals,
        # not a zero-resistance net-name merge. Keep its actual endpoint identity.
        if direct:
            from .circuit_routing import _point,_on_segment
            occupied=dict(routed.segments)
            for identifier,rows in direct.items():
                c=self._component(identifier);anchors={_point(row[2]) for row in rows}
                reserves=[item.port_scene_position(key) for keyid,item in visible_items.items()
                    for key,port in item.ports.items() if (keyid,key) not in {(row[0],row[1]) for row in rows}]
                exclusions={key:[(a,b) for a,b in segments if not any(_on_segment(point,_point(a),_point(b)) for point in anchors)]
                    for key,segments in occupied.items()}
                route=physical_routes({identifier:rows},visible_items,reserved_points=reserves,reserved_segments=exclusions)
                color=QColor(c.wire_color or '#297DC2')
                if route.unrouted:
                    # Explicit paired branch labels are truthful when no safe path
                    # can fit. Never invent an alternate pin or short a shared net.
                    for _,_,point,_ in rows:
                        self._text(f'{c.name} [{c.id}] · {c.a} ↔ {c.b}',point+QPointF(8,-40),color,8)
                    self.component_items[identifier].setVisible(True)
                    continue
                path=QPainterPath()
                for a,b in route.segments[identifier]:path.moveTo(a);path.lineTo(b)
                item=SelectableWirePath(path);pen=QPen(color,3)
                if not c.closed or not c.analysis_enabled:pen.setStyle(Qt.PenStyle.DashLine)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap);item.setPen(pen)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable,True)
                item.setData(WIRE_ROLE,identifier);item.setZValue(14)
                state=' · 0 A' if not c.closed else ''
                item.setToolTip(f'{c.name} [{c.id}] · {c.a} ↔ {c.b}\n{c.length_mm:g} mm · {c.cross_section_mm2:g} mm²{state}')
                self.scene.addItem(item);self._route_items.append(item);self.wire_paths[identifier]=item
                occupied[identifier]=route.segments[identifier]
                middle=rows[0][2]+(rows[1][2]-rows[0][2])/2
                self._text(c.name+state,middle+QPointF(5,-23),color,8)
                self.branch_items[identifier]=[item]
        if routed.unrouted:
            self.routing_note = self._word(
                f'{len(routed.unrouted)}개 단자를 같은 노드 라벨로 연결 표시합니다. 자동 배치나 부품 이동으로 배선을 정리할 수 있습니다.',
                f'{len(routed.unrouted)} terminals use matching net labels. Auto arrange or move components to simplify wiring.')
            visible = self.visible_scene_bounds()
            self._text(self.routing_note, QPointF(visible.left(), visible.bottom()+35), BUS, 9)
        else:
            self.routing_note = ''
        if not rectangles:
            self._text(self._word('회로가 비어 있습니다. 위에서 보드·배터리·모터·저항·스위치를 추가하세요.',
                'Empty circuit. Add a board, battery, motor, actuator, resistor, capacitor, coil or switch above.'), QPointF(40,80), INK, 13)
        from ..board_supply import board_supply_warnings
        warnings=board_supply_warnings(self.workspace,self.result,language='en' if self.english else 'ko')
        visible=list(warnings[:4])
        if len(warnings)>4:visible.append(self._word(f'그 외 {len(warnings)-4}개 · 마우스를 올려 상세 확인',f'{len(warnings)-4} more · hover for details'))
        warning_details='\n'.join(warnings)[:12000]
        self.supply_warnings.setText('\n'.join(visible));self.supply_warnings.setToolTip(warning_details)
        self.supply_warnings.setVisible(bool(warnings) and not self.inspection_only)
        if self.inspection_only:
            # Inspection summaries remain available without covering the
            # before/after canvas with hidden editor widgets.
            self.view.setToolTip(warning_details)
            self.preview_warnings.setText(self._word(f'전원 경고 {len(warnings)}개', f'{len(warnings)} power warnings') if warnings else '')
            self.preview_warnings.setToolTip(warning_details)
            self.preview_warnings.setVisible(bool(warnings))
        bounds = self.visible_scene_bounds().adjusted(-35,-35,35,35)
        self.scene.setSceneRect(bounds)

    def visible_scene_bounds(self):
        """Physical wire paths replace hidden symbols; hidden positions are not framing."""
        bounds = QRectF()
        for item in (*self.component_items.values(), *self._route_items):
            if item.isVisible(): bounds = bounds.united(item.sceneBoundingRect())
        return bounds

    def fit_scene(self):
        self.route_timer.stop()
        self._route()
        self._fit_view()

    def _fit_view(self):
        # A layout resize changes the viewport, not the circuit topology. Avoid
        # deleting/recreating routed graphics from an asynchronous resize.
        if not self.isVisible(): return
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_view()
        self.fit_timer.start(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.inspection_only and hasattr(self, 'fit_timer'): self.fit_timer.start(0)

    def accept(self):
        if not self.editable: return
        self.fit_timer.stop()
        self.route_timer.stop()
        self.accepted_workspace = ElectricalWorkspace.model_validate(self.workspace.model_dump()).model_copy(deep=True)
        self.accepted_parts = deepcopy(list(self.parts))
        super().accept()

    def reject(self):
        self.fit_timer.stop()
        self.route_timer.stop()
        self.accepted_workspace = None; self.accepted_parts = None; self.ai_request = None
        super().reject()
