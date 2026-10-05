"""Search source-backed materials and preview assignments to explicit CAD bodies."""
from __future__ import annotations

from copy import deepcopy
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QHBoxLayout, QLineEdit,
    QListWidget, QListWidgetItem, QPlainTextEdit, QTableWidget, QTableWidgetItem)

from .workflows import PreviewDialog, choice
from .widgets import button, label
from ..models import Design, Material
from ..material_catalog import UNITS, LABELS, categories, search_catalog, format_details
from ..material_assignments import assign_material, remove_material, custom_material


class MaterialDialog(PreviewDialog):
    """``checked`` is a complete validated design only after preview succeeds.

    Opening/searching never assigns a preset. Existing custom material and part
    colors remain untouched unless the user previews and explicitly applies.
    """
    def __init__(self, parent, design, part_id=None, *, part_ids=None):
        super().__init__(parent, '부품 재질 / 물성 목록',
            '적용할 부품 체크 → 재질 검색 또는 직접 입력 → 미리보기 → 적용. 미확인 물성은 빈칸이며 자동 추정하지 않습니다.')
        self.base = Design.model_validate(design).model_dump()
        initial = part_ids if part_ids is not None else part_id
        chosen = {initial} if isinstance(initial, str) else set(initial or ())
        self.entries = ()
        self.entry = None
        self.original_material = None
        self._preview_cache = getattr(parent, 'result', None)
        self._loading = True

        self.controls.addWidget(label('적용 대상 부품 · 체크한 부품만 변경'))
        self.targets = QListWidget()
        self.targets.setObjectName('materialTargetParts')
        self.targets.setMaximumHeight(135)
        for part in self.base['parts']:
            assigned = (part.get('material') or {}).get('name', '미지정')
            item = QListWidgetItem(part['name']+' · '+assigned)
            item.setData(Qt.ItemDataRole.UserRole, part['id'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if part['id'] in chosen else Qt.CheckState.Unchecked)
            self.targets.addItem(item)
        self.controls.addWidget(self.targets)
        self.target_status = label('', True)
        self.controls.addWidget(self.target_status)

        self.mode = choice([('preserve', '현재 재질 보기 · 변경 없음'),
            ('catalog', '선택한 목록 재질 적용'), ('custom', '사용자 물성 입력'), ('remove', '개별 재질 지정 해제')])
        self.controls.addWidget(self.mode)
        self.replace_existing = QCheckBox('기존 재질도 교체 · 체크한 부품만')
        self.controls.addWidget(self.replace_existing)

        self.query = QLineEdit()
        self.query.setObjectName('materialCatalogSearch')
        self.query.setPlaceholderText('6061 · 304 · PC · 씰 · Si 검색')
        self.controls.addWidget(self.query)
        self.category = choice([('', '전체 재질 분류')]+[(name, name) for name in categories()])
        self.controls.addWidget(self.category)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(('재질', '분류'))
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMaximumHeight(170)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.controls.addWidget(self.table)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setProperty('cadUserText', True)
        self.details.setMaximumHeight(155)
        self.controls.addWidget(self.details)
        self.sources = choice([])
        self.sources.setProperty('cadUserText', True)
        self.controls.addWidget(self.sources)
        source_row = QHBoxLayout()
        self.source_button = button('공식 자료 열기', self.open_source)
        self.catalog_button = button('선택 재질 미리보기', self.use_catalog)
        source_row.addWidget(self.source_button)
        source_row.addWidget(self.catalog_button)
        self.controls.addLayout(source_row)

        self.controls.addWidget(label('직접 입력 · 빈칸 = 미확인 · 밀도는 필수'))
        form = QFormLayout()
        self.controls.addLayout(form)
        self.name = QLineEdit()
        self.name.setProperty('cadUserText', True)
        form.addRow('재질 이름', self.name)
        self.behavior = choice([(None, '사용자 재질 · 모델 미지정'), ('isotropic', '등방성'),
                                ('anisotropic', '이방성'), ('nonlinear', '비선형 / 고무')])
        form.addRow('재질 모델', self.behavior)
        self.inputs = {}
        for key, unit in UNITS.items():
            field = QLineEdit()
            field.setPlaceholderText('미확인' if key != 'density' else '밀도 필수')
            field.setProperty('cadUserText', True)
            field.setObjectName('material_'+key)
            form.addRow(LABELS[key]+' · '+unit, field)
            self.inputs[key] = field
            field.textChanged.connect(self.manual_changed)
        self.controls.addWidget(button('현재 재질 다시 불러오기', self.load_current))
        self.controls.addWidget(label('밀도는 질량·관성에 사용합니다. E·ν·강도·열·흡수율은 조건과 출처를 함께 보관합니다. 인장해석 설정과 다른 부품을 자동 변경하지 않습니다.', True))
        self.controls.addStretch()

        self.query.textChanged.connect(self.search)
        self.category.currentIndexChanged.connect(self.search)
        self.table.itemSelectionChanged.connect(self.show_entry)
        self.targets.itemChanged.connect(self.target_changed)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.replace_existing.toggled.connect(self.schedule)
        self.name.textChanged.connect(self.manual_changed)
        self.behavior.currentIndexChanged.connect(self.manual_changed)
        self._loading = False
        self.load_current()
        self.search()

    def selected_part_ids(self):
        return tuple(self.targets.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.targets.count())
            if self.targets.item(index).checkState() == Qt.CheckState.Checked)

    def target_changed(self, *_):
        targets = self.selected_part_ids()
        self.target_status.setText(f'{len(targets)}개 부품 선택 · 기존 사용자 색상 유지')
        self.viewport.select_many(list(targets))
        self.schedule()

    def load_current(self, *_):
        self._loading = True
        targets = self.selected_part_ids()
        part = next((part for part in self.base['parts'] if part['id'] in targets), None)
        self.original_material = deepcopy(part.get('material')) if part else None
        material = Material.model_validate(self.original_material or {})
        self.name.setText(material.name)
        self.behavior.setCurrentIndex(max(0, self.behavior.findData(material.behavior)))
        for key, field in self.inputs.items():
            value = getattr(material, key)
            field.setText('' if self.original_material is None or value is None else str(value))
        self.mode.setCurrentIndex(self.mode.findData('preserve'))
        self._loading = False
        self.mode_changed()
        self.target_changed()

    def manual_changed(self, *_):
        if self._loading:
            return
        self.mode.setCurrentIndex(self.mode.findData('custom'))
        self.schedule()

    def mode_changed(self, *_):
        manual = self.mode.currentData() in ('preserve', 'custom')
        self.name.setEnabled(manual)
        self.behavior.setEnabled(manual)
        for field in self.inputs.values():
            field.setEnabled(manual)
        self.replace_existing.setEnabled(self.mode.currentData() in ('catalog', 'custom'))
        self.schedule()

    def search(self, *_):
        previous = self.entry.catalog_id if self.entry else None
        self.entries = search_catalog(self.query.text(), self.category.currentData() or None)
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.entries))
        for row, entry in enumerate(self.entries):
            for column, text in enumerate((entry.name, entry.category)):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, entry.catalog_id)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.table.blockSignals(False)
        if self.entries:
            row = next((index for index, entry in enumerate(self.entries) if entry.catalog_id == previous), 0)
            self.table.selectRow(row)
        self.show_entry()

    def show_entry(self, *_):
        row = self.table.currentRow()
        self.entry = self.entries[row] if 0 <= row < len(self.entries) else None
        self.details.setPlainText(format_details(self.entry) if self.entry else '일치하는 재질이 없습니다.')
        self.sources.clear()
        if self.entry:
            for source in self.entry.sources:
                self.sources.addItem(source.title+' · '+source.revision, source.url)
        self.source_button.setEnabled(self.entry is not None)
        self.catalog_button.setEnabled(self.entry is not None)
        if self.mode.currentData() == 'catalog':
            self.schedule()

    def use_catalog(self, *_):
        if self.entry is None:
            return
        self.mode.setCurrentIndex(self.mode.findData('catalog'))
        self.schedule()

    def open_source(self, *_):
        url = self.sources.currentData()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def candidate(self):
        targets = self.selected_part_ids()
        if not targets:
            raise ValueError('재질을 적용할 부품을 체크하세요.')
        mode = self.mode.currentData()
        if mode == 'preserve':
            return deepcopy(self.base)
        if mode == 'remove':
            return remove_material(self.base, targets).model_dump()
        if mode == 'catalog':
            if self.entry is None:
                raise ValueError('목록에서 재질을 선택하세요.')
            return assign_material(self.base, targets, catalog_id=self.entry.catalog_id,
                                   replace_existing=self.replace_existing.isChecked()).model_dump()
        values = {}
        for key, field in self.inputs.items():
            text = field.text().strip()
            if not text and key == 'density':
                raise ValueError('밀도 kg/m³를 입력하세요.')
            try:
                values[key] = float(text) if text else None
            except ValueError:
                raise ValueError(LABELS[key]+' 값을 숫자로 입력하세요.') from None
        # Preserve absent legacy optional fields if the displayed value is unchanged.
        original = Material.model_validate(self.original_material or {})
        changes = {key: value for key, value in values.items() if value != getattr(original, key)}
        changes.update(name=self.name.text().strip(), behavior=self.behavior.currentData())
        material = custom_material(original, changes)
        return assign_material(self.base, targets, material, replace_existing=self.replace_existing.isChecked()).model_dump()

    def checked_compute(self, raw, revision):
        from ..kernel import KERNEL_LOCK
        from ..preview_metadata import reuse_preview
        from ..interference import assess
        def check():
            if not self.alive or revision != self.revision:
                raise RuntimeError('미리보기가 취소되었습니다.')
        with KERNEL_LOCK:
            check()
            design = Design.model_validate(raw)
            baseline = Design.model_validate(self.base)
            result = reuse_preview(design, baseline, self._preview_cache)
            if result is None:
                # Validate the baseline once. Never use an un-attested parent mesh.
                _, verified = PreviewDialog.compute(self.base)
                check()
                result = reuse_preview(design, baseline, verified)
                if result is None:
                    # Conservative fallback if a future dialog adds geometry edits.
                    return super().checked_compute(raw, revision)
                self._preview_cache = verified
            check()
            collisions = result['stats']['collisions']
            report = assess(design, baseline, collisions=collisions,
                            baseline_collisions=collisions, check=check)
            check()
            return design, result, report, None

    def present(self):
        super().present()
        self.viewport.select_many(list(self.selected_part_ids()))
        if self.mode.currentData() == 'preserve':
            self.apply_button.setEnabled(False)
            self.status.setText('현재 재질 보기 · 변경 없음. 목록 재질 또는 직접 입력으로 미리본 뒤 적용하세요.')
        else:
            self.status.setText(self.status.text()+f' · 체크한 {len(self.selected_part_ids())}개 부품의 재질만 변경')
