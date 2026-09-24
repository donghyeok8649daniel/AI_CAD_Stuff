import time
from copy import deepcopy

import pytest
from PySide6.QtCore import Qt,QThreadPool,QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cadstudio.catalog import preset
from cadstudio.native.placement_dialog import PlacementDialog


@pytest.fixture(scope='module')
def app():
    global _APP
    _APP=QApplication.instance() or QApplication([]);_APP.setQuitOnLastWindowClosed(False)
    yield _APP
    assert QThreadPool.globalInstance().waitForDone(10000)
    _APP.processEvents()


def wait(app,condition):
    deadline=time.monotonic()+30
    while not condition() and time.monotonic()<deadline:app.processEvents();QTest.qWait(10)
    assert condition()


def dispose(app,dialog):
    dialog.reject();assert QThreadPool.globalInstance().waitForDone(10000)
    dialog.deleteLater();app.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()


def test_move_preview_grounding_reset_and_cancel(app):
    raw=preset('robot_arm').model_dump();before=deepcopy(raw)
    dialog=PlacementDialog(None,raw,[raw['parts'][-1]['id']]);dialog.resize(820,600);dialog.show()
    try:
        wait(app,lambda:dialog.checked is not None)
        assert not dialog.apply_button.isEnabled() and len(dialog.moved_ids)==len(raw['parts'])
        dialog.fields['x'].setValue(25);wait(app,lambda:not dialog.running and not dialog.timer.isActive())
        assert dialog.checked is None and '고정' in dialog.status.text()
        dialog.grounded.setChecked(True);dialog.fields['rz'].setValue(90);dialog.center.setCurrentIndex(dialog.center.findData('world'))
        wait(app,lambda:dialog.checked is not None)
        assert dialog.apply_button.isEnabled() and dialog.apply_button.visibleRegion().contains(dialog.apply_button.rect())
        assert dialog.checked.parts[0].fixed and len(dialog.viewport.actors)==len(raw['parts'])
        dialog.reset_values();wait(app,lambda:dialog.checked is not None)
        assert not dialog.apply_button.isEnabled()
        dialog.connected.setChecked(False);wait(app,lambda:not dialog.timer.isActive())
        assert dialog.checked is None and '선택 밖' in dialog.status.text()
    finally:dispose(app,dialog)
    assert raw==before


def test_m_shortcut_commits_once_and_undo_redo_restore_placement(app,monkeypatch,tmp_path):
    from cadstudio.native import window
    from cadstudio.native.model_picker import LocalModelPicker
    monkeypatch.setattr(LocalModelPicker,'refresh',lambda self:None);monkeypatch.setattr(window,'DATA_DIR',tmp_path)
    w=window.MainWindow();errors=[];w.show_error=errors.append;w.show();w.activateWindow();app.processEvents()
    raw=preset('robot_arm').model_dump()
    try:
        w.apply_design(raw,'start');wait(app,lambda:not w.busy);before=deepcopy(w.document.design)
        w.select_parts([raw['parts'][-1]['id']])
        def execute(dialog):
            dialog.grounded.setChecked(True);dialog.fields['x'].setValue(40);dialog.fields['ry'].setValue(25)
            wait(app,lambda:dialog.checked is not None);dialog.accept();return 1
        monkeypatch.setattr(PlacementDialog,'exec',execute)
        w.viewport.widget.setFocus();app.processEvents();QTest.keyClick(w.viewport.widget,Qt.Key.Key_M);wait(app,lambda:not w.busy)
        assert not errors and w.document.design!=before
        after=deepcopy(w.document.design)
        assert w.document.journal.path()[-1]['label']=='부품 이동 / 회전'
        assert len(w.selected_parts)==len(raw['parts'])
        w.undo();wait(app,lambda:not w.busy);assert w.document.design==before
        w.redo();wait(app,lambda:not w.busy);assert w.document.design==after
        w.prompt.setFocus();w.prompt.clear();QTest.keyClicks(w.prompt,'m');assert w.prompt.toPlainText()=='m' and w.document.design==after
    finally:
        w.document.dirty=False;w.close();QThreadPool.globalInstance().waitForDone(10000);app.processEvents()


def test_native_clipboard_fallback_survives_system_loss_and_prefers_other_cad_copy(app,monkeypatch):
    from PySide6.QtCore import QMimeData
    from cadstudio.native import clipboard
    class MissingClipboard:
        def __init__(self):self.mime=QMimeData()
        def setMimeData(self,mime):pass  # Windows clipboard is locked/unavailable.
        def mimeData(self):return self.mime
    system=MissingClipboard();monkeypatch.setattr(QApplication,'clipboard',lambda:system)
    kind='application/x-promptcad-parts-v1';sketch='application/x-promptcad-sketch-v1'
    clipboard.write(kind,b'part snapshot','CAD');clipboard.write(sketch,b'sketch snapshot','Sketch')
    assert clipboard.read(kind)==b'part snapshot' and clipboard.read(sketch)==b'sketch snapshot'
    system.mime.setData(kind,b'copy from another CAD instance')
    assert clipboard.read(kind)==b'copy from another CAD instance'
