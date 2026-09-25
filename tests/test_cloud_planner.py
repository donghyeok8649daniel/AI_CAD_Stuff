"""No paid calls: real SDK streaming, cancellation and kernel with mock HTTP."""
import asyncio
from copy import deepcopy
import json
import math
import threading

import httpx
import pytest

from cadstudio.catalog import preset
from cadstudio.kernel import build
from cadstudio.models import Design, DraftRequest
from cadstudio.native.cloud_ai import generate, response_schema, decode_plan
from cadstudio.native.cad_schema import plan_schema
from cadstudio.native.local_ai import DraftControl, DraftCancelled


def events(*items):
    return b''.join(('data: '+json.dumps(item,ensure_ascii=False)+'\n\n').encode() for item in items)


def answer(value):
    text=json.dumps(value,ensure_ascii=False)
    return httpx.Response(200,headers={'content-type':'text/event-stream'},content=events(
        {'type':'response.output_text.delta','delta':text[:50]},
        {'type':'response.output_text.delta','delta':text[50:]},
        {'type':'response.completed','response':{'status':'completed'}}))


def scope(intent='part',tools=('create','hole'),shapes=('cylinder',),new_parts=('hub',)):
    return dict(intent=intent,tools=list(tools),shapes=list(shapes),new_parts=list(new_parts),connections=[])


def plan():
    return dict(construction=['직경 40, 높이 10, 관통 구멍 직경 8'],summary='구멍 있는 원통',name=None,assumptions=None,
        base=dict(tool='create',target='hub',args=dict(name='허브',geometry=dict(kind='cylinder',diameter=40,height=10,bore_diameter=None),color=None,transform=None)),
        actions=[dict(tool='hole',target='hub',args=dict(face='+Z',diameter=8,depth=None,through_all=True,centers=None,pattern=None,finish=None))])


def invoke(handle,**kwargs):
    return generate(kwargs.pop('request',DraftRequest(prompt='직경 40 높이 10 원통에 직경 8 관통 구멍')),kwargs.pop('model','gpt-6-astra'),api_key='test-placeholder',transport=httpx.MockTransport(handle),**kwargs)


def test_cloud_plan_uses_real_geometry_history_and_responses_contract():
    requests=[];progress=[]
    def handle(request):
        body=json.loads(request.content);requests.append(body)
        assert str(request.url)=='https://api.openai.com/v1/responses'
        assert body['model']=='gpt-6-astra' and body['reasoning']=={'effort':'medium'}
        assert body['store'] is False and body['stream'] is True
        assert not {'temperature','top_p','tools'} & body.keys()
        return answer(scope() if len(requests)==1 else plan())
    result=invoke(handle,progress=progress.append,deadline=None)
    assert len(requests)==2 and result['provider']=='openai' and result['attempts']==1
    assert len(result['journal_steps'])==2 and len(result['tool_actions'])==2
    shape=build(Design.model_validate(result['design']))[0]
    assert shape.Volume()==pytest.approx(math.pi*(20**2-4**2)*10,rel=1e-7)
    assert any('수신' in p for p in progress)


def test_schema_is_closed_nullable_and_preserves_dimension_dictionary():
    original=plan_schema();before=deepcopy(original);schema=response_schema(original)
    def visit(value):
        if isinstance(value,dict):
            assert 'default' not in value and 'oneOf' not in value
            if value.get('type')=='object':
                assert value['additionalProperties'] is False
                assert set(value['properties'])==set(value['required'])
            for child in value.values():visit(child)
        elif isinstance(value,list):
            for child in value:visit(child)
    visit(schema);assert original==before
    actions=schema['properties']['actions']['items']['anyOf']
    dims=next(a for a in actions if a['properties']['tool'].get('enum')==['dimensions'])
    assert dims['properties']['args']['properties']['values']['type']=='array'
    raw={'summary':'변경','actions':[{'tool':'dimensions','target':'p','args':{'values':[
        {'key':'thickness','value_json':'12'},{'key':'points','value_json':'[{"x":0,"y":1}]'}]}}]}
    decoded=json.loads(decode_plan(json.dumps(raw)))
    assert decoded['actions'][0]['args']['values']=={'thickness':12,'points':[{'x':0,'y':1}]}
    raw['actions'][0]['args']['values'].append({'key':'thickness','value_json':'20'})
    with pytest.raises(ValueError,match='중복'):decode_plan(json.dumps(raw))


def test_edit_preserves_other_parts_and_retries_from_original_document():
    current=preset('robot_arm');before=current.model_dump();calls=[];identifier=current.parts[0].id
    def handle(request):
        body=json.loads(request.content);calls.append(body)
        if len(calls)==1:return answer(scope('edit',('dimensions',),(),()))
        return answer(dict(summary='치수 수정',actions=[dict(tool='dimensions',target=identifier,
            args={'values':[{'key':'diameter','value_json':'-5' if len(calls)==2 else '90'}]})]))
    result=invoke(handle,request=DraftRequest(prompt='베이스 지름 90으로',current=current),model='gpt-4.1')
    assert result['attempts']==2 and len(calls)==3
    assert all('reasoning' not in c for c in calls)
    assert result['design']['parts'][0]['geometry']['diameter']==90
    assert result['design']['mates']==before['mates'] and result['design']['parts'][1:]==before['parts'][1:]
    assert current.model_dump()==before and len(result['journal_steps'])==1
    assert '검증 오류' in calls[2]['input'][-1]['content']


def test_bad_geometry_has_bounded_repairs_and_never_mutates_current():
    calls=[];current=preset('cylinder');before=current.model_dump()
    def handle(request):
        calls.append(request)
        if len(calls)==1:return answer(scope())
        data=plan();data['base']['args']['geometry']['diameter']=-40
        return answer(data)
    with pytest.raises(ValueError,match='3차례'):invoke(handle,request=DraftRequest(prompt='새 원통',current=current))
    assert len(calls)==4 and current.model_dump()==before


@pytest.mark.parametrize('phase',['headers','stream'])
def test_unlimited_cancel_closes_pending_request(phase):
    entered=threading.Event();closed=threading.Event();control=DraftControl();errors=[]
    class Stalled(httpx.AsyncByteStream):
        async def __aiter__(self):
            entered.set()
            try:await asyncio.sleep(60)
            finally:closed.set()
            yield b''
    async def handle(request):
        if phase=='stream':return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Stalled())
        entered.set()
        try:await asyncio.sleep(60)
        finally:closed.set()
    def work():
        try:invoke(handle,control=control,deadline=None)
        except Exception as exc:errors.append(exc)
    worker=threading.Thread(target=work,daemon=True);worker.start();assert entered.wait(5)
    control.cancel();worker.join(2)
    assert not worker.is_alive() and closed.is_set() and isinstance(errors[0],DraftCancelled)


def test_total_deadline_also_cancels_cloud():
    async def handle(request):await asyncio.sleep(60)
    with pytest.raises(ValueError,match='OpenAI가 제한 시간'):invoke(handle,deadline=.03)


@pytest.mark.parametrize('status,match',[(401,'인증'),(429,'잔액'),(400,'요청 형식')])
def test_api_errors_are_safe_actionable_and_not_retried(status,match):
    calls=[]
    def handle(request):
        calls.append(request);return httpx.Response(status,json={'error':{'message':'private request details','type':'error'}})
    with pytest.raises(ValueError,match=match) as error:invoke(handle)
    assert len(calls)==1 and 'private' not in str(error.value)


@pytest.mark.parametrize('event,match',[
    ({'type':'response.incomplete','response':{'status':'incomplete'}},'출력이 제한'),
    ({'type':'response.refusal.delta','delta':'no'},'응답하지'),
    ({'type':'response.failed','response':{'status':'failed'}},'생성에 실패'),
    ({'type':'response.output_text.delta','delta':'{}'},'끊어졌'),
])
def test_incomplete_and_refused_streams_are_never_applied(event,match):
    with pytest.raises(ValueError,match=match):
        invoke(lambda request:httpx.Response(200,headers={'content-type':'text/event-stream'},content=events(event)))
