from copy import deepcopy
import json
import math

import httpx
import pytest

from cadstudio.kernel import build, exact_bounds
from cadstudio.models import Design, DraftRequest
from cadstudio.native.cad_tools import context, messages
from cadstudio.native.cad_scope import scope_messages
from cadstudio.native.document import Document
from test_cad_tools import execute, create, action


def hole(**kwargs):
    return execute(create(), action('hole', face='+Z', diameter=8, **kwargs)).design


def edit(current, **fields):
    return execute(action('edit_feature', feature_id='ai-feature-1', **fields), current=current)


@pytest.mark.parametrize('diameter', [4, 12])
def test_existing_hole_can_shrink_and_enlarge_preserving_references_and_history(diameter):
    current = hole(); before = current.model_dump()
    reply = edit(current, diameter=diameter)
    assert current.model_dump() == before
    p = reply.design.parts[0]; f = p.features[0]
    assert len(p.features) == 1 and f.id == 'ai-feature-1'
    assert f.reference == current.parts[0].features[0].reference
    assert build(reply.design)[0].Volume() == pytest.approx(80*50*25-math.pi*(diameter/2)**2*25)
    doc = Document(); doc.commit(current, 'base')
    doc.commit(reply.design, 'AI edit', dict(journal_steps=reply.journal_steps))
    assert doc.journal.path()[-1]['context']['tool_actions'][0]['tool'] == 'edit_feature'
    assert len(reply.journal_steps) == 1


def test_hole_blind_depth_and_counterbore_are_real_cuts():
    current = hole()
    reply = edit(current, through_all=False, depth=7, diameter=6,
                 hole_finish='counterbore', head_diameter=12, head_depth=2)
    assert build(reply.design)[0].Volume() == pytest.approx(100000-math.pi*9*7-math.pi*(36-9)*2)
    assert not reply.design.parts[0].features[0].through_all
    with pytest.raises(ValueError, match='관통'):
        edit(current, depth=7)


def test_multiple_circles_require_explicit_entity_id():
    current = hole(centers=[[-20,0],[20,0]])
    with pytest.raises(ValueError, match='entity_id'): edit(current, diameter=4)
    reply = edit(current, entity_id='hole-0', diameter=4)
    assert [e.radius for e in reply.design.parts[0].features[0].sketch.entities] == [2,4]
    assert build(reply.design)[0].Volume() == pytest.approx(100000-math.pi*(4+16)*25)


def test_pad_depth_and_suppression_rebuild_original_feature():
    current = execute(create(), action('pad', face='+Z', depth=10, profile={'circle':{'diameter':20}})).design
    changed = edit(current, depth=20).design
    assert exact_bounds(build(changed)[0]).zlen == pytest.approx(45)
    disabled = edit(changed, suppressed=True).design
    assert build(disabled)[0].Volume() == pytest.approx(100000)
    enabled = edit(disabled, suppressed=False).design
    assert build(enabled)[0].Volume() == pytest.approx(100000+math.pi*100*20)


@pytest.mark.parametrize('tool,first,second', [('fillet',1,2), ('chamfer',1,2), ('shell',2,3)])
def test_edit_finishing_operations_changes_actual_shape(tool, first, second):
    args = dict(thickness=first,open_faces=['+Z']) if tool=='shell' else dict(size=first,edges='+Z')
    current = execute(create(), action(tool, **args)).design
    changed = edit(current, size=second).design
    shape = build(changed)[0]
    assert shape.isValid() and shape.Volume() != pytest.approx(build(current)[0].Volume())
    if tool=='shell':
        assert shape.Volume() == pytest.approx(100000-74*44*22)


def test_pattern_edit_preserves_support_and_changes_number_of_solids():
    current = execute(create(), action('solid',operation='linear_pattern',count=2,spacing=[100,0,0])).design
    changed = edit(current,count=3).design
    assert len(build(changed)[0].Solids())==3
    assert build(changed)[0].Volume()==pytest.approx(300000)


def test_thread_pitch_length_and_handedness_edit_retains_selected_cylinder():
    current=execute(create('cylinder',diameter=12,height=20,bore_diameter=0),
                    action('thread',diameter=12,pitch=2,length=6)).design
    changed=edit(current,pitch=1.5,length=4.5,handedness='left').design
    assert changed.parts[0].features[0].cylinder==current.parts[0].features[0].cylinder
    assert changed.parts[0].features[0].handedness=='left'
    assert build(changed)[0].isValid()
    assert build(changed)[0].Volume()!=pytest.approx(build(current)[0].Volume())


def test_feature_edit_keeps_downstream_finishing_and_assembly():
    current=execute(create(),action('hole',face='+Z',diameter=8),
        action('chamfer',edges='-Z',size=.5),create('cylinder',target='pin',diameter=4,height=15,bore_diameter=0),
        action('joint','hinge',kind='revolute',parent='part',child='pin')).design
    before=current.model_dump()
    changed=edit(current,diameter=6).design
    assert changed.mates==current.mates and len(changed.parts[0].features)==2
    assert changed.parts[0].features[1]==current.parts[0].features[1]
    assert all(s.isValid() for s in build(changed))
    assert current.model_dump()==before


@pytest.mark.parametrize('path', [
    ['parts','part','features','ai-feature-1','sketch','entities','hole-0','radius'],
    ['parts',0,'features',0,'sketch','entities',0,'radius']])
def test_id_and_index_dimension_bindings_cannot_be_silently_overridden(path):
    raw=hole().model_dump(); raw['parameters']={'r':'4'}
    raw['dimension_bindings']=[dict(path=path,expression='r')]
    current=Design.model_validate(raw);before=current.model_dump()
    with pytest.raises(ValueError,match='parameter'): edit(current,diameter=12)
    assert current.model_dump()==before


def test_base_dimension_binding_using_indices_is_not_overwritten():
    raw=execute(create()).design.model_dump();raw['parameters']={'h':'25'}
    raw['dimension_bindings']=[dict(path=['parts',0,'geometry','thickness'],expression='h')]
    current=Design.model_validate(raw)
    with pytest.raises(ValueError,match='parameter'):
        execute(action('dimensions',values={'thickness':30}),current=current)


@pytest.mark.parametrize('kind,value', [('radius',4),('diameter',8)])
def test_driving_circle_dimension_is_updated_with_geometry(kind,value):
    raw=hole().model_dump(); sketch=raw['parts'][0]['features'][0]['sketch']
    sketch['entity_constraints']=[dict(id='d',kind=kind,a='hole-0',value=value),
                                 dict(id='center',kind='fixed',a='hole-0',a_point='center',x=0,y=0)]
    changed=edit(Design.model_validate(raw),diameter=12).design
    assert changed.parts[0].features[0].sketch.entities[0].radius==pytest.approx(6)
    assert changed.parts[0].features[0].sketch.entity_constraints[0].value==pytest.approx(6 if kind=='radius' else 12)
    assert build(changed)[0].Volume()==pytest.approx(100000-math.pi*36*25)


def test_expression_and_fixed_circle_are_not_discarded():
    raw=hole().model_dump(); raw['parameters']={'r':'4'}
    sketch=raw['parts'][0]['features'][0]['sketch']
    sketch['entity_constraints']=[dict(id='d',kind='radius',a='hole-0',value=4,expression='r')]
    with pytest.raises(ValueError,match='구속'): edit(Design.model_validate(raw),diameter=12)
    sketch['entity_constraints']=[dict(id='f',kind='fixed',a='hole-0',a_point='all',reference=[0,0,4])]
    with pytest.raises(ValueError,match='구속'): edit(Design.model_validate(raw),diameter=12)


def test_linked_profile_radius_blocked_but_extrusion_depth_independent():
    raw=hole(through_all=False,depth=10).model_dump(); f=raw['parts'][0]['features'][0]
    raw['sketches']=[dict(id='source',name='source sketch',geometry=deepcopy(f['sketch']))]
    f['sketch_id']='source'; current=Design.model_validate(raw)
    with pytest.raises(ValueError,match='원본 스케치'): edit(current,diameter=12)
    changed=edit(current,depth=15).design
    assert changed.parts[0].features[0].sketch_id=='source'
    assert build(changed)[0].Volume()==pytest.approx(100000-math.pi*16*15)


@pytest.mark.parametrize('fields', [dict(diameter=-1),dict(diameter=True),dict(depth='5'),
    dict(size=2),dict(operation='add'),dict(face=3),dict(suppressed='false'),dict(diameter=float('nan')),
    dict(head_depth=4),dict(through_all=True,reverse_depth=2),dict(diameter=2000)])
def test_invalid_or_inactive_edits_fail_without_mutating_document(fields):
    current=hole();before=current.model_dump()
    with pytest.raises(ValueError): edit(current,**fields)
    assert current.model_dump()==before


def test_context_exposes_dimensions_and_selected_feature_to_both_stages():
    current=hole();request=DraftRequest(prompt='이 구멍을 6mm로',current=current,selected_part='part',selected_feature='ai-feature-1')
    feature=context(current)['parts'][0]['features'][0]
    assert feature['circles']==[dict(id='hole-0',diameter=8,center={'x':0,'y':0})]
    assert feature['dimensions']['through_all'] is True and 'diameter' in feature['editable']
    assert not {'reference','edges'} & set(feature)
    for produce in (messages,scope_messages):
        assert json.loads(produce(request)[1]['content'])['selected_feature']=='ai-feature-1'


@pytest.mark.parametrize('provider', ['ollama','openai'])
def test_both_providers_plan_existing_feature_edit_via_real_kernel(provider):
    from cadstudio.native.local_ai import ollama_draft
    from cadstudio.native.cloud_ai import generate
    from test_cloud_planner import answer
    current=hole();calls=[]
    scope=dict(intent='edit',tools=['edit_feature'],shapes=[],new_parts=[],connections=[])
    plan=dict(summary='구멍 지름 수정',actions=[action('edit_feature',feature_id='ai-feature-1',diameter=6)])
    def handle(request):
        calls.append(json.loads(request.content)); data=scope if len(calls)==1 else plan
        return answer(data) if provider=='openai' else httpx.Response(200,json={'done':True,'message':{'content':json.dumps(data)}})
    request=DraftRequest(prompt='구멍 지름을 6mm로 줄여줘',current=current)
    kwargs=dict(transport=httpx.MockTransport(handle),deadline=None)
    reply=generate(request,'gpt-6-astra',api_key='test-placeholder',**kwargs) if provider=='openai' else ollama_draft(request,'test',**kwargs)
    assert len(calls)==2 and reply['tool_actions'][0]['tool']=='edit_feature'
    assert len(reply['design']['parts'][0]['features'])==1
    assert build(Design.model_validate(reply['design']))[0].Volume()==pytest.approx(100000-math.pi*9*25)
