from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
import pytest
from fastapi.testclient import TestClient
from cadstudio.catalog import preset
from cadstudio.models import Project
from cadstudio import server
from cadstudio.native_export import conversion_package


def journal_project():
    base=preset('cylinder').model_dump();current=deepcopy(base)
    entries=[dict(id='s0',parent=None,label='원 생성',created_at='2026-09-22T00:00:00Z',changes=[],context={})]
    for i in range(1,46):
        old=current['parts'][0]['geometry']['height'];current['parts'][0]['geometry']['height']=old+1
        entries.append(dict(id=f's{i}',parent=f's{i-1}',label='높이 변경',created_at='2026-09-22T00:00:00Z',changes=[dict(path=['parts',0,'geometry','height'],before=old,after=old+1)]))
    # A branch based on the initial sketch keeps all 45 abandoned steps.
    branch=deepcopy(base);branch['parts'][0]['geometry']['diameter']=42
    entries.append(dict(id='branch',parent='s0',label='다른 분기',created_at='2026-09-22T00:00:00Z',changes=[dict(path=['parts',0,'geometry','diameter'],before=base['parts'][0]['geometry']['diameter'],after=42)],context={'tool_actions':[{'tool':'원','face':3,'feature':'base','entity':'circle-1'}]}))
    return dict(version=2,design=branch,history=dict(base=base,entries=entries,cursor='branch',head='branch'))


def test_history_survives_save_load_branches_and_native_conversion(tmp_path,monkeypatch):
    project=Project.model_validate(journal_project())
    assert len(project.history.entries)==47
    monkeypatch.setattr(server,'DATA',tmp_path)
    with TestClient(server.app,headers={'X-CAD-Request':'1'}) as client:
        r=client.post('/api/projects',json=project.model_dump());assert r.status_code==200,r.text
        saved=client.get('/api/projects/'+r.json()['id']).json()
        assert saved==project.model_dump()
        assert client.post('/api/projects/validate',json=saved).status_code==200
    with ZipFile(BytesIO(conversion_package(project))) as archive:
        loaded=Project.model_validate_json(archive.read('design.cad.json'))
        assert loaded.history==project.history


@pytest.mark.parametrize('corrupt',['before','parent','cursor','current','prototype'])
def test_corrupt_history_rejected(corrupt):
    p=journal_project()
    if corrupt=='before':p['history']['entries'][1]['changes'][0]['before']=999
    if corrupt=='parent':p['history']['entries'][1]['parent']='s4'
    if corrupt=='cursor':p['history']['cursor']='s1'
    if corrupt=='current':p['design']['parts'][0]['geometry']['diameter']=41
    if corrupt=='prototype':p['history']['entries'][1]['changes'][0]['path']=['__proto__','polluted']
    with pytest.raises(ValueError):Project.model_validate(p)


def test_old_projects_remain_readable():
    p=Project.model_validate(dict(version=1,design=preset('extrusion').model_dump()))
    assert p.history is None
