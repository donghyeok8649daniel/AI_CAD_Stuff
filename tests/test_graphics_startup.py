import json
import subprocess
import sys
from pathlib import Path

from cadstudio.native import graphics


def test_hardware_success_never_loads_software(monkeypatch,tmp_path):
    attempts=[];loaded=[]
    monkeypatch.setattr(graphics,'probe',lambda mode,data: attempts.append(mode) or {'mode':mode,'ok':True})
    monkeypatch.setattr(graphics,'load_renderer',lambda mode,data:loaded.append(mode))
    state=graphics.prepare(tmp_path)
    assert attempts==loaded==['hardware'] and state['selected']=='hardware'


def test_native_crash_falls_back_without_reusing_the_failed_context(monkeypatch,tmp_path):
    loaded=[]
    monkeypatch.setattr(graphics,'probe',lambda mode,data: {'mode':mode,'ok':mode=='software','exit_code':0 if mode=='software' else 3221225477})
    monkeypatch.setattr(graphics,'load_renderer',lambda mode,data:loaded.append(mode))
    state=graphics.prepare(tmp_path)
    assert loaded==['software'] and state['selected']=='software'
    assert json.loads((tmp_path/'graphics-status.json').read_text())==state
    assert state['attempts'][0]['exit_code']==3221225477


def test_all_failed_backends_leave_the_ui_process_without_a_graphics_import(monkeypatch,tmp_path):
    monkeypatch.setattr(graphics,'probe',lambda mode,data: {'mode':mode,'ok':False})
    def forbidden(*args):raise AssertionError('Do not load a failed renderer into CAD')
    monkeypatch.setattr(graphics,'load_renderer',forbidden)
    assert graphics.prepare(tmp_path)['selected'] is None


def test_explicit_software_does_not_probe_the_hardware_driver(monkeypatch,tmp_path):
    attempts=[]
    monkeypatch.setattr(graphics,'probe',lambda mode,data:attempts.append(mode) or {'mode':mode,'ok':True})
    monkeypatch.setattr(graphics,'load_renderer',lambda *args:None)
    assert graphics.prepare(tmp_path,'software')['selected']=='software' and attempts==['software']


def test_probe_timeout_reaps_only_its_own_child_and_falls_back(monkeypatch,tmp_path):
    class Process:
        killed=False
        def wait(self,timeout=None):
            if timeout is not None:raise subprocess.TimeoutExpired('probe',timeout)
            return -1
        def kill(self):self.killed=True
    process=Process()
    monkeypatch.setattr(graphics.subprocess,'Popen',lambda *args,**kwargs:process)
    result=graphics.probe('hardware',tmp_path)
    assert process.killed and not result['ok'] and result['error']=='Graphics probe timed out'
    assert not list(tmp_path.glob('graphics-probe-*'))


def test_report_does_not_mask_a_native_failure_during_driver_cleanup(monkeypatch,tmp_path):
    class Process:
        def wait(self,timeout=None):return 3221225477
    def start(args,**kwargs):
        graphics.write_json(Path(args[-1]),{'ok':True})
        return Process()
    monkeypatch.setattr(graphics.subprocess,'Popen',start)
    result=graphics.probe('software',tmp_path)
    assert not result['ok'] and result['exit_code']==3221225477


def test_malformed_probe_report_is_a_failed_probe(monkeypatch,tmp_path):
    class Process:
        def wait(self,timeout=None):return 0
    def start(args,**kwargs):
        Path(args[-1]).write_text('{unfinished',encoding='utf-8')
        return Process()
    monkeypatch.setattr(graphics.subprocess,'Popen',start)
    assert not graphics.probe('hardware',tmp_path)['ok']


def test_probe_windows_path_arguments_stay_separate(monkeypatch,tmp_path):
    report=tmp_path/'한글 공백'/'probe.json'
    command=graphics.child_command('software',report)
    assert command[-3:]==['--graphics-probe','software',str(report)]


def test_recovery_window_is_actionable_and_imports_no_vtk(monkeypatch,tmp_path):
    vtk_before={name for name in sys.modules if name.startswith('vtkmodules')}
    from PySide6.QtWidgets import QApplication,QDialog,QPushButton
    from PySide6.QtCore import QTimer
    app=QApplication.instance() or QApplication([])
    def close():
        dialog=next(w for w in app.topLevelWidgets() if isinstance(w,QDialog) and w.isVisible())
        buttons=[b.text() for b in dialog.findChildren(QPushButton)]
        assert '그래픽 검사 다시 시도' in buttons and '진단 폴더 열기' in buttons and '진단 내용 복사' in buttons
        dialog.reject()
    QTimer.singleShot(50,close)
    assert not graphics.recovery_dialog(app,tmp_path,{'selected':None})
    assert {name for name in sys.modules if name.startswith('vtkmodules')}==vtk_before
