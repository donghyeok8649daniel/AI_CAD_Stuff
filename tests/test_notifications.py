import json
from types import SimpleNamespace
from cadstudio.native import notifications


def test_completion_notice_respects_preference_and_never_includes_design_contents(monkeypatch,tmp_path):
    calls=[]
    class Tray:
        MessageIcon=SimpleNamespace(Information=1)
        @staticmethod
        def isSystemTrayAvailable():return True
        def __init__(self,*args):self.messageClicked=SimpleNamespace(connect=lambda f:None)
        def setToolTip(self,*args):pass
        def show(self):pass
        def showMessage(self,*args):calls.append(args)
    monkeypatch.setattr(notifications,'QSystemTrayIcon',Tray)
    monkeypatch.setattr(notifications,'QApplication',SimpleNamespace(alert=lambda *a:None,instance=lambda:None))
    window=SimpleNamespace(data_dir=tmp_path,windowIcon=lambda:None)
    notifier=notifications.CompletionNotifier(window);notifier.notify();notifier.notify(True)
    assert len(calls)==2 and '완료' in calls[0][0] and '검토 필요' in calls[1][0]
    notifier.set_enabled(False);notifier.notify()
    assert len(calls)==2 and json.loads(notifier.path.read_text())=={'ai_complete':False}
    assert not notifications.CompletionNotifier(window).enabled
