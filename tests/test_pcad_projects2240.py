"""Dedicated project names keep the same native document and history format."""
from copy import deepcopy
from pathlib import Path
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication,QEvent,QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QFileDialog

from cadstudio.models import Design
from cadstudio.native.document import Document,read_project,resolve_project_path
from cadstudio.native.window import MainWindow


def document():
    value=Document()
    initial=Design(name='기록 보존',parts=[dict(id='plate',name='판',role='structure',
        geometry=dict(kind='plate',length=60,width=35,thickness=4,hole_count=0))])
    value.commit(initial,'판 생성',dict(tool='create'))
    edited=initial.model_dump();edited['parts'][0]['geometry']['length']=70
    value.commit(edited,'길이 수정',dict(tool='dimension'))
    value.prompt='원본 프롬프트 유지'
    return value


def harness(value):
    return SimpleNamespace(busy=False,sketching=False,document=value,title=lambda:None,
        message=lambda text:None,show_error=lambda text:pytest.fail(text))


@pytest.mark.parametrize('chosen,expected',[
    ('part','part.pcad'),('part.pcad','part.pcad'),('part.PCAD','part.PCAD'),
    ('part.cad.json','part.cad.json'),('part.CAD.JSON','part.CAD.JSON'),
])
def test_native_save_dialog_defaults_and_explicit_suffixes(tmp_path,monkeypatch,chosen,expected):
    calls=[];value=document();before=value.project().model_dump(mode='json')
    def select(*args):
        calls.append(args)
        return str(tmp_path/chosen),''
    monkeypatch.setattr(QFileDialog,'getSaveFileName',select)
    assert MainWindow.save(harness(value))
    assert value.path==tmp_path/expected
    assert calls[0][2].endswith('기록 보존.pcad')
    assert calls[0][3].startswith('Prompt CAD 프로젝트 (*.pcad)')
    assert read_project(value.path).model_dump(mode='json')==before


def test_legacy_save_keeps_path_and_save_as_defaults_to_pcad(tmp_path,monkeypatch):
    value=document();legacy=tmp_path/'previous.CAD.JSON';value.write(legacy)
    original=legacy.read_bytes();calls=[]
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *args:pytest.fail('ordinary Save prompted'))
    assert MainWindow.save(harness(value)) and value.path==legacy
    def select(*args):
        calls.append(args)
        return str(tmp_path/'previous.pcad'),''
    monkeypatch.setattr(QFileDialog,'getSaveFileName',select)
    assert MainWindow.save(harness(value),True)
    assert Path(calls[0][2])==tmp_path/'previous.pcad'
    assert legacy.read_bytes()==original==(tmp_path/'previous.pcad').read_bytes()


def test_legacy_resolution_is_narrow_and_existing_source_wins(tmp_path):
    value=document();legacy=tmp_path/'project.cad.json';migrated=tmp_path/'project.pcad'
    value.write(migrated)
    assert resolve_project_path(legacy)==migrated
    assert read_project(legacy)==read_project(migrated)
    value.write(legacy)
    assert resolve_project_path(legacy)==legacy
    ordinary=tmp_path/'project.json'
    assert resolve_project_path(ordinary)==ordinary
    with pytest.raises(FileNotFoundError):read_project(ordinary)
    with pytest.raises(FileNotFoundError):read_project(tmp_path/'missing.cad.json')


@pytest.fixture(scope='module')
def app():
    value=QApplication.instance() or QApplication([])
    value.setQuitOnLastWindowClosed(False)
    yield value
    assert QThreadPool.globalInstance().waitForDone(15000)


@pytest.fixture
def window(app,tmp_path,monkeypatch):
    import cadstudio.native.window as module
    from cadstudio.native.model_picker import LocalModelPicker
    monkeypatch.setattr(module,'DATA_DIR',tmp_path/'profile')
    monkeypatch.setattr(LocalModelPicker,'refresh',lambda self:None)
    value=MainWindow(restore=False);value.completion_notifier.enabled=False
    errors=[];monkeypatch.setattr(value,'show_error',lambda text:errors.append(text))
    value.show();app.processEvents()
    yield value,errors
    assert not value.busy
    value.document.dirty=False;value.close();value.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()


def wait(app,window,errors):
    deadline=time.monotonic()+20
    while window.busy and time.monotonic()<deadline:
        app.processEvents();QTest.qWait(10)
    assert not window.busy and not errors,errors


def test_actual_native_save_open_pcad_preserves_history_and_undo(app,window,tmp_path,monkeypatch):
    value,errors=window;original=document();value.document=original
    expected=deepcopy(original.project().model_dump(mode='json'))
    target=tmp_path/'native roundtrip.pcad'
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *args:(str(target),''))
    assert value.save() and value.document.path==target
    assert value.autosave.name=='native-autosave.pcad'
    value.autosave_document()
    assert value.autosave.exists() and read_project(value.autosave)==read_project(target)
    value.new_document();assert value.document.design is None
    calls=[]
    def select(*args):
        calls.append(args);return str(target),''
    monkeypatch.setattr(QFileDialog,'getOpenFileName',select)
    value.open_project();wait(app,value,errors)
    assert '.pcad' in calls[0][3] and '.cad.json' in calls[0][3]
    assert value.document.path==target
    assert value.document.project().model_dump(mode='json')==expected
    assert value.result['stats']['valid'] and len(value.viewport.actors)==1
    assert value.result['stats']['volume']==pytest.approx(70*35*4)
    value.undo();wait(app,value,errors)
    assert value.document.design['parts'][0]['geometry']['length']==60
    value.redo();wait(app,value,errors)
    assert value.document.project().model_dump(mode='json')==expected


def test_actual_native_open_legacy_and_missing_migrated_reference(app,window,tmp_path):
    value,errors=window;legacy=tmp_path/'legacy.cad.json';original=document();original.write(legacy)
    expected=original.project().model_dump(mode='json')
    value.open_project(legacy);wait(app,value,errors)
    assert value.document.path==legacy
    assert value.document.project().model_dump(mode='json')==expected
    assert value.save() and value.document.path==legacy
    migrated=tmp_path/'migrated.pcad';original.write(migrated)
    value.open_project(tmp_path/'migrated.cad.json');wait(app,value,errors)
    assert value.document.path==migrated
    assert value.document.project().model_dump(mode='json')==expected
    assert value.save() and not (tmp_path/'migrated.cad.json').exists()


def test_actual_native_recovery_prefers_pcad_and_keeps_legacy_fallback(app,window):
    value,errors=window;legacy=value.data_dir/'native-autosave.cad.json';original=document()
    original.write(legacy)
    assert value.recovery_autosave_path()==legacy
    value.recover_autosave();wait(app,value,errors)
    assert value.document.path is None and value.document.dirty
    assert value.document.project()==original.project()
    value.document.dirty=False
    changed=document();changed.design['name']='새 자동저장';changed.journal.data['base']['name']='새 자동저장'
    changed.write(value.autosave)
    assert value.recovery_autosave_path()==value.autosave
    value.recover_autosave();wait(app,value,errors)
    assert value.document.design['name']=='새 자동저장'
    assert value.document.path is None and value.document.dirty
    assert legacy.exists()
