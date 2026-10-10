"""Evidence entry and read-only fault diagnosis; photos upload only on request."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QSize, Qt, Signal, Slot
from PySide6.QtGui import QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QScrollArea, QSplitter, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget)

from ..electrical import ElectricalWorkspace
from ..electrical_diagnostics import (DiagnosticMeasurement, ElectricalDiagnosisRequest,
    MAX_PHOTOS, MAX_TOTAL_PHOTO_BYTES, diagnose_electrical, diagnostic_report_text, inspect_photo)
from .draft_control import DraftControl
from .mcu_pin_dialog import english, word
from .widgets import button


class _Signals(QObject):
    completed = Signal(int, object)
    failed = Signal(int, str)
    progress = Signal(int, str)


class _DiagnosisWorker(QRunnable):
    def __init__(self, generation, workspace, request, config, control, language):
        super().__init__()
        self.signals = _Signals()
        self.generation, self.workspace, self.request = generation, workspace, request
        self.config, self.control, self.language = config, control, language

    @Slot()
    def run(self):
        try:
            from .electrical_diagnostics_ai import diagnose_with_codex
            report = diagnose_with_codex(self.workspace, self.request, self.config.get("model", ""),
                executable=self.config.get("executable", ""), effort=self.config.get("effort", "medium"),
                deadline=self.config.get("deadline", 600), control=self.control, language=self.language,
                progress=lambda value: self.signals.progress.emit(self.generation, value))
            self.signals.completed.emit(self.generation, report)
        except Exception as error:
            self.signals.failed.emit(self.generation, str(error)[:1600])


class ElectricalDiagnosticsDialog(QDialog):
    """Opening/attaching/reviewing never sends photos or alters the design.

    ``diagnostic_report`` is a snapshot; use ``model_dump(mode='json')`` if the
    caller wants to retain it. Saving creates a separate user-selected report.
    No external instruments, serial devices, flashing or API keys are used.
    """
    def __init__(self, parent, workspace, component_id="", *, codex_config=None, project_path=None):
        super().__init__(parent)
        self.setWindowTitle(word("사진 · 증상 · 실측 전기 고장 진단", "Electrical diagnosis · photos, symptoms and readings"))
        self.resize(1200, 820)
        self.workspace = ElectricalWorkspace.model_validate(workspace or {}).model_copy(deep=True)
        self.codex_config = dict(codex_config or {})
        self.project_path = Path(project_path).resolve() if project_path else None
        self.diagnostic_report = None
        self.measurements, self.photos = [], []
        self._running, self._closing, self._generation = False, False, 0
        self._control, self._worker = None, None
        self._measurement_serial, self._photo_serial = 0, 0
        self.language = "en" if english() else "ko"
        layout = QVBoxLayout(self)
        notice = QLabel(word("저장 회로와 사용자 입력 계측값을 비교합니다. 실제 기기를 검사·계측·작동하지 않습니다. 사진의 도통·전류 정격·온도는 가설입니다.",
            "Compare stored wiring and user-entered readings. Hardware is not inspected, measured or operated. Photo continuity, current ratings and temperature remain hypotheses."))
        notice.setWordWrap(True); layout.addWidget(notice)
        split = QSplitter(Qt.Orientation.Horizontal); layout.addWidget(split, 1)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); split.addWidget(scroll)
        self.inputs_widget = QWidget(); edit = QVBoxLayout(self.inputs_widget); scroll.setWidget(self.inputs_widget)
        form = QFormLayout(); edit.addLayout(form)
        self.target = QComboBox(); self.target.setObjectName("diagnosisTarget")
        self.target.addItem(word("회로 전체", "Whole circuit"), "")
        for item in self.workspace.components: self.target.addItem(f"{item.name} [{item.id}]", item.id)
        if component_id and self.target.findData(component_id) >= 0: self.target.setCurrentIndex(self.target.findData(component_id))
        form.addRow(word("증상 대상", "Symptom target"), self.target)
        self.symptoms = QPlainTextEdit(); self.symptoms.setObjectName("diagnosisSymptoms"); self.symptoms.setMaximumHeight(110)
        self.symptoms.setPlaceholderText(word("예: 모터가 멈춤, 특정 전선이 뜨거움, 퓨즈가 끊김. 언제·어디서·어떤 상태인지 적으세요.",
            "Example: motor stopped, one wire feels hot, fuse open. Describe when, where and operating state."))
        form.addRow(word("증상", "Symptoms"), self.symptoms)
        self.context = QPlainTextEdit(); self.context.setObjectName("diagnosisContext"); self.context.setMaximumHeight(70)
        self.context.setPlaceholderText(word("전원·부하·접점 상태, 최근 변경, 정격 출처 등", "Supply/load/contact state, recent changes, rating source"))
        form.addRow(word("동작 조건", "Operating context"), self.context)
        edit.addWidget(QLabel(word("사진 · 로컬 첨부 (최대 6장, 장당 8 MiB, 합계 30 MB)",
            "Photos · local attachments (6 max, 8 MiB each, 30 MB total)")))
        self.photo_list = QListWidget(); self.photo_list.setObjectName("diagnosisPhotos"); self.photo_list.setMaximumHeight(115)
        self.photo_list.setIconSize(QSize(96, 72)); self.photo_list.setSpacing(4)
        edit.addWidget(self.photo_list)
        photo_controls = QHBoxLayout(); edit.addLayout(photo_controls)
        self.add_photo_button = button(word("사진 첨부", "Attach photos"), self.choose_photos)
        self.remove_photo_button = button(word("사진 제거", "Remove photo"), self.remove_photo)
        photo_controls.addWidget(self.add_photo_button); photo_controls.addWidget(self.remove_photo_button)
        transmission = QLabel(word("첨부는 로컬에 유지됩니다. 아래 ‘Codex 사진·증상 진단’ 버튼을 누르면 선택된 사진·회로·증상·계측값을 ChatGPT 로그인 계정으로 전송합니다.",
            "Attachments stay local. Clicking ‘Codex photo/symptom diagnosis’ sends selected photos, circuit, symptoms and readings through your ChatGPT login."))
        transmission.setWordWrap(True); edit.addWidget(transmission)
        edit.addWidget(QLabel(word("선택 계측값 · 빈 값은 미측정, 임의 추정하지 않음", "Optional readings · blank means unmeasured")))
        measurement_form = QFormLayout(); edit.addLayout(measurement_form)
        self.quantity = QComboBox(); self.quantity.setObjectName("diagnosisQuantity")
        for key, ko, en in (("voltage", "전압 V", "Voltage V"), ("current", "전류 A", "Current A"),
                ("resistance", "저항 Ω / OL", "Resistance Ω / OL"), ("continuity", "도통 1/0", "Continuity 1/0"),
                ("temperature", "온도 °C", "Temperature °C")):
            self.quantity.addItem(word(ko, en), key)
        measurement_form.addRow(word("물리량", "Quantity"), self.quantity)
        self.measure_target = QComboBox(); self.measure_target.setObjectName("diagnosisMeasurementTarget")
        self.measure_target.addItem(word("노드 두 개", "Node pair"), "")
        for item in self.workspace.components: self.measure_target.addItem(f"{item.name} [{item.id}]", item.id)
        if component_id and self.measure_target.findData(component_id) >= 0: self.measure_target.setCurrentIndex(self.measure_target.findData(component_id))
        measurement_form.addRow(word("계측 대상", "Reading target"), self.measure_target)
        nodes = QWidget(); node_layout = QHBoxLayout(nodes); node_layout.setContentsMargins(0, 0, 0, 0)
        self.node_a, self.node_b = QComboBox(), QComboBox()
        for node in self.workspace.nodes: self.node_a.addItem(node); self.node_b.addItem(node)
        if len(self.workspace.nodes) > 1: self.node_b.setCurrentIndex(1)
        node_layout.addWidget(self.node_a); node_layout.addWidget(QLabel("−")); node_layout.addWidget(self.node_b)
        measurement_form.addRow(word("노드 A − B", "Node A − B"), nodes)
        self.value = QLineEdit(); self.value.setObjectName("diagnosisValue")
        self.value.setPlaceholderText(word("수치 또는 저항 OL · 도통 1=연결, 0=끊김", "Number or resistance OL · continuity 1=yes, 0=no"))
        measurement_form.addRow(word("값 (SI 단위)", "Value (SI units)"), self.value)
        self.provenance = QComboBox(); self.provenance.addItem(word("보고된 수치", "Reported reading"), "user_reported")
        self.provenance.addItem(word("사용자가 직접 계측", "User measured"), "measured")
        measurement_form.addRow(word("출처", "Origin"), self.provenance)
        self.power = QComboBox(); self.power.addItem(word("인가 상태 미확인", "Power state unknown"), "unknown")
        self.power.addItem(word("전원 인가", "Powered"), "powered"); self.power.addItem(word("전원 분리·방전 확인", "Unpowered / discharge checked"), "unpowered")
        measurement_form.addRow(word("계측 시 전원", "Power during reading"), self.power)
        self.isolated = QCheckBox(word("시험 대상 분리 · 병렬 경로 없음 확인", "Test target isolated / parallel paths checked"))
        measurement_form.addRow("", self.isolated)
        self.reading_note = QLineEdit(); self.reading_note.setObjectName("diagnosisReadingNote")
        self.reading_note.setPlaceholderText(word("계측기·위치·리드 보정·오차·시점", "Instrument, location, lead correction, uncertainty, time"))
        measurement_form.addRow(word("계측 메모", "Reading note"), self.reading_note)
        directions = QLabel(word("전압: A−B. 전류: 부하 A→B, 전원은 B→A 공급이 양수. 저항·도통은 전원 분리·방전·시험 경로 분리 후에만 해석합니다.",
            "Voltage: A−B. Current: load A→B; source delivered B→A is positive. Resistance/continuity is interpreted only after power removal, discharge and path isolation."))
        directions.setWordWrap(True); edit.addWidget(directions)
        reading_controls = QHBoxLayout(); edit.addLayout(reading_controls)
        self.add_reading_button = button(word("계측값 추가", "Add reading"), self.add_reading)
        self.remove_reading_button = button(word("선택 계측값 제거", "Remove selected reading"), self.remove_reading)
        reading_controls.addWidget(self.add_reading_button); reading_controls.addWidget(self.remove_reading_button)
        self.readings = QTableWidget(0, 4); self.readings.setObjectName("diagnosisReadings"); self.readings.setMinimumHeight(130)
        self.readings.setHorizontalHeaderLabels([word("물리량", "Quantity"), word("대상", "Target"), word("값", "Value"), word("조건", "Conditions")])
        self.readings.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.readings.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.readings.horizontalHeader().setStretchLastSection(True)
        edit.addWidget(self.readings)
        display = QWidget(); results = QVBoxLayout(display); split.addWidget(display); split.setSizes([530, 670])
        self.status = QLabel(word("증상·선택 계측값을 입력한 뒤 진단하세요.", "Enter symptoms and optional readings, then run diagnosis."))
        self.status.setWordWrap(True); self.status.setObjectName("diagnosisStatus"); results.addWidget(self.status)
        tabs = QTabWidget(); results.addWidget(tabs, 1)
        self.report_text = QPlainTextEdit(); self.report_text.setReadOnly(True); self.report_text.setObjectName("diagnosisReport")
        tabs.addTab(self.report_text, word("근거 · 진단 · 확인 절차", "Evidence, findings and confirmations"))
        self.expected = QTableWidget(0, 4); self.expected.setObjectName("diagnosisExpectedBranches")
        self.expected.setHorizontalHeaderLabels([word("부품", "Component"), "A", "V (A−B)", "Ω"])
        self.expected.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.expected.horizontalHeader().setStretchLastSection(True)
        tabs.addTab(self.expected, word("저장 회로 DC 추정", "Stored circuit DC estimate"))
        controls = QHBoxLayout(); layout.addLayout(controls)
        self.review_button = button(word("회로·입력값 진단 (로컬)", "Review circuit/readings locally"), self.review, True)
        self.review_button.setObjectName("diagnosisLocalReview"); controls.addWidget(self.review_button)
        self.ai_button = button(word("Codex 사진·증상 진단 · 전송", "Codex photo/symptom diagnosis · send"), self.start_codex)
        self.ai_button.setObjectName("diagnosisCodexSend"); controls.addWidget(self.ai_button)
        self.cancel_button = button(word("진단 취소", "Cancel diagnosis"), self.cancel_diagnosis)
        self.cancel_button.setEnabled(False); controls.addWidget(self.cancel_button)
        self.export_button = button(word("보고서 저장…", "Save report…"), self.export_report)
        self.export_button.setObjectName("diagnosisExport"); self.export_button.setEnabled(False); controls.addWidget(self.export_button)
        controls.addWidget(button(word("닫기", "Close"), self.reject))
        self.symptoms.textChanged.connect(self.mark_dirty); self.context.textChanged.connect(self.mark_dirty)
        self.target.currentIndexChanged.connect(self.mark_dirty)
        self.measure_target.currentIndexChanged.connect(self._update_nodes); self._update_nodes()

    def _update_nodes(self, *_):
        enabled = not self.measure_target.currentData()
        self.node_a.setEnabled(enabled); self.node_b.setEnabled(enabled)

    def mark_dirty(self, *_):
        if self._running: return
        self.diagnostic_report = None; self.export_button.setEnabled(False)
        self.status.setText(word("입력이 변경되었습니다. 진단을 실행하세요.", "Inputs changed. Run diagnosis."))
        self.report_text.clear(); self.expected.setRowCount(0)

    def show_error(self, error):
        self.status.setText(str(error)[:1600])
        QMessageBox.warning(self, word("진단 입력 확인", "Check diagnosis inputs"), str(error)[:1600])

    def choose_photos(self):
        paths, _ = QFileDialog.getOpenFileNames(self, word("현장 사진 첨부", "Attach photos"), "", "Photos (*.png *.jpg *.jpeg *.webp)")
        for path in paths:
            try: self.add_photo(path)
            except (ValueError, OSError) as error: self.show_error(error); break

    def add_photo(self, path):
        if self._running: raise ValueError("Diagnosis is running.")
        if len(self.photos) >= MAX_PHOTOS: raise ValueError("사진은 최대 6장입니다. / At most 6 photos.")
        self._photo_serial += 1
        photo = inspect_photo(path, f"photo-{self._photo_serial}")
        if any(item.path == photo.path for item in self.photos): raise ValueError("이미 첨부한 사진입니다. / Photo already attached.")
        if sum(item.size_bytes for item in self.photos) + photo.size_bytes > MAX_TOTAL_PHOTO_BYTES:
            raise ValueError("사진 합계는 30 MB 이하여야 합니다. / Photos total at most 30 MB.")
        reader = QImageReader(photo.path)
        size = reader.size()
        if not reader.canRead() or not size.isValid() or size.width() * size.height() > 25_000_000:
            raise ValueError("디코딩 가능한 25 MP 이하 사진을 첨부하세요. / Use a decodable image of at most 25 MP.")
        image = reader.read()
        if image.isNull(): raise ValueError("사진을 읽을 수 없습니다. / Photo cannot be decoded.")
        icon = QIcon(QPixmap.fromImage(image.scaled(96, 72, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))
        self.photos.append(photo)
        item = QListWidgetItem(icon, f"{photo.id} · {photo.name} · {photo.size_bytes / 1024:.0f} KiB")
        item.setToolTip(photo.path); self.photo_list.addItem(item); self.mark_dirty()
        return photo

    def remove_photo(self):
        if self._running: return
        index = self.photo_list.currentRow()
        if index >= 0: self.photos.pop(index); self.photo_list.takeItem(index); self.mark_dirty()

    def add_reading(self):
        try:
            text = self.value.text().strip()
            if not text: raise ValueError(word("값을 입력하세요. 빈 값은 미측정입니다.", "Enter a value; blank means unmeasured."))
            self._measurement_serial += 1
            opened = self.quantity.currentData() == "resistance" and text.lower() in ("ol", "open", "inf", "∞")
            component = self.measure_target.currentData() or ""
            reading = DiagnosticMeasurement(id=f"measurement-{self._measurement_serial}", quantity=self.quantity.currentData(),
                value=None if opened else float(text), outcome="open" if opened else "reading", component_id=component,
                node_a="" if component else self.node_a.currentText(), node_b="" if component else self.node_b.currentText(),
                provenance=self.provenance.currentData(), power_state=self.power.currentData(),
                isolated=self.isolated.isChecked(), note=self.reading_note.text())
            if len(self.measurements) >= 64: raise ValueError("At most 64 readings.")
            self.measurements.append(reading); self._refresh_readings(); self.mark_dirty()
        except (ValueError, TypeError) as error: self.show_error(error)

    def _refresh_readings(self):
        self.readings.setRowCount(len(self.measurements))
        for row, item in enumerate(self.measurements):
            values = [item.quantity, item.component_id or f"{item.node_a}−{item.node_b}",
                "OL" if item.outcome == "open" else f"{item.value:g}",
                f"{item.provenance} / {item.power_state}" + (" / isolated" if item.isolated else "")]
            for column, value in enumerate(values): self.readings.setItem(row, column, QTableWidgetItem(value))
        self.readings.resizeColumnsToContents()

    def remove_reading(self):
        if self._running: return
        row = self.readings.currentRow()
        if row >= 0: self.measurements.pop(row); self._refresh_readings(); self.mark_dirty()

    def diagnosis_request(self):
        return ElectricalDiagnosisRequest(symptoms=self.symptoms.toPlainText(), operating_context=self.context.toPlainText(),
            selected_component_id=self.target.currentData() or "", measurements=self.measurements, photos=self.photos)

    def review(self):
        if self._running: return
        try: self.display_report(diagnose_electrical(self.workspace, self.diagnosis_request(), language=self.language))
        except (ValueError, TypeError) as error: self.show_error(error)

    def display_report(self, report):
        self.diagnostic_report = report
        self.report_text.setPlainText(diagnostic_report_text(report)); self.export_button.setEnabled(True)
        states = {"fault_in_inputs": word("입력 근거에 오류 있음", "Fault in entered evidence"),
            "needs_confirmation": word("실제 고장 확인 필요", "Physical fault requires confirmation"),
            "reviewed": word("입력 근거 비교 완료", "Entered evidence reviewed")}
        self.status.setText(states[report.status] + " · " + word("실제 하드웨어 미검증", "Hardware unverified"))
        self.expected.setRowCount(len(report.expected_branches))
        for row, item in enumerate(report.expected_branches):
            values = [item["name"], item["current_a"] if item["analysis_enabled"] else None,
                item["voltage_drop_v"] if item["analysis_enabled"] else None, item["resistance_ohm"]]
            for column, value in enumerate(values):
                self.expected.setItem(row, column, QTableWidgetItem(str(value) if column == 0 else "—" if value is None else f"{value:.5g}"))
        self.expected.resizeColumnsToContents()

    def _set_busy(self, running):
        self._running = running; self.inputs_widget.setEnabled(not running)
        self.review_button.setEnabled(not running); self.ai_button.setEnabled(not running)
        self.cancel_button.setEnabled(running); self.export_button.setEnabled(not running and self.diagnostic_report is not None)

    def start_codex(self):
        if self._running or self._closing: return
        if not self.codex_config.get("model"):
            self.status.setText(word("메인 AI 패널의 Codex 연결에서 ChatGPT 로그인과 모델 선택을 먼저 완료하세요.",
                "Connect ChatGPT and select a model in the main Codex AI panel first.")); return
        try: request = self.diagnosis_request()
        except (ValueError, TypeError) as error: self.show_error(error); return
        self._generation += 1; self._control = DraftControl(); self._set_busy(True)
        self.status.setText(word("Codex에 선택한 근거를 전송해 진단 중…", "Sending selected evidence to Codex for diagnosis…"))
        worker = _DiagnosisWorker(self._generation, self.workspace.model_copy(deep=True), request.model_copy(deep=True),
            dict(self.codex_config), self._control, self.language)
        self._worker = worker
        worker.signals.completed.connect(self._completed, Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(self._failed, Qt.ConnectionType.QueuedConnection)
        worker.signals.progress.connect(self._progress, Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(worker)

    def cancel_diagnosis(self):
        if self._control: self._control.cancel()
        self.cancel_button.setEnabled(False)
        self.status.setText(word("진단 취소 중…", "Cancelling diagnosis…"))

    @Slot(int, object)
    def _completed(self, generation, report):
        if self._closing or generation != self._generation: return
        self._set_busy(False); self._worker = None; self.display_report(report)

    @Slot(int, str)
    def _failed(self, generation, message):
        if self._closing or generation != self._generation: return
        self._set_busy(False); self._worker = None; self.status.setText(message)

    @Slot(int, str)
    def _progress(self, generation, message):
        if not self._closing and generation == self._generation: self.status.setText(message)

    def export_report_to(self, path):
        if self.diagnostic_report is None or self._running: raise ValueError("진단을 먼저 실행하세요. / Run diagnosis first.")
        target = Path(path).expanduser().resolve()
        if target == self.project_path or target.suffix.lower() not in (".json", ".txt"):
            raise ValueError("별도의 .json 또는 .txt 보고서로 저장하세요. / Save a separate .json or .txt report.")
        content = self.diagnostic_report.model_dump_json(indent=2) if target.suffix.lower() == ".json" else diagnostic_report_text(self.diagnostic_report)
        target.write_text(content, encoding="utf-8")
        return target

    def export_report(self):
        base = self.project_path.with_suffix(".diagnostics.json") if self.project_path else Path("electrical-diagnostics.json")
        path, _ = QFileDialog.getSaveFileName(self, word("진단 보고서 저장", "Save diagnostic report"), str(base),
            "Diagnostic JSON (*.json);;Text report (*.txt)")
        if not path: return
        try: self.export_report_to(path)
        except (ValueError, OSError) as error: self.show_error(error)

    def _close(self):
        self._closing = True; self._generation += 1
        if self._control: self._control.cancel()

    def reject(self):
        self._close(); super().reject()

    def closeEvent(self, event):
        self._close(); super().closeEvent(event)
