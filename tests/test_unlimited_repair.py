"""Unlimited means no validation-attempt ceiling, not accepting invalid shapes."""
import asyncio
import json
from copy import deepcopy
import httpx
import pytest

from cadstudio.models import DraftRequest, Design
from cadstudio.kernel import build
from cadstudio.native.codex_ai import generate
from cadstudio.native.local_ai import DraftControl, DraftCancelled, ollama_draft
from test_cloud_planner import scope, plan
from test_codex_planner import Session
from test_draft_repair import fixture_plan, selected_scope, request


def run_provider(provider, req, replies, control=None, progress=None):
    session=Session(replies)
    if provider=='codex':
        result=generate(req,'gpt-6-astra',deadline=None,control=control,progress=progress,session_factory=lambda _:session)
    else:
        def handle(r):
            session.calls.append(json.loads(r.content)['messages'])
            return httpx.Response(200,json=dict(done=True,message=dict(content=json.dumps(session.replies.pop(0)))))
        result=ollama_draft(req,'test',httpx.MockTransport(handle),deadline=None,control=control,progress=progress)
    return result,session


@pytest.mark.parametrize('provider',['codex','ollama'])
def test_validation_can_recover_after_old_limits_without_growing_history(provider):
    bad=plan();bad['base']['args']['geometry']['diameter']=-1
    req=DraftRequest(prompt='직경40 높이10 구멍8 원통');before=req.model_dump();events=[]
    result,session=run_provider(provider,req,[scope()]+[bad]*7+[plan()],progress=events.append)
    assert result['attempts']==8 and result['validation']['status']=='ready'
    assert req.model_dump()==before and build(Design.model_validate(result['design']))[0].isValid()
    assert max(map(len,session.calls))<=4
    assert any('8회' in text and '무제한' in text for text in events)


@pytest.mark.parametrize('provider',['codex','ollama'])
def test_overlap_repair_continues_past_six_and_retains_renderable_checkpoint(provider):
    req=request();control=DraftControl()
    result,_=run_provider(provider,req,[selected_scope()]+[fixture_plan()]*7+[fixture_plan(True)],control=control)
    assert result['attempts']==8 and result['validation']['status']=='ready'
    saved=control.checkpoint()
    assert saved['response']['validation']['status']=='needs_repair'
    assert saved['response']['repair']['request_fingerprint']
    assert saved['preview']['stats']['collisions']
    assert saved['response']['design']['parts'][1]['geometry']['thickness']==2


def test_cancel_after_repeated_invalid_plan_stops_without_fabricated_success():
    control=DraftControl();bad=plan();bad['base']['args']['geometry']['diameter']=-1
    session=Session([scope()]+[bad]*8)
    original=session.content
    async def content(*args):
        if len(session.calls)==9:control.cancel();control.check()
        return await original(*args)
    session.content=content
    with pytest.raises(DraftCancelled):
        generate(DraftRequest(prompt='원통'),'gpt-6-astra',deadline=None,control=control,session_factory=lambda _:session)
    assert session.closed and control.checkpoint() is None


def test_service_error_is_not_retried_forever_and_checkpoint_remains():
    control=DraftControl();session=Session([selected_scope(),fixture_plan()]);original=session.content
    async def content(*args):
        if not session.replies:raise ValueError('Codex 사용량 한도에 도달했습니다.')
        return await original(*args)
    session.content=content
    result=generate(request(),'gpt-6-astra',deadline=None,control=control,session_factory=lambda _:session)
    assert session.closed and len(session.calls)==2
    assert result['validation']['status']=='needs_repair' and control.checkpoint()
    assert any('사용량 한도' in text for text in result['assumptions'])


def test_first_request_cancel_restores_checkpoint_without_applying(app,monkeypatch,tmp_path):
    from cadstudio.native import window, codex_ai
    from cadstudio.native.model_picker import LocalModelPicker
    from test_openai_setup_native import wait
    monkeypatch.setattr(window,'DATA_DIR',tmp_path)
    monkeypatch.setattr(LocalModelPicker,'refresh',lambda _:None)
    # Obtain an actual renderable *rejected* draft, not an unverified empty plan.
    saved_control=DraftControl()
    def progress(text):
        if saved_control.checkpoint():saved_control.cancel();saved_control.check()
    with pytest.raises(DraftCancelled):
        run_provider('codex',request(),[selected_scope(),fixture_plan(),fixture_plan()],control=saved_control,progress=progress)
    saved=saved_control.checkpoint()
    def fake(req,model,**kw):
        kw['control'].keep_draft(saved['response'],saved['preview'])
        while not kw['control'].cancelled.wait(.01):pass
        kw['control'].check()
    monkeypatch.setattr(codex_ai,'generate',fake)
    w=window.MainWindow();w.show();w.provider.setCurrentIndex(w.provider.findData('codex'))
    w.codex_config=dict(executable='test.exe',model='gpt-6-astra');w.prompt.setPlainText(request().prompt)
    try:
        before=deepcopy(w.document.design);w.generate_draft();task=w.ai_task
        wait(app,lambda:task.control.checkpoint() is not None)
        w.cancel_ai();task.thread.join(2);app.processEvents()
        assert w.ai_task is None and w.document.design==before
        assert w.last_draft and w.last_draft['response']['repair'] and w.accept_draft.isEnabled()
        w.apply_draft();assert w.document.design==before
    finally:w.document.dirty=False;w.close();app.processEvents()


from test_placement_native import app
