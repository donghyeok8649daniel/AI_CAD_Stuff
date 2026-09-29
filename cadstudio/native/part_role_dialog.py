from PySide6.QtWidgets import QDialog,QVBoxLayout,QComboBox,QCheckBox,QDialogButtonBox
from ..part_roles import LABELS,COLORS
from .widgets import label


class PartRoleDialog(QDialog):
    def __init__(self,parent,parts):
        super().__init__(parent);self.setWindowTitle('부품 역할 / 기본색');self.resize(400,290)
        layout=QVBoxLayout(self);layout.addWidget(label(f'{len(parts)}개 부품',True))
        layout.addWidget(label('역할에 맞는 기본 색상을 선택하세요. 재질·물성과 관절 상태 표시는 별도로 유지됩니다.',True))
        self.role=QComboBox()
        for key,text in LABELS.items():self.role.addItem(text,key)
        roles={p.get('role','unspecified') for p in parts}
        if len(roles)==1:self.role.setCurrentIndex(self.role.findData(roles.pop()))
        layout.addWidget(self.role)
        self.use_color=QCheckBox('선택 부품에 역할 기본색도 적용');self.use_color.setChecked(True);layout.addWidget(self.use_color)
        layout.addWidget(label('선택을 끄면 직접 지정한 색상은 그대로 유지합니다.',True))
        self.swatch=label('',True);layout.addWidget(self.swatch)
        self.role.currentIndexChanged.connect(self.refresh);self.use_color.toggled.connect(self.refresh);self.refresh()
        box=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);box.accepted.connect(self.accept);box.rejected.connect(self.reject);layout.addWidget(box)
    def refresh(self):
        color=COLORS.get(self.role.currentData()) if self.use_color.isChecked() else None
        self.swatch.setText('● '+color if color else '현재 색상 유지')
        self.swatch.setStyleSheet('color:'+color+';padding:8px;' if color else '')
