"""GitHub reference reader. GET only; fixed host, bounded snapshots, no execution."""
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import quote, urlsplit

import httpx

from .references import MAX_BYTES, SUFFIXES, extract_reference

TOKEN_URL='https://github.com/settings/personal-access-tokens/new'


def repository(value):
    value=value.strip().rstrip('/')
    if value.startswith('https://'):
        url=urlsplit(value)
        if url.netloc!='github.com' or url.query or url.fragment:raise ValueError('github.com 저장소 주소를 입력하세요.')
        value=url.path.strip('/')
    if value.endswith('.git'):value=value[:-4]
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}',value) or value.split('/')[1] in ('.','..'):
        raise ValueError('저장소 주소는 https://github.com/소유자/저장소 또는 소유자/저장소 형식입니다.')
    return value


def file_path(value):
    if len(value)>1000 or '\\' in value or any(ord(c)<32 for c in value) or value.startswith('/') or any(p in ('.','..','') for p in value.split('/')):
        raise ValueError('저장소 안의 올바른 파일 경로를 선택하세요.')
    return value


def token_value(value):
    value=value.strip()
    if len(value)>500 or (value and not re.fullmatch(r'[A-Za-z0-9_]+',value)):
        raise ValueError('GitHub 토큰에 공백 또는 지원하지 않는 문자가 있습니다.')
    return value


def existing_token(repo):
    """Only called by an explicit 'use existing Git login' action. Never log output."""
    repo=repository(repo)
    git=shutil.which('git')
    if not git:
        path=Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Git/cmd/git.exe'
        if path.is_file():git=str(path)
    if not git:raise ValueError('Git을 찾지 못했습니다. GitHub 읽기 토큰을 입력하세요.')
    try:
        result=subprocess.run([git,'-c','credential.interactive=false','credential','fill'],
            input=f'protocol=https\nhost=github.com\npath={repo}.git\n\n',text=True,capture_output=True,timeout=12,
            cwd=Path(git).parent,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),
            env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='never'))
        value=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line).get('password','')
        if result.returncode or not value:raise ValueError()
        return token_value(value)
    except Exception:raise ValueError('저장된 GitHub 인증을 찾지 못했습니다. 읽기 토큰을 입력하세요.') from None


class GitHubReader:
    def __init__(self,token='',transport=None):
        self.token=token_value(token);self.transport=transport

    async def get(self,client,path,limit=12_000_000):
        # No response URLs, redirects, download_url or external submodule hosts are used.
        async with client.stream('GET',path) as response:
            code=response.status_code
            if code!=200:
                message={401:'GitHub 인증이 만료되었거나 올바르지 않습니다.',403:'GitHub 읽기 권한 또는 API 요청 한도를 확인하세요.',404:'저장소·브랜치·파일을 찾지 못했습니다. 비공개 저장소의 읽기 권한도 확인하세요.',429:'GitHub 요청 한도에 도달했습니다. 잠시 뒤 다시 시도하세요.'}.get(code,'GitHub 자료를 읽지 못했습니다.')
                raise ValueError(f'{message} (HTTP {code})')
            chunks=[];size=0
            async for chunk in response.aiter_bytes():
                size+=len(chunk)
                if size>limit:raise ValueError('GitHub 응답이 너무 큽니다. 작은 문서나 더 좁은 저장소를 선택하세요.')
                chunks.append(chunk)
        try:return json.loads(b''.join(chunks))
        except (ValueError,UnicodeError):raise ValueError('GitHub 응답 형식을 읽지 못했습니다.') from None

    def run(self,operation,control):
        async def work():
            headers={'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'PromptCADStudio-references'}
            if self.token:headers['Authorization']='Bearer '+self.token
            try:
                async with httpx.AsyncClient(base_url='https://api.github.com',headers=headers,timeout=20,trust_env=False,follow_redirects=False,transport=self.transport) as client:
                    return await operation(client)
            except httpx.HTTPError:raise ValueError('GitHub 연결에 실패했습니다. 네트워크를 확인하세요.') from None
        return asyncio.run(control.execute(work,45,'GitHub 자료 조회 시간이 초과되었습니다. 다시 연결하세요.'))

    def connect(self,repo,ref,control):
        repo=repository(repo);ref=ref.strip()
        if len(ref)>240 or any(ord(c)<32 for c in ref):raise ValueError('브랜치 이름을 확인하세요.')
        async def work(client):
            account=await self.get(client,'/user',1_000_000) if self.token else {}
            meta=await self.get(client,'/repos/'+repo,1_000_000)
            branch=ref or meta.get('default_branch','')
            if not branch:raise ValueError('아직 파일이 없는 저장소입니다.')
            # Resolve once: all files come from a single immutable commit snapshot.
            commit=await self.get(client,'/repos/'+repo+'/commits/'+quote(branch,safe=''),4_000_000)
            revision=commit.get('sha','')
            if not re.fullmatch('[a-f0-9]{40}',revision):raise ValueError('저장소 버전을 확인하지 못했습니다.')
            tree=await self.get(client,'/repos/'+repo+'/git/trees/'+revision+'?recursive=1')
            files=[]
            for row in tree.get('tree',[]):
                if row.get('type')!='blob' or row.get('mode') not in ('100644','100755'):continue
                path=file_path(row['path'])
                if Path(path).suffix.lower() not in SUFFIXES:continue
                size=row.get('size',0);sha=row.get('sha','')
                if not isinstance(size,int) or not 0<size<=MAX_BYTES or not re.fullmatch('[a-f0-9]{40}',sha):continue
                files.append({'path':path,'size':size,'sha':sha})
            files.sort(key=lambda r:(not Path(r['path']).name.lower().startswith('readme'),r['path'].lower()))
            return {'repo':repo,'branch':branch,'revision':revision,'login':account.get('login',''),
                    'private':bool(meta.get('private')),'files':files,'truncated':bool(tree.get('truncated'))}
        return self.run(work,control)

    def fetch(self,connection,rows,control):
        repo=repository(connection['repo']);revision=connection['revision']
        if not re.fullmatch('[a-f0-9]{40}',revision):raise ValueError('저장소에 다시 연결하세요.')
        if not 1<=len(rows)<=8:raise ValueError('참고할 파일을 1~8개 선택하세요.')
        allowed={r['path']:r for r in connection['files']}
        for row in rows:
            if allowed.get(row['path'])!=row:raise ValueError('연결한 저장소의 파일을 다시 선택하세요.')
        async def work(client):
            result=[]
            for row in rows:
                control.check();blob=await self.get(client,'/repos/'+repo+'/git/blobs/'+row['sha'])
                if blob.get('encoding')!='base64':raise ValueError('파일 내용을 읽지 못했습니다.')
                try:data=base64.b64decode(''.join(blob['content'].split()),validate=True)
                except (KeyError,ValueError):raise ValueError('파일 내용을 읽지 못했습니다.') from None
                if len(data)>MAX_BYTES or hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()!=row['sha']:
                    raise ValueError('파일 버전 또는 크기가 달라졌습니다. 저장소에 다시 연결하세요.')
                path=row['path'];source=f'https://github.com/{repo}/blob/{revision}/{quote(path,safe="/")}'
                result.append(extract_reference(Path(path).name,data,source=source,revision=revision,check=control.check))
            return result
        return self.run(work,control)
