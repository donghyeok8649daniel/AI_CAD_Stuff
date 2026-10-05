"""Large CAD histories stay complete, portable and atomic on disk."""
from copy import deepcopy
from io import BytesIO
import errno
import json
from zipfile import ZipFile

import cadquery as cq
import pytest

from cadstudio.models import Design,Part
from cadstudio.native import document as native_document
from cadstudio.native.document import Document,MAX_PROJECT_READ_BYTES,read_project


@pytest.fixture(scope='module')
def large_document(tmp_path_factory):
    from cadstudio.imported import import_asset
    folder=tmp_path_factory.mktemp('large-project-fixture')
    mesh_file=folder/'외부부품.stl'
    cq.exporters.export(cq.Workplane('XY').box(2,3,4).val(),str(mesh_file),exportType='STL')
    asset=import_asset(mesh_file);mesh_file.unlink()
    design=Design(name='원통 연구 · μm / Ω',parts=[
        Part(id='body',name='시편',geometry=dict(kind='cylinder',height=20,diameter=10)),
        Part(id='mesh',name='가져온 STL',geometry=dict(kind='imported',asset_id='external'),transform=dict(x=60)),
    ],assets={'external':asset})
    doc=Document()
    # A checked research/AI context is allowed to contain a large source
    # snapshot. The geometry and every branch still validate normally.
    doc.commit(design,'원본 · 외부 메시',{'research_snapshot':'파형µ'*4_200_000})
    root=doc.journal.data['cursor']
    raw=deepcopy(doc.design);raw['parts'][0]['geometry']['height']=35
    doc.commit(raw,'높이 변경');abandoned=doc.journal.data['cursor']
    doc.commit(doc.journal.at(root),'원본 복원',cursor=root)
    raw=deepcopy(doc.design);raw['parts'][0]['geometry']['diameter']=14
    doc.commit(raw,'새 분기');branch=doc.journal.data['cursor']
    return doc,root,abandoned,branch


def test_project_over_32mb_saves_compact_utf8_and_reopens_all_history_branches_and_mesh(tmp_path,large_document):
    from cadstudio.imported import decode_shape
    doc,root,abandoned,branch=large_document
    target=tmp_path/'큰 설계.cad.json';doc.write(target)
    assert target.stat().st_size>32_000_000
    data=target.read_bytes()
    assert len(data)==target.stat().st_size and b'\n' not in data
    assert '원통 연구 · μm / Ω'.encode('utf-8') in data
    loaded=read_project(target);restored=Document();restored.load(loaded,target)
    assert loaded.model_dump()==doc.project().model_dump()
    assert len(restored.journal.data['entries'])==3 and restored.journal.data['cursor']==branch
    assert restored.journal.at(root)['parts'][0]['geometry']['height']==20
    assert restored.journal.at(abandoned)['parts'][0]['geometry']['height']==35
    assert restored.journal.at(branch)['parts'][0]['geometry']['diameter']==14
    restored.commit(restored.journal.at(root),'되돌리기',cursor=root)
    assert restored.design['assets']==doc.design['assets']
    asset=loaded.design.assets['external']
    assert asset.format=='stl' and decode_shape(asset.data,asset.sha256).isValid()
    assert doc.path==target and not doc.dirty and not list(tmp_path.glob('*.tmp'))


def test_existing_conversion_package_rescues_full_large_project_without_normal_save(tmp_path,large_document):
    from cadstudio.models import Project
    from cadstudio.native_export import conversion_package
    doc,*_=large_document
    with ZipFile(BytesIO(conversion_package(doc.project()))) as archive:
        saved=archive.read('design.cad.json')
        assert len(saved)>32_000_000 and archive.getinfo('design.step').file_size>0
        rescued=Project.model_validate_json(saved)
    assert rescued.model_dump()==doc.project().model_dump()
    target=tmp_path/'구조.zip에서 복원.cad.json';target.write_bytes(saved)
    assert read_project(target).history==rescued.history


@pytest.mark.parametrize('failure',['fsync','replace'])
def test_save_failure_preserves_original_disk_file_dirty_state_and_complete_history(tmp_path,monkeypatch,failure):
    doc=Document();doc.commit(Design(parts=[Part(id='p',name='원본',geometry=dict(kind='cylinder'))]),'원본')
    target=tmp_path/'원본.cad.json';doc.write(target);original=target.read_bytes()
    raw=deepcopy(doc.design);raw['parts'][0]['name']='저장되지 않은 변경';doc.commit(raw,'부품 이름')
    expected=doc.project().model_dump()
    def fail(*args):raise OSError(errno.ENOSPC,'Synthetic disk full')
    monkeypatch.setattr(native_document.os,failure,fail)
    with pytest.raises(OSError,match='Synthetic disk full'):doc.write(target)
    assert target.read_bytes()==original and json.loads(original)['design']['parts'][0]['name']=='원본'
    assert doc.dirty and doc.path==target and doc.project().model_dump()==expected
    assert not list(tmp_path.glob('*.tmp'))


def test_autosave_keeps_manual_save_path_and_dirty_state_with_unicode(tmp_path):
    doc=Document();doc.commit(Design(name='원본',parts=[]),'원본')
    manual=tmp_path/'manual.cad.json';doc.write(manual)
    changed=deepcopy(doc.design);changed['name']='자동저장 · λ';doc.commit(changed,'설계 이름')
    autosave=tmp_path/'recovery.cad.json';doc.write(autosave,autosave=True)
    assert doc.dirty and doc.path==manual
    assert read_project(autosave).design.name=='자동저장 · λ'
    assert read_project(manual).design.name=='원본'


def test_read_limit_counts_physical_bytes_allows_explicit_override_and_accepts_utf8_bom(tmp_path):
    doc=Document();doc.commit(Design(name='한글 · µ',parts=[]),'시작')
    target=tmp_path/'bom.cad.json';doc.write(target)
    target.write_bytes(b'\xef\xbb\xbf'+target.read_bytes())
    size=target.stat().st_size
    assert size>len(target.read_text(encoding='utf-8-sig'))
    with pytest.raises(ValueError,match='원본과 작업 기록'):read_project(target,max_bytes=size-1)
    assert read_project(target,max_bytes=size).design.name=='한글 · µ'
    assert read_project(target,max_bytes=None).history==doc.project().history
    with pytest.raises(ValueError,match='양의 바이트'):read_project(target,max_bytes=0)
    assert MAX_PROJECT_READ_BYTES==512*1024*1024


def test_default_read_ceiling_rejects_oversized_file_before_allocating_json(tmp_path,monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    target=tmp_path/'oversized.cad.json'
    target.write_bytes(b'unchanged')
    actual_stat=Path.stat;actual_open=Path.open
    monkeypatch.setattr(Path,'stat',lambda path,*args,**kwargs:
        SimpleNamespace(st_size=MAX_PROJECT_READ_BYTES+1) if path==target else actual_stat(path,*args,**kwargs))
    def no_oversized_allocation(path,*args,**kwargs):
        if path==target:raise AssertionError('Oversized input must not be read into memory')
        return actual_open(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',no_oversized_allocation)
    with pytest.raises(ValueError,match='512 MiB'):read_project(target)
    with actual_open(target,'rb') as stream:assert stream.read()==b'unchanged'


def test_reader_still_bounds_bytes_when_file_grows_after_stat(tmp_path,monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    target=tmp_path/'growing.cad.json';target.write_bytes(b' '*300)
    actual_stat=Path.stat
    monkeypatch.setattr(Path,'stat',lambda path,*args,**kwargs:
        SimpleNamespace(st_size=10) if path==target else actual_stat(path,*args,**kwargs))
    with pytest.raises(ValueError,match='현재 읽기 한도'):read_project(target,max_bytes=100)
