from pathlib import Path
import threading
import httpx
import pytest
import cadstudio.ollama_setup as setup


def test_installed_model_is_reused_without_installer_or_pull(monkeypatch):
    calls=[]
    def request(req):
        calls.append((req.method,req.url.path))
        return httpx.Response(200,json={'version':'0.34.3'} if req.url.path=='/api/version' else {'models':[{'name':'qwen3:8b'}]})
    client=httpx.Client(transport=httpx.MockTransport(request));monkeypatch.setattr(setup,'executable',lambda:Path('existing-ollama.exe'));monkeypatch.setattr(setup.httpx,'Client',lambda **kwargs:client)
    monkeypatch.setattr(setup.subprocess,'run',lambda *a,**kw:pytest.fail('must reuse existing installation'))
    assert setup.setup('qwen3:8b')=='qwen3:8b'
    assert calls==[('GET','/api/version'),('GET','/api/tags')]


def test_cancel_before_network_or_model_download(monkeypatch):
    monkeypatch.setattr(setup,'executable',lambda:Path('existing.exe'));event=threading.Event();event.set()
    with pytest.raises(ValueError,match='중단'):setup.setup('qwen3:8b',cancel=event)


def test_only_supported_model_names_can_reach_installer():
    with pytest.raises(ValueError,match='선택'):setup.setup('unexpected-model')


def test_discovery_reads_names_without_pulling(monkeypatch):
    calls=[]
    def request(req):
        calls.append((req.method,str(req.url)));return httpx.Response(200,json={'models':[{'name':'qwen3:8b'},{'name':'custom:latest'},{'name':'qwen3:8b'}]})
    client=httpx.Client(transport=httpx.MockTransport(request));monkeypatch.setattr(setup.httpx,'Client',lambda **kwargs:client)
    assert setup.discover_models()==['custom:latest','qwen3:8b'];assert calls==[('GET','http://127.0.0.1:11434/api/tags')]


def test_discovery_starts_existing_server_only(monkeypatch):
    calls=[];process=[]
    def request(req):
        calls.append(req)
        if len(calls)==1:raise httpx.ConnectError('offline',request=req)
        return httpx.Response(200,json={'models':[{'name':'local-model'}]})
    client=httpx.Client(transport=httpx.MockTransport(request));monkeypatch.setattr(setup.httpx,'Client',lambda **kwargs:client);monkeypatch.setattr(setup,'executable',lambda:Path('ollama.exe'));monkeypatch.setattr(setup.subprocess,'Popen',lambda args,**kwargs:process.append((args,kwargs)));monkeypatch.setattr(setup.time,'sleep',lambda _:None)
    assert setup.discover_models()==['local-model'];assert process[0][0]==['ollama.exe','serve'];assert process[0][1]['env']['OLLAMA_HOST']=='127.0.0.1:11434'
