"""Optional native Windows tray notification and taskbar attention, no remote service."""
import json
from PySide6.QtWidgets import QApplication,QSystemTrayIcon


class CompletionNotifier:
    def __init__(self,window):
        self.window=window;self.tray=None;self.path=window.data_dir/'notification-settings.json';self.enabled=True
        try:self.enabled=json.loads(self.path.read_text(encoding='utf-8')).get('ai_complete',True) is not False
        except (OSError,ValueError,AttributeError):pass

    def set_enabled(self,enabled):
        self.enabled=bool(enabled)
        try:
            temporary=self.path.with_suffix('.tmp');temporary.write_text(json.dumps({'ai_complete':self.enabled}),encoding='utf-8');temporary.replace(self.path)
        except OSError:pass

    def focus(self):
        if self.window.isMinimized():self.window.showNormal()
        else:self.window.show()
        self.window.raise_();self.window.activateWindow();self.window.ai_dock.show();self.window.ai_dock.raise_()

    def notify(self,needs_review=False):
        if not self.enabled:return
        title='Prompt CAD Studio · AI 검토 필요' if needs_review else 'Prompt CAD Studio · AI 설계 완료'
        text='초안이 준비되었습니다. 남은 검증 항목을 미리보기에서 확인하세요.' if needs_review else '검증된 설계 초안이 준비되었습니다. 미리보기에서 확인하고 적용하세요.'
        service=getattr(QApplication.instance(),'cad_language',None)
        if service and service.language=='en':
            title='Prompt CAD Studio · AI draft needs review' if needs_review else 'Prompt CAD Studio · AI design complete'
            text='A draft is ready. Review remaining validation issues in the preview.' if needs_review else 'A validated draft is ready. Review the preview before applying.'
        QApplication.alert(self.window,0)
        if QSystemTrayIcon.isSystemTrayAvailable():
            if self.tray is None:
                self.tray=QSystemTrayIcon(self.window.windowIcon(),self.window);self.tray.setToolTip('Prompt CAD Studio');self.tray.messageClicked.connect(self.focus);self.tray.show()
            self.tray.showMessage(title,text,QSystemTrayIcon.MessageIcon.Information,10000)
