from pathlib import Path
import sys
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QEvent
from cadstudio.native import window as W
from cadstudio import updater as U


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(W, 'DATA_DIR', tmp_path/'data')
    value = W.MainWindow(restore=False)
    value.show()
    app.processEvents()
    yield value
    value.document.dirty = False
    value.sketching = False
    value.close()
    value.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_update_disabled_during_unfinished_sketch(window):
    assert window.actions['update'].isEnabled()
    window.sketching = True
    window.set_busy(False)
    assert not window.actions['update'].isEnabled()


@pytest.mark.parametrize('save_allowed', [False, True])
def test_update_save_gate_and_single_close_prompt(window, tmp_path, monkeypatch, save_allowed):
    exe = tmp_path/'PromptCADStudio.exe'
    helper = tmp_path/'PromptCADStudioUpdater.exe'
    helper.write_bytes(b'helper')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(exe))
    monkeypatch.setattr(U, 'latest_release', lambda: {'version': '9.0.0', 'size': 100})
    monkeypatch.setattr(window, 'run', lambda work, done, *args: done(work()))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    saved = []
    launched = []
    monkeypatch.setattr(window, 'check_save', lambda: saved.append(True) or save_allowed)
    monkeypatch.setattr(W.subprocess, 'Popen', lambda command, **kwargs: launched.append(command))
    window.check_updates()
    assert len(saved) == 1
    assert bool(launched) == save_allowed
    if save_allowed:
        assert '--wait-pid' in launched[0] and '--restart' in launched[0]
        assert not window.isVisible()
