"""Real child-process protocol tests; no credentials or paid/model requests."""
import asyncio
import json
import os
from pathlib import Path
import sys
import threading

import pytest

from cadstudio.native import codex_connection as connection
from cadstudio.native.local_ai import DraftControl, DraftCancelled


FAKE_SERVER = r'''
import json, os, sys
mode=os.environ.get('FAKE_MODE','ok')
def send(value): print(json.dumps(value),flush=True)
for line in sys.stdin:
 q=json.loads(line);method=q['method'];p=q.get('params',{})
 with open(os.environ['FAKE_LOG'],'a',encoding='utf-8') as f:f.write(json.dumps(q)+'\n')
 if 'id' not in q:continue
 result={}
 if method=='initialize':result={'userAgent':'fake'}
 elif method=='config/read':result={'config':{'mcp_servers':{'test.server':{'command':'example','enabled':True,'tool_timeout_sec':None}},'plugins':{'demo@0.1':{'enabled':True}},'apps':{'_default':{'enabled':True}}}}
 elif method=='mcpServerStatus/list':result={'data':[{'name':'unexpected','tools':{'write':{}}}],'nextCursor':None} if mode=='tools' else {'data':[],'nextCursor':None}
 elif method=='account/read':result={'account':{'type':'apiKey' if mode=='api' else 'chatgpt','planType':'pro'}}
 elif method=='model/list':result={'data':[{'model':'gpt-6-astra','displayName':'Astra','isDefault':True,'supportedReasoningEfforts':[{'reasoningEffort':'medium'}]}],'nextCursor':None}
 elif method=='thread/start':result={'thread':{'id':'thread-test'}}
 elif method=='turn/start':result={'turn':{'id':'turn-test','status':'inProgress'}}
 elif method=='account/login/start':result={'type':'chatgpt','loginId':'login-test','authUrl':'https://auth.openai.com/authorize?example=true'}
 send({'id':q['id'],'result':result})
 if method=='turn/start' and mode in ('ok','final_eof','invalid_final_eof','partial_eof','final_fail'):
  send({'method':'item/completed','params':{'threadId':'unrelated','turnId':'turn-test','item':{'type':'agentMessage','text':'bad'}}})
  send({'method':'item/completed','params':{'threadId':'thread-test','turnId':'old','item':{'type':'agentMessage','text':'bad'}}})
  send({'method':'item/completed','params':{'threadId':'thread-test','turnId':'turn-test','item':{'type':'agentMessage','phase':'commentary','text':'Planning...'}}})
  if mode=='partial_eof':
   send({'method':'item/agentMessage/delta','params':{'threadId':'thread-test','turnId':'turn-test','delta':'{"answer":'}})
   sys.exit(0)
  send({'method':'item/completed','params':{'threadId':'thread-test','turnId':'turn-test','item':{'type':'agentMessage','phase':'final_answer','text':'{"answer":' if mode=='invalid_final_eof' else '{"answer":42}'}}})
  if mode in ('final_eof','invalid_final_eof'):sys.exit(0)
  if mode=='final_fail':
   send({'method':'turn/completed','params':{'threadId':'thread-test','turn':{'id':'turn-test','status':'failed','error':{'codexErrorInfo':'usageLimitExceeded'}}}})
   continue
  send({'method':'turn/completed','params':{'threadId':'thread-test','turn':{'id':'turn-test','status':'completed','error':None}}})
 if method=='turn/start' and mode=='fail':
  send({'method':'turn/completed','params':{'threadId':'thread-test','turn':{'id':'turn-test','status':'failed','error':{'message':'usage_limit secret-fake-key'}}}})
 if method=='account/login/start' and mode=='ok':
  send({'method':'account/login/completed','params':{'loginId':'login-test','success':True}})
'''


@pytest.fixture
def server(monkeypatch, tmp_path):
    script=tmp_path/'fake.py';script.write_text(FAKE_SERVER,encoding='utf-8')
    log=tmp_path/'calls.jsonl';children=[];launch=[]
    actual=asyncio.create_subprocess_exec
    async def spawn(*args,**kw):
        launch.append((args,kw['env'].copy()))
        kw['env']['FAKE_LOG']=str(log)
        child=await actual(sys.executable,'-u',str(script),**kw);children.append(child);return child
    monkeypatch.setattr(connection.asyncio,'create_subprocess_exec',spawn)
    def session():return connection.CodexSession(sys.executable,profile=tmp_path/'profile')
    return session,log,children,launch


def test_protocol_final_response_auth_gate_and_profile_isolation(server,monkeypatch):
    factory,log,children,launch=server
    monkeypatch.setenv('OPENAI_API_KEY','secret-fake-key');monkeypatch.setenv('CODEX_API_KEY','fake')
    async def run():
        async with factory() as s:
            assert (await s.account())['plan']=='pro'
            assert (await s.models())[0]['model']=='gpt-6-astra'
            return await s.content('gpt-6-astra',[{'role':'system','content':'CAD'},{'role':'user','content':'wheel'}],{'type':'object'},'medium',lambda x:None)
    assert asyncio.run(run())=='{"answer":42}'
    assert children[0].returncode is not None
    args,env=launch[0]
    assert not any(k.startswith('OPENAI_') for k in env) and 'CODEX_API_KEY' not in env
    assert Path(env['CODEX_HOME']).name=='profile' and 'model_provider="openai"' in args
    requests=[json.loads(line) for line in log.read_text().splitlines()]
    start=next(q for q in requests if q['method']=='thread/start')
    assert start['params']['ephemeral'] and start['params']['sandbox']=='read-only'
    assert start['params']['config']['mcp_servers']=={'test.server':{'command':'example','enabled':False}}
    assert start['params']['config']['plugins']['demo@0.1']['enabled'] is False
    turn=next(q for q in requests if q['method']=='turn/start')
    assert turn['params']['serviceTier']=='default' and turn['params']['outputSchema']=={'type':'object'}


def test_api_key_account_is_rejected_before_generation(server,monkeypatch):
    factory,log,children,_=server;monkeypatch.setenv('FAKE_MODE','api')
    async def run():
        async with factory() as s:
            await s.content('gpt-6-astra',[{'content':'CAD'}],{},'medium',lambda x:None)
    with pytest.raises(ValueError,match='API 키는 사용하지'):asyncio.run(run())
    assert 'turn/start' not in log.read_text() and children[0].returncode is not None


def test_unlimited_cancel_interrupts_only_owned_child(server,monkeypatch):
    factory,log,children,_=server;monkeypatch.setenv('FAKE_MODE','wait');control=DraftControl();errors=[]
    async def run():
        async with factory() as s:
            return await s.content('gpt-6-astra',[{'role':'system','content':'CAD'}],{},'medium',lambda x:None)
    def work():
        try:asyncio.run(control.execute(run,None))
        except Exception as exc:errors.append(exc)
    t=threading.Thread(target=work);t.start()
    import time
    end=time.monotonic()+10
    while time.monotonic()<end and (not log.exists() or 'turn/start' not in log.read_text()):time.sleep(.02)
    assert log.exists() and 'turn/start' in log.read_text()
    control.cancel();t.join(5)
    assert not t.is_alive() and isinstance(errors[0],DraftCancelled)
    assert children[0].returncode is not None and 'turn/interrupt' in log.read_text()


def test_failed_turn_is_actionable_without_secret(server,monkeypatch):
    factory,log,children,_=server;monkeypatch.setenv('FAKE_MODE','fail')
    async def run():
        async with factory() as s:
            await s.content('gpt-6-astra',[{'role':'system','content':'CAD'}],{},'medium',lambda x:None)
    with pytest.raises(ValueError,match='사용량 한도') as exc:asyncio.run(run())
    assert 'secret-fake' not in str(exc.value) and children[0].returncode is not None


def test_login_is_managed_by_codex_and_does_not_generate(server):
    factory,log,children,_=server;progress=[]
    async def run():
        async with factory() as s:return await s.login(progress.append)
    assert asyncio.run(run())=={'plan':'pro'}
    assert progress[0]['login_url'].startswith('https://auth.openai.com/')
    assert 'turn/start' not in log.read_text()


def test_unexpected_external_tool_blocks_before_model_request(server,monkeypatch):
    factory,log,children,_=server;monkeypatch.setenv('FAKE_MODE','tools')
    async def run():
        async with factory() as s:await s.content('gpt-6-astra',[{'content':'CAD'}],{},'medium',lambda x:None)
    with pytest.raises(ValueError,match='다른 도구를 분리'):asyncio.run(run())
    assert 'turn/start' not in log.read_text() and children[0].returncode is not None


@pytest.mark.parametrize('url',['http://auth.openai.com/login','https://auth.openai.com.evil.test/','https://user@chatgpt.com/','https://chatgpt.com:444/login','file:///tmp/key'])
def test_login_rejects_untrusted_urls(url):
    with pytest.raises(ValueError):connection.login_url(url)


def test_settings_store_only_selection(tmp_path,monkeypatch):
    monkeypatch.setenv('CADSTUDIO_DATA_DIR',str(tmp_path))
    connection.save_settings('example.exe','gpt-6-astra')
    assert connection.settings()==dict(executable='example.exe',model='gpt-6-astra')
    assert set(json.loads((tmp_path/'codex-settings.json').read_text()))=={'executable','model'}


def test_existing_codex_home_is_reused_without_reading_credentials(server,monkeypatch,tmp_path):
    _,log,children,launch=server
    monkeypatch.setenv('CODEX_HOME',str(tmp_path/'existing-codex'))
    monkeypatch.setenv('CADSTUDIO_DATA_DIR',str(tmp_path/'cad'))
    async def run():
        async with connection.CodexSession(sys.executable) as s:
            return await s.account()
    assert asyncio.run(run())=={'plan':'pro'}
    assert launch[0][1]['CODEX_HOME']==str(tmp_path/'existing-codex')
    assert not (tmp_path/'existing-codex').exists()  # Adapter never reads/writes/copies the auth store.
    assert 'account/login/start' not in log.read_text()
