import asyncio
import json
import math
from copy import deepcopy
import pytest

from cadstudio.models import Design,DraftRequest
from cadstudio.kernel import build
from cadstudio.catalog import preset
from cadstudio.native.codex_ai import generate
from test_cloud_planner import scope,plan


class Session:
    def __init__(self,replies):self.replies=list(replies);self.calls=[];self.closed=False
    async def __aenter__(self):return self
    async def __aexit__(self,*args):self.closed=True
    async def account(self):return {'plan':'pro'}
    async def models(self):return [{'model':'gpt-6-astra','efforts':['medium']}]
    async def content(self,model,messages,schema,effort,progress):
        self.calls.append(deepcopy(messages));return json.dumps(self.replies.pop(0))


def test_codex_generates_real_hole_and_history_without_changing_original():
    session=Session([scope(),plan()]);request=DraftRequest(prompt='직경 40 높이 10 허브에 지름 8 관통 구멍')
    result=generate(request,'gpt-6-astra',session_factory=lambda _:session)
    solid=build(Design.model_validate(result['design']))[0]
    assert solid.Volume()==pytest.approx(math.pi*(20**2-4**2)*10,rel=1e-7)
    assert result['provider']=='codex' and len(result['journal_steps'])==2 and session.closed


def test_invalid_plan_repair_is_bounded_and_transactional():
    bad=plan();bad['base']['args']['geometry']['diameter']=-10
    session=Session([scope(),bad,bad,bad]);current=preset('cylinder');before=current.model_dump()
    with pytest.raises(ValueError,match='3차례'):
        generate(DraftRequest(prompt='허브',current=current),'gpt-6-astra',session_factory=lambda _:session)
    assert len(session.calls)==4 and current.model_dump()==before and session.closed


def test_account_model_is_required_no_automatic_fallback():
    session=Session([])
    with pytest.raises(ValueError,match='현재 Codex 계정'):
        generate(DraftRequest(prompt='바퀴'),'invented-model',session_factory=lambda _:session)
    assert not session.calls and session.closed


def test_deadline_closes_stalled_codex_session():
    session=Session([])
    async def wait(*args):await asyncio.sleep(60)
    session.content=wait
    with pytest.raises(ValueError,match='Codex가 제한 시간'):
        generate(DraftRequest(prompt='바퀴'),'gpt-6-astra',deadline=.02,session_factory=lambda _:session)
    assert session.closed
