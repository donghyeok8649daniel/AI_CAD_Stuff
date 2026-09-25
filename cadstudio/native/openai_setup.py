"""Native, user-initiated API setup; no account credentials or automatic requests."""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLineEdit, QVBoxLayout

from .widgets import button, label


API_KEYS_URL = 'https://platform.openai.com/api-keys'
BILLING_URL = 'https://platform.openai.com/account/billing/overview'


class OpenAISetupDialog(QDialog):
    def __init__(self, parent=None, api_key=''):
        super().__init__(parent)
        self.setWindowTitle('OpenAI 연결 안내')
        self.resize(470, 430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(label('OpenAI API 시작하기', True))
        layout.addWidget(label('브라우저에서 로그인한 뒤 API 키를 발급해 아래에 붙여넣으세요. 로그인만으로 CAD 인증이 완료되지는 않습니다.', True))
        self.keys_button = button('1. 로그인 · API 키 발급 ↗', lambda: self.open_page(API_KEYS_URL), True)
        self.keys_button.setToolTip(API_KEYS_URL)
        layout.addWidget(self.keys_button)
        self.billing_button = button('2. API 결제 설정 ↗', lambda: self.open_page(BILLING_URL))
        self.billing_button.setToolTip(BILLING_URL)
        layout.addWidget(self.billing_button)
        layout.addWidget(label('API 사용량에 따라 요금이 발생합니다. 이 창을 열거나 키를 입력하는 것만으로 설계를 요청하지 않습니다.', True))
        layout.addWidget(label('3. 발급한 API 키 붙여넣기'))
        self.key = QLineEdit(api_key)
        self.key.setObjectName('openaiSetupKey')
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText('API 키 · 이번 실행 동안만 사용')
        self.key.setClearButtonEnabled(True)
        layout.addWidget(self.key)
        layout.addWidget(label('키는 프로젝트나 설정 파일에 저장하지 않습니다. 인증 여부는 초안 생성 요청 시 확인합니다.', True))
        self.status = label('', True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status.hide()
        layout.addWidget(self.status)
        layout.addStretch()
        buttons = QDialogButtonBox()
        self.use_button = buttons.addButton('입력한 키 사용', QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton('닫기', QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.key.textChanged.connect(lambda text: self.use_button.setEnabled(bool(text.strip())))
        self.use_button.setEnabled(bool(api_key.strip()))
        # Enter in the key field applies the key, never opens a website.
        for control in (self.keys_button, self.billing_button):
            control.setAutoDefault(False)
        self.use_button.setDefault(True)
        layout.addWidget(buttons)

    def open_page(self, url):
        # Only fixed official pages; credentials and designs never enter URLs.
        if url not in (API_KEYS_URL, BILLING_URL):
            return
        try:
            opened = QDesktopServices.openUrl(QUrl(url))
        except Exception:
            opened = False
        self.status.setText('브라우저에서 로그인·설정을 마친 뒤 이 창으로 돌아오세요.' if opened else f'브라우저를 열지 못했습니다. 아래 주소를 복사해 직접 여세요.\n{url}')
        self.status.show()
