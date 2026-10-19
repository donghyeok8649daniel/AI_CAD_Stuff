"""Recovery never validates live state on the UI or publishes stale snapshots."""
import ast
from copy import deepcopy
from pathlib import Path
from threading import Event,get_ident
from types import SimpleNamespace
import pytest
from cadstudio.models import Design,Part
from cadstudio.native.document import Document,read_project
from cadstudio.native.autosave import AutosaveQueue
from cadstudio.native import document as document_module


def document(name='original'):
    doc=Document();doc.commit(Design(name=name,parts=[Part(id='p',name='part',geometry=dict(kind='cylinder'))]),'start')
    return doc


def rename(doc,name):
    data=deepcopy(doc.design);data['name']=name;doc.commit(data,name)


def pause_project(monkeypatch,name):
    entered=Event();release=Event();threads=[];original=Document.project
    def project(doc):
        threads.append(get_ident())
        if doc.design['name']==name:
            entered.set();assert release.wait(10),'test did not release validation'
        return original(doc)
    monkeypatch.setattr(Document,'project',project)
    return entered,release,threads


def test_owned_snapshot_excludes_replay_cache_and_live_path_dirty_state(tmp_path):
    doc=document();doc.path=tmp_path/'manual.pcad';doc.prompt='saved prompt'
    doc.journal.cache['unpersisted']=object()
    snap=doc.autosave_snapshot();rename(doc,'changed');doc.prompt='new prompt'
    assert snap.design['name']=='original' and snap.prompt=='saved prompt'
    assert not snap.journal.cache and len(snap.journal.data['entries'])==1
    snap.design['parts'][0]['name']='snapshot only'
    assert doc.design['parts'][0]['name']=='part'
    assert doc.path==tmp_path/'manual.pcad' and doc.dirty


def test_submit_does_not_wait_for_validation_coalesces_pending_and_flushes_latest(tmp_path,monkeypatch):
    target=tmp_path/'recovery.pcad';original=document();original.write(target);old=target.read_bytes()
    entered,release,threads=pause_project(monkeypatch,'running')
    doc=document('running');doc.path=tmp_path/'manual.pcad';main=get_ident();queue=AutosaveQueue(target)
    try:
        a=queue.submit(doc);assert entered.wait(10) and not a.done()
        rename(doc,'superseded');b=queue.submit(doc)
        rename(doc,'latest');c=queue.submit(doc)
        assert b.result(timeout=1) is False and target.read_bytes()==old
        # Edits after submit must not leak into this recovery snapshot.
        rename(doc,'not submitted');release.set()
        assert queue.flush() is True and a.result(timeout=10) is False and c.result(timeout=10) is True
        assert threads and all(thread!=main for thread in threads)
        loaded=read_project(target)
        assert loaded.design.name=='latest' and len(loaded.history.entries)==3
        assert doc.design['name']=='not submitted' and doc.dirty and doc.path==tmp_path/'manual.pcad'
        assert not list(tmp_path.glob('*.tmp'))
    finally:release.set();queue.close()


def test_open_new_document_invalidates_inflight_write(tmp_path,monkeypatch):
    target=tmp_path/'recovery.pcad';document().write(target);before=target.read_bytes()
    entered,release,_=pause_project(monkeypatch,'old document');queue=AutosaveQueue(target)
    try:
        old=queue.submit(document('old document'));assert entered.wait(10)
        queue.invalidate();release.set()
        assert old.result(timeout=10) is False and target.read_bytes()==before
        queue.submit(document('new document'));queue.flush()
        assert read_project(target).design.name=='new document'
    finally:release.set();queue.close()


def test_failed_history_still_rejected_preserves_disk_and_allows_retry(tmp_path):
    target=tmp_path/'recovery.pcad';doc=document();doc.write(target);before=target.read_bytes()
    invalid=doc.autosave_snapshot();invalid.design['name']='unrecorded mutation'
    queue=AutosaveQueue(target)
    try:
        failure=queue.submit(invalid)
        with pytest.raises(ValueError):failure.result(timeout=10)
        assert target.read_bytes()==before and len(queue.errors())==1 and not queue.errors()
        rename(doc,'valid retry');queue.submit(doc);queue.flush()
        assert read_project(target).design.name=='valid retry'
    finally:queue.close()


@pytest.mark.parametrize('operation',['fsync','replace'])
def test_io_failure_preserves_recovery_cleans_temp_and_retry(tmp_path,monkeypatch,operation):
    target=tmp_path/'recovery.pcad';doc=document();doc.write(target);before=target.read_bytes();rename(doc,'changed')
    queue=AutosaveQueue(target)
    try:
        with monkeypatch.context() as patch:
            def fail(*args):raise OSError('synthetic disk failure')
            patch.setattr(document_module.os,operation,fail)
            future=queue.submit(doc)
            with pytest.raises(OSError,match='synthetic'):future.result(timeout=10)
            assert target.read_bytes()==before and not list(tmp_path.glob('*.tmp'))
        queue.submit(doc);queue.flush();assert read_project(target).design.name=='changed'
    finally:queue.close()


def test_snapshot_keeps_abandoned_branch_and_restorable_states(tmp_path):
    doc=document();root=doc.journal.data['cursor'];rename(doc,'abandoned');branch=doc.journal.data['cursor']
    doc.commit(doc.journal.at(root),'restore',cursor=root);rename(doc,'new branch')
    queue=AutosaveQueue(tmp_path/'recovery.pcad')
    try:queue.submit(doc);queue.close()
    finally:
        if not queue._closed:queue.close()
    restored=Document();restored.load(read_project(tmp_path/'recovery.pcad'))
    assert len(restored.journal.data['entries'])==3
    assert restored.journal.at(root)['name']=='original'
    assert restored.journal.at(branch)['name']=='abandoned'
    assert restored.design['name']=='new branch'


def test_ui_queues_autosave_invalidates_new_and_loaded_docs_and_flushes_close():
    # Permission for this task is file analysis only: parse, never import Qt.
    source=Path(document_module.__file__).with_name('window.py');tree=ast.parse(source.read_text(encoding='utf-8-sig'))
    cls=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='MainWindow')
    methods={node.name:node for node in cls.body if isinstance(node,ast.FunctionDef)}
    text=lambda name:ast.unparse(methods[name])
    assert 'autosave_queue.submit' in text('autosave_document') and 'document.write' not in text('autosave_document')
    assert 'autosave_queue.invalidate' in text('new_document')
    assert 'autosave_queue.invalidate' in text('open_project')
    assert text('closeEvent').index('autosave_queue.close()')<text('closeEvent').index('viewport.shutdown()')


@pytest.mark.parametrize('invalid',[False,True])
def test_actual_close_method_flushes_latest_or_refuses_shutdown_without_gui(tmp_path,invalid):
    tree=ast.parse(Path(document_module.__file__).with_name('window.py').read_text(encoding='utf-8-sig'))
    cls=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='MainWindow')
    method=next(node for node in cls.body if isinstance(node,ast.FunctionDef) and node.name=='closeEvent')
    namespace={};exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'actual_close_ast','exec'),namespace)
    doc=document();target=tmp_path/'recovery.pcad';doc.write(target);original=target.read_bytes()
    if invalid:doc.design['name']='unrecorded'
    else:rename(doc,'latest before closing')
    queue=AutosaveQueue(target);events=[]
    self=SimpleNamespace(cancel_ai=lambda:None,codex_probe_task=None,busy=False,sketching=False,
        check_save=lambda:True,document=doc,autosave_queue=queue,message=events.append,
        autosave_timer=SimpleNamespace(stop=lambda:events.append('timer stopped')),
        editor=SimpleNamespace(stop=lambda:events.append('editor stopped')),
        viewport=SimpleNamespace(shutdown=lambda:events.append('viewport stopped')))
    event=SimpleNamespace(accept=lambda:events.append('accepted'),ignore=lambda:events.append('ignored'))
    namespace['closeEvent'](self,event)
    if invalid:
        assert events[-1]=='ignored' and 'viewport stopped' not in events and target.read_bytes()==original
        assert not queue._closed
        doc.design['name']='original';rename(doc,'retry');namespace['closeEvent'](self,event)
        assert events[-1]=='accepted' and read_project(target).design.name=='retry'
    else:
        assert events[-1]=='accepted' and events.index('timer stopped')<events.index('viewport stopped')
        assert read_project(target).design.name=='latest before closing'
    assert queue._closed
