"""BOM requirements reach actual tools, persisted history and measured review."""
from copy import deepcopy
import json

import pytest

from cadstudio.bom_design import parse_bom_text, reconcile_bom
from cadstudio.kernel import preview
from cadstudio.models import Design, DraftRequest, Part
from cadstudio.native.cad_tools import execute_plan, messages
from cadstudio.native.cad_scope import Scope, scope_messages
from cadstudio.native.cad_schema import plan_schema
from cadstudio.native.document import Document, read_project
from cadstudio.native.draft_repair import DraftRepair, review_candidate
from cadstudio.native.draft_summary import draft_summary


def requirement(quantity=2):
    return parse_bom_text(f'부품명,수량,단위,길이(mm),너비(mm),두께(mm),역할\n지지판,{quantity},ea,80,60,4,구조\n')


def request(quantity=2):
    bom=requirement(quantity)
    return DraftRequest(prompt='부품표대로 조립용 부품을 만들어줘',current=Design(bom=bom),bom=bom)


def plan(req,count=2,length=80):
    actions=[]
    for i in range(count):
        actions += [dict(tool='create',target=f'plate_{i}',args=dict(name='지지판',role='structure',
            geometry=dict(kind='plate',length=length,width=60,thickness=4,hole_count=0),transform=dict(x=i*100))),
            dict(tool='bom_bind',target=f'plate_{i}',args=dict(item_id=req.bom.items[0].id))]
    return json.dumps(dict(summary='BOM 판재 설계',actions=actions))


def test_legacy_absent_defaults_keep_serialized_history_identity():
    design=Design(parts=[dict(id='old',name='old',geometry=dict(kind='plate',length=20,width=10,thickness=2,hole_count=0))])
    assert 'bom' not in design.model_dump()
    assert 'bom' not in design.parts[0].model_dump()
    assert 'bom' not in DraftRequest(prompt='test',current=design).model_dump()


def test_bom_two_instances_tools_actual_geometry_and_portable_history(tmp_path):
    req=request();before=req.current.model_dump();reply=execute_plan(plan(req),req)
    assert req.current.model_dump()==before
    assert len(reply.design.parts)==2
    assert reconcile_bom(reply.design).all_matched
    actual=preview(reply.design)
    review=review_candidate(reply.design,req.current,actual,bom=req.bom)
    assert review['status']=='ready' and review['bom']['all_matched']
    doc=Document();doc.commit(req.current,'BOM import')
    doc.commit(reply.design,'BOM plan',dict(journal_base=reply.journal_base,journal_steps=reply.journal_steps))
    assert doc.design==reply.design.model_dump()
    path=tmp_path/'assembly.cad.json';doc.write(path)
    loaded=read_project(path)
    assert loaded.design.bom.source_sha256==req.bom.source_sha256
    assert loaded.design.parts[1].bom.item_id==req.bom.items[0].id
    entries=doc.journal.data['entries'];prior=entries[-2]['id'];head=entries[-1]['id']
    doc.commit(doc.journal.at(prior),'Undo',cursor=prior)
    assert len(doc.design['parts'])==2 and 'bom' not in doc.design['parts'][1]
    doc.commit(doc.journal.at(head),'Redo',cursor=head)
    assert reconcile_bom(doc.design).all_matched


@pytest.mark.parametrize('count,length',[(1,80),(2,79)])
def test_quantity_and_actual_dimension_mismatch_blocks_apply(count,length):
    req=request();reply=execute_plan(plan(req,count,length),req);actual=preview(reply.design)
    review=review_candidate(reply.design,req.current,actual,bom=req.bom)
    assert review['status']=='needs_repair'
    assert review['bom']['items'][0]['status']=='mismatch'
    assert not review['collisions']
    assert 'BOM' in draft_summary(dict(summary='test',validation=review),actual)


def test_request_bom_cannot_replace_saved_authoritative_inputs():
    req=request();other=requirement(1);req.bom=other
    with pytest.raises(ValueError,match='먼저 저장'):execute_plan(plan(req),req)


def test_candidate_cannot_drop_or_alter_bom_to_bypass_review():
    req=request();reply=execute_plan(plan(req),req);raw=reply.design.model_dump();raw.pop('bom')
    candidate=Design.model_validate(raw)
    review=review_candidate(candidate,req.current,preview(candidate),bom=req.bom)
    assert review['status']=='needs_repair'
    assert any('원본 BOM' in message for message in review['issues'])


def test_binding_two_parts_never_replaces_first_instance_or_uses_quantity_metadata():
    req=request();reply=execute_plan(plan(req),req)
    assert all(part.bom for part in reply.design.parts)
    duplicate=reply.design.model_dump();duplicate['parts'][1].pop('bom')
    report=reconcile_bom(duplicate)
    assert report.items[0].actual_quantity==1


def test_scope_and_strict_grammar_allow_explicit_bom_instance_bindings():
    req=request()
    selected=Scope.parse(json.dumps(dict(intent='assembly',tools=['create'],shapes=['plate'],new_parts=['a','b'])),req)
    assert 'bom_bind' in selected.tools
    schema=plan_schema(selected.tools,selected.shapes,new_parts=selected.new_parts)
    binding=next(a for a in schema['properties']['actions']['items']['anyOf'] if a['properties']['tool'].get('const')=='bom_bind')
    assert binding['properties']['args']['required']==['item_id']
    for payload in [messages(req),scope_messages(req),selected.plan_messages(req)]:
        data=json.loads(payload[1]['content'])
        assert req.bom.source_sha256 in data['bom_reference']
        assert req.bom.items[0].id in data['current_design']['bom_reference']


def test_repair_feedback_retains_renderable_bom_mismatch_and_exact_rows():
    req=request();reply=execute_plan(plan(req,count=1),req);repair=DraftRepair(req);actual=preview(reply.design)
    selected=Scope(tools=('create','bom_bind'),shapes=('plate',),intent='assembly',new_parts=('plate_0',))
    with pytest.raises(ValueError,match='BOM reconciliation'):
        repair.check(reply,actual,plan(req,count=1),selected,provider='codex',attempts=1)
    pending=repair.pending('codex',1)
    assert pending['validation']['status']=='needs_repair'
    assert pending['repair']['request_fingerprint']
    assert req.bom.items[0].id in pending['repair']['feedback']


def test_unknown_bom_dimensions_remain_explicit_pending_not_fabricated():
    bom=parse_bom_text('부품명,수량,단위\n빈 스펙 판재,1,ea\n')
    req=DraftRequest(prompt='개념 판재',current=Design(bom=bom),bom=bom)
    candidate=execute_plan(plan(req,1),req)
    review=review_candidate(candidate.design,req.current,preview(candidate.design),bom=bom)
    assert not review['bom']['all_matched']
    assert review['pending_checks']
    assert review['status']=='ready'  # valid concept may be applied; missing specs stay pending


def test_source_cli_registration_refuses_non_native_execution_without_qt(monkeypatch,tmp_path):
    import native_desktop
    monkeypatch.setattr(native_desktop.sys,'argv',['native_desktop.py','--register-cad-files','--registration-report',str(tmp_path/'report.json')])
    monkeypatch.delattr(native_desktop.sys,'frozen',raising=False)
    assert native_desktop.main()==2
    report=json.loads((tmp_path/'report.json').read_text(encoding='utf-8'))
    assert report['success'] is False and 'EXE' in report['error']
