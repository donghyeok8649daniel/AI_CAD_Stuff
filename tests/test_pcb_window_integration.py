"""Narrow real MainWindow PCB entry methods with a QWidget host; no VTK window."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import ast
from pathlib import Path
from copy import deepcopy
from PySide6.QtWidgets import QApplication,QWidget,QComboBox,QStackedWidget
from cadstudio.models import Design
from cadstudio.pcb import divider_example
from cadstudio.native.document import Document
from cadstudio.native.window import MainWindow


def test_existing_window_entrypoint_explicit_commit_and_stale_gate():
    app=QApplication.instance() or QApplication([])
    host=QWidget();host.document=Document();host.document.commit(Design(name='CAD host',parts=[]),'base');host.workspace=QComboBox();host.workspace.addItem('Model','model');host.workspace.addItem('PCB','pcb');host.stack=QStackedWidget(host);host.busy=False;host.sketching=False
    commits=[];host.apply_design=lambda *args,**kwargs:commits.append((args,kwargs));host.refresh_pcb_workspace=lambda:MainWindow.refresh_pcb_workspace(host);host.commit_pcb_workspace=lambda packet:MainWindow.commit_pcb_workspace(host,packet)
    host.workspace.currentIndexChanged.connect(lambda *_:host.refresh_pcb_workspace() if host.workspace.currentData()=='pcb' else None)
    try:
        MainWindow.show_pcb_workspace(host);assert host.workspace.currentData()=='pcb' and host.stack.currentWidget() is host.pcb_panel
        host.pcb_panel.replace_project(divider_example());host.pcb_panel.request_apply(False);assert len(commits)==1
        args,_=commits[0];assert args[0]['parts']==host.document.design['parts'] and args[2]['tool']=='pcb-workspace'
        packet=[];host.pcb_panel.applyRequested.connect(packet.append);host.pcb_panel.request_apply(False);before=len(commits)
        host.document.design['name']='stale';MainWindow.commit_pcb_workspace(host,packet[-1]);assert len(commits)==before
        assert 'Stale' in host.pcb_panel.status.text()
    finally:host.pcb_panel.alive=False;host.pcb_panel.stop_advice();host.close();host.deleteLater();app.processEvents()


def test_window_workspace_toolbar_refresh_close_wiring_parses():
    source=Path(MainWindow.__module__.replace('.','/'))
    import cadstudio.native.window as module
    text=Path(module.__file__).read_text(encoding='utf-8');tree=ast.parse(text)
    klass=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MainWindow');methods={n.name:ast.get_source_segment(text,n) for n in klass.body if isinstance(n,ast.FunctionDef)}
    assert "('pcb','PCB')" in methods['make_toolbar'] and "'pcb_workspace'" in methods['make_menus']
    assert 'refresh_pcb_workspace' in methods['workspace_changed'] and 'refresh_pcb_workspace' in methods['title']
    assert 'panel.stop_advice()' in methods['closeEvent'] and 'panel.dirty' in methods['check_save']
