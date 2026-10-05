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
from collections import deque
from urllib.parse import quote, urlsplit

import httpx

from .references import MAX_BYTES, MAX_CHARS, SUFFIXES, extract_reference
from .models import ReferenceMaterial

TOKEN_URL='https://github.com/settings/personal-access-tokens/new'
MAX_TREE_ENTRIES=100000
MAX_TREE_REQUESTS=1024
MAX_AUTO_FILES=24
MAX_AUTO_BYTES=12_000_000
AUTO_REFERENCE_NOTE='Repository scope snapshot; '


def scope_path(value):
    value=str(value or '').strip().strip('/')
    return file_path(value) if value else ''


def is_repository_snapshot(reference,repo):
    return (reference.note.startswith(AUTO_REFERENCE_NOTE)
            and reference.source.startswith('https://github.com/'+repository(repo)+'/tree/'))


def repository_index_reference(connection,*,max_chars=MAX_CHARS):
    """Transmit an honest bounded index, while the viewer retains full metadata."""
    repo=repository(connection['repo']);revision=connection['revision']
    if not re.fullmatch('[a-f0-9]{40}',revision):raise ValueError('저장소에 다시 연결하세요.')
    entries=connection.get('entries',connection['files'])
    scope=connection.get('scope_path','')
    header=(f'# Repository reference index\nRepository: https://github.com/{repo}\nCommit: {revision}\n'
            f'Scope: /{scope}\nIndexed paths in scope: {len(entries)}\n'
            f'Readable text/PDF candidates: {len(connection["files"])}\n'
            f'Tree enumeration complete: {not connection.get("truncated",False)}\n'
            'Listed paths are metadata, not proof that their contents were read. '
            'Only bounded text excerpts are supplied; binaries, large files, symlinks and submodules are not read or executed.\n\n'
            '## Repository path index\n')
    body=header+'\n'.join(f'{row["path"]} | {row.get("type","blob")} | {row.get("size",0)} bytes | {row["sha"]}' for row in entries)
    clipped=body[:max(1,min(MAX_CHARS,int(max_chars)))]
    return ReferenceMaterial(name=(repo.replace('/','-')+'-repository-index.md')[-80:],
        source=f'https://github.com/{repo}/tree/{revision}#cad-reference-index',revision=revision,
        sha256=hashlib.sha256(body.encode('utf-8')).hexdigest(),text=clipped,
        truncated=len(clipped)<len(body) or bool(connection.get('truncated')),
        note=AUTO_REFERENCE_NOTE+f'selected scope metadata indexed: {len(entries)} paths; '+
             ('tree enumeration incomplete; ' if connection.get('truncated') else 'tree enumeration complete; ')+
             'only the visible index excerpt is transmitted if truncated. File bodies are separate bounded excerpts.')


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

    async def tree_entries(self,client,repo,revision,control):
        tree=await self.get(client,'/repos/'+repo+'/git/trees/'+revision+'?recursive=1')
        if not tree.get('truncated'):
            rows=tree.get('tree',[])
            return rows[:MAX_TREE_ENTRIES],len(rows)>MAX_TREE_ENTRIES
        # GitHub truncates large recursive trees. Walk immutable subtrees from
        # the root instead of calling an incomplete index a whole repository.
        rows=[];pending=deque([('',revision)]);cache={};requests=0;truncated=False
        while pending:
            control.check();prefix,sha=pending.popleft()
            if sha not in cache:
                if requests>=MAX_TREE_REQUESTS:truncated=True;break
                subtree=await self.get(client,'/repos/'+repo+'/git/trees/'+sha)
                cache[sha]=subtree.get('tree',[]);requests+=1
                if subtree.get('truncated'):truncated=True
            for raw in cache[sha]:
                path=file_path(prefix+raw['path']);row={**raw,'path':path}
                rows.append(row)
                if len(rows)>=MAX_TREE_ENTRIES:truncated=True;break
                if row.get('type')=='tree' and re.fullmatch('[a-f0-9]{40}',row.get('sha','')):
                    pending.append((path+'/',row['sha']))
            if len(rows)>=MAX_TREE_ENTRIES:break
        return rows,truncated or bool(pending)

    def connect(self,repo,ref,control,path=''):
        repo=repository(repo);ref=ref.strip()
        selected_scope=scope_path(path)
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
            tree,truncated=await self.tree_entries(client,repo,revision,control)
            files=[];entries=[]
            for row in tree:
                path=file_path(row['path'])
                if selected_scope and path!=selected_scope and not path.startswith(selected_scope+'/'):continue
                size=row.get('size',0);sha=row.get('sha','')
                if not isinstance(size,int) or isinstance(size,bool) or size<0 or not re.fullmatch('[a-f0-9]{40}',sha):continue
                entries.append({'path':path,'size':size,'sha':sha,'type':row.get('type',''),'mode':row.get('mode','')})
                if (row.get('type')!='blob' or row.get('mode') not in ('100644','100755')
                        or Path(path).suffix.lower() not in SUFFIXES or not 0<size<=MAX_BYTES):continue
                files.append({'path':path,'size':size,'sha':sha})
            if selected_scope and not entries:raise ValueError('선택한 저장소 경로를 찾지 못했습니다. 경로를 비워 전체 저장소를 연결하세요.')
            files.sort(key=lambda r:(not Path(r['path']).name.lower().startswith('readme'),
                                     Path(r['path']).suffix.lower() not in {'.md','.rst','.txt'},
                                     r['path'].startswith('.'),r['path'].lower()))
            entries.sort(key=lambda r:r['path'].casefold())
            return {'repo':repo,'branch':branch,'revision':revision,'login':account.get('login',''),
                    'private':bool(meta.get('private')),'files':files,'entries':entries,
                    'scope_path':selected_scope,'indexed_paths':len(entries),'truncated':truncated}
        return self.run(work,control)

    def snapshot(self,connection,control,*,max_chars=60000,max_references=3):
        """Read a bounded automatic overview of an already pinned whole scope.

        Every indexed path remains visible in the viewer. Text budgets do not
        pretend that all bodies were read; users can still attach exact files.
        """
        if max_chars<1 or max_references<1:raise ValueError('참고자료 용량이 가득 찼습니다. 기존 자료를 일부 제거한 뒤 연결하세요.')
        max_chars=min(60000,int(max_chars));max_references=min(8,int(max_references))
        repo=repository(connection['repo']);revision=connection['revision']
        if not re.fullmatch('[a-f0-9]{40}',revision):raise ValueError('저장소에 다시 연결하세요.')
        index=repository_index_reference(connection,max_chars=min(MAX_CHARS,max_chars))
        if max_references==1 or len(index.text)>=max_chars:return [index]
        available=min(max_chars-len(index.text),MAX_CHARS*(max_references-1))
        async def work(client):
            sections=[];read=[];skipped=[];bytes_read=0;used=0
            for row in connection['files']:
                control.check();path=file_path(row['path']);sha=row['sha'];size=row['size']
                if len(read)>=MAX_AUTO_FILES or available-used<200:break
                if (not re.fullmatch('[a-f0-9]{40}',sha) or not isinstance(size,int)
                        or not 0<size<=MAX_BYTES):raise ValueError('저장소 파일 목록을 다시 조회하세요.')
                if bytes_read+size>MAX_AUTO_BYTES:skipped.append(path);continue
                blob=await self.get(client,'/repos/'+repo+'/git/blobs/'+sha)
                if blob.get('encoding')!='base64':skipped.append(path);continue
                try:data=base64.b64decode(''.join(blob['content'].split()),validate=True)
                except (KeyError,ValueError):raise ValueError('파일 내용을 읽지 못했습니다.') from None
                if (len(data)!=size or len(data)>MAX_BYTES
                        or hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()!=sha):
                    raise ValueError('파일 버전 또는 크기가 달라졌습니다. 저장소에 다시 연결하세요.')
                bytes_read+=len(data)
                source=f'https://github.com/{repo}/blob/{revision}/{quote(path,safe="/")}'
                try:reference=extract_reference(Path(path).name,data,source=source,revision=revision,check=control.check)
                except ValueError:skipped.append(path);continue
                prefix=f'\n\n## {path}\nSource: {source}\nBlob: {sha}\n'
                budget=min(4000,available-used-len(prefix)-80)
                if budget<=0:break
                excerpt=reference.text[:budget]
                clipped=reference.truncated or len(excerpt)<len(reference.text)
                section=prefix+('Bounded excerpt; remaining contents were not transmitted.\n' if clipped else 'Text snapshot.\n')+excerpt
                section=section[:available-used]
                sections.append(section);used+=len(section);read.append(path)
            combined=''.join(sections)
            references=[index]
            for offset in range(0,len(combined),MAX_CHARS):
                text=combined[offset:offset+MAX_CHARS]
                chunk=offset//MAX_CHARS+1
                references.append(ReferenceMaterial(name=(repo.replace('/','-')+f'-repository-excerpts-{chunk}.md')[-80:],
                    source=f'https://github.com/{repo}/tree/{revision}#cad-reference-excerpts-{chunk}',revision=revision,
                    sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),text=text,truncated=True,
                    note=AUTO_REFERENCE_NOTE+f'{len(read)}/{len(connection["files"])} readable candidates included; '
                         f'{len(skipped)} skipped after extraction/byte checks. Excerpts only; code is never executed.'))
            index.note+=f' Automatic text excerpts cover {len(read)}/{len(connection["files"])} candidates.'
            return references
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
