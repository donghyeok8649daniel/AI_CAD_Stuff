"""Explicit mechanical purpose, without changing display roles or wiring."""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QComboBox, QDialogButtonBox, QApplication
from ..mechanical_functions import FUNCTIONS, function_label, mechanical_function
from .widgets import label


class MechanicalFunctionDialog(QDialog):
    def __init__(self, parent, parts):
        super().__init__(parent)
        en = getattr(getattr(QApplication.instance(), 'cad_language', None), 'language', 'ko') == 'en'
        self.setWindowTitle('Mechanical function' if en else '기계 기능 · 체결 / 관절 / 액추에이터')
        self.resize(460, 300)
        layout = QVBoxLayout(self)
        layout.addWidget(label(f'{len(parts)} parts' if en else f'{len(parts)}개 부품', True))
        layout.addWidget(label(
            'Choose the physical purpose. A joint constraint does not create a motor.' if en else
            '부품의 실제 용도를 지정하세요. 조립 구속만 설정하면 모터가 생기는 것은 아닙니다.', True))
        self.function = QComboBox()
        self.function.setObjectName('mechanicalFunctionChoice')
        values = {mechanical_function(part) for part in parts}
        if len(values) != 1:
            self.function.addItem('Keep individual values' if en else '각 부품의 현재 기능 유지', None)
        for key in FUNCTIONS:
            self.function.addItem(function_label(key, language='en' if en else 'ko'), key)
        if len(values) == 1:
            self.function.setCurrentIndex(self.function.findData(values.pop()))
        layout.addWidget(self.function)
        layout.addWidget(label(
            'Colors, electrical registrations and joint motion remain independent. Actuator designation does not certify a product, torque rating or powered operation.' if en else
            '색상·전장 등록·관절 운동은 별도로 유지됩니다. 구동기로 지정해도 제품·토크 정격·실제 구동이 검증된 것은 아닙니다.', True))
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
