"""Version 3 protocol recovery, exact effort settings and photo input regressions."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest
from PIL import Image

from cadstudio.models import DraftRequest
from cadstudio.native import codex_connection as connection
from cadstudio.native.codex_ai import generate
from cadstudio.native.codex_models import CodexRuntimeSettings, effort_options, normalize_model, validate_selection
from cadstudio.native.codex_reconnect import ConnectionInterrupted, RecoveringSession
from cadstudio.native.local_ai import DraftControl, DraftCancelled
from test_codex_connection import server
from test_codex_planner import Session
from test_cloud_planner import scope, plan


def test_exact_efforts_preserve_ultra_and_max_as_distinct_supported_values():
    values = ['low','medium','high','xhigh','max','ultra','future-effort']
    entry = normalize_model(dict(model='gpt-6.1-sol', displayName='Sol', defaultReasoningEffort='low',
        supportedReasoningEfforts=[dict(reasoningEffort=v) for v in [*values,'ultra','invalid\nvalue',None]]))
    assert entry['efforts'] == values and entry['default_effort'] == 'low'
    assert effort_options(entry) == list(zip(['Low','Medium','High','Extra high','Max','Ultra','future-effort'],values))
    assert validate_selection([entry],'gpt-6.1-sol','ultra') is entry
    with pytest.raises(ValueError,match='지원하지'):validate_selection([entry],'gpt-6.1-sol','invented')
    assert normalize_model({'model':None}) is None


def test_final_json_item_survives_lost_trailing_completion_event(server,monkeypatch):
    factory,log,children,_ = server;monkeypatch.setenv('FAKE_MODE','final_eof');progress=[]
    async def run():
        async with factory() as session:
            return await session.content('gpt-6.1-sol',[dict(role='system',content='JSON')],{},'ultra',progress.append)
    assert json.loads(asyncio.run(run())) == {'answer':42}
    assert progress and children[0].returncode is not None
    assert '"effort": "ultra"' in log.read_text()


@pytest.mark.parametrize('mode',['invalid_final_eof','partial_eof'])
def test_disconnect_without_complete_json_cannot_be_reported_as_success(server,monkeypatch,mode):
    factory,_,children,_ = server;monkeypatch.setenv('FAKE_MODE',mode)
    async def run():
        async with factory() as session:
            return await session.content('gpt-6.1-sol',[dict(role='system',content='JSON')],{},'low',lambda _:None)
    with pytest.raises(ConnectionInterrupted):asyncio.run(run())
    assert children[0].returncode is not None


def test_explicit_failed_turn_is_not_replaced_by_earlier_final_item(server,monkeypatch):
    factory,_,_,_ = server;monkeypatch.setenv('FAKE_MODE','final_fail')
    async def run():
        async with factory() as session:
            return await session.content('gpt-6.1-sol',[dict(role='system',content='JSON')],{},'low',lambda _:None)
    with pytest.raises(ValueError,match='사용량 한도'):asyncio.run(run())


def test_verified_photos_use_official_local_image_input(server,tmp_path):
    photo=tmp_path/'fixture.png';Image.new('RGB',(16,16),'blue').save(photo)
    factory,log,_,_ = server
    async def run():
        async with factory() as session:
            return await session.content('gpt-6.1-sol',[dict(role='system',content='JSON')],{},'low',lambda _:None,
                local_image_paths=[photo])
    assert json.loads(asyncio.run(run())) == {'answer':42}
    call=next(row for row in map(json.loads,log.read_text().splitlines()) if row['method']=='turn/start')
    assert call['params']['input'][1] == dict(type='localImage',path=str(photo.resolve()))
    invalid=tmp_path/'secret.txt';invalid.write_text('private input')
    with pytest.raises(ValueError,match='사진'):connection.local_image_inputs([invalid])
    with pytest.raises(ValueError,match='8장'):connection.local_image_inputs([photo]*9)


def test_healthy_app_server_is_reused_after_upstream_failure():
    created=[];calls=[];control=DraftControl()
    class Healthy(Session):
        alive=True
        async def content(self,*args,**kwargs):
            calls.append(kwargs)
            if len(calls)==1:raise ConnectionInterrupted('offline')
            return 'restored'
    def factory(_):
        item=Healthy([]);created.append(item);return item
    async def quick(_):await asyncio.sleep(0)
    async def run():
        async with RecoveringSession(factory,'',control,lambda _:None,sleep=quick) as session:
            return await session.content(local_image_paths=('same-image',))
    assert asyncio.run(control.execute(run,None))=='restored'
    assert len(created)==1 and created[0].closed and calls==[dict(local_image_paths=('same-image',))]*2


def test_runtime_changes_affect_next_phase_and_keep_actual_generation_provenance():
    runtime=CodexRuntimeSettings('first','medium');calls=[]
    class Changing(Session):
        async def models(self):return [dict(model='first',efforts=['medium']),dict(model='second',efforts=['ultra'])]
        async def content(self,model,messages,schema,effort,progress):
            calls.append((model,effort,deepcopy(messages)))
            runtime.update(model='second',effort='ultra')
            return json.dumps(scope() if len(calls)==1 else plan())
    session=Changing([])
    result=generate(DraftRequest(prompt='허브'),'first',session_factory=lambda _:session,runtime_config=runtime)
    assert [row[:2] for row in calls]==[('first','medium'),('second','ultra')]
    assert result['model']=='second' and result['effort']=='ultra' and session.closed


def test_runtime_change_during_disconnect_does_not_mutate_retried_phase(monkeypatch):
    original=RecoveringSession.__init__
    async def quick(_):await asyncio.sleep(0)
    monkeypatch.setattr(RecoveringSession,'__init__',lambda self,*a,**kw:original(self,*a,**kw,sleep=quick))
    runtime=CodexRuntimeSettings('first','medium');calls=[]
    class Flaky(Session):
        alive=True
        async def models(self):return [dict(model='first',efforts=['medium']),dict(model='second',efforts=['ultra'])]
        async def content(self,model,messages,schema,effort,progress):
            calls.append((model,effort,deepcopy(messages)))
            if len(calls)==1:
                runtime.update(model='second',effort='ultra')
                raise ConnectionInterrupted('offline')
            return json.dumps(scope() if len(calls)==2 else plan())
    session=Flaky([])
    result=generate(DraftRequest(prompt='허브'),'first',session_factory=lambda _:session,runtime_config=runtime)
    assert [row[:2] for row in calls]==[('first','medium'),('first','medium'),('second','ultra')]
    assert calls[0][2]==calls[1][2] and result['model']=='second' and result['effort']=='ultra'


def test_retained_candidate_keeps_its_model_after_later_model_corrections_fail():
    from test_draft_repair import fixture_plan, selected_scope, request
    runtime=CodexRuntimeSettings('first','medium');control=DraftControl()
    class Repairing(Session):
        async def models(self):return [dict(model='first',efforts=['medium']),dict(model='second',efforts=['ultra'])]
        async def content(self,model,messages,schema,effort,progress):
            raw=await super().content(model,messages,schema,effort,progress)
            if len(self.calls)==2:runtime.update(model='second',effort='ultra')
            return raw
    session=Repairing([selected_scope(),fixture_plan(),*[dict(summary='invalid',actions=[])]*5])
    pending=generate(request(),'first',session_factory=lambda _:session,runtime_config=runtime,control=control)
    assert pending['validation']['status']=='needs_repair'
    assert (pending['model'],pending['effort'])==('first','medium')
    assert control.checkpoint()['response']['model']=='first'
    assert runtime.snapshot()==('second','ultra')


def test_server_retry_notifications_pause_active_deadline_and_resume_on_output(monkeypatch,tmp_path):
    control=DraftControl();clock=[];packet=0
    monkeypatch.setattr(connection,'find_executable',lambda _: 'owned.exe')
    session=connection.CodexSession(profile=tmp_path)
    session.network_wait=lambda waiting:(clock.append(waiting),control.network_wait(waiting))
    async def account():return dict(plan='pro')
    async def rpc(method,params,**kwargs):
        return {'thread':{'id':'thread'}} if method=='thread/start' else {'turn':{'id':'turn'}} if method=='turn/start' else {'data':[]}
    async def event():
        nonlocal packet
        packet+=1
        if packet==1:return dict(method='error',params=dict(threadId='thread',turnId='turn',willRetry=True))
        if packet==2:
            await asyncio.sleep(.08)
            return dict(method='item/completed',params=dict(threadId='thread',turnId='turn',item=dict(type='agentMessage',text='{"answer":42}')))
        return dict(method='turn/completed',params=dict(threadId='thread',turn=dict(id='turn',status='completed')))
    session.account=account;session.rpc=rpc;session.event=event
    async def work():return await session.content('gpt-6.1-sol',[dict(content='JSON')],{},'low',lambda _:None)
    assert json.loads(asyncio.run(control.execute(work,.04)))=={'answer':42}
    assert clock==[True,False,False] and not control.network_paused


def test_automatic_cli_prefers_desktop_but_explicit_custom_path_wins(monkeypatch,tmp_path):
    desktop=tmp_path/'desktop.exe';desktop.touch();npm=tmp_path/'npm.exe';npm.touch()
    monkeypatch.setattr(connection,'desktop_executables',lambda:[desktop])
    monkeypatch.setattr(connection.shutil,'which',lambda _:str(npm))
    assert connection.find_executable()==str(desktop.resolve())
    assert connection.find_executable(str(npm))==str(npm.resolve())


def test_legacy_automatic_npm_path_migrates_but_explicit_choice_is_preserved(monkeypatch,tmp_path):
    monkeypatch.setenv('CADSTUDIO_DATA_DIR',str(tmp_path/'data'));monkeypatch.setenv('APPDATA',str(tmp_path/'appdata'))
    npm=tmp_path/'appdata/npm/node_modules/@openai/codex/vendor/x86_64-pc-windows-msvc/codex/codex.exe'
    npm.parent.mkdir(parents=True);npm.touch();desktop=tmp_path/'desktop.exe';desktop.touch()
    monkeypatch.setattr(connection,'desktop_executables',lambda:[desktop])
    connection.save_settings(str(npm),'gpt-6.1-sol')
    assert connection.settings()['executable']==str(desktop.resolve())
    connection.save_settings(str(npm),'gpt-6.1-sol',executable_source='explicit')
    assert connection.settings()==dict(executable=str(npm),model='gpt-6.1-sol')
    assert connection.settings(include_source=True)['executable_source']=='explicit'
    connection.save_settings(str(npm),'gpt-6-astra')
    assert connection.settings(include_source=True)['executable_source']=='explicit'


def test_draft_control_reexport_keeps_cancellation_exception_identity():
    from cadstudio.native.draft_control import DraftControl as CoreControl, DraftCancelled as CoreCancelled
    assert CoreControl is DraftControl and CoreCancelled is DraftCancelled
