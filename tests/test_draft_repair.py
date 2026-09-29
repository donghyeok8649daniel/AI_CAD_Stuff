import json
import asyncio
from copy import deepcopy
import pytest

from cadstudio.models import Design, DraftRequest
from cadstudio.kernel import build, preview
from cadstudio.interference import validate_candidate
from cadstudio.native.codex_ai import generate
from cadstudio.native.cad_scope import Scope
from cadstudio.native.cad_tools import execute_plan
from cadstudio.native.draft_repair import DraftRepair
from test_codex_planner import Session
from test_cloud_planner import scope


def fixture_plan(clear=False):
    actions=[dict(tool='create',target='frame',args=dict(name='클램프 프레임',color='#ffffff',geometry=dict(kind='plate',length=30,width=20,thickness=10,hole_count=0))),
             dict(tool='create',target='guide_rail',args=dict(name='시편',color='#bbbbbb',geometry=dict(kind='plate',length=60,width=4,thickness=2,hole_count=0),transform=dict(z=6)))]
    if clear:actions.append(dict(tool='pocket',target='frame',args=dict(face='+Z',profile=dict(rectangle=dict(width=31,height=4.4)),depth=4.2)))
    return dict(name='시편 클램프',summary='시편 유지, 프레임에 여유 홈',actions=actions)


def selected_scope():return scope(intent='assembly',tools=('create',),shapes=('plate',),new_parts=('frame','guide_rail'))


def request():return DraftRequest(prompt='흰 프레임에 길이60 폭4 두께2 시편을 끼울 홈을 만들고 시편 치수를 유지해')


def test_repair_expands_cut_schema_and_uses_measured_local_intersections():
    session=Session([selected_scope(),fixture_plan(),fixture_plan(True)]);schemas=[]
    original=session.content
    async def content(model,messages,schema,effort,progress):
        schemas.append(deepcopy(schema));return await original(model,messages,schema,effort,progress)
    session.content=content
    result=generate(request(),'gpt-6-astra',session_factory=lambda _:session)
    assert result['validation']['status']=='ready' and result['attempts']==2
    assert 'pocket' not in json.dumps(schemas[1]) and 'pocket' in json.dumps(schemas[2])
    feedback=session.calls[2][-1]['content']
    assert 'overlap_local_mm' in feedback and '"z":[6.0,8.0]' in feedback
    assert '"z":[0.0,2.0]' in feedback
    design=Design.model_validate(result['design']);validate_candidate(design)
    assert len(design.parts)==2 and design.parts[1].geometry.thickness==2
    assert design.parts[0].color=='#ffffff' and design.parts[0].features


def test_pending_survives_later_invalid_plans_and_resume_replays_original():
    bad=fixture_plan();invalid={'summary':'invalid','actions':[]}
    session=Session([selected_scope(),bad,*[invalid]*5])
    req=request();before=req.model_dump()
    pending=generate(req,'gpt-6-astra',session_factory=lambda _:session)
    assert req.model_dump()==before and pending['validation']['status']=='needs_repair'
    assert pending['validation']['collisions'][0]['volume']==pytest.approx(240)
    assert 'Last attempted correction was invalid' in session.calls[-1][-1]['content']
    resumed=Session([fixture_plan(True)])
    ready=generate(req,'gpt-6-astra',repair=pending['repair'],session_factory=lambda _:resumed)
    assert ready['validation']['status']=='ready' and len(resumed.calls)==1
    assert 'overlap_local_mm' in resumed.calls[0][-1]['content']
    assert len(ready['design']['parts'])==2 and len(ready['journal_steps'])==3
    altered=req.model_copy(update={'prompt':'changed'})
    with pytest.raises(ValueError,match='원본 설계나 요청'):
        generate(altered,'gpt-6-astra',repair=pending['repair'],session_factory=lambda _:Session([]))


def test_rotated_overlap_reports_true_local_coordinates_and_keeps_contract():
    raw=fixture_plan()
    for action in raw['actions']:
        t=action['args'].setdefault('transform',{});t.update(x=50,y=30,rz=90)
    req=request();selected=Scope.parse(json.dumps(selected_scope()),req)
    state=DraftRepair(req);result=execute_plan(json.dumps(raw),req)
    with pytest.raises(ValueError,match='overlap_local_mm'):state.check(result,preview(result.design),json.dumps(raw),selected)
    feedback=state.best['feedback'];assert '"x":[-15.0,15.0]' in feedback
    assert set(state.best['scope']['new_parts'])=={'frame','guide_rail'}
    assert len(result.design.parts)==2


def test_review_does_not_turn_grouping_into_permission_to_apply():
    req=request();selected=Scope.parse(json.dumps(selected_scope()),req);result=execute_plan(json.dumps(fixture_plan()),req)
    data=result.design.model_dump();data['part_groups']=[dict(id='combined',name='group',part_ids=['frame','guide_rail'])]
    result.design=Design.model_validate(data)
    state=DraftRepair(req)
    with pytest.raises(ValueError,match='간섭'):state.check(result,preview(result.design),'{}',selected)
    assert state.best['result']['validation']['status']=='needs_repair'


def test_timeout_keeps_renderable_candidate_but_cancel_stays_cancel():
    from cadstudio.native.local_ai import DraftControl,DraftCancelled
    req=request();session=Session([selected_scope(),fixture_plan()]);content=session.content
    async def stall(*args):
        if not session.replies:await asyncio.sleep(60)
        return await content(*args)
    session.content=stall
    pending=generate(req,'gpt-6-astra',deadline=2,session_factory=lambda _:session)
    assert pending['validation']['status']=='needs_repair' and session.closed
    assert pending['repair']['plan']
    control=DraftControl();session2=Session([selected_scope(),fixture_plan()]);content2=session2.content
    async def cancel(*args):
        if not session2.replies:control.cancel();control.check()
        return await content2(*args)
    session2.content=cancel
    with pytest.raises(DraftCancelled):generate(req,'gpt-6-astra',control=control,session_factory=lambda _:session2)
    assert session2.closed


def test_existing_specimen_context_exposes_centered_thickness_and_full_action_budget():
    from cadstudio.catalog import preset
    from cadstudio.native.cad_tools import context,CADPlan
    from cadstudio.native.cad_schema import plan_schema
    current=preset('flat_specimen');before=current.model_dump()
    assert context(current)['parts'][0]['local_bounds_mm']['z']==[-1.5,1.5]
    assert current.model_dump()==before
    assert plan_schema()['properties']['actions']['maxItems']==64


def test_pending_preview_and_direct_apply_are_blocked(app,monkeypatch,tmp_path):
    from cadstudio.native import window
    from cadstudio.native.model_picker import LocalModelPicker
    from cadstudio.native.draft_preview import DraftPreviewDialog
    from cadstudio.native.draft_summary import draft_summary
    monkeypatch.setattr(window,'DATA_DIR',tmp_path)
    monkeypatch.setattr(LocalModelPicker,'refresh',lambda _:None)
    pending=generate(request(),'gpt-6-astra',session_factory=lambda _:Session([selected_scope()]+[fixture_plan()]*6))
    result=preview(Design.model_validate(pending['design']))
    w=window.MainWindow();w.show();before=deepcopy(w.document.design);task=object();w.ai_task=task
    packet=dict(response=pending,design=pending['design'],preview=result,serial=w.operation_serial,provider='codex',prompt=request().prompt,request=request().model_dump())
    try:
        w.ai_complete((task,packet));app.processEvents()
        assert w.last_draft is packet and w.accept_draft.isEnabled() and '✓' in w.codex_status.text()
        w.apply_draft();assert w.document.design==before and not w.busy
        dialog=DraftPreviewDialog(w,None,result,draft_summary(pending,result),validation=pending['validation'],repairable=True);dialog.show();app.processEvents()
        assert dialog.repair_button.isVisible() and not dialog.apply_button.isEnabled()
        dialog.accept();assert dialog.isVisible()
        dialog.issues.setCurrentIndex(1);app.processEvents();assert set(dialog.viewport.selected_ids)=={'frame','guide_rail'}
        dialog.mode.setCurrentIndex(1);app.processEvents();assert not dialog.viewport.selected_ids
        dialog.repair_button.click();assert dialog.result()==2
        assert w.document.design==before
        w.ai_retained_draft=packet;w.ai_task=object();w.ai_failed((w.ai_task,'connection dropped'))
        assert w.last_draft is packet and w.accept_draft.isEnabled()
    finally:w.document.dirty=False;w.close();app.processEvents()


from test_placement_native import app
