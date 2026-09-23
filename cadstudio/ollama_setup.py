"""Optional Windows AI setup; pinned official installer, verified before launch."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request
import httpx

INSTALLER_URL='https://github.com/ollama/ollama/releases/download/v0.34.3/OllamaSetup.exe'
INSTALLER_SHA256='fe1cce219b07ba13982a9419bfa3697c911bf77667ee636c967baed1b06ee3a0'
MODELS={'qwen3:4b':'약 2.5GB','qwen3:8b':'약 5.2GB'}


def executable():
    path=shutil.which('ollama')
    if path:return Path(path)
    candidate=Path(os.environ.get('LOCALAPPDATA',''))/'Programs/Ollama/ollama.exe'
    return candidate if candidate.is_file() else None


def installed_models():
    try:
        with httpx.Client(trust_env=False,timeout=3) as client:
            response=client.get('http://127.0.0.1:11434/api/tags');response.raise_for_status();return [m['name'] for m in response.json().get('models',[])]
    except (httpx.HTTPError,ValueError):return []


def loaded_model_status():
    """Report actual processor allocation, without loading/unloading any model."""
    try:
        with httpx.Client(trust_env=False,timeout=2,follow_redirects=False) as client:
            response=client.get('http://127.0.0.1:11434/api/ps');response.raise_for_status()
            result={}
            for model in response.json().get('models',[]):
                name=model.get('name') or model.get('model');size=model.get('size');vram=model.get('size_vram')
                if not isinstance(name,str) or not isinstance(size,(int,float)) or not isinstance(vram,(int,float)):continue
                if size<=0 or vram<0:continue
                ratio=min(100,max(0,round(100*vram/size)))
                result[name]=f'GPU {ratio}%' if ratio>=99 else f'CPU + GPU {ratio}%' if vram else 'CPU 실행 · 큰 모델은 응답이 느릴 수 있습니다'
            return result
    except (httpx.HTTPError,ValueError,TypeError,AttributeError):return {}


def discover_models():
    """Start an existing installation if needed; never install or pull implicitly."""
    with httpx.Client(trust_env=False,timeout=2,follow_redirects=False) as client:
        def read():
            response=client.get('http://127.0.0.1:11434/api/tags');response.raise_for_status()
            data=response.json()
            return sorted({m['name'] for m in data.get('models',[]) if isinstance(m,dict) and isinstance(m.get('name'),str) and m['name']})
        try:return read()
        except httpx.ConnectError:
            exe=executable()
            if exe is None:raise ValueError('Ollama가 없습니다. 아래 로컬 AI 설치 버튼을 사용하세요.') from None
            subprocess.Popen([str(exe),'serve'],env=dict(os.environ,OLLAMA_HOST='127.0.0.1:11434'),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                time.sleep(.3)
                try:return read()
                except httpx.ConnectError:pass
            raise ValueError('Ollama에 연결되지 않습니다. 실행 상태를 확인하고 새로 찾기를 누르세요.') from None
        except (httpx.HTTPError,ValueError,TypeError):raise ValueError('Ollama 모델 목록을 읽지 못했습니다. 실행 상태를 확인하세요.') from None


def setup(model,progress=lambda message:None,cancel=None):
    if model not in MODELS:raise ValueError('지원하는 로컬 모델을 선택하세요.')
    def check():
        if cancel is not None and cancel.is_set():raise ValueError('설치 / 다운로드를 중단했습니다. 다시 실행하면 모델 다운로드를 이어받습니다.')
    exe=executable()
    if exe is None:
        if os.name!='nt':raise ValueError('이 설치 도구는 Windows용입니다.')
        progress('Ollama 공식 설치 파일 다운로드 · 약 1.6GB · 완료 후 임시 설치 파일 삭제')
        with tempfile.TemporaryDirectory(prefix='PromptCAD-Ollama-') as folder:
            path=Path(folder)/'OllamaSetup.exe';digest=hashlib.sha256();size=0;last=0
            with urllib.request.urlopen(urllib.request.Request(INSTALLER_URL,headers={'User-Agent':'PromptCADStudio'}),timeout=45) as response,path.open('wb') as stream:
                total=int(response.headers.get('Content-Length',0))
                while chunk:=response.read(2**20):
                    check();size+=len(chunk);digest.update(chunk);stream.write(chunk)
                    if size-last>=32*2**20:progress(f'Ollama 설치 파일 {size/2**20:.0f} / {total/2**20:.0f} MiB');last=size
            if digest.hexdigest()!=INSTALLER_SHA256:raise ValueError('Ollama 설치 파일의 SHA256이 일치하지 않습니다. 실행하지 않았습니다.')
            check();progress('검증한 Ollama 설치 파일 실행 중…')
            result=subprocess.run([str(path),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-'],creationflags=subprocess.CREATE_NO_WINDOW,timeout=600)
            if result.returncode not in (0,3010):raise ValueError(f'Ollama 설치 실패: 종료 코드 {result.returncode}')
        exe=executable()
        if exe is None:raise ValueError('설치 후 Ollama 실행 파일을 찾지 못했습니다. Windows를 다시 시작한 뒤 확인하세요.')
    check();progress('Ollama 실행 상태 확인…')
    with httpx.Client(trust_env=False,timeout=httpx.Timeout(300,connect=4)) as client:
        def ready():
            try:return client.get('http://127.0.0.1:11434/api/version').status_code==200
            except httpx.HTTPError:return False
        if not ready():
            env=dict(os.environ,OLLAMA_HOST='127.0.0.1:11434');subprocess.Popen([str(exe),'serve'],env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            for _ in range(60):
                check()
                if ready():break
                time.sleep(.5)
            else:raise ValueError('Ollama 서버가 시작되지 않았습니다.')
        models=client.get('http://127.0.0.1:11434/api/tags').json().get('models',[])
        if any(m['name']==model for m in models):progress('이미 설치된 모델을 사용합니다: '+model);return model
        progress(f'{model} 다운로드 · {MODELS[model]} · 다른 CAD 설치본과 공용으로 사용')
        last=0
        with client.stream('POST','http://127.0.0.1:11434/api/pull',json={'model':model,'stream':True}) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                check()
                if not line:continue
                data=json.loads(line)
                if data.get('error'):raise ValueError(data['error'])
                if time.monotonic()-last>.75 or data.get('status')=='success':
                    progress(data.get('status','다운로드')+(f" · {data.get('completed',0)/2**30:.2f} / {data['total']/2**30:.2f} GiB" if data.get('total') else ''));last=time.monotonic()
        if model not in installed_models():raise ValueError('다운로드 후 모델 목록에서 확인하지 못했습니다. 다시 시도하세요.')
    progress(model+' 설치 완료');return model
