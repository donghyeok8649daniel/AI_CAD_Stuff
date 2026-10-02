"""Native entry point for a deliberately narrow bolt proof-load comparison."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QFormLayout, QHBoxLayout, QLineEdit,
                               QPlainTextEdit, QVBoxLayout)

from ..fastener_checks import (PITCH_SOURCE_PDF, SOURCE_PDF, AxialBoltCheck, check_axial_bolts,
                               format_axial_check)
from .widgets import button, label


class FastenerCheckDialog(QDialog):
    """Requires real load inputs and explicit equal-share/variant assumptions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("볼트 축방향 인장 사전 검토")
        self.resize(760, 690)
        self.check_result: AxialBoltCheck | None = None
        self.copied_report = ""

        root = QVBoxLayout(self)
        root.addWidget(label(
            "ISO 898-1 강재 볼트의 나사부에 순수한 정적 축인장이 걸릴 때만 "
            "증명하중과 비교합니다. 실제 총 하중·동일 볼트 개수·안전계수를 입력하세요. "
            "결합부나 기계 전체의 안전 판정은 하지 않습니다.", True))

        form = QFormLayout()
        root.addLayout(form)
        self.thread = QComboBox()
        for thread, pitch in (("M4", 0.7), ("M5", 0.8), ("M6", 1.0), ("M8", 1.25)):
            self.thread.addItem(f"{thread} × {pitch:g} mm", thread)
        form.addRow("볼트 보통 피치", self.thread)
        self.property_class = QComboBox()
        for strength_class in ("8.8", "10.9"):
            self.property_class.addItem(strength_class, strength_class)
        form.addRow("실제 강도 등급", self.property_class)

        self.force = QLineEdit()
        self.force.setPlaceholderText("실제 총 축방향 인장 하중 · N")
        form.addRow("총 축방향 인장 하중 (N)", self.force)
        self.bolt_count = QLineEdit()
        self.bolt_count.setPlaceholderText("하중을 함께 받는 동일 볼트 개수")
        form.addRow("볼트 개수", self.bolt_count)
        self.safety_factor = QLineEdit()
        self.safety_factor.setPlaceholderText("사용자가 정한 안전계수 · 1 이상")
        form.addRow("안전계수", self.safety_factor)

        self.equal_sharing = QCheckBox("동일 볼트가 축방향 하중을 균등하게 분담한다고 가정합니다")
        root.addWidget(self.equal_sharing)
        self.head_geometry = QCheckBox("낮은 머리·접시머리처럼 증명하중을 낮출 수 있는 머리 형상이 아님을 확인했습니다")
        root.addWidget(self.head_geometry)
        self.m8_variant = QCheckBox("M8은 6az 용융아연도금 감소 증명하중 대상이 아님을 확인했습니다")
        root.addWidget(self.m8_variant)
        self.thread.currentIndexChanged.connect(self.update_variant)

        root.addWidget(label(
            "전단·굽힘·편심·프리로드·피로·나사산 뽑힘·플라스틱 모재는 계산하지 않습니다. "
            "확인한 실물 볼트의 등급·피치·코팅이 자료와 일치해야 합니다.", True))
        row = QHBoxLayout()
        self.calculate_button = button("축인장 검토 계산", self.calculate, True)
        row.addWidget(self.calculate_button)
        self.source_button = button("Bossard 원문 열기", self.open_source)
        row.addWidget(self.source_button)
        self.pitch_source_button = button("보통 피치 원문 열기", self.open_pitch_source)
        row.addWidget(self.pitch_source_button)
        root.addLayout(row)

        self.status = label("하중·개수·안전계수는 아직 입력되지 않았습니다.", True)
        root.addWidget(self.status)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("계산 결과와 적용 범위가 여기에 표시됩니다.")
        root.addWidget(self.output, 1)
        bottom = QHBoxLayout()
        self.copy_button = button("검토 결과 복사", self.copy_report)
        self.copy_button.setEnabled(False)
        bottom.addWidget(self.copy_button)
        bottom.addStretch()
        bottom.addWidget(button("닫기", self.reject))
        root.addLayout(bottom)

        for field in (self.force, self.bolt_count, self.safety_factor):
            field.textChanged.connect(self.clear_previous_result)
        self.equal_sharing.toggled.connect(self.clear_previous_result)
        self.head_geometry.toggled.connect(self.clear_previous_result)
        self.m8_variant.toggled.connect(self.clear_previous_result)
        self.property_class.currentIndexChanged.connect(self.clear_previous_result)
        self.update_variant()
        self.set_status("하중·개수·안전계수는 아직 입력되지 않았습니다.")

    @staticmethod
    def current_language() -> str:
        service = getattr(QApplication.instance(), "cad_language", None)
        return getattr(service, "language", "ko")

    def set_status(self, source_text: str):
        self.status.setText(source_text)
        service = getattr(QApplication.instance(), "cad_language", None)
        if service is not None:
            service.apply(self.status)

    def update_variant(self, *_):
        is_m8 = self.thread.currentData() == "M8"
        self.m8_variant.setVisible(is_m8)
        self.m8_variant.setChecked(False)
        self.clear_previous_result()

    def clear_previous_result(self, *_):
        self.check_result = None
        self.copied_report = ""
        self.output.clear()
        self.copy_button.setEnabled(False)
        self.set_status("입력이 바뀌었습니다. 다시 계산하세요.")

    def calculate(self):
        self.clear_previous_result()
        if not all((self.force.text().strip(), self.bolt_count.text().strip(),
                    self.safety_factor.text().strip())):
            self.set_status("총 하중·볼트 개수·안전계수를 모두 입력하세요.")
            return
        try:
            force = float(self.force.text().strip())
            count = int(self.bolt_count.text().strip())
            safety = float(self.safety_factor.text().strip())
        except (ValueError, OverflowError):
            self.set_status("하중·개수·안전계수는 숫자로 입력하세요.")
            return
        try:
            self.check_result = check_axial_bolts(
                self.thread.currentData(), self.property_class.currentData(),
                force, count, safety,
                assume_equal_sharing=self.equal_sharing.isChecked(),
                applicable_head_geometry=self.head_geometry.isChecked(),
                m8_standard_proof_variant=self.m8_variant.isChecked(),
            )
        except (ValueError, OverflowError) as exc:
            self.set_status(str(exc) or "입력값을 확인하세요.")
            return
        self.output.setPlainText(format_axial_check(self.check_result, self.current_language()))
        self.copy_button.setEnabled(True)
        if self.check_result.within_proof_reference:
            self.set_status("이 축인장 가정에서 참조 증명하중 이내 · 결합부 검증은 별도")
        else:
            self.set_status("축인장 가정에서도 참조 증명하중 초과 · 설계 수정 필요")

    def open_source(self):
        QDesktopServices.openUrl(QUrl(SOURCE_PDF))

    def open_pitch_source(self):
        QDesktopServices.openUrl(QUrl(PITCH_SOURCE_PDF))

    def copy_report(self):
        if self.check_result is None:
            return
        self.copied_report = format_axial_check(self.check_result, self.current_language())
        QApplication.instance()._fastener_check_copy = self.copied_report
        QApplication.clipboard().setText(self.copied_report)
        self.set_status("출처와 검토 범위를 포함한 결과를 복사했습니다.")
