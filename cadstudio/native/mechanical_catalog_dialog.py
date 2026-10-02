"""Offline, source-linked mechanical and power component browser."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QHBoxLayout,
                               QLineEdit, QPlainTextEdit, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from ..mechanical_catalog import (MechanicalCatalogEntry, HoleSpec, categories,
                                  format_ai_spec, format_details, search_catalog)
from .widgets import button, label


class MechanicalCatalogDialog(QDialog):
    """Browse exact parts and a small set of sourced hole/head dimensions.

    After acceptance ``entry`` contains the selected record and ``hole_spec``
    contains an ISO 273 medium clearance hole only when that type was selected.
    No geometry or project state is changed by this dialog.
    """

    def __init__(self, parent=None, query: str = ""):
        super().__init__(parent)
        self.setWindowTitle("기계·전원 규격 자료 · 오프라인")
        self.resize(980, 670)
        self.entry: MechanicalCatalogEntry | None = None
        self.hole_spec: HoleSpec | None = None
        self.copied_spec = ""
        self.entries: tuple[MechanicalCatalogEntry, ...] = ()

        root = QVBoxLayout(self)
        root.addWidget(label(
            "정확한 품번과 출처를 검색하세요. 전류 정격·자유공기 전류는 실제 부하 전류나 "
            "밀폐 하네스 허용값이 아닙니다. 미확인 패널 구멍과 FDM 공차는 자동 입력하지 않습니다.", True))

        search_row = QHBoxLayout()
        self.query = QLineEdit(query)
        self.query.setPlaceholderText("품번 · 제조사 · M4 · AWG18 · 관통홀 검색")
        search_row.addWidget(self.query, 1)
        self.category = QComboBox()
        self.category.addItem("전체 분류", None)
        for name in categories():
            self.category.addItem(name, name)
        search_row.addWidget(self.category)
        search_row.addWidget(button("검색", self.search))
        root.addLayout(search_row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(("분류", "제조사", "품번 / 규격", "핵심 설명"))
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 2)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        root.addWidget(self.details, 2)

        source_row = QHBoxLayout()
        source_row.addWidget(label("공식 자료"))
        self.sources = QComboBox()
        # Manufacturer source titles are literal identifiers, not UI strings.
        self.sources.setProperty("cadUserText", True)
        source_row.addWidget(self.sources, 1)
        self.open_button = button("공식 자료 열기", self.open_source)
        source_row.addWidget(self.open_button)
        root.addLayout(source_row)

        action_row = QHBoxLayout()
        self.status = label("선택한 항목을 프로젝트에 적용하기 전 제조사 조건을 확인하세요.", True)
        action_row.addWidget(self.status, 1)
        self.copy_button = button("AI 사양 복사", self.copy_ai_spec)
        action_row.addWidget(self.copy_button)
        self.use_button = button("선택", self.choose, True)
        action_row.addWidget(self.use_button)
        action_row.addWidget(button("닫기", self.reject))
        root.addLayout(action_row)

        self.query.textChanged.connect(self.search)
        self.category.currentIndexChanged.connect(self.search)
        self.table.itemSelectionChanged.connect(self.update_selection)
        self.table.doubleClicked.connect(lambda *_: self.choose())
        self.search()

    def search(self, *_):
        self.entries = search_catalog(self.query.text(), self.category.currentData())
        self.table.setRowCount(len(self.entries))
        for row, entry in enumerate(self.entries):
            values = (entry.category, entry.manufacturer, entry.model, entry.summary)
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
        if self.entries:
            self.table.selectRow(0)
        else:
            self.table.clearSelection()
        self.update_selection()

    def selected(self) -> MechanicalCatalogEntry | None:
        row = self.table.currentRow()
        return self.entries[row] if 0 <= row < len(self.entries) else None

    def update_selection(self):
        entry = self.selected()
        self.sources.clear()
        self.copy_button.setEnabled(entry is not None)
        self.use_button.setEnabled(entry is not None)
        self.open_button.setEnabled(entry is not None and bool(entry.sources))
        self.sources.setEnabled(entry is not None and bool(entry.sources))
        if entry is None:
            self.details.setPlainText("일치하는 자료가 없습니다. 품번이나 규격 크기로 다시 검색하세요.")
            return
        self.details.setPlainText(format_details(entry))
        for source in entry.sources:
            title = f"{source.title} · {source.retrieved_on}"
            self.sources.addItem(title, source.url)

    def open_source(self):
        url = self.sources.currentData()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def copy_ai_spec(self):
        entry = self.selected()
        if entry is None:
            return
        self.copied_spec = format_ai_spec(entry)
        # Retain the last copy when the system clipboard is temporarily locked.
        QApplication.instance()._mechanical_catalog_copy = self.copied_spec
        QApplication.clipboard().setText(self.copied_spec)
        self.status.setText("품번·조건·공식 출처가 포함된 사양을 복사했습니다.")

    def choose(self):
        entry = self.selected()
        if entry is None:
            return
        self.entry = entry
        self.hole_spec = entry.hole_spec
        self.accept()
