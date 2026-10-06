"""A transactional electrical workspace joining CAD bodies, products and wiring.

The table is an index of the current Design, not a second electrical model.
Readiness is structural inspection; no implicit DC solve or hardware approval.
Child editors operate on drafts and only the outer Save returns a Design.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget)

from ..models import Design
from ..electrical import ElectricalWorkspace
from ..electrical_catalog import CATALOG, get_catalog_entry
from .mcu_pin_dialog import PinDiagramView, word, english
from .widgets import button, label


KIND_LABELS = {
    'mcu': ('MCU / MPU', 'MCU / MPU'), 'battery': ('전원', 'Supply'),
    'load': ('센서 / 전자제품', 'Sensor / device'), 'motor': ('모터', 'Motor'),
    'actuator': ('액추에이터', 'Actuator'), 'resistor': ('저항', 'Resistor'),
    'capacitor': ('커패시터', 'Capacitor'), 'inductor': ('코일', 'Inductor'),
    'switch': ('스위치', 'Switch'), 'wire': ('전선', 'Wire'),
    'cad': ('미등록 CAD', 'Unregistered CAD'),
}
REGISTRATION_LABELS = {
    'registered': ('등록됨', 'Registered'), 'legacy': ('기존 연결', 'Legacy link'),
    'unregistered': ('미등록', 'Unregistered'), 'duplicate': ('중복 CAD 연결', 'Duplicate CAD link'),
    'circuit_only': ('회로 항목', 'Circuit item'),
}


@dataclass(frozen=True)
class WorkspaceRow:
    key: str
    name: str
    kind: str
    part_id: str
    component_id: str
    model_name: str
    registration: str
    inspection: str
    search_text: str


class ElectricalWorkbenchDialog(QDialog):
    """One native entrypoint for discovery, registration, wiring and inspection."""
    partActivated = Signal(str)

    def __init__(self, parent, design, part_id=None):
        super().__init__(parent)
        self.setWindowTitle(word('전장 작업 · CAD 부품 / 실제 제품 / 핀 / 배선',
                                 'Electrical workspace · CAD / products / pins / wiring'))
        self.setObjectName('electricalWorkbench')
        self.resize(1280, 780)
        self.setMinimumSize(820, 500)
        self.original = Design.model_validate(design)
        self.draft = self.original.model_copy(deep=True)
        self.checked = None
        self.ai_request = None
        self._changed = False
        self._rows = []
        self._visible_rows = []
        self._components = {}
        self._parts = {}
        self._component_reports = {}
        self._part_reports = {}
        self._entries = {entry.catalog_id: entry for entry in CATALOG}
        self._selected_key = 'part:' + part_id if part_id else ''
        self._metadata_candidates = ()

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        self.counts_label = QLabel()
        self.counts_label.setObjectName('electricalWorkbenchCounts')
        self.counts_label.setWordWrap(True)
        self.counts_label.setStyleSheet('font-size:15px;font-weight:600;padding:8px;border:1px solid #34515c;border-radius:6px;')
        layout.addWidget(self.counts_label)
        self.overview = label('', True)
        self.overview.setObjectName('electricalWorkbenchOverview')
        layout.addWidget(self.overview)

        self.tabs = QTabWidget()
        self.tabs.setObjectName('electricalWorkbenchTabs')
        self.tabs.setMinimumHeight(0)
        layout.addWidget(self.tabs, 1)
        self._create_project_page()
        self._create_catalog_page()

        self.notice = label(word(
            '색상만으로 전장 등록되지 않습니다. 미등록 부품을 선택해 실제 모델과 핀을 지정하세요. 미확인 값은 보류하며 등록·배선 점검은 실물 구동 승인과 다릅니다.',
            'Color does not register electronics. Select an unregistered CAD body and assign its actual model and pins. Unknown data stays pending; registration and wiring inspection do not approve hardware operation.'), True)
        self.notice.setObjectName('electricalWorkbenchNotice')
        layout.addWidget(self.notice)
        controls = QDialogButtonBox()
        self.apply_button = controls.addButton(word('전장 변경 저장', 'Save electrical changes'), QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_button.setObjectName('electricalWorkbenchApply')
        self.apply_button.setProperty('primary', True)
        self.cancel_button = controls.addButton(word('취소 / 닫기', 'Cancel / close'), QDialogButtonBox.ButtonRole.RejectRole)
        self.cancel_button.setObjectName('electricalWorkbenchCancel')
        controls.accepted.connect(self.accept)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)
        self.refresh()
        self.filter_catalog()

    def _create_project_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        filters = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setObjectName('electricalWorkbenchSearch')
        self.query.setPlaceholderText(word('부품 이름 · CAD ID · 실제 모델 검색', 'Find a part name · CAD ID · actual model'))
        filters.addWidget(self.query, 1)
        self.kind_filter = QComboBox()
        self.kind_filter.setObjectName('electricalWorkbenchKind')
        self.kind_filter.addItem(word('모든 종류', 'All kinds'), '')
        for key, names in KIND_LABELS.items(): self.kind_filter.addItem(word(*names), key)
        filters.addWidget(self.kind_filter)
        self.state_filter = QComboBox()
        self.state_filter.setObjectName('electricalWorkbenchState')
        for key, ko, en in [('', '모든 상태', 'All states'), ('unregistered', '미등록', 'Unregistered'),
                ('registered', '등록됨', 'Registered'), ('legacy', '기존 연결', 'Legacy links'),
                ('pending', '입력 / 확인 필요', 'Inputs / review pending'), ('blocked', '연결 문제', 'Connection issues'),
                ('circuit_only', 'CAD 연결 없음', 'No CAD link')]:
            self.state_filter.addItem(word(ko, en), key)
        filters.addWidget(self.state_filter)
        self.all_cad = QCheckBox(word('모든 CAD 부품', 'All CAD bodies'))
        self.all_cad.setObjectName('electricalWorkbenchAllCad')
        self.all_cad.setToolTip(word('전장 역할이 아닌 부품도 찾아 수동 등록합니다.', 'Find and register bodies that do not have an electrical role.'))
        filters.addWidget(self.all_cad)
        layout.addLayout(filters)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 6)
        self.table.setObjectName('electricalWorkbenchParts')
        self.table.setHorizontalHeaderLabels([word('부품 / 회로 항목', 'Part / circuit item'), word('실제 모델', 'Actual model'),
            word('종류', 'Kind'), word('등록', 'Registration'), word('점검', 'Inspection'), word('CAD 부품', 'CAD body')])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        for index, width in enumerate((185, 190, 112, 105, 120, 125)): self.table.setColumnWidth(index, width)
        left_layout.addWidget(self.table, 1)
        self.result_count = label('', True)
        self.result_count.setObjectName('electricalWorkbenchResultCount')
        left_layout.addWidget(self.result_count)
        actions = QHBoxLayout()
        self.register_button = button(word('선택 부품 등록 / 편집…', 'Register / edit selected…'), self.register_selected, True)
        self.register_button.setObjectName('electricalWorkbenchRegister')
        actions.addWidget(self.register_button)
        self.focus_button = button(word('CAD에서 보기', 'Show in CAD'), self.focus_selected)
        self.focus_button.setObjectName('electricalWorkbenchFocus')
        actions.addWidget(self.focus_button)
        actions.addStretch(1)
        left_layout.addLayout(actions)
        correspondence = QHBoxLayout()
        self.link_button = button(word('기존 회로 ↔ CAD 대응…', 'Link existing circuit ↔ CAD…'), self.link_selected)
        self.link_button.setObjectName('electricalWorkbenchLink'); correspondence.addWidget(self.link_button)
        self.ai_button = button(word('AI 배선 요청…', 'Prepare AI wiring…'), self.prepare_ai_request)
        self.ai_button.setObjectName('electricalWorkbenchAiRequest'); correspondence.addWidget(self.ai_button)
        correspondence.addStretch(1); left_layout.addLayout(correspondence)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)
        self.selected_title = QLabel(word('부품을 선택하세요.', 'Select a part.'))
        self.selected_title.setWordWrap(True)
        self.selected_title.setStyleSheet('font-weight:600;font-size:14px;')
        self.selected_title.setObjectName('electricalWorkbenchSelectedTitle')
        right_layout.addWidget(self.selected_title)
        detail_tabs = self.detail_tabs = QTabWidget()
        detail_tabs.setMinimumHeight(0)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setObjectName('electricalWorkbenchDetails')
        detail_tabs.addTab(self.details, word('모델 / 전원', 'Model / power'))
        self.diagram = PinDiagramView(self)
        self.diagram.setObjectName('electricalWorkbenchDiagram')
        self.diagram.setToolTip(word('휠: 핀 모식도 확대 / 축소 · 드래그: 이동 · 등록 / 편집에서 핀 연결을 변경합니다.',
            'Wheel: zoom pin diagram · drag: pan · use Register / edit to change pin connections.'))
        detail_tabs.addTab(self.diagram, word('실제 핀 / 단자', 'Physical pins / terminals'))
        self.issues = QListWidget()
        self.issues.setObjectName('electricalWorkbenchIssues')
        self.issues.setWordWrap(True)
        detail_tabs.addTab(self.issues, word('확인할 항목', 'Items to resolve'))
        detail_tabs.currentChanged.connect(lambda *_: self.diagram.fit())
        right_layout.addWidget(detail_tabs, 1)
        self.source_button = button(word('선택 모델 공식 자료', 'Official reference for selected model'), self.open_selected_source)
        self.source_button.setObjectName('electricalWorkbenchSource')
        right_layout.addWidget(self.source_button)
        self.metadata_button = button(word('제품 자료에서 찾기', 'Find from product metadata'), self.find_product_metadata)
        self.metadata_button.setObjectName('electricalWorkbenchMetadataFind')
        self.metadata_button.setToolTip(word('저장된 제조사·정확한 모델명이 일치하는 자료를 찾습니다. 자동 등록하거나 기존 핀을 바꾸지 않습니다.',
            'Find exact manufacturer / model matches from stored metadata. This does not register a product or change any existing pins.'))
        right_layout.addWidget(self.metadata_button)
        splitter.addWidget(right)
        splitter.setSizes([820, 390])
        layout.addWidget(splitter, 1)

        circuit_actions = QHBoxLayout()
        self.schematic_button = button(word('회로도 · 핀 / 전선 연결…', 'Schematic · pins / wires…'), self.edit_schematic)
        self.schematic_button.setObjectName('electricalWorkbenchSchematic')
        circuit_actions.addWidget(self.schematic_button)
        self.power_button = button(word('전원 · 정격 · 배선 편집…', 'Supply · ratings · wiring…'), self.edit_circuit)
        self.power_button.setObjectName('electricalWorkbenchPower')
        circuit_actions.addWidget(self.power_button)
        self.inspection_button = button(word('등록 / 연결 점검 새로고침', 'Refresh registration / wiring inspection'), self.refresh)
        self.inspection_button.setObjectName('electricalWorkbenchRefresh')
        circuit_actions.addWidget(self.inspection_button)
        circuit_actions.addStretch(1)
        layout.addLayout(circuit_actions)
        self.tabs.addTab(page, word('현재 설계의 전장', 'Electronics in this design'))
        self.query.textChanged.connect(self.filter_rows)
        self.kind_filter.currentIndexChanged.connect(self.filter_rows)
        self.state_filter.currentIndexChanged.connect(self.filter_rows)
        self.all_cad.toggled.connect(self.filter_rows)
        self.table.itemSelectionChanged.connect(self.show_selected)
        self.table.doubleClicked.connect(lambda *_: self.register_selected())

    def _create_catalog_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(label(word('정확한 제품과 제품군 자료를 구분합니다. 등록 가능한 모델에도 실측 정격과 전원·핀 배선을 직접 확인해야 합니다.',
            'Exact products are separate from family references. Even a registerable model needs operating inputs and explicit power / pin connections.'), True))
        filters = QHBoxLayout()
        self.catalog_query = QLineEdit()
        self.catalog_query.setObjectName('electricalWorkbenchCatalogSearch')
        self.catalog_query.setPlaceholderText(word('제조사 · 모델명 · 제품군 검색', 'Find a manufacturer · model · family'))
        filters.addWidget(self.catalog_query, 1)
        self.catalog_category = QComboBox()
        self.catalog_category.setObjectName('electricalWorkbenchCatalogCategory')
        self.catalog_category.addItem(word('모든 분류', 'All categories'), '')
        for category in sorted({entry.category for entry in CATALOG}): self.catalog_category.addItem(category, category)
        filters.addWidget(self.catalog_category)
        self.catalog_registerable = QCheckBox(word('등록 가능 모델만', 'Registerable models only'))
        self.catalog_registerable.setObjectName('electricalWorkbenchCatalogRegisterable')
        filters.addWidget(self.catalog_registerable)
        layout.addLayout(filters)
        self.catalog_counts_label = label('', True)
        self.catalog_counts_label.setObjectName('electricalWorkbenchCatalogCounts')
        layout.addWidget(self.catalog_counts_label)
        self.catalog_table = QTableWidget(0, 4)
        self.catalog_table.setObjectName('electricalWorkbenchCatalog')
        self.catalog_table.setHorizontalHeaderLabels([word('분류', 'Category'), word('제조사', 'Manufacturer'), word('제품 / 제품군', 'Product / family'), word('지원', 'Support')])
        self.catalog_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.catalog_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.catalog_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.catalog_table.setAlternatingRowColors(True)
        self.catalog_table.verticalHeader().hide()
        self.catalog_table.horizontalHeader().setStretchLastSection(True)
        for index, width in enumerate((180, 130, 510)): self.catalog_table.setColumnWidth(index, width)
        layout.addWidget(self.catalog_table, 1)
        self.catalog_details = QPlainTextEdit()
        self.catalog_details.setReadOnly(True)
        self.catalog_details.setMaximumHeight(110)
        self.catalog_details.setObjectName('electricalWorkbenchCatalogDetails')
        layout.addWidget(self.catalog_details)
        actions = QHBoxLayout()
        self.catalog_source_button = button(word('공식 제품 자료 열기', 'Open official reference'), self.open_catalog_source)
        actions.addWidget(self.catalog_source_button)
        actions.addStretch(1)
        self.catalog_use_button = button(word('선택한 CAD 부품에 등록…', 'Register on selected CAD body…'), self.use_catalog_model, True)
        self.catalog_use_button.setObjectName('electricalWorkbenchCatalogUse')
        actions.addWidget(self.catalog_use_button)
        layout.addLayout(actions)
        self.tabs.addTab(page, word('제품 카탈로그', 'Product catalog'))
        self.catalog_query.textChanged.connect(self.filter_catalog)
        self.catalog_category.currentIndexChanged.connect(self.filter_catalog)
        self.catalog_registerable.toggled.connect(self.filter_catalog)
        self.catalog_table.itemSelectionChanged.connect(self.show_catalog_selected)

    def refresh(self, *_):
        from ..electrical_readiness import build_electrical_readiness
        self.report = build_electrical_readiness(self.draft, language='en' if english() else 'ko')
        self._parts = {part.id: part for part in self.draft.parts}
        self._components = {component.id: component for component in (self.draft.electrical.components if self.draft.electrical else ())}
        self._component_reports = {row.component_id: row for row in self.report.components}
        self._candidate_ids = {row.part_id for row in self.report.parts}
        self._part_reports = {row.part_id: row for row in self.report.parts}
        linked_ids = set()
        rows = []
        for component in self._components.values():
            item = self._component_reports[component.id]
            entry = self._entries.get(component.catalog_id)
            model_name = entry.display_name if entry else component.catalog_id or word('사용자 정의', 'Custom')
            issues = (*item.issues, *getattr(self._part_reports.get(component.part_id), 'issues', ()))
            inspection = 'blocked' if any(issue.severity == 'blocked' for issue in issues) else 'pending' if any(issue.severity == 'pending' for issue in issues) else 'review'
            part = self._parts.get(component.part_id)
            if part: linked_ids.add(part.id)
            rows.append(WorkspaceRow('component:' + component.id, component.name, component.kind,
                component.part_id, component.id, model_name, item.registration_status, inspection,
                ' '.join((component.name, component.id, component.kind, component.part_id, part.name if part else '', model_name, component.catalog_id)).casefold()))
        for part in self.draft.parts:
            if part.id in linked_ids: continue
            rows.append(WorkspaceRow('part:' + part.id, part.name, 'cad', part.id, '',
                word('모델 지정 전', 'Model not assigned'), 'unregistered', 'pending',
                ' '.join((part.name, part.id, part.role)).casefold()))
        def row_priority(row):
            # Keep incomplete physical registrations visible above a project's
            # many wire rows. Preserve source order within each category.
            if not row.component_id:
                part = self._parts.get(row.part_id)
                return 0 if part and part.role == 'electrical' else 4
            if row.kind == 'wire': return 3
            return 1 if row.part_id in self._parts else 2
        self._rows = sorted(rows, key=row_priority)
        counts = self.report.counts
        self.counts_label.setText(word('전장 CAD {electrical_parts}개   ·   등록 {registered_parts}개   ·   미등록 {unregistered_parts}개   ·   확인 필요 {pending_components}개   ·   연결 문제 {blocked_components}개',
            'Electrical CAD {electrical_parts}   ·   Registered {registered_parts}   ·   Unregistered {unregistered_parts}   ·   Pending {pending_components}   ·   Connection issues {blocked_components}').format(**counts))
        self.overview.setText(word('회로 항목 {components}개 · 전선 {wires}개 · 기존 CAD 연결 {legacy_components}개 · 사용자 정의 {custom_components}개 · 확인된 모식도 없음 {missing_diagrams}개. 저장 전 변경은 이 창의 초안에만 반영됩니다.',
            'Circuit items {components} · Wires {wires} · Legacy CAD links {legacy_components} · Custom {custom_components} · No verified diagram {missing_diagrams}. Changes stay in this draft until saved.').format(**counts))
        self.apply_button.setEnabled(self._changed or bool(self.ai_request))
        self.filter_rows()

    def filter_rows(self, *_):
        selected = self.selected_row()
        preferred = selected.key if selected else self._selected_key
        query = self.query.text().strip().casefold()
        kind = self.kind_filter.currentData()
        state = self.state_filter.currentData()
        self._visible_rows = [row for row in self._rows
            if (self.all_cad.isChecked() or row.component_id or row.part_id in self._candidate_ids)
            and (not query or query in row.search_text) and (not kind or row.kind == kind)
            and (not state or state in (row.registration, row.inspection))]
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(self._visible_rows))
        for index, row in enumerate(self._visible_rows):
            registration = word(*REGISTRATION_LABELS.get(row.registration, ('기존 연결', 'Legacy link')))
            status = word('연결 문제', 'Connection issue') if row.inspection == 'blocked' else word('확인 필요', 'Pending review') if row.inspection == 'pending' else word('입력 기준 점검', 'Input-based review')
            part = self._parts.get(row.part_id)
            values = (row.name, row.model_name, word(*KIND_LABELS[row.kind]), registration, status,
                      part.name if part else word('CAD 연결 없음', 'No CAD link'))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value + ('\n' + row.part_id if column == 5 and row.part_id else ''))
                if column == 4: item.setForeground(QColor('#ef8982' if row.inspection == 'blocked' else '#e8bc6c' if row.inspection == 'pending' else '#76c7b4'))
                self.table.setItem(index, column, item)
        selected_index = next((index for index, row in enumerate(self._visible_rows)
                               if row.key == preferred or (preferred.startswith('part:') and row.part_id == preferred[5:])), 0)
        if self._visible_rows: self.table.selectRow(selected_index)
        else: self.table.clearSelection()
        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)
        self.result_count.setText(word('표시 {count}개 · 더블클릭: 등록 / 편집', 'Showing {count} items · double-click: register / edit').format(count=len(self._visible_rows)))
        self.show_selected()

    def selected_row(self):
        index = self.table.currentRow()
        return self._visible_rows[index] if 0 <= index < len(self._visible_rows) else None

    def show_selected(self):
        row = self.selected_row()
        self.register_button.setEnabled(bool(row))
        self.focus_button.setEnabled(bool(row and row.part_id in self._parts))
        self.link_button.setEnabled(bool(self.selected_row() and self.draft.electrical and self.draft.electrical.components))
        self.source_button.setEnabled(False)
        self.metadata_button.setEnabled(False)
        self._metadata_candidates = ()
        self.issues.clear()
        if not row:
            self.selected_title.setText(word('선택한 항목 없음', 'No selected item'))
            self.details.setPlainText(word('검색어 또는 필터를 변경하세요. 모든 CAD 부품에서 다른 부품도 등록할 수 있습니다.', 'Change the search or filters. Enable All CAD bodies to register another body.'))
            self.diagram.draw(None, ())
            self.show_catalog_selected()
            return
        self._selected_key = row.key
        self.selected_title.setText(row.name)
        component = self._components.get(row.component_id)
        lines = [word('CAD 부품', 'CAD body') + ': ' + (row.part_id or word('연결 없음', 'Not linked')),
                 word('등록 상태', 'Registration') + ': ' + word(*REGISTRATION_LABELS[row.registration])]
        part = self._parts.get(row.part_id)
        if part and part.product:
            from ..electrical_catalog import catalog_model_candidates
            self._metadata_candidates = catalog_model_candidates(part.product.manufacturer, part.product.model)
            lines += ['', word('저장된 제품 자료', 'Stored product metadata') + ': ' + part.product.manufacturer + ' / ' + part.product.model]
            if self._metadata_candidates:
                lines += [word('정확한 모델명 자료 후보 · 적용 전 검토 필요', 'Exact model reference candidate · review before applying'),
                          *[entry.display_name for entry in self._metadata_candidates],
                          word('제품 자료 일치는 실물 형상·핀의 동일성 증명이 아닙니다. IC 자료를 사용자 보드/캐리어의 회로로 대체하지 마세요.',
                               'A metadata match does not prove identical physical geometry or pins. An IC reference must not replace a custom board / carrier circuit.')]
                self.metadata_button.setEnabled(True)
        if component:
            from .electrical_part_dialog import feature_connections
            from ..product_diagrams import product_diagram
            entry = self._entries.get(component.catalog_id)
            item = self._component_reports[component.id]
            power_status = {'documented': ('물리 전원 핀 지정됨 · 실물 미검증', 'Physical supply pins assigned · hardware unverified'),
                'missing': ('물리 전원 핀 지정 필요', 'Physical supply pin assignment needed'),
                'isolated': ('외부 전원 경로 없음', 'No external supply path'),
                'not_applicable': ('해당 없음', 'Not applicable'),
                'undocumented': ('물리 전원 단자 자료 미확인', 'Physical supply terminal reference unknown')}
            lines += [word('실제 모델', 'Actual model') + ': ' + row.model_name,
                word('전원 / 리턴 노드', 'Power / return nets') + ': ' + component.a + ' / ' + component.b,
                word('공급 연결 문서', 'Power connection documentation') + ': ' + word(*power_status[item.power_status]),
                word('연결 지정 / 지원 단자', 'Assigned / supported terminals') + f': {item.assigned_terminals} / {item.available_terminals}',
                word('DC 계산', 'DC analysis') + ': ' + (word('입력값으로 포함 · 실물 검증 아님', 'Included using entered values · not hardware validation') if component.analysis_enabled else word('동작 정격 미확인 / 미지원 · 계산 제외', 'Operating ratings unknown / unsupported · excluded'))]
            for title, connected in ((word('양극 도통 경로', 'Passive positive supply path'), item.supply_path_connected),
                    (word('리턴 도통 경로', 'Passive return path'), item.return_path_connected)):
                if connected is not None:
                    lines += [title + ': ' + (word('외부 전원 경로 있음 · 전압 / 구동 미검증', 'External source path exists · voltage / operation unverified') if connected else word('외부 전원 경로 없음', 'No external source path'))]
            if component.kind == 'battery':
                voltage = f'{component.voltage_v:g} V' if component.voltage_v > 0 else word('미입력', 'Not entered')
                lines += [word('지정 전원', 'Declared supply') + ': ' + voltage, word('전원 ON', 'Power ON') if component.closed else word('전원 OFF', 'Power OFF')]
            elif component.kind in ('load', 'motor', 'actuator', 'mcu'):
                voltage = f'{component.rated_voltage_v:g} V' if component.rated_voltage_v > 0 else word('전압 미입력', 'Voltage not entered')
                current = f'{component.rated_current_a:g} A' if component.rated_current_a > 0 else word('소비전류 미입력', 'Operating current not entered')
                lines += [word('입력 정격', 'Entered ratings') + ': ' + voltage + ' / ' + current]
            if component.kind == 'wire': lines += [f'{word("길이 / 도체 단면", "Length / conductor section")}: {component.length_mm:g} mm / {component.cross_section_mm2:g} mm²']
            for title, mapping in [(word('보드 전원 핀', 'Board supply pins'), component.board_supply_pins),
                    (word('신호 핀', 'Signal pins'), component.signal_pins), (word('제품 단자', 'Product terminals'), component.terminal_pins)]:
                if mapping: lines += ['', title, *[key + ' → ' + value for key, value in mapping.items()]]
            if entry: lines += ['', entry.spec_summary]
            if component.source_url: lines += ['', word('공식 출처', 'Official source') + ': ' + component.source_url]
            self.source_button.setEnabled(bool(component.source_url or entry and entry.source_url))
            self.diagram.draw(component, feature_connections(component, self.draft.electrical), diagram=product_diagram(component.catalog_id))
            self.diagram.fit()
            issues = (*item.issues, *getattr(self._part_reports.get(row.part_id), 'issues', ()))
        else:
            lines += ['', word('형상은 있지만 전장 모델이 등록되지 않았습니다. 등록 / 편집에서 모델·단자·전원을 연결하세요.',
                               'This CAD body has no electrical registration. Use Register / edit to assign its model, terminals and power.'),
                      word('단순 하우징·예약 공간이면 부하로 억지 등록하지 말고 CAD 속성에서 부품 역할을 검토하세요.',
                           'If this is only a housing or reserved space, review its role in CAD properties instead of inventing an electrical load.')]
            self.diagram.draw(None, ())
            issues = tuple(issue for issue in self.report.issues if issue.part_id == row.part_id)
        self.details.setPlainText('\n'.join(lines))
        for issue in issues:
            text = word('연결 문제', 'Connection issue') if issue.severity == 'blocked' else word('확인 필요', 'Pending') if issue.severity == 'pending' else word('참고', 'Info')
            item = QListWidgetItem(text + ' · ' + issue.message + ('\n' + issue.next_action if issue.next_action else ''))
            item.setToolTip(issue.code)
            self.issues.addItem(item)
        if not issues: self.issues.addItem(word('현재 문서 점검 항목 없음 · 실물 검증을 의미하지 않습니다.', 'No current documentation issues · this is not hardware validation.'))
        self.show_catalog_selected()

    def adopt_design(self, candidate):
        """Adopt a validated child draft; geometry/history are never rebuilt here."""
        candidate = Design.model_validate(candidate)
        if candidate == self.draft: return
        self.draft = candidate
        self._changed = self.draft != self.original
        self.refresh()

    def adopt_workspace(self, workspace):
        workspace = ElectricalWorkspace.model_validate(workspace)
        if workspace == self.draft.electrical: return
        # Structural copy retains all CAD objects and user metadata; only the
        # circuit field changes. Child editors already own independent models.
        self.adopt_design(self.draft.model_copy(update={'electrical': workspace}))

    def adopt_circuit_editor(self, editor):
        """Keep CAD role changes and queued requests in this private draft."""
        raw = self.draft.model_dump(mode='json')
        workspace = getattr(editor, 'accepted_workspace', None) or getattr(editor, 'workspace', None)
        if workspace is not None: raw['electrical'] = workspace.model_dump(mode='json')
        accepted_parts = getattr(editor, 'accepted_parts', None)
        if accepted_parts is not None: raw['parts'] = accepted_parts
        self.adopt_design(raw)
        if getattr(editor, 'ai_request', None): self.queue_ai_request(editor.ai_request)

    def link_selected(self):
        row = self.selected_row()
        if not row or not self.link_button.isEnabled(): return
        from .electrical_part_dialog import ElectricalCadLinkDialog
        dialog = ElectricalCadLinkDialog(self, self.draft, row.component_id or None, row.part_id or None)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.checked is not None: self.adopt_design(dialog.checked)
        finally: dialog.deleteLater()

    def queue_ai_request(self, request):
        self.ai_request = dict(request)
        self.apply_button.setText(word('전장 변경 저장 · AI 요청 준비', 'Save electrical changes · prepare AI'))
        self.apply_button.setEnabled(True)
        self.notice.setText(word('AI 요청 대기 중 · 저장하면 메인 AI 입력창으로 준비합니다. 초안 생성은 메인 버튼으로 시작하며 취소하면 요청을 폐기합니다.',
            'AI request queued · save prepares it in the main AI input. Generate draft starts it; cancel discards this request.'))

    def prepare_ai_request(self):
        from PySide6.QtWidgets import QInputDialog
        prompt, ok = QInputDialog.getMultiLineText(self, word('AI 배선 요청 준비', 'Prepare AI wiring request'),
            word('원하는 부품·핀·전선 변경을 입력하세요. 저장 후 메인 AI 입력창으로 준비합니다.', 'Describe component, pin or wire changes. Save prepares the request in the main AI input.'))
        if not ok or not prompt.strip(): return
        row = self.selected_row()
        self.queue_ai_request(dict(prompt=prompt.strip(), component_id=row.component_id if row else '', part_id=row.part_id if row else '', terminal=''))

    def register_selected(self, *_ , catalog_id=None):
        row = self.selected_row()
        if row is None: return
        if not row.part_id or row.part_id not in self._parts or row.registration == 'duplicate':
            self.edit_circuit()
            return
        from .electrical_part_dialog import ElectricalPartDialog
        dialog = ElectricalPartDialog(self, self.draft, row.part_id)
        try:
            if catalog_id:
                index = dialog.model_combo.findData(catalog_id)
                if index >= 0: dialog.model_combo.setCurrentIndex(index)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.checked is not None:
                self.adopt_design(dialog.checked)
        finally: dialog.deleteLater()

    def edit_schematic(self):
        from .electrical_schematic import ElectricalSchematicDialog
        workspace = self.draft.electrical or ElectricalWorkspace()
        dialog = ElectricalSchematicDialog(self, workspace, parts=[part.model_dump(mode='json') for part in self.draft.parts], design=self.draft)
        try:
            dialog.partActivated.connect(self.partActivated.emit)
            row = self.selected_row()
            if row and row.component_id: dialog.focus_component(row.component_id)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.accepted_workspace is not None:
                self.adopt_circuit_editor(dialog)
        finally: dialog.deleteLater()

    def edit_circuit(self):
        from .electrical_dialog import ElectricalDialog
        dialog = ElectricalDialog(self, self.draft.model_dump(mode='json'))
        try:
            row = self.selected_row()
            if row and row.component_id:
                index = next((index for index, component in enumerate(dialog.components) if component['id'] == row.component_id), -1)
                if index >= 0: dialog.table.selectRow(index)
            if dialog.exec() == QDialog.DialogCode.Accepted: self.adopt_circuit_editor(dialog)
        finally: dialog.deleteLater()

    def focus_selected(self):
        row = self.selected_row()
        if row and row.part_id in self._parts: self.partActivated.emit(row.part_id)

    def open_selected_source(self):
        row = self.selected_row()
        component = self._components.get(row.component_id) if row else None
        entry = self._entries.get(component.catalog_id) if component else None
        url = component.source_url or (entry.source_url if entry else '') if component else ''
        if url: QDesktopServices.openUrl(QUrl(url))

    def filter_catalog(self, *_):
        from ..electrical_catalog import catalog_counts, catalog_support
        query = self.catalog_query.text().strip().casefold()
        category = self.catalog_category.currentData()
        self._catalog_rows = [entry for entry in CATALOG
            if (not query or query in ' '.join((entry.display_name, entry.catalog_id, entry.category, *entry.aliases)).casefold())
            and (not category or entry.category == category)
            and (not self.catalog_registerable.isChecked() or catalog_support(entry.catalog_id) != 'reference')]
        self.catalog_table.blockSignals(True)
        self.catalog_table.setUpdatesEnabled(False)
        self.catalog_table.setRowCount(len(self._catalog_rows))
        support_names = {'board_pins': ('보드 핀 · 등록 가능', 'Board pins · registerable'),
            'terminals': ('제품 단자 · 등록 가능', 'Product terminals · registerable'),
            'manual': ('수동 단자 · 등록 가능', 'Manual terminals · registerable'),
            'reference': ('자료 전용 · 자동 등록 불가', 'Reference only · cannot auto-register')}
        for row, entry in enumerate(self._catalog_rows):
            for column, value in enumerate((entry.category, entry.manufacturer, entry.model, word(*support_names[catalog_support(entry.catalog_id)]))):
                self.catalog_table.setItem(row, column, QTableWidgetItem(value))
        if self._catalog_rows: self.catalog_table.selectRow(0)
        self.catalog_table.setUpdatesEnabled(True)
        self.catalog_table.blockSignals(False)
        counts = catalog_counts()
        self.catalog_counts_label.setText(word('전체 자료 {total}개 · 등록 가능 {registerable}개 · 자료 전용 {reference}개 · 현재 검색 {shown}개. 핀/단자 지원은 DC·펌웨어 시뮬레이션 지원과 다릅니다.',
            'All references {total} · Registerable {registerable} · Reference only {reference} · Showing {shown}. Pin / terminal support is separate from DC or firmware simulation support.').format(**counts, shown=len(self._catalog_rows)))
        self.show_catalog_selected()

    def selected_catalog_entry(self):
        index = self.catalog_table.currentRow()
        return self._catalog_rows[index] if hasattr(self, '_catalog_rows') and 0 <= index < len(self._catalog_rows) else None

    def show_catalog_selected(self):
        from ..electrical_catalog import catalog_support
        entry = self.selected_catalog_entry()
        row = self.selected_row()
        self.catalog_source_button.setEnabled(bool(entry and entry.source_url))
        eligible = bool(entry and catalog_support(entry.catalog_id) != 'reference' and row and row.part_id in self._parts and row.registration != 'duplicate')
        self.catalog_use_button.setEnabled(eligible)
        self.catalog_use_button.setToolTip(word('현재 설계 목록에서 먼저 CAD 부품을 선택하세요. 등록 창에서 미리보기 후 저장합니다.', 'Select a CAD body in the design list first. Preview and save in the registration dialog.'))
        if not entry:
            self.catalog_details.setPlainText(word('검색 결과 없음', 'No search results'))
            return
        destination = row.name if row and row.part_id in self._parts else word('CAD 부품 선택 필요', 'Select a CAD body')
        self.catalog_details.setPlainText(entry.display_name + '\n' + entry.spec_summary + '\n' + entry.source_url + '\n' + word('등록 대상: ', 'Registration target: ') + destination)

    def open_catalog_source(self):
        entry = self.selected_catalog_entry()
        if entry and entry.source_url: QDesktopServices.openUrl(QUrl(entry.source_url))

    def find_product_metadata(self):
        if not self._metadata_candidates: return
        self.catalog_category.setCurrentIndex(0)
        self.catalog_registerable.setChecked(False)
        self.catalog_query.setText(self._metadata_candidates[0].catalog_id)
        self.tabs.setCurrentIndex(1)

    def use_catalog_model(self):
        entry = self.selected_catalog_entry()
        if entry and self.catalog_use_button.isEnabled(): self.register_selected(catalog_id=entry.catalog_id)

    def reject(self):
        self.checked = None
        self.ai_request = None
        super().reject()

    def accept(self):
        if not self._changed and not self.ai_request: return
        try: self.checked = Design.model_validate(self.draft.model_dump(mode='json'))
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, word('전장 변경 확인', 'Check electrical changes'), str(exc)[:1200])
            return
        super().accept()
