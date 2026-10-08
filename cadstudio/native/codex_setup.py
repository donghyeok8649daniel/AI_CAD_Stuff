"""ChatGPT OAuth is handled by Codex, never by a CAD password/key field."""
from PySide6.QtCore import Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QComboBox, QFileDialog, QLineEdit, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QScrollArea, QWidget

from .widgets import button, label
from .codex_connection import INSTALL_URL, find_executable, settings, save_settings, login_url
from .codex_usage import usage_text, USAGE_NOTE


class CodexSetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Codex 연결 · ChatGPT 구독'); self.resize(530, 610)
        self.task = None; self.catalog = []; self.model_name = ''; self.executable_path = ''; self.auth_url = ''
        self.usage = None
        saved = settings(); self.preferred = saved['model']
        root = QVBoxLayout(self); scroll = QScrollArea(); scroll.setWidgetResizable(True)
        body = QWidget(); layout = QVBoxLayout(body); scroll.setWidget(body); root.addWidget(scroll, 1)
        layout.addWidget(label('Pro 계정으로 CAD 설계하기', True))
        layout.addWidget(label('ChatGPT 계정으로 로그인한 Codex를 사용합니다. 구독의 Codex 사용량·모델 접근 제한이 적용됩니다. 유료 API로 자동 전환하지 않습니다.', True))
        layout.addWidget(label('이미 Codex에 로그인했다면 ‘기존 로그인 사용 · 모델 찾기’를 누르세요. CAD가 비밀번호나 로그인 토큰을 복사하지 않습니다.', True))
        layout.addWidget(label('Codex 실행 파일'))
        self.path = QLineEdit(saved['executable'])
        try: self.path.setText(find_executable(saved['executable']))
        except ValueError: pass
        self.path.setPlaceholderText('codex.exe · 설치된 CLI 자동 찾기')
        row = QHBoxLayout(); row.addWidget(self.path)
        self.browse_button = button('찾기…', self.browse); row.addWidget(self.browse_button); layout.addLayout(row)
        self.install_button = button('Codex 설치 안내 ↗', lambda: QDesktopServices.openUrl(QUrl(INSTALL_URL))); layout.addWidget(self.install_button)
        self.diagnostics_button=button('연결 진단 보기…',self.show_diagnostics);layout.addWidget(self.diagnostics_button)
        self.login_button = button('ChatGPT로 로그인', lambda: self.start(True), True); layout.addWidget(self.login_button)
        self.check_button = button('기존 로그인 사용 · 모델 찾기', lambda: self.start(False), True); layout.insertWidget(layout.indexOf(self.login_button), self.check_button)
        self.browser_button = button('로그인 페이지 다시 열기 ↗', self.open_login); self.browser_button.hide(); layout.addWidget(self.browser_button)
        layout.addWidget(label('사용할 모델 · 계정에서 조회한 목록'))
        self.models = QComboBox(); self.models.setEnabled(False); layout.addWidget(self.models)
        self.usage_label=label('Codex 주간 · 잔여량 확인 전',True);self.usage_label.setToolTip(USAGE_NOTE);layout.addWidget(self.usage_label)
        layout.addWidget(label('잔여율·초기화 시각은 기존 로그인 사용 버튼으로 새로고침합니다.',True))
        layout.addWidget(label('로그인·모델 조회만으로 설계를 생성하지 않습니다. 초안 생성을 누르면 프롬프트와 현재 설계 정보가 Codex로 전송됩니다.', True))
        layout.addStretch()
        self.status = QPlainTextEdit(); self.status.setReadOnly(True); self.status.setMinimumHeight(80); self.status.setMaximumHeight(130)
        self.status.setPlainText('이미 로그인했다면 기존 로그인 사용을 누르세요. 로그인하지 않은 경우에만 ChatGPT로 로그인하세요.')
        root.addWidget(self.status)
        box = QDialogButtonBox(); self.use_button = box.addButton('Codex 모드 사용', QDialogButtonBox.ButtonRole.AcceptRole)
        self.cancel_button = box.addButton('취소', QDialogButtonBox.ButtonRole.ActionRole); self.cancel_button.clicked.connect(self.cancel)
        box.addButton('닫기', QDialogButtonBox.ButtonRole.RejectRole); box.accepted.connect(self.accept); box.rejected.connect(self.reject); root.addWidget(box)
        self.use_button.setEnabled(False); self.cancel_button.hide()
        self.path.textEdited.connect(self.invalidate)
        for item in (self.login_button, self.check_button, self.browse_button, self.install_button, self.browser_button): item.setAutoDefault(False)

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Codex 실행 파일 선택', '', 'Codex (codex.exe);;모든 파일 (*)')
        if path: self.path.setText(path); self.invalidate()

    def show_diagnostics(self):
        import json
        from .codex_connection import data_root
        from .. import __version__
        dialog=QDialog(self);dialog.setWindowTitle('Codex 연결 진단');dialog.resize(620,400)
        layout=QVBoxLayout(dialog);view=QPlainTextEdit(dialog);view.setReadOnly(True)
        try:
            path=data_root()/'codex-diagnostics.json'
            rows=json.loads(path.read_text(encoding='utf-8')) if path.is_file() and path.stat().st_size<65536 else []
            rows=[{k:v for k,v in row.items() if k in ('category','method','rpc_code','http_status','at','app_version')} for row in rows[-32:] if isinstance(row,dict)] if isinstance(rows,list) else []
        except (OSError,ValueError,TypeError):rows=[]
        view.setPlainText('Prompt CAD Studio '+__version__+'\n\n'+(json.dumps(rows,ensure_ascii=False,indent=2) if rows else '저장된 연결 오류 없음')+'\n\n로그인 정보·API 키·프롬프트·작업물은 이 진단에 포함되지 않습니다.')
        layout.addWidget(view);layout.addWidget(button('닫기',dialog.accept));dialog.exec();dialog.deleteLater()

    def invalidate(self):
        self.catalog = []; self.models.clear(); self.models.setEnabled(False); self.use_button.setEnabled(False)
        self.usage=None;self.usage_label.setText('Codex 주간 · 잔여량 확인 전')

    def controls(self, running):
        for widget in (self.path, self.browse_button, self.login_button, self.check_button): widget.setEnabled(not running)
        self.models.setEnabled(not running and bool(self.catalog)); self.use_button.setEnabled(not running and bool(self.catalog))
        self.cancel_button.setVisible(running)

    def start(self, login):
        if self.task: return
        from .codex_connection import connect
        from .ai_task import AITask
        self.invalidate(); self.auth_url = ''; self.browser_button.hide()
        executable = self.path.text().strip()
        self.task = AITask(lambda control, progress: connect(executable, login=login, control=control, progress=progress), self)
        self.task.progress.connect(self.progress, Qt.ConnectionType.QueuedConnection)
        self.task.completed.connect(self.completed, Qt.ConnectionType.QueuedConnection)
        self.task.failed.connect(self.failed, Qt.ConnectionType.QueuedConnection)
        self.controls(True); self.status.setPlainText('로그인 준비 중…' if login else 'Codex 연결과 모델 목록 확인 중…')
        self.task.start()

    @Slot(object)
    def progress(self, packet):
        task, info = packet
        if task is not self.task: return
        if isinstance(info, dict) and 'login_url' in info:
            try: self.auth_url = login_url(info['login_url'])
            except ValueError: self.cancel(); return
            self.browser_button.show(); self.open_login()

    def open_login(self):
        if not self.auth_url: return
        opened = QDesktopServices.openUrl(QUrl(self.auth_url))
        self.status.setPlainText('브라우저에서 ChatGPT 로그인을 완료하세요. 완료되면 모델 목록이 표시됩니다.' if opened else '브라우저를 열지 못했습니다. 기본 브라우저 설정 후 로그인 페이지 다시 열기를 누르세요.')

    @Slot(object)
    def completed(self, packet):
        task, result = packet
        if task is not self.task: return
        self.task = None; self.auth_url = ''; self.browser_button.hide(); self.catalog = result['models']
        self.executable_path = result['executable']; self.path.setText(self.executable_path)
        self.models.clear()
        for model in self.catalog: self.models.addItem(model['name'], model['model'])
        selected = self.models.findData(self.preferred)
        if selected < 0: selected = next((i for i, model in enumerate(self.catalog) if model['default']), 0)
        self.models.setCurrentIndex(selected); self.controls(False)
        self.usage=result.get('usage');self.usage_label.setText(usage_text(self.usage))
        self.status.setPlainText(f"ChatGPT 연결 완료 · 구독: {result['account']['plan']}\n모델을 선택하고 ‘Codex 모드 사용’을 누르세요. 설계 생성은 아직 요청하지 않았습니다.")

    @Slot(object)
    def failed(self, packet):
        task, message = packet
        if task is not self.task: return
        self.task = None; self.auth_url = ''; self.browser_button.hide(); self.controls(False); self.status.setPlainText(message)
        self.usage=None;self.usage_label.setText(usage_text(None))

    def cancel(self):
        if self.task: self.task.cancel(); self.task = None
        self.auth_url = ''; self.browser_button.hide(); self.controls(False); self.status.setPlainText('연결을 취소했습니다.')

    def accept(self):
        if self.task or not self.catalog: return
        self.model_name = self.models.currentData()
        save_settings(self.executable_path, self.model_name)
        super().accept()

    def done(self, result):
        self.cancel(); super().done(result)
