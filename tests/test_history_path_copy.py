"""New private replay isolation regressions. No GUI or geometry kernel."""
from copy import deepcopy
from types import SimpleNamespace
import sys

import pytest
from cadstudio.models import Design, HistoryChange, Project
from cadstudio import history as H


def design():
    return Design(name='Replay isolation',parts=[dict(id='a',name='A',geometry=dict(kind='plate',hole_count=0)),
        dict(id='b',name='B',geometry=dict(kind='plate',hole_count=0))]).model_dump()


def change(path,before,after,**kwargs):
    return HistoryChange(path=path,before=before,after=after,**kwargs)


def entry(identifier,parent,changes=()):
    return dict(id=identifier,parent=parent,label=identifier,created_at='2026-10-18T00:00:00Z',
        source='manual',context={},changes=[c.model_dump() for c in changes])


def project(base,current,rows,cursor,head):
    return dict(version=2,design=current,history=dict(version=1,base=base,entries=rows,cursor=cursor,head=head))


def test_public_apply_keeps_untouched_subtrees_independent():
    base=design();old=deepcopy(base)
    result=H.apply_changes(base,[change(['parts',0,'name'],'A','Changed')])
    result['parts'][1]['geometry']['width']=123
    assert base==old and result['parts'][0]['name']=='Changed'


def test_private_replay_clones_progressive_paths_and_owns_new_payload():
    base=design();old=deepcopy(base)
    value={'nested':[1,2]}
    changes=[change(['parts',0,'name'],'A','Changed'),
        change(['parts',0,'transform','z'],0.,2.),
        change(['name'],base['name'],'Second edit'),
        change(['extra'],None,value,existed=False),
        change(['extra','nested',1],2,7)]
    shared=H.apply_changes(base,changes,_path_copy=True)
    ordinary=H.apply_changes(base,changes)
    assert shared==ordinary and base==old
    value['nested'][0]=99
    changes[3].after['nested'][0]=88
    assert shared['extra']=={'nested':[1,7]}
    assert shared['parts'][1] is base['parts'][1]  # Private replay only; never exposed as a public result.


@pytest.mark.parametrize('path,operation',[
    (['parts',-1,'name'],'set'),(['parts',True,'name'],'set'),
    (['parts',9,'name'],'set'),(['parts',0],'remove'),
    (['parts',0,'geometry','width','missing'],'set'),(['parts',0,'__proto__'],'set')])
def test_path_failures_match_public_errors_and_never_mutate_parent(path,operation):
    row=SimpleNamespace(path=path,operation=operation,existed=True,before='missing',after='new')
    base=design();old=deepcopy(base)
    errors=[]
    for private in (False,True):
        with pytest.raises(ValueError) as caught:
            H.apply_changes(base,[row],_path_copy=private)
        errors.append(str(caught.value));assert base==old
    assert errors[0]==errors[1]


def test_late_before_mismatch_preserves_parent_after_an_earlier_valid_edit():
    base=design();old=deepcopy(base)
    with pytest.raises(ValueError,match='이전 값'):
        H.apply_changes(base,[change(['parts',0,'name'],'A','Changed'),
            change(['parts',0,'transform','z'],99.,2.)],_path_copy=True)
    assert base==old


def test_after_allocation_failure_preserves_parent(monkeypatch):
    base=design();old=deepcopy(base)
    row=change(['parts',0,'geometry'],base['parts'][0]['geometry'],{'kind':'plate','hole_count':0})
    original=H.deepcopy
    def fail(value):
        if value is row.after:raise MemoryError('Injected changed payload allocation')
        return original(value)
    monkeypatch.setattr(H,'deepcopy',fail)
    with pytest.raises(MemoryError,match='changed payload'):
        H.apply_changes(base,[row],_path_copy=True)
    assert base==old


def test_fork_and_selected_ancestor_survive_all_past_state_validation_and_roundtrip(monkeypatch):
    base=design();selected=deepcopy(base);selected['parts'][0]['transform']['z']=1.
    rows=[entry('root',None),entry('one','root',[change(['parts',0,'transform','z'],0.,1.)]),
        entry('sibling','one',[change(['parts',1,'transform','z'],0.,2.)]),
        entry('head','one',[change(['parts',0,'transform','z'],1.,3.)])]
    raw=project(base,selected,rows,'one','head');before=deepcopy(raw)
    validate=Design.model_validate;calls=[]
    def counted(cls,value,*args,**kwargs):
        calls.append(value)
        return validate(value,*args,**kwargs)
    monkeypatch.setattr(Design,'model_validate',classmethod(counted))
    checked=Project.model_validate(raw)
    assert len(calls)==3 and checked.design.parts[0].transform.z==1.
    assert raw==before
    again=Project.model_validate_json(checked.model_dump_json())
    assert again==checked and len(calls)==6
    assert not any(name in sys.modules for name in ('PySide6','vtkmodules','OCP','cadquery'))


def test_invalid_intermediate_cannot_hide_behind_valid_final_shape():
    base=design()
    rows=[entry('root',None),entry('bad','root',[change(['parts',0,'geometry','width'],60.,-1.)]),
        entry('fixed','bad',[change(['parts',0,'geometry','width'],-1.,60.)])]
    raw=project(base,base,rows,'fixed','fixed');old=deepcopy(raw)
    with pytest.raises(ValueError):Project.model_validate(raw)
    assert raw==old


def test_parameter_normalization_difference_is_still_rejected_without_mutating_input():
    base=Design.model_validate({**design(),'parameters':{'w':'10'},
        'dimension_bindings':[dict(path=['parts',0,'geometry','width'],expression='w')]}).model_dump()
    rows=[entry('root',None),entry('bad','root',[change(['parts',0,'geometry','width'],10.,11.)]),
        entry('fixed','bad',[change(['parts',0,'geometry','width'],11.,10.)])]
    raw=project(base,base,rows,'fixed','fixed');old=deepcopy(raw)
    with pytest.raises(ValueError,match='해석 결과와 다른'):Project.model_validate(raw)
    assert raw==old


def test_malformed_parent_and_current_geometry_guards_still_reject():
    base=design();changed=deepcopy(base);changed['name']='Unrecorded current'
    rows=[entry('root',None),entry('one','root',[change(['name'],base['name'],'Recorded')])]
    with pytest.raises(ValueError,match='현재 단계와 프로젝트'):Project.model_validate(project(base,changed,rows,'one','one'))
    rows[1]['parent']='absent'
    with pytest.raises(ValueError,match='이전에 존재하지 않는 단계'):Project.model_validate(project(base,base,rows,'root','one'))
