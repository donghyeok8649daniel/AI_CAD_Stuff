"""Whole-repository reference discovery is read-only and honestly bounded."""

import asyncio
import base64
import hashlib
import json
from time import monotonic,sleep

import httpx
import pytest

from cadstudio.github_reference import GitHubReader,repository_index_reference,scope_path
from cadstudio.models import DraftRequest
from cadstudio.native.local_ai import DraftCancelled,DraftControl
from cadstudio.references import extract_reference,merge_references


REPO='donghyeok8649daniel/al-fatigue-probability-theory'
REVISION='a'*40


def fixture(*,count=4,truncated=False,corrupt=False,blob_delay=0):
    blobs={};entries=[];calls=[]
    files={'README.md':b'# Study\nPhysical test data and model time remain distinct.\n',
           'docs/material.md':b'Al cylindrical specimen geometry. No rated load is declared.\n',
           'solver.py':b'raise RuntimeError("This reference must never run")\n',
           'image.png':b'not-a-text-reference'}
    if count>4:
        files.update({f'docs/detail{index:03d}.md':(f'Document {index} '+ 'measurement reference '*1000).encode()
                      for index in range(count-4)})
    for name,data in files.items():
        sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        blobs[sha]=data;entries.append(dict(path=name,type='blob',mode='100644',size=len(data),sha=sha))
    entries.append(dict(path='external',type='commit',mode='160000',sha='c'*40))
    entries.append(dict(path='linked.md',type='blob',mode='120000',size=11,sha='d'*40))
    async def handle(request):
        calls.append(request)
        assert request.method=='GET' and request.url.host=='api.github.com'
        path=request.url.path
        if path=='/repos/'+REPO:body={'default_branch':'main','private':False}
        elif '/commits/' in path:body={'sha':REVISION}
        elif '/git/trees/' in path:
            if not truncated:body={'tree':entries,'truncated':False}
            elif request.url.query==b'recursive=1':body={'tree':entries[:1],'truncated':True}
            elif path.endswith(REVISION):
                body={'tree':[row for row in entries if not row['path'].startswith('docs/')]
                      +[dict(path='docs',type='tree',mode='040000',sha='b'*40)],'truncated':False}
            elif path.endswith('b'*40):
                body={'tree':[{**row,'path':row['path'][5:]} for row in entries if row['path'].startswith('docs/')],'truncated':False}
            else:raise AssertionError(path)
        elif '/git/blobs/' in path:
            if blob_delay:await asyncio.sleep(blob_delay)
            data=blobs[path.rsplit('/',1)[-1]]
            body={'encoding':'base64','content':base64.b64encode(b'bad' if corrupt else data).decode()}
        else:raise AssertionError(path)
        return httpx.Response(200,json=body)
    return GitHubReader(transport=httpx.MockTransport(handle)),calls


def test_blank_scope_indexes_the_whole_root_and_automatically_reads_bounded_text():
    reader,calls=fixture();control=DraftControl()
    connection=reader.connect('https://github.com/'+REPO,'',control)
    assert connection['scope_path']=='' and connection['truncated'] is False
    assert {row['path'] for row in connection['entries']}=={'README.md','docs/material.md','solver.py','image.png','external','linked.md'}
    refs=reader.snapshot(connection,control)
    DraftRequest(prompt='use references',references=refs)
    assert len(refs)>=2
    index=refs[0]
    assert 'image.png' in index.text and 'solver.py' in index.text
    assert 'Listed paths are metadata' in index.text
    content='\n'.join(ref.text for ref in refs[1:])
    assert 'Al cylindrical specimen' in content and 'must never run' in content
    assert all(ref.revision==REVISION for ref in refs)
    assert all(request.method=='GET' for request in calls)
    assert not any(request.url.path.endswith('c'*40) or request.url.path.endswith('d'*40) for request in calls)


def test_explicit_directory_limits_scope_while_empty_defaults_to_whole_repository():
    reader,_=fixture();control=DraftControl()
    connection=reader.connect(REPO,'main',control,'docs')
    assert [row['path'] for row in connection['entries']]==['docs/material.md']
    assert connection['scope_path']=='docs'
    refs=reader.snapshot(connection,control)
    assert 'Scope: /docs' in refs[0].text and 'solver.py' not in refs[0].text
    with pytest.raises(ValueError,match='경로'):
        reader.connect(REPO,'main',control,'missing')
    for path in ('../outside','docs//bad','docs\\file'):
        with pytest.raises(ValueError):scope_path(path)


def test_truncated_recursive_api_response_walks_immutable_subtrees_instead_of_lying():
    reader,calls=fixture(truncated=True);connection=reader.connect(REPO,'',DraftControl())
    assert connection['truncated'] is False
    assert 'docs/material.md' in {row['path'] for row in connection['entries']}
    paths=[request.url.path for request in calls]
    assert '/repos/'+REPO+'/git/trees/'+REVISION in paths
    assert '/repos/'+REPO+'/git/trees/'+'b'*40 in paths
    assert '/repos/'+REPO+'/git/trees/'+'c'*40 not in paths


def test_large_repository_content_and_reference_count_limits_are_visible_and_respected():
    reader,_=fixture(count=80);control=DraftControl();connection=reader.connect(REPO,'',control)
    refs=reader.snapshot(connection,control,max_chars=12000,max_references=2)
    assert len(connection['entries'])==82
    assert len(refs)<=2 and sum(len(ref.text) for ref in refs)<=12000
    assert all(len(ref.text)<=20000 for ref in refs)
    assert 'excerpts' in refs[0].note.lower()
    one=reader.snapshot(connection,control,max_chars=900,max_references=1)
    assert len(one)==1 and len(one[0].text)==900 and one[0].truncated
    with pytest.raises(ValueError):reader.snapshot(connection,control,max_references=0)


def test_refresh_replaces_repository_snapshot_by_chunk_without_removing_manual_sources():
    reader,_=fixture();control=DraftControl();connection=reader.connect(REPO,'',control)
    old=reader.snapshot(connection,control)
    changed={**connection,'revision':'b'*40}
    new=[repository_index_reference(changed)]
    manual=extract_reference('notes.txt',b'Keep this manually attached note')
    merged=merge_references([manual,*old],new)
    assert manual in merged
    assert sum(ref.name.endswith('repository-index.md') for ref in merged)==1
    assert next(ref for ref in merged if ref.name.endswith('repository-index.md')).revision=='b'*40


def test_snapshot_integrity_failure_and_cancel_preserve_connection_metadata():
    reader,_=fixture(corrupt=True);control=DraftControl();connection=reader.connect(REPO,'',control)
    original=json.dumps(connection,sort_keys=True)
    with pytest.raises(ValueError,match='버전'):reader.snapshot(connection,control)
    assert json.dumps(connection,sort_keys=True)==original
    control.cancel()
    with pytest.raises(DraftCancelled):reader.snapshot(connection,control)


def test_native_connect_adds_repository_before_excerpts_finish_and_preserves_parent_references(tmp_path,monkeypatch):
    from threading import Event
    from PySide6.QtWidgets import QApplication,QWidget
    from cadstudio.native import reference_dialog
    qt=QApplication.instance() or QApplication([]);qt.setQuitOnLastWindowClosed(False)
    parent=QWidget();parent.data_dir=tmp_path
    original=extract_reference('local.md',b'Existing user reference remains intact.')
    parent.reference_materials=[original];parent.github_reference_token=''
    reader,calls=fixture()
    blob_requested=Event();release_blob=Event();transport=reader.transport
    async def gated_request(request):
        if '/git/blobs/' in request.url.path and not blob_requested.is_set():
            blob_requested.set()
            # Hold excerpts pending until the UI assertions finish. Yield to
            # the worker event loop so cancellation remains functional.
            while not release_blob.is_set():await asyncio.sleep(.005)
        return await transport.handle_async_request(request)
    reader.transport=httpx.MockTransport(gated_request)
    monkeypatch.setattr(reference_dialog,'GitHubReader',lambda token:reader)
    dialog=reference_dialog.ReferenceDialog(parent)
    def wait(condition):
        end=monotonic()+5
        while not condition():
            if monotonic()>end:raise TimeoutError(dialog.status.toPlainText())
            qt.processEvents();sleep(.005)
        qt.processEvents()
    try:
        dialog.repo.setText('https://github.com/'+REPO)
        assert dialog.scope_path.text()==''
        dialog.connect_button.click()
        wait(lambda:dialog.connection is not None and blob_requested.is_set())
        assert dialog.files.count()==6
        assert len(dialog.refs)==2 and dialog.refs[-1].name.endswith('repository-index.md')
        assert dialog.task is not None
        release_blob.set()
        wait(lambda:dialog.task is None)
        assert len(dialog.refs)>2 and original in dialog.refs
        assert '자동 추가 완료' in dialog.status.toPlainText()
        assert parent.reference_materials==[original]
        settings=json.loads(dialog.settings_path.read_text(encoding='utf-8'))
        assert set(settings)=={'repo','branch'} and REPO==settings['repo']
        assert all(request.method=='GET' for request in calls)
        assert 'scope' in dialog.refs[1].note.lower()
    finally:
        release_blob.set()
        dialog.reject()
        assert parent.reference_materials==[original]
        dialog.deleteLater();parent.deleteLater();qt.processEvents()


def test_native_path_search_reaches_complete_index_beyond_bounded_visible_rows(tmp_path):
    from PySide6.QtWidgets import QApplication,QWidget
    from cadstudio.native.reference_dialog import ReferenceDialog,MAX_VISIBLE_REPOSITORY_PATHS
    qt=QApplication.instance() or QApplication([]);qt.setQuitOnLastWindowClosed(False)
    parent=QWidget();parent.data_dir=tmp_path;parent.reference_materials=[];parent.github_reference_token=''
    reader,_=fixture();connection=reader.connect(REPO,'',DraftControl())
    connection['entries']=[dict(path=f'assets/item{index:05d}.png',size=200,sha='e'*40,type='blob',mode='100644')
                           for index in range(MAX_VISIBLE_REPOSITORY_PATHS+20)]
    target=connection['files'][0];connection['entries'].append(target)
    dialog=ReferenceDialog(parent)
    try:
        dialog.connected((reader,connection))
        assert dialog.files.count()==MAX_VISIBLE_REPOSITORY_PATHS
        assert len(dialog.repository_rows)==MAX_VISIBLE_REPOSITORY_PATHS+21
        dialog.filter.setText('README')
        assert dialog.files.count()==1
        assert dialog.files.item(0).data(256)['path']=='README.md'
        assert '2,021' in dialog.list_count.text()
    finally:
        dialog.reject();dialog.deleteLater();parent.deleteLater();qt.processEvents()


def test_native_full_reference_capacity_never_discards_existing_user_material(tmp_path):
    from PySide6.QtWidgets import QApplication,QWidget
    from cadstudio.native.reference_dialog import ReferenceDialog
    qt=QApplication.instance() or QApplication([]);qt.setQuitOnLastWindowClosed(False)
    parent=QWidget();parent.data_dir=tmp_path;parent.github_reference_token=''
    original=[extract_reference(f'local{index}.md',f'User material {index}'.encode()) for index in range(8)]
    parent.reference_materials=original
    reader,_=fixture();connection=reader.connect(REPO,'',DraftControl())
    dialog=ReferenceDialog(parent)
    try:
        dialog.connected((reader,connection,True))
        assert dialog.refs==original and parent.reference_materials==original
        assert dialog.task is None
        assert '자동 추가하지 않았습니다' in dialog.status.toPlainText()
        assert dialog.connection is not None
    finally:
        dialog.reject();dialog.deleteLater();parent.deleteLater();qt.processEvents()
