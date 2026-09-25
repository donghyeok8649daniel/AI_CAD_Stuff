"""Native, user-initiated API setup; no account credentials or automatic requests."""
import os
from PySide6.QtCore import Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLineEdit, QVBoxLayout, QScrollArea, QWidget, QPlainTextEdit

from .widgets import button, label


API_KEYS_URL = 'https://platform.openai.com/api-keys'
BILLING_URL = 'https://platform.openai.com/account/billing/overview'


class OpenAISetupDialog(QDialog):
    def __init__(self, parent=None, api_key='', model='gpt-4.1'):
        super().__init__(parent)
        self.setWindowTitle('OpenAI 연결 안내')
        self.resize(500, 560)
        self.task = None
        self.has_check_result = False
        root = QVBoxLayout(self)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        body = QWidget(); scroll.setWidget(body); root.addWidget(scroll, 1)
        self.scroll = scroll
        layout = QVBoxLayout(body)
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
        layout.addWidget(label('사용할 모델'))
        self.model = QLineEdit(model)
        self.model.setPlaceholderText('예: gpt-6-astra')
        layout.addWidget(self.model)
        self.check_button = button('키 · 모델 확인 (설계 생성 안 함)', self.check_connection)
        self.check_button.setAutoDefault(False)
        layout.addWidget(self.check_button)
        layout.addWidget(label('키는 프로젝트나 설정 파일에 저장하지 않습니다. 모델 조회 성공만으로 결제 잔액이나 설계 생성 권한을 보장하지는 않습니다.', True))
        self.status = QPlainTextEdit()
        self.status.setReadOnly(True)
        self.status.setMinimumHeight(72); self.status.setMaximumHeight(148)
        self.status.hide()
        root.addWidget(self.status)
        self.key.textEdited.connect(self.invalidate_result)
        self.model.textEdited.connect(self.invalidate_result)
        layout.addStretch()
        buttons = QDialogButtonBox()
        self.use_button = buttons.addButton('입력한 키 사용', QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton('닫기', QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.key.textChanged.connect(lambda text: self.use_button.setEnabled(self.task is None and bool(text.strip() or os.getenv('OPENAI_API_KEY', '').strip())))
        self.use_button.setEnabled(bool(api_key.strip() or os.getenv('OPENAI_API_KEY', '').strip()))
        # Enter in the key field applies the key, never opens a website.
        for control in (self.keys_button, self.billing_button):
            control.setAutoDefault(False)
        self.use_button.setDefault(True)
        root.addWidget(buttons)

    def check_connection(self):
        if self.task:
            self.cancel_check()
            self.status.setPlainText('키·모델 확인을 취소했습니다.'); self.status.show()
            return
        from .cloud_connection import check_access
        from .ai_task import AITask
        key = self.key.text().strip() or os.getenv('OPENAI_API_KEY', '')
        model = self.model.text().strip()
        self.task = AITask(lambda control, progress: check_access(key, model, control=control), self)
        self.task.completed.connect(self.checked, Qt.ConnectionType.QueuedConnection)
        self.task.failed.connect(self.check_failed, Qt.ConnectionType.QueuedConnection)
        self.key.setEnabled(False); self.model.setEnabled(False); self.use_button.setEnabled(False)
        self.check_button.setText('확인 취소')
        self.status.setPlainText('API 인증과 모델 조회 확인 중… 최대 15초\n프롬프트·설계를 전송하거나 설계를 생성하지 않습니다.'); self.status.show()
        self.task.start()

    def invalidate_result(self):
        if self.has_check_result:
            self.has_check_result = False
            self.status.setPlainText('키 또는 모델을 변경했습니다. 키·모델 확인을 다시 실행하세요.')

    def finish_check(self):
        self.task = None
        self.key.setEnabled(True); self.model.setEnabled(True)
        self.use_button.setEnabled(bool(self.key.text().strip() or os.getenv('OPENAI_API_KEY', '').strip()))
        self.check_button.setText('키 · 모델 확인 (설계 생성 안 함)')

    def cancel_check(self):
        if self.task:
            self.task.cancel()
            self.finish_check()

    @Slot(object)
    def checked(self, packet):
        task, message = packet
        if task is not self.task: return
        self.finish_check(); self.has_check_result = True; self.status.setPlainText(message); self.status.show()

    @Slot(object)
    def check_failed(self, packet):
        self.checked(packet)

    def done(self, result):
        self.cancel_check()
        super().done(result)

    def open_page(self, url):
        # Only fixed official pages; credentials and designs never enter URLs.
        if url not in (API_KEYS_URL, BILLING_URL):
            return
        try:
            opened = QDesktopServices.openUrl(QUrl(url))
        except Exception:
            opened = False
        self.status.setPlainText('브라우저에서 로그인·설정을 마친 뒤 이 창으로 돌아오세요.' if opened else f'브라우저를 열지 못했습니다. 아래 주소를 복사해 직접 여세요.\n{url}')
        self.status.show()
