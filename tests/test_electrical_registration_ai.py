"""Offline provider/tool flow: register actual CAD bodies and wire exact pins."""
from copy import deepcopy
import json

import httpx
import pytest

from cadstudio.models import Design,Part,DraftRequest,PartGroup
from cadstudio.native.cad_scope import Scope
from cadstudio.native.cad_schema import plan_schema
from cadstudio.native.cad_tools import context,execute_plan
from cadstudio.electrical_registration import register_part,registration_for_part
from cadstudio.native.document import Document,read_project


def bodies():
    return Design(parts=[Part(id='controller',name='Controller CAD',color='#112233',
                              geometry=dict(kind='plate',length=80,width=50,thickness=3,hole_count=0)),
                         Part(id='sensor',name='Sensor CAD',color='#445566',transform=dict(x=100),
                              geometry=dict(kind='plate',length=15,width=10,thickness=2,hole_count=0))],
                  part_groups=[PartGroup(id='group',name='Assembly',part_ids=['controller','sensor'])])


def actions():
    return [dict(tool='electrical_register',target='controller',args=dict(catalog_id='rpi4b')),
            dict(tool='electrical_register',target='sensor',args=dict(catalog_id='ams_as5600_asot',kind='load')),
            dict(tool='electrical_connect',target='controller',args=dict(pin='GPIO17',target_part_id='sensor',target_terminal='port:OUT'))]


def plan(sequence=None):return json.dumps(dict(summary='Register CAD electrical features',actions=sequence or actions()))


def test_register_and_pin_connect_preserve_geometry_colors_groups_and_original():
    current=bodies();before=deepcopy(current.model_dump())
    result=execute_plan(plan(),DraftRequest(prompt='보드와 센서를 실제 제품으로 등록하고 GPIO17 OUT 연결',current=current))
    assert current.model_dump()==before
    for old,new in zip(current.parts,result.design.parts):
        assert old.geometry==new.geometry and old.transform==new.transform
        assert old.color==new.color and new.role=='electrical'
        assert old.features==new.features  # Electrical feature is outside manufacturing history.
    assert result.design.part_groups==current.part_groups
    controller=registration_for_part(result.design,'controller');sensor=registration_for_part(result.design,'sensor')
    assert controller.signal_pins['GPIO17']==sensor.terminal_pins['OUT']
    assert not controller.analysis_enabled and not sensor.analysis_enabled
    assert controller.rated_current_a==sensor.rated_current_a==0
    assert len(result.tool_actions)==3 and all(a['validated'] for a in result.tool_actions)


def test_plan_schema_limits_registration_targets_and_exact_connect_args():
    selected=('electrical_register','electrical_connect','electrical_unregister')
    schema=plan_schema(selected,existing_parts=['controller','sensor'])
    choices={a['properties']['tool']['const']:a for a in schema['properties']['actions']['items']['anyOf']}
    assert set(choices)==set(selected)
    assert choices['electrical_register']['properties']['target']['enum']==['controller','sensor']
    assert 'analysis_enabled' in choices['electrical_register']['properties']['args']['properties']
    assert set(choices['electrical_connect']['properties']['args']['required'])=={'pin','target_part_id','target_terminal'}
    assert choices['electrical_unregister']['properties']['args']['additionalProperties'] is False


def test_registration_keeps_general_local_plan_within_existing_context_budget():
    broad=plan_schema()
    assert len(json.dumps(broad))<22000
    request=DraftRequest(prompt='register existing CAD body',current=bodies())
    # Compact fallback output still uses the full runtime registration checks.
    with pytest.raises(ValueError):
        execute_plan(plan([dict(tool='electrical_register',target='controller',
                               args=dict(catalog_id='rpi4b',rated_current_a=-1))]),request)
    exact=plan_schema(['electrical_register'],existing_parts=['controller'])
    args=exact['properties']['actions']['items']['anyOf'][0]['properties']['args']
    assert args['properties']['terminal_pins']['items']['required']==['pin','node']
    assert args['properties']['rated_current_a']['anyOf'][0]['minimum']==0


@pytest.mark.parametrize('bad',[
    dict(tool='electrical_register',target='missing',args=dict(catalog_id='rpi4b')),
    dict(tool='electrical_register',target='controller',args=dict(catalog_id='fake_board_model')),
    dict(tool='electrical_connect',target='controller',args=dict(pin='3V3',target_part_id='sensor',target_terminal='port:OUT')),
    dict(tool='electrical_connect',target='controller',args=dict(pin='GPIO17',target_part_id='sensor',target_terminal='port:MADE_UP')),
])
def test_bad_body_model_or_pin_has_no_partial_application(bad):
    old=bodies();before=old.model_dump()
    with pytest.raises(ValueError):execute_plan(plan(actions()[:2]+[bad]),DraftRequest(prompt='register',current=old))
    assert old.model_dump()==before


def test_current_ai_context_contains_product_identity_real_pin_labels_and_pending_state():
    old=register_part(bodies(),'controller',dict(catalog_id='rpi4b'))
    data=context(old);feature=data['registered_electrical_features'][0]
    assert feature['part_id']=='controller' and feature['catalog_id']=='rpi4b'
    assert not feature['analysis_enabled'] and feature['source_url'].startswith('https://')
    pin=next(p for p in feature['pins'] if p['key']=='GPIO18')
    assert '12' in pin['label'] and 'GPIO18' in pin['label']
    request=DraftRequest(prompt='이 CAD 부품에 라즈베리파이4 모델을 등록',current=old)
    scope=Scope.parse(json.dumps(dict(intent='edit',tools=['electrical_register'],shapes=[],new_parts=[],connections=[])),request)
    scoped_messages=scope.plan_messages(request)
    assert 'cylinder:' not in scoped_messages[0]['content'] and 'SHAPES for create' not in scoped_messages[0]['content']
    payload=json.loads(scoped_messages[1]['content'])
    assert any(m['id']=='rpi4b' for m in payload['available_electrical_models'])
    assert any(m['id']=='ams_as5600_asot' and m['diagram']=='verified_terminals' for m in payload['available_electrical_models'])


def test_mocked_ollama_registration_and_wiring_draft_uses_existing_parts():
    from ai_transport import is_scope
    from cadstudio.native.local_ai import ollama_draft
    calls=[]
    def handler(request):
        body=json.loads(request.content);calls.append(body)
        response=dict(intent='edit',tools=['electrical_register','electrical_connect'],shapes=[],new_parts=[],connections=[]) if is_scope(request) else json.loads(plan())
        return httpx.Response(200,json=dict(done=True,message=dict(content=json.dumps(response))))
    result=ollama_draft(DraftRequest(prompt='controller를 Pi4, sensor를 AS5600-ASOT로 등록하고 GPIO17→OUT 연결',current=bodies()),
                        'mock-model',httpx.MockTransport(handler),deadline=15)
    assert len(calls)==2 and len(result['design']['parts'])==2
    assert len(result['design']['electrical']['components'])==2
    assert result['tool_actions'][-1]['tool']=='electrical_connect'


def test_registration_feature_roundtrip_and_each_ai_step_undo(tmp_path):
    current=bodies();doc=Document();doc.commit(current,'Bodies')
    reply=execute_plan(plan(),DraftRequest(prompt='register and wire',current=current))
    doc.commit(reply.design,'AI electrical features',dict(source='local',tool_actions=reply.tool_actions,journal_steps=reply.journal_steps))
    file=tmp_path/'electrical.cad.json';doc.write(file);restored=read_project(file)
    assert registration_for_part(restored.design,'sensor').terminal_pins['OUT']
    assert len(doc.journal.path())==4
    before_connection=doc.journal.path()[-2]['id']
    assert not registration_for_part(doc.journal.at(before_connection),'controller').signal_pins
    original=doc.journal.path()[0]['id']
    assert registration_for_part(doc.journal.at(original),'controller') is None


def test_unregister_keeps_body_and_other_registered_devices():
    made=execute_plan(plan(),DraftRequest(prompt='register',current=bodies())).design
    reply=execute_plan(plan([dict(tool='electrical_unregister',target='sensor',args={})]),DraftRequest(prompt='센서 전장 등록만 해제',current=made))
    assert len(reply.design.parts)==2 and registration_for_part(reply.design,'sensor') is None
    assert registration_for_part(reply.design,'controller').signal_pins['GPIO17']


def test_new_body_may_be_registered_in_single_part_plan():
    payload=dict(summary='One board body with electrical identity',base=dict(tool='create',target='controller',args=dict(name='Board envelope',geometry=dict(kind='plate',length=80,width=50,thickness=2,hole_count=0))),
                 actions=[dict(tool='electrical_register',target='controller',args=dict(catalog_id='rpi4b'))])
    reply=execute_plan(json.dumps(payload),DraftRequest(prompt='보드 형상 만들고 실제 Pi4 모델 연결'),single_part=True)
    assert len(reply.design.parts)==1 and registration_for_part(reply.design,'controller').catalog_id=='rpi4b'


def test_codex_subscription_offline_registration_and_connection_flow():
    from test_codex_planner import Session
    from cadstudio.native.codex_ai import generate
    selected=dict(intent='edit',tools=['electrical_register','electrical_connect'],shapes=[],new_parts=[],connections=[])
    session=Session([selected,json.loads(plan())]);old=bodies()
    result=generate(DraftRequest(prompt='현재 CAD 부품에 MCU 센서 모델과 핀 연결',current=old),
                    'gpt-6-astra',session_factory=lambda _:session,deadline=15)
    assert result['provider']=='codex' and session.closed and len(session.calls)==2
    assert len(result['design']['parts'])==2 and len(result['design']['electrical']['components'])==2
    assert not old.electrical


def test_strict_provider_schema_keeps_named_terminal_mapping_as_rows():
    from cadstudio.native.cloud_ai import response_schema,decode_plan
    schema=response_schema(plan_schema(['electrical_register'],existing_parts=['controller']))
    register=schema['properties']['actions']['items']['anyOf'][0]
    terminals=register['properties']['args']['properties']['terminal_pins']['anyOf'][0]
    assert terminals['type']=='array' and set(terminals['items']['required'])=={'pin','node'}
    sequence=[dict(tool='electrical_register',target='controller',args=dict(kind='load',terminal_pins=[dict(pin='PWM',node='SIGNAL_A')]))]
    result=execute_plan(decode_plan(plan(sequence)),DraftRequest(prompt='수동 드라이버 신호 단자',current=bodies()))
    assert registration_for_part(result.design,'controller').terminal_pins=={'PWM':'SIGNAL_A'}


def test_duplicate_named_mapping_rows_cannot_silently_overwrite_a_net():
    sequence=[dict(tool='electrical_register',target='controller',args=dict(kind='load',terminal_pins=[dict(pin='PWM',node='A'),dict(pin='PWM',node='B')]))]
    with pytest.raises(ValueError,match='중복'):
        execute_plan(plan(sequence),DraftRequest(prompt='signals',current=bodies()))
