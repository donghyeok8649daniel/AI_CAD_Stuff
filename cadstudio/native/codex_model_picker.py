"""Codex-owned model catalog selector; changing selection never starts inference."""
from PySide6.QtCore import Signal, QSignalBlocker
from PySide6.QtWidgets import QComboBox


class CodexModelPicker(QComboBox):
    modelSelected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('codexModelPicker')
        self.setMinimumContentsLength(12)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setToolTip('Codex가 반환한 모델 목록입니다. 모델 접근 권한은 실제 요청 시 확인됩니다. 선택만으로 요청하지 않습니다.')
        self.catalog = []
        self.currentIndexChanged.connect(self._selected)

    def set_catalog(self, catalog, preferred=''):
        """Keep a missing saved choice explicit; never silently switch models."""
        self.catalog = [dict(item) for item in catalog if isinstance(item, dict) and item.get('model')]
        with QSignalBlocker(self):
            self.clear()
            identifiers = {item['model'] for item in self.catalog}
            if preferred and preferred not in identifiers:
                suffix = '목록에 없음' if self.catalog else '연결 확인 전'
                self.addItem(preferred + ' · ' + suffix, None)
            elif not preferred:
                self.addItem('Codex 모델 선택…' if self.catalog else '연결 후 모델 목록을 불러옵니다', None)
            for item in self.catalog:
                name = item.get('name') or item['model']
                self.addItem(name if name == item['model'] else name + ' · ' + item['model'], item['model'])
            index = self.findData(preferred) if preferred in identifiers else 0
            self.setCurrentIndex(index)

    def _selected(self):
        model = self.currentData()
        if model and any(item['model'] == model for item in self.catalog):
            self.modelSelected.emit(model)
