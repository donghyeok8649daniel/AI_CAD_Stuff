"""Read-only bilingual motor matrices; no file picker, workers or simulation."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton
from ..motor_state_space import state_space_report, report_text


class MotorMatrixDialog(QDialog):
    def __init__(self, parameter_record=None, parent=None, language='ko'):
        # Validate the complete in-memory record before creating the widget.
        report = state_space_report(parameter_record)
        super().__init__(parent)
        self.report = report
        self.english = language == 'en'
        self.setObjectName('motorMatrixDialog')
        self.setWindowTitle('Motor state-space matrices' if self.english else '모터 상태공간 행렬')
        self.resize(820, 710)
        root = QVBoxLayout(self)
        self.scope_label = QLabel('Read only · algebra review; no simulation or actual RPM.' if self.english else
                                  '읽기 전용 · 행렬 검토만 합니다. 시뮬레이션이나 실제 RPM이 아닙니다.')
        self.scope_label.setTextFormat(Qt.TextFormat.PlainText)
        self.scope_label.setWordWrap(True)
        self.scope_label.setObjectName('motorMatrixScope')
        root.addWidget(self.scope_label)
        self.text = QPlainTextEdit()
        self.text.setObjectName('motorMatrixReport')
        self.text.setReadOnly(True)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.text.setPlainText(report_text(report, language))
        root.addWidget(self.text, 1)
        self.actual_label = QLabel('Actual RPM/current/clock: Unknown · hardware permission: none' if self.english else
                                   '실제 RPM·전류·시간: 미확인 · 장비 구동 권한 없음')
        self.actual_label.setTextFormat(Qt.TextFormat.PlainText)
        self.actual_label.setWordWrap(True)
        self.actual_label.setObjectName('motorMatrixActualUnknown')
        root.addWidget(self.actual_label)
        end = QHBoxLayout()
        end.addStretch()
        close = QPushButton('Close' if self.english else '닫기')
        close.setObjectName('motorMatrixClose')
        close.clicked.connect(self.reject)
        end.addWidget(close)
        root.addLayout(end)
