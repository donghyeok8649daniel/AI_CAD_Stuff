from test_placement_native import app
from PySide6.QtCore import QThreadPool


def test_reference_ui_chat_and_rename_workflow(app,monkeypatch,tmp_path):
    from cadstudio.native import window
    from cadstudio.native.model_picker import LocalModelPicker
    from cadstudio.native.reference_smoke import run_checks
    monkeypatch.setattr(window,'DATA_DIR',tmp_path);monkeypatch.setattr(LocalModelPicker,'refresh',lambda self:None)
    monkeypatch.setenv('CADSTUDIO_DATA_DIR',str(tmp_path))
    w=window.MainWindow();w.show();checks=[]
    def check(condition,message):
        assert condition,message
        checks.append(message)
    try:run_checks(app,w,tmp_path/'report.json',check);assert len(checks)>=15
    finally:w.document.dirty=False;w.close();QThreadPool.globalInstance().waitForDone(10000);app.processEvents()
