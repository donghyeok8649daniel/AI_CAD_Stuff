import hashlib,hmac,json
from pathlib import Path
import pytest
from cadstudio import kernel as K
from cadstudio.models import Design,Part
from cadstudio.verified_preview_cache import VerifiedPreviewCache,MAGIC


@pytest.fixture
def small():
    d=Design(parts=[Part(id='a',name='a',geometry=dict(kind='cylinder',diameter=4,height=5))])
    return d,K.preview(d)


def test_roundtrip_authentication_and_all_preview_values(tmp_path,small):
    d,r=small;c=VerifiedPreviewCache(tmp_path);b=c.binding('a'*64,d,'auto')
    assert c.get(b) is None and c.put(b,d,r)
    other=VerifiedPreviewCache(tmp_path);loaded,preview=other.get(b)
    assert loaded==d and preview==json.loads(json.dumps(r))
    assert not any(p.suffix in ('.py','.pickle') for p in tmp_path.iterdir())


@pytest.mark.parametrize('field,value',[('file_sha256','b'*64),('build','different'),('runtime','different'),('quality','fine'),('design_sha256','c'*64)])
def test_every_binding_change_forces_a_miss(tmp_path,small,field,value):
    d,r=small;c=VerifiedPreviewCache(tmp_path);b=c.binding('a'*64,d,'auto');assert c.put(b,d,r)
    assert c.get({**b,field:value}) is None


@pytest.mark.parametrize('change',['body','header','key','copy-other-file','truncated'])
def test_tampering_never_reuses_a_verdict(tmp_path,small,change):
    d,r=small;c=VerifiedPreviewCache(tmp_path);b=c.binding('a'*64,d,'auto');assert c.put(b,d,r);path=c._path(b)
    original=path.read_bytes()
    if change=='body':path.write_bytes(original[:-1]+bytes([original[-1]^1]))
    elif change=='header':path.write_bytes(original.replace(b'raw_bytes',b'raw_byteX'))
    elif change=='key':(tmp_path/'cache-key.bin').write_bytes(b'0'*32)
    elif change=='copy-other-file':
        other={**b,'file_sha256':'b'*64};c._path(other).write_bytes(original);b=other
    else:path.write_bytes(original[:40])
    assert c.get(b) is None


def test_no_key_or_malformed_key_is_not_replaced(tmp_path,small):
    d,r=small;c=VerifiedPreviewCache(tmp_path);b=c.binding('a'*64,d,'auto')
    assert c.get(b) is None
    key=tmp_path/'cache-key.bin';key.write_bytes(b'broken')
    assert not c.put(b,d,r) and key.read_bytes()==b'broken'


def test_cache_cannot_claim_success_for_invalid_or_different_meshes(tmp_path,small):
    d,r=small;c=VerifiedPreviewCache(tmp_path);b=c.binding('a'*64,d,'auto')
    assert not c.put(b,d,{**r,'stats':{**r['stats'],'valid':False}})
    assert not c.put(b,d,{**r,'_geometry_key':'wrong'})
    assert not c.put(b,d,{**r,'meshes':[]})


def test_limits_are_cache_admission_only_and_do_not_delete_unknown_files(tmp_path,small,monkeypatch):
    from cadstudio import verified_preview_cache as V
    d,r=small;c=VerifiedPreviewCache(tmp_path);unknown=tmp_path/('f'*64+'.preview');unknown.write_bytes(b'user-data')
    monkeypatch.setattr(V,'MAX_FILES',1)
    for ch in 'ab':assert c.put(c.binding(ch*64,d,'auto'),d,r)
    assert unknown.read_bytes()==b'user-data'
    own=[p for p in tmp_path.glob('*.preview') if p!=unknown]
    assert len(own)==1 and c.get(c.binding('b'*64,d,'auto')) is not None
    monkeypatch.setattr(V,'MAX_RAW',1)
    assert not c.put(c.binding('c'*64,d,'auto'),d,r)


def test_cache_error_never_rewrites_project_and_fingerprint_matches_exact_bytes(tmp_path):
    from cadstudio.native.document import Document,read_project
    doc=Document();doc.commit(Design(name='full history'),'start');path=tmp_path/'input.pcad';doc.write(path)
    before=path.read_bytes();seen=[];project=read_project(path,fingerprint=seen.append)
    assert seen==[hashlib.sha256(before).hexdigest()] and len(project.history.entries)==1
    assert path.read_bytes()==before


def test_open_pipeline_rechecks_history_and_authentication_before_skipping_compute(tmp_path,small,monkeypatch):
    from cadstudio.native.document import Document
    from cadstudio import project_open as P
    d,r=small;doc=Document();doc.commit(d,'complete history');path=tmp_path/'same.pcad';doc.write(path)
    cache=tmp_path/'cache';cold={};project,first=P.load_project_preview(path,cache,audit=cold)
    assert not cold['cache_hit'] and cold['cache_stored']
    def forbidden(*args,**kwargs):raise AssertionError('No recalculation on exact authenticated cache hit')
    monkeypatch.setattr(P,'preview',forbidden)
    audit={};reopened,second=P.load_project_preview(path,cache,audit=audit)
    assert audit['cache_hit'] and reopened.history==project.history and second==json.loads(json.dumps(first))
    payload=json.loads(path.read_bytes());payload['design']['name']='history mismatch';path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):P.load_project_preview(path,cache)


def test_changed_valid_project_and_corrupt_cache_recompute_instead_of_claiming_a_hit(tmp_path,small,monkeypatch):
    from cadstudio.native.document import Document
    from cadstudio import project_open as P
    d,r=small;doc=Document();doc.commit(d,'start');path=tmp_path/'same.pcad';doc.write(path);cache=tmp_path/'cache'
    P.load_project_preview(path,cache)
    calls=[];real=P.preview
    def observed(*args,**kwargs):calls.append(True);return real(*args,**kwargs)
    monkeypatch.setattr(P,'preview',observed)
    for p in cache.glob('*.preview'):p.write_bytes(b'corrupt')
    a={};P.load_project_preview(path,cache,audit=a);assert calls==[True] and not a['cache_hit']
    doc.commit(d.model_copy(update={'name':'changed'}),'valid new name');doc.write(path)
    b={};P.load_project_preview(path,cache,audit=b);assert len(calls)==2 and not b['cache_hit']


def test_unwritable_cache_never_prevents_an_otherwise_valid_open(tmp_path,small,monkeypatch):
    from cadstudio.native.document import Document
    from cadstudio import project_open as P
    d,r=small;doc=Document();doc.commit(d,'start');path=tmp_path/'input.pcad';doc.write(path)
    cache=tmp_path/'not-a-directory';cache.write_bytes(b'preserve')
    audit={};project,result=P.load_project_preview(path,cache,audit=audit)
    assert result['stats']['valid'] and project.history and not audit['cache_stored'] and cache.read_bytes()==b'preserve'


def test_saved_current_preview_reopens_without_recalculation_and_updates_labels(tmp_path,small,monkeypatch):
    from cadstudio.native.document import Document
    from cadstudio import project_open as P
    d,r=small;doc=Document();doc.commit(d,'start')
    changed=d.model_copy(deep=True);changed.parts[0].name='new saved label';changed.parts[0].color='#123456'
    doc.commit(changed,'metadata edit');path=tmp_path/'saved.pcad';doc.write(path);before=path.read_bytes()
    assert P.remember_saved_preview(path,doc.design,r,tmp_path/'cache')
    def forbidden(*args,**kwargs):raise AssertionError('Saved checked preview was not reused')
    monkeypatch.setattr(P,'preview',forbidden);audit={}
    project,result=P.load_project_preview(path,tmp_path/'cache',audit=audit)
    assert audit['cache_hit'] and len(project.history.entries)==2 and result['meshes'][0]['name']=='new saved label'
    assert result['meshes'][0]['color']=='#123456' and path.read_bytes()==before
    assert not P.remember_saved_preview(path,doc.design,None,tmp_path/'cache')
