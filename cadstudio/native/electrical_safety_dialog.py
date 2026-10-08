"""Declared electrical limits and read-only fault review in a private draft."""
from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QScrollArea,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..electrical import ElectricalWorkspace
from ..electrical_safety import evaluate_electrical_safety
from .mcu_pin_dialog import english, word
from .widgets import button


SPEC_FIELDS = (
    ("max_voltage_v", "실제 허용 DC 전압 (V)", "Maximum DC voltage (V)"),
    ("rated_power_w", "허용 연속 열 손실 (W)", "Continuous heat dissipation limit (W)"),
    ("fuse_current_a", "퓨즈 정격 전류 (A)", "Fuse rated current (A)"),
    ("max_temperature_c", "허용 온도 (°C)", "Temperature limit (°C)"),
    ("thermal_resistance_k_per_w", "실제 조립 열저항 (K/W)", "Assembled thermal resistance (K/W)"),
    ("ambient_temperature_c", "실제 주위온도 (°C)", "Ambient temperature (°C)"),
    ("duty_cycle", "선언한 듀티 (0–1)", "Declared duty (0–1)"),
    ("heat_loss_fraction", "부하 입력 중 열 손실 비율 (0–1)", "Device input heat fraction (0–1)"),
)


class ElectricalSafetyDialog(QDialog):
    """Blank means unknown. Saving edits never rewires or powers the circuit."""

    def __init__(self, parent, workspace, component_id=""):
        super().__init__(parent)
        self.setWindowTitle(word("쇼트 · 과전류 · 열 검토", "Shorts · overload · thermal review"))
        self.resize(1080, 720)
        self.original = ElectricalWorkspace.model_validate(workspace)
        self.draft = ElectricalWorkspace.model_validate(deepcopy(self.original.model_dump(mode="json")))
        self.workspace = None
        self.current_id = None
        layout = QVBoxLayout(self)
        self.scope = QLabel(word("배선도와 입력 정격을 자동 점검합니다. 빈 칸은 미검증입니다. 데이터시트의 시험 PCB 열저항을 실제 조립의 값으로 대신 사용하지 마세요.",
            "Automatically review stored wiring and declared ratings. Blank means unverified. A thermal metric for a datasheet test PCB is not the assembled cooling condition."))
        self.scope.setWordWrap(True); layout.addWidget(self.scope)
        split = QSplitter(Qt.Orientation.Horizontal, self); layout.addWidget(split, 1)
        edit = QWidget(); form_layout = QVBoxLayout(edit)
        self.choice = QComboBox(); self.choice.setObjectName("electricalSafetyComponent")
        for item in self.draft.components:
            self.choice.addItem(f"{item.name} [{item.id}]", item.id)
        form_layout.addWidget(self.choice)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); form_layout.addWidget(scroll, 1)
        body = QWidget(); form = QFormLayout(body); scroll.setWidget(body)
        self.inputs = {}
        self.max_current = QLineEdit(); self.max_current.setObjectName("electricalSafetyMaxCurrent")
        self.max_current.setPlaceholderText(word("미입력 · 추정하지 않음", "Unknown · not inferred"))
        form.addRow(word("입력한 실제 허용 전류 (A)", "Declared current limit (A)"), self.max_current)
        for key, ko, en in SPEC_FIELDS:
            field = QLineEdit(); field.setObjectName("electricalSafety_" + key)
            field.setPlaceholderText(word("미입력 · 추정하지 않음", "Unknown · not inferred"))
            self.inputs[key] = field; form.addRow(word(ko, en), field)
        self.source = QLineEdit(); self.source.setObjectName("electricalSafetySource")
        self.source.setPlaceholderText("https://…")
        form.addRow(word("정격·열 조건 출처", "Rating / thermal source"), self.source)
        self.preview_button = button(word("입력으로 다시 점검", "Review entered values"), self.review, True)
        self.preview_button.setObjectName("electricalSafetyReview"); form_layout.addWidget(self.preview_button)
        split.addWidget(edit)
        display = QWidget(); results = QVBoxLayout(display)
        self.summary = QLabel(); self.summary.setObjectName("electricalSafetySummary"); self.summary.setWordWrap(True)
        results.addWidget(self.summary)
        self.table = QTableWidget(0, 5); self.table.setObjectName("electricalSafetyBranches")
        self.table.setHorizontalHeaderLabels([word("부품", "Component"), "A", word("기동 A", "Starting A"),
            word("열 손실 W", "Heat loss W"), word("정상상태 °C", "Steady-state °C")])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True); results.addWidget(self.table)
        self.report = QPlainTextEdit(); self.report.setReadOnly(True); self.report.setObjectName("electricalSafetyIssues")
        results.addWidget(self.report, 1); split.addWidget(display); split.setSizes([400, 650])
        controls = QDialogButtonBox()
        self.save_button = controls.addButton(word("정격 변경 저장", "Save rating changes"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_button.setObjectName("electricalSafetySave")
        controls.addButton(word("닫기 · 변경 취소", "Close · discard changes"), QDialogButtonBox.ButtonRole.RejectRole)
        controls.accepted.connect(self.accept); controls.rejected.connect(self.reject); layout.addWidget(controls)
        if component_id and self.choice.findData(component_id) >= 0:
            self.choice.setCurrentIndex(self.choice.findData(component_id))
        self.load_component()
        self.choice.currentIndexChanged.connect(self.change_component)
        self.refresh_report()

    def component(self):
        return next((item for item in self.draft.components if item.id == self.current_id), None)

    def load_component(self):
        self.current_id = self.choice.currentData()
        item = self.component()
        self.save_button.setEnabled(item is not None)
        self.preview_button.setEnabled(item is not None)
        self.max_current.setText("" if item is None or item.max_current_a is None else str(item.max_current_a))
        for key, field in self.inputs.items():
            value = getattr(item.safety, key) if item is not None and item.safety is not None else None
            field.setText("" if value is None else str(value))
            field.setEnabled(item is not None and (key != "fuse_current_a" or item.kind == "switch")
                and (key != "heat_loss_fraction" or item.kind in ("load", "motor", "actuator", "mcu")))
        self.source.setText(item.safety.source_url if item is not None and item.safety is not None else "")

    def store_component(self):
        item = self.component()
        if item is None:
            return
        raw = deepcopy(self.draft.model_dump(mode="json"))
        edited = next(component for component in raw["components"] if component["id"] == item.id)
        edited["max_current_a"] = float(self.max_current.text().strip()) if self.max_current.text().strip() else None
        values = {key: float(field.text().strip()) for key, field in self.inputs.items() if field.text().strip()}
        if self.source.text().strip():
            values["source_url"] = self.source.text().strip()
        if values:
            edited["safety"] = values
        elif "safety" in edited:
            edited["safety"] = None
        self.draft = ElectricalWorkspace.model_validate(raw)

    def change_component(self, *_):
        selected = self.choice.currentData()
        try:
            self.store_component()
        except (ValueError, TypeError) as error:
            self.choice.blockSignals(True); self.choice.setCurrentIndex(self.choice.findData(self.current_id)); self.choice.blockSignals(False)
            self.show_error(error); return
        self.current_id = selected; self.load_component(); self.refresh_report()

    def show_error(self, error):
        QMessageBox.warning(self, word("정격 입력 확인", "Check rating inputs"), str(error)[:1000])

    def review(self):
        try:
            self.store_component(); self.refresh_report()
        except (ValueError, TypeError) as error:
            self.show_error(error)

    def refresh_report(self):
        report = evaluate_electrical_safety(self.draft, language="en" if english() else "ko")
        self.safety_report = report
        labels = dict(fault=word("결선·정격 오류", "Wiring / rating fault"), attention=word("경고 있음", "Warnings"),
            pending=word("미검증 조건 있음", "Unverified conditions"), assessed=word("입력 모델 점검 완료", "Entered model reviewed"))
        faults = sum(item.severity == "error" for item in report.issues)
        warnings = sum(item.severity == "warning" for item in report.issues)
        pending = sum(item.severity == "pending" for item in report.issues)
        self.summary.setText(f"{labels[report.status]} · {word('오류', 'Errors')} {faults} · {word('경고', 'Warnings')} {warnings} · {word('미검증', 'Pending')} {pending}")
        self.table.setRowCount(len(report.branches))
        for index, item in enumerate(report.branches):
            values = (item.name, item.current_a, item.startup_current_a, item.dissipated_power_w, item.estimated_temperature_c)
            for column, value in enumerate(values):
                text = value if column == 0 else ("—" if value is None else f"{value:.5g}")
                self.table.setItem(index, column, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        self.report.setPlainText("\n\n".join([*(f"[{item.severity} · {item.scenario}] {item.message}" for item in report.issues), report.scope]))

    def accept(self):
        try:
            self.store_component()
        except (ValueError, TypeError) as error:
            self.show_error(error); return
        self.workspace = ElectricalWorkspace.model_validate(deepcopy(self.draft.model_dump(mode="json")))
        super().accept()

    def reject(self):
        self.workspace = None
        super().reject()
