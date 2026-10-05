"""Guided single-source DC path entry and preview for the native electrical desk."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLineEdit, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget)

from ..electrical import ElectricalWorkspace
from ..power_paths import PowerPathBuild, PowerPathSpec, build_power_path, format_power_path_report
from .widgets import button, label, number


class PowerPathDialog(QDialog):
    """Append a previewed power path; never silently fill missing product values."""

    def __init__(self, parent, existing: ElectricalWorkspace | dict, parts: list[dict]):
        super().__init__(parent)
        self.setWindowTitle('전원 연결 설계 · 공급선과 리턴선')
        self.resize(720, 790)
        self.existing = ElectricalWorkspace.model_validate(existing)
        self.parts = parts
        self.build: PowerPathBuild | None = None
        outer = QVBoxLayout(self)
        outer.addWidget(label('배터리 + → 스위치 → 공급선 → 부하 → 리턴선 → 배터리 - 경로를 작성합니다. '
                              '입력 전류·전압·실제 전선 치수를 확인하고 미리보기에서 계산한 뒤 기존 회로에 추가합니다.', True))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        forms = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 3)

        def section(title):
            group = QGroupBox(title)
            form = QFormLayout(group)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            forms.addWidget(group)
            return form

        overview = section('경로 이름과 출력 상태')
        self.name = QLineEdit('전원 경로')
        overview.addRow('경로 이름', self.name)
        self.source_enabled = QCheckBox('전원 인가 · 배터리 출력 ON')
        self.source_enabled.setChecked(True)
        overview.addRow(self.source_enabled)
        self.switch_closed = QCheckBox('스위치 닫힘 · 전원 경로 도통')
        self.switch_closed.setChecked(True)
        overview.addRow(self.switch_closed)

        source = section('배터리 / DC 공급원')
        self.source_voltage = number(0, 0, 1000, ' V', decimals=5)
        source.addRow('개방 전압 · 필수', self.source_voltage)
        self.source_internal_r = number(0, 0, 10000, ' Ω', decimals=6)
        source.addRow('내부저항 · 0은 이상적 전원 모델', self.source_internal_r)
        self.source_capacity = number(0, 0, 10000, ' A', decimals=5)
        source.addRow('입력한 최대 출력 전류 · 0은 미검증', self.source_capacity)
        self.source_part = self._part_combo()
        source.addRow('CAD 배터리 부품 · 선택', self.source_part)

        switch = section('직렬 스위치')
        self.switch_r = number(.01, .000001, 1000, ' Ω', decimals=6)
        switch.addRow('닫힌 접점저항 · 기본 0.01 Ω 근사', self.switch_r)
        self.switch_capacity = number(0, 0, 10000, ' A', decimals=5)
        switch.addRow('입력한 허용 전류 · 0은 미검증', self.switch_capacity)
        self.switch_part = self._part_combo()
        switch.addRow('CAD 스위치 부품 · 선택', self.switch_part)

        feed = section('양극 공급 전선')
        self.feed_length = number(0, 0, 1e7, ' mm', decimals=3)
        feed.addRow('실제 배선 길이 · 필수', self.feed_length)
        self.feed_area = number(0, 0, 1e5, ' mm²', decimals=5)
        feed.addRow('도체 단면적 · 필수', self.feed_area)
        feed_catalog_row, self.feed_catalog = self._wire_catalog_picker()
        feed.addRow('정확한 전선 SKU · 선택', feed_catalog_row)
        self.feed_resistivity = number(.01724, .0000001, 100, ' Ω·mm²/m', decimals=7)
        feed.addRow('저항률 · 기본은 상온 구리 근사', self.feed_resistivity)
        self.feed_catalog_note = label('수동 입력 · 기본 상온 구리 저항률 근사', True)
        feed.addRow(self.feed_catalog_note)
        self.feed_capacity = number(0, 0, 10000, ' A', decimals=5)
        feed.addRow('입력한 허용 전류 · 0은 미검증', self.feed_capacity)
        self.feed_part = self._part_combo()
        feed.addRow('CAD 공급선 부품 · 선택', self.feed_part)

        load = section('부하')
        self.load_kind = QComboBox()
        self.load_kind.addItem('일반 저항 등가 부하', 'load')
        self.load_kind.addItem('모터 · 정격 등가 부하', 'motor')
        self.load_kind.addItem('액추에이터 · 정격 등가 부하', 'actuator')
        self.load_kind.addItem('MCU / 보드 전원 부하', 'mcu')
        load.addRow('모델 종류', self.load_kind)
        self.load_voltage = number(0, 0, 1000, ' V', decimals=5)
        load.addRow('실제 입력 정격 전압 · 필수', self.load_voltage)
        self.load_current = number(0, 0, 10000, ' A', decimals=5)
        load.addRow('해당 작동점의 전류 · 필수', self.load_current)
        self.startup_current = number(0, 0, 10000, ' A', decimals=5)
        load.addRow('모터 기동 전류 · 0은 미입력', self.startup_current)
        self.load_part = self._part_combo()
        load.addRow('CAD 부하 부품 · 선택', self.load_part)

        ret = section('음극 리턴 전선')
        self.return_length = number(0, 0, 1e7, ' mm', decimals=3)
        ret.addRow('실제 배선 길이 · 필수', self.return_length)
        self.return_area = number(0, 0, 1e5, ' mm²', decimals=5)
        ret.addRow('도체 단면적 · 필수', self.return_area)
        return_catalog_row, self.return_catalog = self._wire_catalog_picker()
        ret.addRow('정확한 전선 SKU · 선택', return_catalog_row)
        self.return_resistivity = number(.01724, .0000001, 100, ' Ω·mm²/m', decimals=7)
        ret.addRow('저항률 · 기본은 상온 구리 근사', self.return_resistivity)
        self.return_catalog_note = label('수동 입력 · 기본 상온 구리 저항률 근사', True)
        ret.addRow(self.return_catalog_note)
        self.return_capacity = number(0, 0, 10000, ' A', decimals=5)
        ret.addRow('입력한 허용 전류 · 0은 미검증', self.return_capacity)
        self.return_part = self._part_combo()
        ret.addRow('CAD 리턴선 부품 · 선택', self.return_part)
        forms.addStretch(1)

        outer.addWidget(label('DC 저항 등가만 계산합니다. 전선 허용 전류와 배터리 내부저항은 실측 또는 명시된 자료로 확인하세요. '
                              'MCU 코드·모터 드라이버·배터리 수명·열 안전은 여기서 판단하지 않습니다.', True))
        self.preview = QPlainTextEdit()
        self.preview.setObjectName('powerPathPreview')
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(210)
        outer.addWidget(self.preview, 2)
        actions = QHBoxLayout()
        self.schematic_button = button('회로도 미리보기…', self.show_schematic)
        self.schematic_button.setObjectName('powerPathSchematicPreview')
        actions.addWidget(self.schematic_button)
        actions.addStretch(1)
        self.apply_button = button('기존 회로에 추가', self.accept, True)
        self.apply_button.setObjectName('powerPathApply')
        actions.addWidget(self.apply_button)
        actions.addWidget(button('취소', self.reject))
        outer.addLayout(actions)

        self._manual_resistivity = {'feed': self.feed_resistivity.value(),
                                    'return': self.return_resistivity.value()}
        self.feed_catalog.currentIndexChanged.connect(self._refresh_wire_catalog)
        self.return_catalog.currentIndexChanged.connect(self._refresh_wire_catalog)
        self.feed_area.valueChanged.connect(self._refresh_wire_catalog)
        self.return_area.valueChanged.connect(self._refresh_wire_catalog)

        for field in (self.source_voltage, self.source_internal_r, self.source_capacity,
                      self.switch_r, self.switch_capacity, self.feed_length, self.feed_area,
                      self.feed_resistivity, self.feed_capacity, self.load_voltage,
                      self.load_current, self.startup_current, self.return_length,
                      self.return_area, self.return_resistivity, self.return_capacity):
            field.valueChanged.connect(self.refresh_preview)
        for field in (self.source_part, self.switch_part, self.feed_part, self.load_part, self.return_part,
                      self.load_kind):
            field.currentIndexChanged.connect(self.refresh_preview)
        for field in (self.source_enabled, self.switch_closed):
            field.toggled.connect(self.refresh_preview)
        self.name.textChanged.connect(self.refresh_preview)
        self._refresh_wire_catalog()
        self.refresh_preview()

    def _part_combo(self):
        field = QComboBox()
        field.addItem('CAD 부품에 연결하지 않음', '')
        for item in self.parts:
            field.addItem(f"{item['name']} · {item['id']}", item['id'])
        return field

    def _wire_catalog_picker(self):
        from ..mechanical_catalog import search_catalog
        field = QComboBox()
        field.addItem('수동 저항률 사용', '')
        for entry in search_catalog(category='전선'):
            wire = entry.wire_spec
            if wire is not None:
                field.addItem(f'{entry.display_name} · {wire.awg} AWG · {wire.dcr_ohm_per_m:.5g} Ω/m',
                              entry.catalog_id)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(field, 1)
        layout.addWidget(button('공식 출처', lambda: self._open_wire_source(field)))
        return row, field

    @staticmethod
    def _open_wire_source(field):
        from ..mechanical_catalog import get_catalog_entry
        entry = get_catalog_entry(field.currentData())
        if entry is not None and entry.source_url:
            QDesktopServices.openUrl(QUrl(entry.source_url))

    def _refresh_wire_catalog(self, *_):
        from ..mechanical_catalog import get_catalog_entry
        for key, catalog, area, resistance, note in (
                ('feed', self.feed_catalog, self.feed_area, self.feed_resistivity, self.feed_catalog_note),
                ('return', self.return_catalog, self.return_area, self.return_resistivity,
                 self.return_catalog_note)):
            entry = get_catalog_entry(catalog.currentData())
            if entry is not None and entry.wire_spec is not None:
                if resistance.isEnabled():
                    self._manual_resistivity[key] = resistance.value()
                rho = entry.wire_spec.dcr_ohm_per_m * area.value()
                resistance.blockSignals(True)
                resistance.setValue(min(100, max(resistance.minimum(), rho)))
                resistance.blockSignals(False)
                resistance.setEnabled(False)
                note.setText(f'{entry.display_name}: 제조사 명목 DC 저항 {entry.wire_spec.dcr_ohm_per_m:.6g} Ω/m · '
                             '입력 면적과 등가 저항률로 변환합니다. 자유공기 전류를 이 회로의 허용 전류로 자동 적용하지 않습니다.')
            else:
                if not resistance.isEnabled():
                    resistance.blockSignals(True)
                    resistance.setValue(self._manual_resistivity[key])
                    resistance.blockSignals(False)
                resistance.setEnabled(True)
                note.setText('수동 입력 · 기본 상온 구리 저항률 근사. 실제 도체 재질·온도를 확인하세요.')
        self.refresh_preview()

    def _spec(self) -> PowerPathSpec:
        needed = ((self.source_voltage, '배터리 개방 전압'), (self.feed_length, '공급선 길이'),
                  (self.feed_area, '공급선 도체 단면적'), (self.load_voltage, '부하 정격 전압'),
                  (self.load_current, '부하 작동 전류'), (self.return_length, '리턴선 길이'),
                  (self.return_area, '리턴선 도체 단면적'))
        missing = [title for field, title in needed if field.value() <= 0]
        if missing:
            raise ValueError('필수 입력: ' + ', '.join(missing))
        optional = lambda field: field.value() or None
        return PowerPathSpec.model_validate(dict(
            name=self.name.text().strip(), source_voltage_v=self.source_voltage.value(),
            source_internal_resistance_ohm=self.source_internal_r.value(),
            source_max_current_a=optional(self.source_capacity), source_enabled=self.source_enabled.isChecked(),
            source_part_id=self.source_part.currentData(), switch_closed=self.switch_closed.isChecked(),
            switch_contact_resistance_ohm=self.switch_r.value(),
            switch_max_current_a=optional(self.switch_capacity), switch_part_id=self.switch_part.currentData(),
            positive_wire_length_mm=self.feed_length.value(),
            positive_wire_cross_section_mm2=self.feed_area.value(),
            positive_wire_resistivity_ohm_mm2_per_m=self.feed_resistivity.value(),
            positive_wire_catalog_id=self.feed_catalog.currentData(),
            positive_wire_max_current_a=optional(self.feed_capacity),
            positive_wire_part_id=self.feed_part.currentData(),
            load_kind=self.load_kind.currentData(), load_voltage_v=self.load_voltage.value(),
            load_current_a=self.load_current.value(),
            load_startup_current_a=optional(self.startup_current) if self.load_kind.currentData() in ('motor','actuator') else None,
            load_part_id=self.load_part.currentData(), return_wire_length_mm=self.return_length.value(),
            return_wire_cross_section_mm2=self.return_area.value(),
            return_wire_resistivity_ohm_mm2_per_m=self.return_resistivity.value(),
            return_wire_catalog_id=self.return_catalog.currentData(),
            return_wire_max_current_a=optional(self.return_capacity),
            return_wire_part_id=self.return_part.currentData()))

    def refresh_preview(self, *_):
        try:
            self.build = build_power_path(self.existing, self._spec())
        except (ValueError, TypeError) as error:
            self.build = None
            self.preview.setPlainText('경로를 아직 적용할 수 없습니다.\n' + str(error)[:1100])
        else:
            current_language = getattr(QApplication.instance(), 'cad_language', None)
            self.preview.setPlainText(format_power_path_report(
                self.build, getattr(current_language, 'language', 'ko')))
        self.apply_button.setEnabled(self.build is not None)
        self.schematic_button.setEnabled(self.build is not None)

    def show_schematic(self):
        if self.build is None:
            return
        from .electrical_schematic import ElectricalSchematicDialog
        ElectricalSchematicDialog(self, self.build.workspace, self.build.result).exec()

    def accept(self):
        self.refresh_preview()
        if self.build is not None:
            super().accept()
