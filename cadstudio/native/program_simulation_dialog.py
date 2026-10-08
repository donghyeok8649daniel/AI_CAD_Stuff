"""Automatic safe code-to-wiring projection; Qt owns all visible widgets."""
from __future__ import annotations

import json
import threading

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QHeaderView, QPlainTextEdit, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..electrical import ElectricalWorkspace
from ..program_attachment import ProgramAttachment, read_program
from ..program_simulation import simulate_program
from .widgets import button


class _Signals(QObject):
    finished = Signal(int, object)
    failed = Signal(int, str)


class _Worker(QRunnable):
    def __init__(self, generation, workspace, attachment, cancel, selected, language):
        super().__init__()
        self.signals = _Signals()
        self.generation, self.workspace, self.attachment = generation, workspace, attachment
        self.cancel, self.selected, self.language = cancel, selected, language

    @Slot()
    def run(self):
        try:
            result = simulate_program(self.workspace, self.attachment,
                cancel_event=self.cancel, selected_component_id=self.selected)
            report = None
            if result.status != 'cancelled' and not self.cancel.is_set():
                from ..electrical_safety import evaluate_electrical_safety
                report = evaluate_electrical_safety(self.workspace, language=self.language)
            if self.cancel.is_set(): result.status = 'cancelled'
            self.signals.finished.emit(self.generation, (result, report))
        except Exception as exc:
            self.signals.failed.emit(self.generation, str(exc)[:1400])


class ProgramSimulationDialog(QDialog):
    """Upload immediately projects one exact board through current saved wires.

    ``attachmentsChanged`` supplies portable source data to the project's
    normal transactional save path. The dialog never edits circuit topology.
    Uploaded source is read-only in this view and is never executed by Python,
    a compiler, shell, MCU, remote API or the real Raspberry Pi.
    """
    attachmentsChanged = Signal(object)

    def __init__(self, workspace, parent=None, language='ko', selected_component_id=''):
        super().__init__(parent)
        self.english = language == 'en'
        self.workspace = ElectricalWorkspace.model_validate(workspace.model_dump() if hasattr(workspace, 'model_dump') else workspace).model_copy(deep=True)
        self.selected_component_id = selected_component_id
        self.attachments = [ProgramAttachment.model_validate(item) for item in getattr(self.workspace, 'programs', [])]
        self.result = None; self.safety_report = None
        self._generation = 0; self._closing = False; self._running = False
        self._cancel = threading.Event(); self._worker = None
        self.setWindowTitle(self.word('코드 · 배선 자동 시뮬레이션', 'Code · automatic wiring simulation'))
        self.setObjectName('programSimulationDialog')
        self.resize(1080, 720)
        layout = QVBoxLayout(self)
        scope = QLabel(self.word('코드 업로드 → 정확한 보드·핀 자동 확인 → 현재 배선의 GPIO/PWM 신호 추적',
            'Upload source → resolve exact board/pins → trace GPIO/PWM commands through current wires'), self)
        scope.setWordWrap(True); layout.addWidget(scope)
        row = QHBoxLayout()
        self.upload_button = button(self.word('코드 업로드…', 'Upload code…'), self.upload_program)
        self.program_combo = QComboBox(self); self.program_combo.setObjectName('programAttachmentCombo')
        self.program_combo.currentIndexChanged.connect(self._attachment_selected)
        self.run_button = button(self.word('배선대로 다시 추적', 'Trace current wiring'), self.run_simulation)
        self.cancel_button = button(self.word('취소', 'Cancel'), self.cancel_simulation)
        self.export_button = button(self.word('추적 JSON 저장…', 'Export trace JSON…'), self.export_result)
        for widget in (self.upload_button, self.program_combo, self.run_button, self.cancel_button, self.export_button): row.addWidget(widget)
        layout.addLayout(row)
        self.status = QLabel(self); self.status.setObjectName('programSimulationStatus'); self.status.setWordWrap(True); layout.addWidget(self.status)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.source_view = QPlainTextEdit(splitter); self.source_view.setReadOnly(True); self.source_view.setObjectName('programSourceView')
        pane = QWidget(splitter); pane_layout = QVBoxLayout(pane)
        self.events = QTableWidget(0, 6, pane); self.events.setObjectName('programTraceTable')
        self.events.setHorizontalHeaderLabels(self.word(['시간 s', '핀', 'Duty', '주파수 Hz', '노드', '수신 단자'],
            ['Time s', 'Pin', 'Duty', 'Frequency Hz', 'Net', 'Receiving terminals']))
        self.events.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for column in range(5): self.events.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.events.horizontalHeader().setStretchLastSection(True)
        pane_layout.addWidget(self.events, 2)
        self.issues = QPlainTextEdit(pane); self.issues.setReadOnly(True); self.issues.setObjectName('programSimulationIssues'); pane_layout.addWidget(self.issues, 1)
        splitter.addWidget(self.source_view); splitter.addWidget(pane); splitter.setSizes([400, 680]); layout.addWidget(splitter, 1)
        note = QLabel(self.word('자동 추적 범위: Arduino digitalWrite/analogWrite/delay, Raspberry Pi GPIO/gpiozero 출력, STM32 HAL GPIO/지연. '
            '입력 센서·통신·동적 제어·전체 펌웨어/OS·모터 물리·과열은 이 추적으로 검증하지 않습니다. 미지원 코드는 성공으로 표시하지 않습니다.',
            'Automatic scope: Arduino digitalWrite/analogWrite/delay; Raspberry Pi GPIO/gpiozero outputs; STM32 HAL GPIO/delay. '
            'Sensor reads, communications, dynamic control, full firmware/OS, motor physics and thermal behavior are outside this trace. Unsupported code is blocked.'), self)
        note.setWordWrap(True); layout.addWidget(note)
        footer = QHBoxLayout()
        self.remove_button = button(self.word('선택 첨부 삭제', 'Remove selected attachment'), self.remove_program)
        footer.addWidget(self.remove_button); footer.addStretch()
        self.apply_button = button(self.word('프로그램 첨부 적용', 'Apply program attachments'), self.accept)
        footer.addWidget(self.apply_button); footer.addWidget(button(self.word('취소 / 닫기', 'Cancel / close'), self.reject)); layout.addLayout(footer)
        self._refresh_attachments()
        self._set_busy(False)
        if self.attachments: self._attachment_selected(self.program_combo.currentIndex())
        else: self.status.setText(self.word('코드를 업로드하면 추가 설정 없이 현재 배선으로 자동 추적합니다.',
            'Upload code to automatically trace the current wiring without further setup.'))

    def word(self, ko, en): return en if self.english else ko

    def _refresh_attachments(self):
        self.program_combo.blockSignals(True); self.program_combo.clear()
        for attachment in self.attachments: self.program_combo.addItem(attachment.name, attachment.sha256)
        self.program_combo.blockSignals(False)

    def upload_program(self):
        path, _ = QFileDialog.getOpenFileName(self, self.word('코드 첨부', 'Attach code'), '',
            'Program source (*.ino *.py *.c *.cpp *.h)')
        if not path: return
        try: self.add_program(read_program(path))
        except Exception as exc: self.status.setText(str(exc)[:1400])

    def add_program(self, attachment):
        attachment = ProgramAttachment.model_validate(attachment)
        old = next((index for index, value in enumerate(self.attachments) if value.name == attachment.name
                    or (value.sha256 == attachment.sha256 and (not attachment.board_component_id
                        or value.board_component_id == attachment.board_component_id))), None)
        if old is None:
            if len(self.attachments) >= 32: raise ValueError('프로그램 첨부는 최대 32개입니다.')
            self.attachments.append(attachment); index = len(self.attachments) - 1
        else: self.attachments[old] = attachment; index = old
        self._refresh_attachments(); self.program_combo.setCurrentIndex(index)
        self.attachmentsChanged.emit([item.model_dump() for item in self.attachments])
        self._attachment_selected(index)

    def _attachment_selected(self, index):
        if not 0 <= index < len(self.attachments): return
        self.source_view.setPlainText(self.attachments[index].source)
        if not self._running: self.run_simulation()

    def remove_program(self):
        if self._running: return
        index = self.program_combo.currentIndex()
        if not 0 <= index < len(self.attachments): return
        self.attachments.pop(index); self._refresh_attachments()
        self.result = None; self.safety_report = None
        self.source_view.clear(); self.events.setRowCount(0); self.issues.clear()
        self.attachmentsChanged.emit([item.model_dump() for item in self.attachments])
        self._set_busy(False)
        if self.attachments: self._attachment_selected(self.program_combo.currentIndex())
        else: self.status.setText(self.word('첨부를 제거했습니다. 적용 전에는 저장된 프로젝트가 바뀌지 않습니다.',
            'Attachment removed from this draft. Apply to persist; Cancel keeps the saved project.'))

    def _set_busy(self, busy):
        self._running = busy
        self.upload_button.setEnabled(not busy); self.program_combo.setEnabled(not busy)
        self.run_button.setEnabled(not busy and bool(self.attachments)); self.cancel_button.setEnabled(busy)
        self.export_button.setEnabled(not busy and self.result is not None)
        self.apply_button.setEnabled(not busy)
        self.remove_button.setEnabled(not busy and bool(self.attachments))

    def run_simulation(self):
        if self._running or self._closing: return
        index = self.program_combo.currentIndex()
        if not 0 <= index < len(self.attachments): return
        self._generation += 1; self._cancel = threading.Event(); self._set_busy(True)
        self.status.setText(self.word('코드 · 핀 · 전원 · 현재 배선을 확인하는 중…', 'Checking source, pins, supply and current wiring…'))
        worker = _Worker(self._generation, self.workspace.model_copy(deep=True), self.attachments[index], self._cancel, self.selected_component_id,
            'en' if self.english else 'ko')
        self._worker = worker
        worker.signals.finished.connect(self._finished, Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(self._failed, Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(worker)

    def cancel_simulation(self):
        self._cancel.set(); self.cancel_button.setEnabled(False)

    @Slot(int, object)
    def _finished(self, generation, payload):
        if self._closing or generation != self._generation: return
        result, self.safety_report = payload
        self.result = result; self._set_busy(False)
        if result.board_component_id:
            index = next((index for index, attachment in enumerate(self.attachments)
                          if attachment.sha256 == result.attachment_sha256), None)
            if index is not None and self.attachments[index].board_component_id != result.board_component_id:
                self.attachments[index] = self.attachments[index].model_copy(update={'board_component_id': result.board_component_id})
                self.attachmentsChanged.emit([item.model_dump() for item in self.attachments])
        states = {'ready':('신호 명령 추적 완료 · 하드웨어 동작 인증 아님', 'Signal trace ready · not hardware validation'),
            'blocked':('코드 또는 배선 확인 필요', 'Source or wiring blocked'), 'fault':('배선 위험 감지', 'Wiring fault detected'),
            'cancelled':('추적 취소됨', 'Trace cancelled')}
        self.status.setText(self.word(*states[result.status]) + ' · ' + (result.board_component_id or '—'))
        if self.safety_report is not None:
            self.status.setText(self.status.text() + ' · '+self.word('기존 회로 안전: ', 'Saved circuit safety: ')+self.safety_report.status)
        self.events.setUpdatesEnabled(False); self.events.setRowCount(len(result.events))
        for row, event in enumerate(result.events):
            values = [f'{event.time_s:.5g}', event.pin, f'{event.duty:.5g}', '—' if event.frequency_hz is None else f'{event.frequency_hz:g}', event.node or '—', ', '.join(event.targets)]
            for column, value in enumerate(values): self.events.setItem(row, column, QTableWidgetItem(value))
        self.events.setUpdatesEnabled(True)
        english_messages = {
            'physical_supply_pads':'Only the existing board A/B supply path is checked; physical power/USB/regulator pads have not been registered.',
            'hal_initialization':'HAL GPIO commands only. Clock/GPIO initialization, interrupts, timers and full firmware execution remain unverified.',
            'pwm_frequency':'Duty commands are traced; unspecified PWM frequency and switching waveform are not guessed.',
            'physical_behavior':'GPIO/PWM command and wiring trace only; MCU timing, sensor inputs, motor speed, actual output current, heat and OS behavior remain unverified.',
            'trace_limit':'Trace data limit reached; only commands up to this limit are shown.',
            'released_gpio':'GPIO cleanup releases drive. Floating input voltage or a safe stop is not assumed to be LOW.',
        }
        lines = [f'[{item.severity}] '+(english_messages.get(item.code,item.message) if self.english else item.message) for item in result.issues]
        if self.safety_report is not None:
            lines.append('\n'+self.word('기존 회로 DC/열 안전 평가 (동적 GPIO 전력 모델 아님): ',
                'Saved circuit DC/thermal safety (not a dynamic GPIO power model): ')+self.safety_report.status)
            lines.extend(f'[DC/{item.severity}] {item.message}' for item in self.safety_report.issues)
        self.issues.setPlainText('\n'.join(lines))

    @Slot(int, str)
    def _failed(self, generation, message):
        if self._closing or generation != self._generation: return
        self._set_busy(False); self.status.setText(message)

    def export_result(self):
        if self.result is None: return
        path, _ = QFileDialog.getSaveFileName(self, self.word('추적 저장', 'Save trace'), 'program-trace.json', 'JSON (*.json)')
        if not path: return
        try:
            from pathlib import Path
            data={'program_trace':self.result.model_dump(), 'saved_circuit_safety':self.safety_report.model_dump() if self.safety_report is not None else None}
            Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as exc: self.status.setText(str(exc)[:1200])

    def closeEvent(self, event):
        self._closing = True; self._cancel.set(); self._generation += 1
        super().closeEvent(event)

    def done(self, result):
        self._closing = True; self._cancel.set(); self._generation += 1
        super().done(result)
