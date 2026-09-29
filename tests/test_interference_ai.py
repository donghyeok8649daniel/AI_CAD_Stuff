import asyncio
import json
import httpx
import pytest
from cadstudio.models import DraftRequest
from cadstudio.native.codex_ai import generate as codex
from cadstudio.native.cloud_ai import generate as cloud
from cadstudio.native.local_ai import _ollama_reply,DraftControl
from cadstudio.native.cad_tools import execute_plan
from test_cloud_planner import answer,scope
from test_codex_planner import Session


def plan(x):
    return dict(name='Pair',summary='두 부품 조립',construction=[],assumptions=[],actions=[
        dict(tool='create',target=identifier,args=dict(name=identifier,geometry=dict(kind='plate',length=10,width=10,thickness=5,hole_count=0),transform=dict(x=pos)))
        for identifier,pos in [('a',0),('b',x)]])


@pytest.mark.parametrize('provider',['codex','openai','ollama'])
@pytest.mark.parametrize('repair',[False,True])
def test_ai_overlap_is_repaired_or_rejected_never_silently_accepted(provider,repair):
    req=DraftRequest(prompt='별개 부품 두 개를 만들어줘');bad=plan(5);replies=[bad,plan(20)] if repair else [bad]*(6 if provider=='codex' else 3)
    calls=[];selected=scope(intent='assembly',tools=('create',),shapes=('plate',),new_parts=('a','b'))
    if provider=='codex':
        session=Session([selected]+replies)
        invoke=lambda:codex(req,'gpt-6-astra',session_factory=lambda _:session)
        calls=session.calls
    elif provider=='openai':
        queue=[selected]+replies
        def handle(r):calls.append(json.loads(r.content));return answer(queue.pop(0))
        invoke=lambda:cloud(req,'gpt-6-astra',api_key='test-key',transport=httpx.MockTransport(handle))
    else:
        queue=list(replies)
        def handle(r):calls.append(json.loads(r.content));return httpx.Response(200,json=dict(done=True,message=dict(content=json.dumps(queue.pop(0)))))
        async def run():
            async with httpx.AsyncClient(base_url='http://127.0.0.1:11434',transport=httpx.MockTransport(handle)) as client:
                return await _ollama_reply(client,'test',[dict(role='system',content='test'),dict(role='user',content=req.prompt)],DraftControl(),lambda _:None,parser=lambda content:execute_plan(content,req))
        invoke=lambda:asyncio.run(run())
    if repair:
        result=invoke();assert result['attempts']==2 and len(result['design']['parts'])==2
    else:
        result=invoke()
        assert result['validation']['status']=='needs_repair'
        assert result['validation']['collisions'] and result['repair']['plan']
        assert len(result['design']['parts'])==2
    assert any('간섭' in json.dumps(c,ensure_ascii=False) for c in calls[1:])
