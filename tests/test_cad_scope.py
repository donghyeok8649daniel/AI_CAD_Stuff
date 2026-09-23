import asyncio
import json
import threading
import httpx
import pytest

from ai_transport import is_scope, scope_response
from cadstudio.models import DraftRequest, Design, Part
from cadstudio.native.cad_scope import Scope, TOOLS, SHAPES, scope_messages
from cadstudio.native.local_ai import DraftControl, DraftCancelled, ollama_draft


def cad_response():
    plan = dict(summary='원통', actions=[dict(tool='create', target='p', args=dict(name='p', geometry=dict(kind='cylinder', diameter=30, height=20)))])
    return httpx.Response(200, json=dict(done=True, message=dict(content=json.dumps(plan))))


def test_model_selection_restricts_grammar_preserves_original_request_and_reuses_client():
    calls = []
    class Transport(httpx.AsyncBaseTransport):
        closed = 0
        async def aclose(self): self.closed += 1
        async def handle_async_request(self, request):
            assert self.closed == 0
            body = json.loads(request.content); calls.append(body)
            assert body['stream'] and body['think'] is False and body['options']['num_ctx'] == 8192
            assert json.loads(body['messages'][1]['content'])['prompt'] == '내가 요청한 형상'
            if is_scope(request):
                assert body['options']['num_predict'] == 512
                return scope_response(['create', 'dimensions'], ['cylinder'])
            assert [a['properties']['tool']['const'] for a in body['format']['properties']['actions']['items']['anyOf']] == ['create']
            assert [s['properties']['kind']['const'] for s in body['format']['$defs']['Geometry']['anyOf']] == ['cylinder']
            assert 'shell:' not in body['messages'][0]['content'] and 'cylinder:' in body['messages'][0]['content']
            return cad_response()
    transport = Transport()
    result = ollama_draft(DraftRequest(prompt='내가 요청한 형상'), 'qwen3:8b', transport, deadline=None)
    assert len(calls) == 2 and transport.closed == 1 and result['attempts'] == 1


def test_edit_scope_preserves_default_dimensions_and_allows_no_new_shape():
    design = Design(parts=[Part(id='p', name='p', geometry=dict(kind='cylinder'))])
    request = DraftRequest(prompt='기존 치수 수정', current=design, selected_part='p')
    scope = Scope.parse('{"intent":"edit","tools":["dimensions"],"shapes":[]}', request)
    data = json.loads(scope_messages(request)[1]['content'])
    assert data['current_design']['parts'][0]['geometry']['diameter'] == design.parts[0].geometry.diameter
    assert data['selected_part'] == 'p' and scope.tools == ('dimensions',) and scope.shapes == SHAPES and scope.intent=='edit'


def test_single_part_intent_limits_creation_to_one_base_and_compiles_features():
    def handle(request):
        if is_scope(request):
            return httpx.Response(200,json=dict(done=True,message=dict(content=json.dumps(dict(intent='part',tools=['create','shell'],shapes=['plate'])))))
        schema=json.loads(request.content)['format']
        assert schema['properties']['base']['properties']['tool']['const']=='create'
        assert list(schema['properties']).index('base')<list(schema['properties']).index('actions')
        assert [a['properties']['tool']['const'] for a in schema['properties']['actions']['items']['anyOf']]==['shell']
        base=dict(tool='create',target='p',args=dict(name='p',geometry=dict(kind='plate',length=80,width=50,thickness=25)))
        plan=dict(summary='one hollow part',base=base,actions=[dict(tool='shell',target='p',args=dict(thickness=2,open_faces=['+Z']))])
        return httpx.Response(200,json=dict(done=True,message=dict(content=json.dumps(plan))))
    result=ollama_draft(DraftRequest(prompt='상자 하나'), 'test', httpx.MockTransport(handle))
    assert result['planning']['intent']=='part' and len(result['design']['parts'])==1
    assert [a['tool'] for a in result['tool_actions']]==['create','shell']


def test_assembly_intent_keeps_distinct_parts_and_a_real_joint():
    def handle(request):
        if is_scope(request):
            return httpx.Response(200,json=dict(done=True,message=dict(content=json.dumps(dict(intent='assembly',tools=['create','joint'],shapes=['cylinder'])))))
        assert 'base' not in json.loads(request.content)['format']['properties']
        actions=[dict(tool='create',target=target,args=dict(name=target,geometry=dict(kind='cylinder',diameter=diameter,height=20))) for target,diameter in [('base',30),('axle',10)]]
        actions.append(dict(tool='joint',target='hinge',args=dict(kind='revolute',parent='base',child='axle',z=20)))
        return httpx.Response(200,json=dict(done=True,message=dict(content=json.dumps(dict(summary='two parts',actions=actions)))))
    result=ollama_draft(DraftRequest(prompt='회전 조립'), 'test', httpx.MockTransport(handle))
    assert len(result['design']['parts'])==2 and result['design']['mates'][0]['kind']=='revolute'
    assert result['design']['parts'][1]['transform']['z']==20


def test_repetitive_explanation_is_bounded_and_repaired_before_execution():
    generated=[]
    def handle(request):
        if is_scope(request):return scope_response(['create'],['cylinder'])
        body=json.loads(request.content);generated.append(body)
        schema=body['format']['properties']
        assert schema['construction']['items']['maxLength']==80
        assert schema['actions']['maxItems']==32
        plan=dict(summary='cylinder',construction=['repeat a dimension. '*50] if len(generated)==1 else ['Cylinder: diameter 30, height 20 mm'],
            actions=[dict(tool='create',target='p',args=dict(name='p',geometry=dict(kind='cylinder',diameter=30,height=20)))])
        return httpx.Response(200,json=dict(done=True,message=dict(content=json.dumps(plan))))
    result=ollama_draft(DraftRequest(prompt='간단한 회전 부품'), 'test', httpx.MockTransport(handle))
    assert len(generated)==2 and result['attempts']==2
    assert 'construction.0' in generated[1]['messages'][-1]['content']
    assert len(result['design']['parts'])==1 and len(result['journal_steps'])==1


@pytest.mark.parametrize('selection', ['{}', 'not JSON', '{"tools":["run_python"],"shapes":["cylinder"]}'])
def test_invalid_selection_broadens_tools_without_fabricating_a_draft(selection):
    calls = []
    def handle(request):
        calls.append(request)
        if is_scope(request): return httpx.Response(200, json=dict(done=True, message=dict(content=selection)))
        body = json.loads(request.content)
        assert len(body['format']['properties']['actions']['items']['anyOf']) == len(TOOLS)
        return cad_response()
    result = ollama_draft(DraftRequest(prompt='설계'), 'test', httpx.MockTransport(handle))
    assert len(calls) == 2 and result['design']['parts'][0]['geometry']['diameter'] == 30


@pytest.mark.parametrize('phase', ['selection', 'generation'])
@pytest.mark.parametrize('stage', ['headers', 'stream'])
def test_unlimited_cancel_closes_both_phases_even_before_first_token(phase, stage):
    entered = threading.Event(); closed = threading.Event(); errors = []; control = DraftControl()
    class Stalled(httpx.AsyncByteStream):
        async def __aiter__(self):
            entered.set()
            try: await asyncio.sleep(60)
            finally: closed.set()
            yield b''
    async def handle(request):
        assert request.extensions['timeout']['read'] is None
        if phase == 'generation' and is_scope(request): return scope_response(['create'], ['cylinder'])
        if stage == 'stream': return httpx.Response(200, stream=Stalled())
        entered.set()
        try: await asyncio.sleep(60)
        finally: closed.set()
    def run():
        try: ollama_draft(DraftRequest(prompt='설계'), 'test', httpx.MockTransport(handle), deadline=None, control=control)
        except Exception as exc: errors.append(exc)
    thread = threading.Thread(target=run, daemon=True); thread.start()
    assert entered.wait(3); control.cancel(); thread.join(2)
    assert not thread.is_alive() and closed.is_set() and isinstance(errors[0], DraftCancelled)


@pytest.mark.parametrize('phase', ['selection', 'generation'])
def test_one_total_deadline_covers_both_phases(phase):
    calls = []
    async def handle(request):
        calls.append(request)
        if phase == 'generation' and is_scope(request):
            await asyncio.sleep(.1)
            return scope_response(['create'], ['cylinder'])
        await asyncio.sleep(60)
    with pytest.raises(ValueError, match='제한 시간'):
        ollama_draft(DraftRequest(prompt='설계'), 'test', httpx.MockTransport(handle), deadline=.5)
    assert len(calls) == (2 if phase == 'generation' else 1)


def test_joint_grammar_constrains_native_anchor_and_limit_contract():
    from cadstudio.native.cad_schema import plan_schema
    schema=plan_schema(['create','joint'],['cylinder'])
    joint=next(item for item in schema['properties']['actions']['items']['anyOf'] if item['properties']['tool']['const']=='joint')
    args=joint['properties']['args']['properties']
    assert args['parent_anchor']['enum']==args['child_anchor']['enum']==['origin']
    limits=args['limits']
    assert limits['additionalProperties'] is False
    assert set(limits['properties'])=={'x','y','z','rx','ry','rz'}
    assert 'min' not in limits['properties'] and 'max' not in limits['properties']
    assert all(value['minItems']==value['maxItems']==2 and value['items']['type']=='number' for value in limits['properties'].values())


@pytest.mark.parametrize('wrong', ['rigid', 'reversed', 'missing'])
def test_requested_motion_and_parent_child_are_checked_and_repaired(wrong):
    connection = dict(kind='revolute', parent='support', child='rotor')
    generated = []
    current = Design(parts=[])
    before = current.model_dump()
    def handle(request):
        if is_scope(request):
            selection = dict(intent='assembly', tools=['create', 'joint'], shapes=['cylinder'], new_parts=['support','rotor'], connections=[connection])
            return httpx.Response(200, json=dict(done=True, message=dict(content=json.dumps(selection))))
        body = json.loads(request.content); generated.append(body)
        joint_schema = next(a for a in body['format']['properties']['actions']['items']['anyOf'] if a['properties']['tool']['const']=='joint')
        create_schema = next(a for a in body['format']['properties']['actions']['items']['anyOf'] if a['properties']['tool']['const']=='create')
        assert create_schema['properties']['target']['enum']==['support','rotor']
        assert all(joint_schema['properties']['args']['properties'][k] == {'const':v} for k,v in connection.items())
        assert 'support' in body['messages'][0]['content']
        actions = [dict(tool='create', target=target, args=dict(name=target, geometry=dict(kind='cylinder', diameter=diameter, height=20, bore_diameter=bore)))
                   for target, diameter, bore in [('support', 30, 10.2), ('rotor', 10, 0)]]
        args = dict(connection)
        if len(generated)==1:
            if wrong=='rigid': args['kind']='rigid'
            elif wrong=='reversed': args.update(parent='rotor', child='support')
        if wrong!='missing' or len(generated)>1:
            actions.append(dict(tool='joint', target='hinge', args=args))
        return httpx.Response(200, json=dict(done=True, message=dict(content=json.dumps(dict(summary='assembly', actions=actions)))))
    result = ollama_draft(DraftRequest(prompt='지지대는 고정하고 회전체만 회전시켜', current=current), 'test', httpx.MockTransport(handle))
    assert result['attempts']==2 and 'Assembly requirement not met' in generated[1]['messages'][-1]['content']
    assert result['planning']['connections']==(connection,)
    mate=result['design']['mates'][0]
    assert all(mate[k]==v for k,v in connection.items())
    assert current.model_dump()==before
    assert len(result['journal_steps'])==3


def test_geometry_edit_does_not_invent_or_replace_existing_joint_requirements():
    request=DraftRequest(prompt='기존 부품 길이만 변경')
    scope=Scope.parse(json.dumps(dict(intent='edit', tools=['dimensions'], shapes=[], connections=[])), request.model_copy(update={'current':Design(parts=[Part(id='p', name='p', geometry=dict(kind='cylinder'))])}))
    assert not scope.connections and scope.tools==('dimensions',)


def test_planned_ids_include_unconnected_parts_and_reject_missing_components():
    from cadstudio.native.cad_tools import execute_plan
    request=DraftRequest(prompt='서로 떨어진 두 부품')
    scope=Scope.parse(json.dumps(dict(intent='assembly',tools=['create'],shapes=['cylinder'],new_parts=['first','second'],connections=[])),request)
    one=execute_plan(json.dumps(dict(summary='one only',actions=[dict(tool='create',target='first',args=dict(name='first',geometry=dict(kind='cylinder',diameter=10,height=20)))])),request)
    with pytest.raises(ValueError,match='Missing planned parts: second'):
        scope.validate_result(one)
    assert scope.new_parts==('first','second') and not scope.connections


def test_joint_selection_rejects_unknown_part_synonym_before_geometry_generation():
    with pytest.raises(ValueError,match='Joint IDs must refer'):
        Scope.parse(json.dumps(dict(intent='assembly',tools=['create','joint'],shapes=['cylinder'],new_parts=['housing','shaft'],connections=[dict(kind='revolute',parent='support',child='shaft')])),DraftRequest(prompt='조립'))
