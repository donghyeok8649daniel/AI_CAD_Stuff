import time
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_placement_native import app
from test_openai_setup_native import wait


def test_subscription_setup_without_keys_and_result_visible(app,monkeypatch,tmp_path):
    from cadstudio.native import codex_connection as connection
    from cadstudio.native.codex_setup import CodexSetupDialog
    monkeypatch.setenv('CADSTUDIO_DATA_DIR',str(tmp_path));calls=[]
    def connect(path,**kw):
        calls.append(kw['login'])
        return {'account':{'plan':'pro'},'executable':'example.exe','models':[{'model':'gpt-6-astra','name':'Astra','default':True,'efforts':['medium']}]}
    monkeypatch.setattr(connection,'connect',connect)
    d=CodexSetupDialog();d.resize(440,500);d.show();app.processEvents()
    try:
        d.check_button.click();wait(app,lambda:d.task is None)
        assert calls==[False] and 'pro' in d.status.toPlainText() and d.use_button.isEnabled()
        assert d.status.visibleRegion().contains(d.status.rect()) and d.use_button.visibleRegion().contains(d.use_button.rect())
        d.use_button.click();assert connection.settings()['model']=='gpt-6-astra'
        assert not hasattr(d,'key')
    finally:d.reject();d.deleteLater();app.processEvents()


def test_cancel_login_ignores_late_result(app,monkeypatch,tmp_path):
    import threading
    from cadstudio.native import codex_connection as connection
    from cadstudio.native.codex_setup import CodexSetupDialog
    monkeypatch.setenv('CADSTUDIO_DATA_DIR',str(tmp_path));entered=threading.Event();release=threading.Event()
    def connect(path,**kw):entered.set();release.wait(5);return {'account':{'plan':'pro'},'models':[],'executable':'fake.exe'}
    monkeypatch.setattr(connection,'connect',connect)
    d=CodexSetupDialog();d.show();d.login_button.click();wait(app,entered.is_set);task=d.task
    start=time.monotonic();d.reject();assert time.monotonic()-start<.5
    release.set();task.thread.join(2);app.processEvents()
    assert d.task is None and not d.use_button.isEnabled()
    d.deleteLater();app.processEvents()


def test_main_window_has_separate_codex_route_and_cancel(app,monkeypatch,tmp_path):
    from cadstudio.native import window,codex_ai
    from cadstudio.native.model_picker import LocalModelPicker
    from cadstudio.native.local_ai import DraftCancelled
    import threading
    monkeypatch.setenv('CADSTUDIO_DATA_DIR',str(tmp_path));monkeypatch.setattr(window,'DATA_DIR',tmp_path)
    monkeypatch.setattr(LocalModelPicker,'refresh',lambda self:None)
    entered=threading.Event();calls=[]
    def generate(request,model,**kw):
        calls.append((model,kw));entered.set()
        while not kw['control'].cancelled.wait(.01):pass
        raise DraftCancelled('cancel')
    monkeypatch.setattr(codex_ai,'generate',generate)
    w=window.MainWindow();w.show();w.provider.setCurrentIndex(w.provider.findData('codex'));app.processEvents()
    try:
        assert w.codex_setup_button.isVisible() and not w.key.isVisible() and not w.openai_setup_button.isVisible()
        w.codex_config=dict(executable='example.exe',model='gpt-6-astra');w.prompt.setPlainText('바퀴 만들어줘')
        w.generate_button.click();wait(app,entered.is_set)
        assert calls[0][0]=='gpt-6-astra' and 'api_key' not in calls[0][1]
        assert not w.codex_setup_button.isEnabled();w.cancel_ai_button.click();app.processEvents()
        assert w.ai_task is None and w.document.design is None and w.codex_setup_button.isEnabled()
    finally:w.document.dirty=False;w.close();app.processEvents()
