from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QPushButton,QDialogButtonBox,QColorDialog,QLabel,QCheckBox
from ..part_roles import COLORS
from ..role_colors import CONFIGURABLE_ROLES,ROLE_TITLES,normalize_colors,request_colors


class RoleColorSettings(QDialog):
    def __init__(self,parent,colors,error='',view_enabled=False):
        super().__init__(parent);self.setWindowTitle('기본 설정 · 부품 역할 색상');self.resize(500,330)
        self.colors=request_colors(colors);self.buttons={};self.setObjectName('roleColorSettings')
        layout=QVBoxLayout(self)
        text=QLabel('새 부품의 기본색과 전장 / 구조 / 동력 보기 색상을 설정합니다.\n기존 부품별 색상과 원본 파일은 변경하지 않습니다.');text.setWordWrap(True);layout.addWidget(text)
        if error:
            warning=QLabel('저장된 설정을 읽지 못해 기본값으로 열었습니다. 저장하면 새 설정으로 교체합니다.');warning.setWordWrap(True);layout.addWidget(warning)
        form=QFormLayout();layout.addLayout(form)
        for role in CONFIGURABLE_ROLES:
            button=QPushButton();button.setObjectName('roleColor_'+role);button.clicked.connect(lambda checked=False,r=role:self.choose(r))
            self.buttons[role]=button;form.addRow(ROLE_TITLES[role],button)
        policy=QLabel('직접 색을 바꾸려면 선택 부품 색상을 사용하세요. 기존 부품에 새 기본색을 쓰려면 부품 역할 / 기본색에서 적용을 직접 선택하세요. 미지정 역할은 그대로 둡니다.');policy.setWordWrap(True);layout.addWidget(policy)
        self.role_view=QCheckBox('현재 설계를 역할 색상으로 보기');self.role_view.setObjectName('roleColorsCurrentView');self.role_view.setChecked(view_enabled);layout.addWidget(self.role_view)
        legend=QLabel('역할 보기: 명시된 역할과 회로 연결로 확인합니다. 미지정 / 충돌은 중립색으로 표시하며, 끄면 저장된 부품 색상으로 돌아갑니다.');legend.setWordWrap(True);layout.addWidget(legend)
        reset=QPushButton('기본값 복원');reset.setObjectName('restoreRoleColorDefaults');reset.clicked.connect(self.restore_defaults);layout.addWidget(reset)
        box=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept);box.rejected.connect(self.reject);layout.addWidget(box);self.refresh()

    def choose(self,role):
        color=QColorDialog.getColor(QColor(self.colors[role]),self,ROLE_TITLES[role]+' 기본색')
        if color.isValid():self.colors[role]=color.name().upper();self.refresh()

    def restore_defaults(self):
        self.colors={role:COLORS[role] for role in CONFIGURABLE_ROLES};self.refresh()

    def refresh(self):
        for role,button in self.buttons.items():
            color=self.colors[role];button.setText('● '+color)
            button.setStyleSheet('text-align:left;padding:8px;border-left:16px solid '+color+';')

    def selected_colors(self):
        return request_colors(normalize_colors(self.colors))
