"""Only models returned by Codex are selectable; a selection starts no inference."""
import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from cadstudio.native.codex_model_picker import CodexModelPicker
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QComboBox,QDialog,QLabel,QPushButton,QWidget
from types import SimpleNamespace


@pytest.fixture(scope='module')
def app():
    instance=QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    return instance


def catalog():
    return [dict(model='server-A',name='Model A',efforts=['low','high']),
            dict(model='server-B',name='Model B',efforts=['medium','max'])]


def test_catalog_refresh_and_missing_saved_choice_do_not_silently_select_another_model(app):
    picker=CodexModelPicker();changed=QSignalSpy(picker.modelSelected)
    picker.set_catalog(catalog(),'saved-but-unavailable')
    assert changed.count()==0 and picker.currentData() is None
    assert picker.currentText().startswith('saved-but-unavailable')
    picker.set_catalog(catalog(),'server-B')
    assert changed.count()==0 and picker.currentData()=='server-B'
    picker.set_catalog([],'server-B')
    assert changed.count()==0 and picker.currentData() is None
    assert picker.currentText().startswith('server-B')


def test_only_current_catalog_models_emit_a_model_selection(app):
    picker=CodexModelPicker();changed=QSignalSpy(picker.modelSelected)
    picker.set_catalog([None,{},*catalog()])
    assert picker.currentData() is None and changed.count()==0
    picker.setCurrentIndex(picker.findData('server-A'))
    assert changed.count()==1 and changed.at(0)==['server-A']
    picker.addItem('Not in the returned catalog','invented-model')
    picker.setCurrentIndex(picker.count()-1)
    assert changed.count()==1
    picker.setCurrentIndex(picker.findData('server-B'))
    assert changed.count()==2 and changed.at(1)==['server-B']


def test_close_closes_floating_wiring_before_vtk_finalization_only_after_save_approval(app):
    from cadstudio.native.window import MainWindow
    owner=QWidget();panel=QDialog(owner);panel.setWindowFlags(Qt.WindowType.Window)
    order=[]
    host=SimpleNamespace(cancel_ai=lambda:None,codex_probe_task=None,busy=False,sketching=False,
        check_save=lambda:False,wiring_window=panel,autosave_document=lambda:order.append('save'),
        editor=SimpleNamespace(stop=lambda:order.append('stop')),
        viewport=SimpleNamespace(shutdown=lambda:order.append(('shutdown',panel.isVisible()))))
    panel.show();app.processEvents();rejected=QCloseEvent();MainWindow.closeEvent(host,rejected)
    assert not rejected.isAccepted() and panel.isVisible() and not order
    host.check_save=lambda:True;accepted=QCloseEvent();MainWindow.closeEvent(host,accepted)
    assert accepted.isAccepted() and not panel.isVisible() and host.wiring_window is None
    assert order==['save','stop',('shutdown',False)]
    owner.deleteLater();app.processEvents()


def test_connection_probe_does_not_change_another_provider_effort(app,monkeypatch):
    import threading,time
    from cadstudio.native.window import MainWindow
    from cadstudio.native import codex_connection
    entered=threading.Event();release=threading.Event();updates=[]
    def connect(*args,**kwargs):
        entered.set();release.wait(3)
        return dict(models=catalog(),account=dict(plan='test'))
    monkeypatch.setattr(codex_connection,'connect',connect)
    host=QWidget();host.ai_task=None;host.codex_probe_task=None
    host.codex_config=dict(executable='mock.exe',model='server-A');host.codex_connection_verified=False
    host.codex_status=QLabel();host.codex_usage=QLabel();host.codex_check_button=QPushButton()
    host.codex_models=CodexModelPicker();host.provider=QComboBox()
    host.provider.addItem('Codex','codex');host.provider.addItem('API','openai')
    host.update_codex_effort=lambda:updates.append('changed')
    MainWindow.check_codex_status(host);task=host.codex_probe_task
    try:
        assert entered.wait(2);host.provider.setCurrentIndex(1);release.set()
        deadline=time.monotonic()+3
        while host.codex_probe_task and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
        assert host.codex_probe_task is None and not updates
        assert host.codex_connection_verified and host.codex_catalog==catalog()
    finally:
        release.set();task.thread.join(3);host.deleteLater();app.processEvents()


def test_cached_catalog_selection_does_not_restore_failed_connection_checkmark(app,monkeypatch):
    from cadstudio.native.window import MainWindow
    from cadstudio.native import codex_connection
    saved=[];monkeypatch.setattr(codex_connection,'save_settings',lambda *args:saved.append(args))
    status=QLabel('Codex · 연결 확인 실패');provider=QComboBox();provider.addItem('API','openai')
    host=SimpleNamespace(ai_task=None,codex_probe_task=None,codex_catalog=catalog(),
        codex_config=dict(executable='mock.exe',model='server-A'),codex_connection_verified=False,
        codex_status=status,codex_model_label=QLabel(),provider=provider,
        update_codex_effort=lambda:pytest.fail('Another provider effort must be preserved'),
        accept_draft=QPushButton(),message=lambda text:None)
    MainWindow.select_codex_model(host,'server-B')
    assert saved==[('mock.exe','server-B')] and host.codex_config['model']=='server-B'
    assert status.text()=='Codex · 연결 확인 실패' and not host.codex_connection_verified
