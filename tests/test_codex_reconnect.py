import asyncio
from copy import deepcopy
import json

import pytest

from cadstudio.models import DraftRequest
from cadstudio.native.codex_reconnect import RecoveringSession,ConnectionInterrupted,classified_error
from cadstudio.native.local_ai import DraftControl,DraftCancelled
from cadstudio.native.codex_ai import generate
from test_codex_planner import Session
from test_cloud_planner import scope,plan
from test_references import reference


@pytest.mark.parametrize('error',[
    {'codexErrorInfo':'ResponseStreamDisconnected'},
    {'codexErrorInfo':{'httpConnectionFailed':{'httpStatusCode':503}}},
    {'codexErrorInfo':'ResponseTooManyFailedAttempts'},
    {'message':'error sending request for url (private)'}])
def test_transient_errors_are_classified_without_leaking_details(error):
    e=classified_error(error);assert isinstance(e,ConnectionInterrupted) and 'private' not in str(e)


@pytest.mark.parametrize('error',[
    {'codexErrorInfo':{'httpConnectionFailed':{'httpStatusCode':401}}},
    {'codexErrorInfo':'UsageLimitExceeded','message':'connection reset'},
    {'codexErrorInfo':{'httpConnectionFailed':{'httpStatusCode':429}}},
    {'codexErrorInfo':'BadRequest'}, {'message':'unknown problem'}])
def test_permanent_or_unknown_errors_are_not_automatically_retried(error):
    assert not isinstance(classified_error(error),ConnectionInterrupted)


def test_reconnect_wait_does_not_consume_finite_active_deadline():
    control=DraftControl();created=[];progress=[]
    class Interrupted(Session):
        async def account(self):raise ConnectionInterrupted('offline')
    def factory(_):
        item=Interrupted([]) if not created else Session([]);created.append(item);return item
    async def delay(_):await asyncio.sleep(.08)
    async def work():
        async with RecoveringSession(factory,'',control,progress.append,sleep=delay) as s:return await s.account()
    assert asyncio.run(control.execute(work,.04))=={'plan':'pro'}
    assert len(created)==2 and all(s.closed for s in created) and not control.network_paused


def test_recovered_generation_still_has_active_timeout():
    control=DraftControl();created=[]
    class Interrupted(Session):
        async def account(self):raise ConnectionInterrupted('offline')
        async def content(self,*args):raise ConnectionInterrupted('offline')
    class Stuck(Session):
        async def content(self,*args):await asyncio.sleep(60)
    def factory(_):
        item=Interrupted([]) if not created else Stuck([]);created.append(item);return item
    async def delay(_):await asyncio.sleep(.04)
    async def work():
        async with RecoveringSession(factory,'',control,lambda _:None,sleep=delay) as s:return await s.content()
    with pytest.raises(ValueError,match='제한 시간'):asyncio.run(control.execute(work,.06))
    assert all(s.closed for s in created)


def test_cancel_during_offline_wait_closes_session_and_never_retries():
    control=DraftControl();created=[]
    class Interrupted(Session):
        async def account(self):raise ConnectionInterrupted('offline')
    def factory(_):item=Interrupted([]);created.append(item);return item
    async def delay(_):control.cancel();await asyncio.sleep(0)
    async def work():
        async with RecoveringSession(factory,'',control,lambda _:None,sleep=delay) as s:return await s.account()
    with pytest.raises(DraftCancelled):asyncio.run(control.execute(work,None))
    assert len(created)==1 and created[0].closed


def test_reconnect_retains_scope_original_references_and_latest_validation_feedback(monkeypatch):
    original=RecoveringSession.__init__
    async def quick(_):await asyncio.sleep(0)
    monkeypatch.setattr(RecoveringSession,'__init__',lambda self,*a,**kw:original(self,*a,**kw,sleep=quick))
    invalid=plan();invalid['base']['args']['geometry']['diameter']=-10
    replies=[scope(),invalid,ConnectionInterrupted('offline'),plan()];calls=[];created=[]
    class Flaky(Session):
        async def content(self,model,messages,*args):
            calls.append(deepcopy(messages));value=replies.pop(0)
            if isinstance(value,Exception):raise value
            return json.dumps(value)
    def factory(_):item=Flaky([]);created.append(item);return item
    request=DraftRequest(prompt='허브를 만들어줘',references=[reference()]);before=request.model_dump()
    result=generate(request,'gpt-6-astra',session_factory=factory,deadline=None)
    assert result['attempts']==2 and len(calls)==4 and len(created)==2 and all(s.closed for s in created)
    assert calls[2]==calls[3] and 'CAD 검증 오류' in calls[3][-1]['content']
    assert json.loads(calls[3][1]['content'])['reference_materials'][0]['text']==request.references[0].text
    assert request.model_dump()==before
