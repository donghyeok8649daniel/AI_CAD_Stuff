"""Import and review a BOM privately before using it as design input."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPlainTextEdit, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget)

from ..bom_design import (BomDocument, BomItem, catalog_candidates, import_bom_file,
                   parse_bom_text, refresh_bom_issues)
from .widgets import button, label


class BomDesignDialog(QDialog):
    """``accepted_bom`` is set exclusively by the explicit Save action.

    Imported rows and the caller's BOM are copied. A rejected dialog, a failed
    import, and invalid row edits never modify the caller's project. Imports
    read inert table data; this dialog never opens links or invokes an AI job.
    """

    AXES = ("length", "width", "height", "thickness", "diameter")
    ROLES = (("unspecified", "미정", "Unspecified"),
             ("structure", "구조", "Structure"),
             ("electrical", "전장", "Electrical"),
             ("transmission", "전달", "Transmission"),
             ("specimen", "시편", "Specimen"))

    def __init__(self, bom=None, parent=None, language="ko"):
        super().__init__(parent)
        self.language = language
        self.word = lambda ko, en: en if language == "en" else ko
        self.document = self._copy_document(bom) if bom is not None else None
        self.accepted_bom = None
        self._row = -1
        self._loading = False
        self._dirty = False
        self._matches = []
        self.setObjectName("bomDesignDialog2240")
        self.setWindowTitle(self.word("BOM 보고 설계 · 부품표 가져오기 / 검토", "Design from BOM · import / review"))
        self.resize(1180, 800)
        self.setMinimumSize(780, 560)
        root = QVBoxLayout(self)
        root.addWidget(label(self.word(
            "수량·정확한 모델·치수·역할을 검토한 부품표를 설계 입력으로 사용합니다. 빈 값과 불명확한 치수는 확인 항목으로 남습니다. 저장 후 AI 초안을 요청하세요.",
            "Review quantities, exact models, dimensions and roles before using this table as design input. Empty values and ambiguous dimensions remain items to confirm. Request an AI draft after saving.")))
        actions = QHBoxLayout()
        self.import_button = button(self.word("CSV / TSV / XLSX 가져오기…", "Import CSV / TSV / XLSX…"), self.import_file)
        self.import_button.setObjectName("bomImportFile")
        actions.addWidget(self.import_button)
        self.add_button = button(self.word("빈 행 추가", "Add empty row"), self.add_row)
        self.add_button.setObjectName("bomAddRow"); actions.addWidget(self.add_button)
        self.remove_button = button(self.word("선택 행 삭제", "Remove selected row"), self.remove_row)
        self.remove_button.setObjectName("bomRemoveRow"); actions.addWidget(self.remove_button)
        self.sheet_name = QLineEdit(); self.sheet_name.setObjectName("bomSheetName")
        self.sheet_name.setPlaceholderText(self.word("XLSX 시트 이름 · 여러 시트면 입력", "XLSX worksheet · enter when multiple sheets"))
        self.sheet_name.setToolTip(self.word("XLSX에 시트가 여러 개면 가져올 시트 이름을 입력하세요. 시트 하나인 파일은 비워도 됩니다.",
            "Enter the worksheet name when an XLSX has multiple sheets. Leave empty for a workbook with one sheet."))
        actions.addWidget(self.sheet_name, 1); root.addLayout(actions)
        self.summary = label("", muted=True, user_text=True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setObjectName("bomSummary"); root.addWidget(self.summary)

        self.tabs = QTabWidget(); self.tabs.setObjectName("bomTabs"); root.addWidget(self.tabs, 1)
        review = QWidget(); review_layout = QVBoxLayout(review)
        self.table = QTableWidget(0, 8); self.table.setObjectName("bomItems")
        self.table.setHorizontalHeaderLabels([self.word("수량", "Quantity"), self.word("부품명", "Name"),
            self.word("제조사 / 모델", "Manufacturer / model"), self.word("명시 치수 · mm", "Explicit dimensions · mm"),
            self.word("역할", "Role"), self.word("규격 DB", "Catalog"), self.word("확인 사항", "To confirm"),
            self.word("출처 행", "Source row")])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(135)
        self.table.setMaximumHeight(270)
        review_layout.addWidget(self.table, 1)
        split = QSplitter(Qt.Orientation.Horizontal); review_layout.addWidget(split, 2)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); split.addWidget(scroll)
        editor = QWidget(); scroll.setWidget(editor); form = QFormLayout(editor)
        self.fields = {}
        for key, ko, en in (("name", "부품명", "Name"), ("manufacturer", "제조사", "Manufacturer"),
                           ("model", "정확한 모델 / 품번", "Exact model / part number")):
            field = QLineEdit(); field.setObjectName("bom_" + key)
            self.fields[key] = field; form.addRow(self.word(ko, en), field)
            field.textChanged.connect(self._mark_dirty)
        qty_row = QHBoxLayout()
        self.quantity = QLineEdit(); self.quantity.setObjectName("bom_quantity")
        self.quantity.setPlaceholderText(self.word("미정이면 비워두세요", "Leave empty when unknown"))
        self.quantity.textChanged.connect(self._mark_dirty); qty_row.addWidget(self.quantity, 1)
        self.quantity_unit = QComboBox(); self.quantity_unit.setObjectName("bom_quantity_unit")
        self.quantity_unit.addItem(self.word("개 · ea", "Each · ea"), "ea")
        self.quantity_unit.addItem(self.word("단위 미정", "Unit unknown"), "unknown")
        self.quantity_unit.currentIndexChanged.connect(self._mark_dirty); qty_row.addWidget(self.quantity_unit)
        form.addRow(self.word("수량 / 단위", "Quantity / unit"), qty_row)
        self.role = QComboBox(); self.role.setObjectName("bom_role")
        for value, ko, en in self.ROLES: self.role.addItem(self.word(ko, en), value)
        self.role.currentIndexChanged.connect(self._mark_dirty); form.addRow(self.word("부품 역할", "Part role"), self.role)
        catalog_row = QHBoxLayout()
        self.catalog_namespace = QComboBox(); self.catalog_namespace.setObjectName("bom_catalog_namespace")
        for value, ko, en in (("", "목록 미정", "Catalog unspecified"), ("electrical", "전장", "Electrical"), ("mechanical", "기계", "Mechanical")):
            self.catalog_namespace.addItem(self.word(ko, en), value)
        self.catalog_namespace.currentIndexChanged.connect(self._mark_dirty); catalog_row.addWidget(self.catalog_namespace)
        field = QLineEdit(); field.setObjectName("bom_catalog_id"); field.setPlaceholderText(self.word("정확한 목록 ID", "Exact catalog ID"))
        self.fields["catalog_id"] = field; field.textChanged.connect(self._mark_dirty); catalog_row.addWidget(field, 1)
        form.addRow(self.word("규격 DB 연결", "Catalog link"), catalog_row)
        dims = QGridLayout(); self.dimensions = {}
        for index, (axis, ko, en) in enumerate((("length", "길이", "Length"), ("width", "폭", "Width"),
                ("height", "높이", "Height"), ("thickness", "두께", "Thickness"), ("diameter", "직경", "Diameter"))):
            field = QLineEdit(); field.setObjectName("bom_" + axis)
            field.setPlaceholderText("? mm"); field.setMaximumWidth(125)
            field.textChanged.connect(self._mark_dirty); self.dimensions[axis] = field
            dims.addWidget(QLabel(self.word(ko, en)), index // 3 * 2, index % 3)
            dims.addWidget(field, index // 3 * 2 + 1, index % 3)
        form.addRow(self.word("치수 · mm", "Dimensions · mm"), dims)
        form.addRow(label(self.word("축을 확인한 값만 입력하세요. 원본 표의 치수 문자열은 출처에 보존합니다.",
            "Enter values only after confirming their axes. The original dimension string stays in the source record."), muted=True))
        for key, ko, en in (("spec_url", "공식 사양 URL", "Specification URL"),
                           ("purchase_url", "구매 URL", "Purchase URL")):
            field = QLineEdit(); field.setObjectName("bom_" + key); field.setPlaceholderText("https://…")
            self.fields[key] = field; form.addRow(self.word(ko, en), field); field.textChanged.connect(self._mark_dirty)
        self.notes = QPlainTextEdit(); self.notes.setObjectName("bom_notes"); self.notes.setMaximumHeight(80)
        self.notes.textChanged.connect(self._mark_dirty); form.addRow(self.word("메모", "Notes"), self.notes)
        self.apply_button = button(self.word("선택 행 수정 반영", "Apply row edits"), self.apply_row)
        self.apply_button.setObjectName("bomApplyRow"); form.addRow(self.apply_button)

        detail = QWidget(); detail_layout = QVBoxLayout(detail); split.addWidget(detail)
        detail_layout.addWidget(label(self.word("정확히 일치하는 규격 DB 후보", "Exact catalog matches")))
        self.catalog = QComboBox(); self.catalog.setObjectName("bomCatalogMatches")
        self.catalog.setMinimumContentsLength(14)
        self.catalog.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        detail_layout.addWidget(self.catalog)
        self.match_button = button(self.word("선택한 모델 연결", "Link selected model"), self.use_catalog_match)
        self.match_button.setObjectName("bomUseCatalogMatch"); detail_layout.addWidget(self.match_button)
        self.catalog_note = label(self.word("후보는 모델·품번의 정확한 일치로 찾습니다. 모델 연결이 실물 치수나 동작 조건을 확인해 주지는 않습니다.",
            "Matches use exact models and part numbers. Linking a model does not verify physical dimensions or operating conditions."), muted=True)
        detail_layout.addWidget(self.catalog_note)
        self.details = QTabWidget(); detail_layout.addWidget(self.details, 1)
        self.pending = QPlainTextEdit(); self.pending.setReadOnly(True); self.pending.setObjectName("bomPending")
        self.details.addTab(self.pending, self.word("미정 값 / 검토", "Unknowns / review"))
        self.source_details = QPlainTextEdit(); self.source_details.setReadOnly(True); self.source_details.setObjectName("bomSource")
        self.details.addTab(self.source_details, self.word("원본 / 출처", "Original / source"))
        split.setSizes([550, 430]); self.tabs.addTab(review, self.word("부품표 검토", "Review BOM"))

        pasted = QWidget(); paste_layout = QVBoxLayout(pasted)
        paste_layout.addWidget(label(self.word("열 제목이 있는 CSV 또는 탭으로 구분된 표를 붙여넣으세요. 가져오면 현재 검토 중인 부품표가 바뀝니다.",
            "Paste CSV or a tab-separated table with a header row. Importing replaces the table currently under review.")))
        self.paste = QPlainTextEdit(); self.paste.setObjectName("bomPaste")
        self.paste.setPlaceholderText(self.word("부품명\t수량\t모델\t길이 mm\t폭 mm\t역할", "Name\tQuantity\tModel\tLength mm\tWidth mm\tRole"))
        paste_layout.addWidget(self.paste, 1)
        self.paste_button = button(self.word("붙여넣은 표 가져오기", "Import pasted table"), self.import_text)
        self.paste_button.setObjectName("bomImportPaste"); paste_layout.addWidget(self.paste_button)
        self.tabs.addTab(pasted, self.word("표 붙여넣기", "Paste table"))
        self.status = label("", user_text=True); self.status.setObjectName("bomStatus"); root.addWidget(self.status)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        controls = QDialogButtonBox(); self.controls = controls
        self.save_button = controls.addButton(self.word("검토한 BOM 저장", "Save reviewed BOM"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_button.setObjectName("bomSave")
        self.close_button = controls.addButton(self.word("취소 · 변경 버리기", "Cancel · discard changes"), QDialogButtonBox.ButtonRole.RejectRole)
        controls.accepted.connect(self.accept); controls.rejected.connect(self.reject); root.addWidget(controls)
        for control in controls.buttons(): control.setAutoDefault(False)
        for control in (self.import_button, self.add_button, self.remove_button, self.apply_button, self.match_button, self.paste_button):
            control.setAutoDefault(False)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.catalog.currentIndexChanged.connect(lambda *_: self.catalog.setToolTip(self.catalog.currentText()))
        self._populate()

    @staticmethod
    def _copy_document(document):
        checked = BomDocument.model_validate(document)
        return BomDocument.model_validate(deepcopy(checked.model_dump(mode="json")))

    def _mark_dirty(self, *_):
        if not self._loading:
            self._dirty = True
            self.apply_button.setEnabled(self._row >= 0)

    def _status(self, text, error=False):
        self.status.setText(str(text)[:2000])
        self.status.setStyleSheet("color:#f4a090" if error else "")

    def _role_name(self, value):
        return next((self.word(ko, en) for key, ko, en in self.ROLES if key == value), value)

    def _populate(self, selected=None):
        self._loading = True
        items = self.document.items if self.document else []
        self.table.blockSignals(True); self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            quantity = "?" if item.quantity is None else str(item.quantity)
            quantity += " " + ("ea" if item.quantity_unit == "ea" else "?")
            dims = "; ".join(f"{key}={value:g}" for key, value in item.dimensions_mm.items()) or "?"
            linked = f"{item.catalog_namespace}/{item.catalog_id}" if item.catalog_id else self.word("미연결", "Unlinked")
            values = (quantity, item.name, " · ".join(filter(None, (item.manufacturer, item.model))) or "?", dims,
                      self._role_name(item.role), linked, "; ".join(item.issues) or "—", str(item.source_row))
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value)); cell.setToolTip(str(value)); self.table.setItem(row, col, cell)
        for col, width in enumerate((90, 160, 210, 170, 85, 135, 220, 85)): self.table.setColumnWidth(col, width)
        row = next((i for i, item in enumerate(items) if item.id == selected), 0 if items else -1)
        self._row = row; self._dirty = False
        if row >= 0: self.table.selectRow(row)
        self.table.blockSignals(False); self._loading = False
        self._load_row()
        self.save_button.setEnabled(bool(items)); self.remove_button.setEnabled(row >= 0)
        if self.document:
            count = sum(bool(item.issues) for item in items)
            self.summary.setText(self.word("출처: {source} · {rows}행 · 확인할 값이 있는 {pending}행",
                "Source: {source} · {rows} rows · {pending} rows with items to confirm").format(
                    source=self.document.source_name, rows=len(items), pending=count))
            self.summary.setToolTip(self.document.source + "\nSHA-256: " + self.document.source_sha256)
        else:
            self.summary.setText(self.word("부품표 파일이나 표를 가져오세요.", "Import a BOM file or paste a table."))
            self.summary.setToolTip("")

    def _load_row(self):
        item = self.document.items[self._row] if self.document and 0 <= self._row < len(self.document.items) else None
        self._loading = True
        for key, field in self.fields.items(): field.setText(str(getattr(item, key) or "") if item else ""); field.setEnabled(item is not None)
        self.quantity.setText(str(item.quantity) if item and item.quantity is not None else "")
        self.quantity_unit.setCurrentIndex(self.quantity_unit.findData(item.quantity_unit if item else "unknown"))
        self.role.setCurrentIndex(self.role.findData(item.role if item else "unspecified"))
        self.catalog_namespace.setCurrentIndex(self.catalog_namespace.findData(item.catalog_namespace if item else ""))
        for axis, field in self.dimensions.items():
            value = item.dimensions_mm.get(axis) if item else None
            field.setText(f"{value:g}" if value is not None else ""); field.setEnabled(item is not None)
        self.notes.setPlainText(item.notes if item else "")
        for field in (self.quantity, self.quantity_unit, self.role, self.catalog_namespace, self.notes): field.setEnabled(item is not None)
        self._dirty = False; self.apply_button.setEnabled(False); self.remove_button.setEnabled(item is not None)
        self.catalog.clear(); self._matches = catalog_candidates(item) if item else []
        for match in self._matches:
            suffix = self.word(" · 참고 자료", " · reference only") if match.get("reference_only") else ""
            self.catalog.addItem(match["display_name"] + " [" + match["namespace"] + "/" + match["catalog_id"] + "]" + suffix, match)
        if not self._matches: self.catalog.addItem(self.word("정확히 일치하는 모델 없음", "No exact model match"), None)
        self.catalog.setToolTip(self.catalog.currentText()); self.match_button.setEnabled(bool(self._matches))
        if item:
            pending = [self.word("부품", "Part") + ": " + item.name, ""]
            pending += item.issues or [self.word("이 행의 입력값에 추가 확인 항목 없음", "No additional input issue for this row")]
            if len(self._matches) > 1: pending += ["", self.word("정확한 모델 후보가 여러 개입니다. 원하는 품번을 직접 선택하세요.", "More than one exact model matches. Select the intended part number explicitly.")]
            if self.document.warnings: pending += ["", self.word("파일 확인 사항", "File review items"), *self.document.warnings]
            self.pending.setPlainText("\n".join(pending))
            lines = [self.document.source_name, self.document.source, "SHA-256: " + self.document.source_sha256,
                     self.word("원본 행", "Original row") + ": " + str(item.source_row),
                     self.word("원본 치수", "Original dimensions") + ": " + (item.dimensions_text or "?"), ""]
            lines += [str(key) + ": " + str(value) for key, value in item.raw_fields.items()]
            self.source_details.setPlainText("\n".join(lines))
        else:
            self.pending.clear(); self.source_details.clear()
        self._loading = False

    def _selection_changed(self):
        if self._loading: return
        selected = self.table.currentRow()
        if selected == self._row: return
        old = self._row
        if self._dirty and not self.apply_row():
            self.table.blockSignals(True)
            if old >= 0: self.table.selectRow(old)
            self.table.blockSignals(False); return
        self._row = selected
        self.table.blockSignals(True)
        if selected >= 0: self.table.selectRow(selected)
        self.table.blockSignals(False); self._load_row()

    def apply_row(self, *_):
        if not self.document or not 0 <= self._row < len(self.document.items): return True
        if not self._dirty: return True
        item = self.document.items[self._row]
        raw = item.model_dump(mode="json")
        try:
            quantity = self.quantity.text().strip()
            if quantity and (not quantity.isascii() or not quantity.isdecimal() or int(quantity) <= 0):
                raise ValueError(self.word("수량은 양의 정수로 입력하거나 미정이면 비워두세요.", "Quantity must be a positive integer, or empty when unknown."))
            raw["quantity"] = int(quantity) if quantity else None
            raw["quantity_unit"] = self.quantity_unit.currentData()
            raw.update({key: field.text().strip() for key, field in self.fields.items()})
            raw["role"] = self.role.currentData(); raw["notes"] = self.notes.toPlainText().strip()
            raw["catalog_namespace"] = self.catalog_namespace.currentData()
            raw["dimensions_mm"] = {}
            for axis, field in self.dimensions.items():
                text = field.text().strip()
                if not text: continue
                value = float(text)
                if not math.isfinite(value) or value <= 0:
                    raise ValueError(self.word("치수는 유한한 양수(mm)로 입력하거나 비워두세요.", "Dimensions must be finite positive numbers in mm, or empty."))
                raw["dimensions_mm"][axis] = value
            if (any(raw[key] != getattr(item, key) for key in ("manufacturer", "model"))
                    and raw["catalog_id"] == item.catalog_id and raw["catalog_namespace"] == item.catalog_namespace):
                raw["catalog_id"] = ""; raw["catalog_namespace"] = ""
            updated = BomItem.model_validate(raw)
            document = self.document.model_dump(mode="json")
            document["items"][self._row] = updated.model_dump(mode="json")
            checked = refresh_bom_issues(BomDocument.model_validate(document))
        except Exception as exc:
            self._status(str(exc), True); return False
        self.document = self._copy_document(checked); self._populate(item.id)
        self._status(self.word("행 수정이 검토용 부품표에 반영되었습니다. 저장하면 설계 입력으로 사용합니다.",
            "Row edits are in the reviewed table. Save to use them as design input."))
        return True

    def use_catalog_match(self):
        match = self.catalog.currentData()
        if not match: return
        # First validate manual values; a failed edit cannot disappear when a
        # catalog button is clicked or when the row selection changes.
        if not self.apply_row(): return
        item = self.document.items[self._row]
        raw = item.model_dump(mode="json")
        raw.update(manufacturer=match["manufacturer"], model=match["model"],
                   catalog_namespace=match["namespace"], catalog_id=match["catalog_id"])
        try:
            doc = self.document.model_dump(mode="json"); doc["items"][self._row] = BomItem.model_validate(raw).model_dump(mode="json")
            checked = refresh_bom_issues(BomDocument.model_validate(doc))
        except Exception as exc: self._status(str(exc), True); return
        self.document = self._copy_document(checked); self._populate(item.id)
        self._status(self.word("선택한 정확한 모델을 연결했습니다. 치수와 사용 조건은 확인 항목을 검토하세요.",
            "The selected exact model is linked. Review dimensions and operating conditions."))

    def import_file(self, path=None, *, sheet_name=None):
        if isinstance(path, bool): path = None
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, self.word("부품표 가져오기", "Import BOM"), "",
                "BOM (*.csv *.tsv *.xlsx);;CSV (*.csv);;TSV (*.tsv);;Excel (*.xlsx)")
            if not path: return False
        try: document = import_bom_file(Path(path), sheet_name=sheet_name or self.sheet_name.text().strip() or None)
        except Exception as exc: self._status(str(exc), True); return False
        self.document = self._copy_document(document); self._populate(); self.tabs.setCurrentIndex(0)
        self._status(self.word("부품표를 가져왔습니다. 행을 선택해 확인하고 저장하세요.", "BOM imported. Select rows to review, then save."))
        return True

    def import_text(self, text=None):
        if isinstance(text, bool) or text is None: text = self.paste.toPlainText()
        try: document = parse_bom_text(text, source_name="pasted-bom", source="paste")
        except Exception as exc: self._status(str(exc), True); return False
        self.document = self._copy_document(document); self._populate(); self.tabs.setCurrentIndex(0)
        self._status(self.word("붙여넣은 표를 가져왔습니다. 미정 값과 원본 행을 검토하세요.", "Pasted table imported. Review unknown values and original rows."))
        return True

    def add_row(self):
        if not self.apply_row(): return
        if self.document is None:
            self.import_text("Name\tQuantity\nNew part\t\n")
            return
        from uuid import uuid4
        try:
            raw = self.document.model_dump(mode="json")
            item = BomItem(id="bom_item_" + uuid4().hex[:16], name=self.word("새 부품", "New part"), quantity=None,
                           quantity_unit="unknown", source_row=0, raw_fields={})
            raw["items"].append(item.model_dump(mode="json"))
            checked = refresh_bom_issues(BomDocument.model_validate(raw))
        except Exception as exc: self._status(str(exc), True); return
        self.document = self._copy_document(checked); self._populate(item.id)
        self._status(self.word("빈 행을 추가했습니다. 부품명과 확인된 값을 입력하세요.", "An empty row was added. Enter the name and confirmed values."))

    def remove_row(self):
        if not self.document or not 0 <= self._row < len(self.document.items): return
        try:
            raw = self.document.model_dump(mode="json"); raw["items"].pop(self._row)
            checked = refresh_bom_issues(BomDocument.model_validate(raw))
        except Exception as exc: self._status(str(exc), True); return
        self.document = self._copy_document(checked); self._populate()
        self._status(self.word("검토용 부품표에서 행을 삭제했습니다. 저장해야 반영됩니다.", "Row removed from the reviewed table. Save to apply the change."))

    def accept(self):
        if not self.apply_row(): return
        if self.document is None or not self.document.items:
            self._status(self.word("저장할 부품표 행을 먼저 가져오세요.", "Import at least one BOM row before saving."), True); return
        try: self.accepted_bom = self._copy_document(refresh_bom_issues(self.document))
        except Exception as exc: self._status(str(exc), True); return
        super().accept()

    def done(self, result):
        if result != QDialog.DialogCode.Accepted: self.accepted_bom = None
        super().done(result)
