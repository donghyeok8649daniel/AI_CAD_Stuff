"""Native document state and branching history, compatible with CAD JSON v2."""
from copy import deepcopy
from datetime import datetime,timezone
import json
import os
from pathlib import Path
from uuid import uuid4
from pydantic import TypeAdapter
from ..models import Design,Project,HistoryChange
from ..history import apply_changes


MAX_PROJECT_READ_BYTES=512*1024*1024
_PROJECT_JSON=TypeAdapter(Project)


def differences(before,after,path=()):
    if before==after:return []
    if isinstance(before,dict) and isinstance(after,dict):
        changes=[]
        for key in dict.fromkeys([*before,*after]):
            target=[*path,key]
            if key not in after:changes.append(dict(path=target,operation='remove',existed=True,before=deepcopy(before[key]),after=None))
            elif key not in before:changes.append(dict(path=target,operation='set',existed=False,before=None,after=deepcopy(after[key])))
            else:changes.extend(differences(before[key],after[key],target))
        return changes
    if isinstance(before,list) and isinstance(after,list) and len(before)==len(after):
        return [change for i,(a,b) in enumerate(zip(before,after)) for change in differences(a,b,(*path,i))]
    return [dict(path=list(path),operation='set',existed=True,before=deepcopy(before),after=deepcopy(after))]


class Journal:
    def __init__(self,design=None,label='설계 시작',data=None,context=None):
        context=context or {}
        if data:self.data=deepcopy(data)
        else:
            entry=self.entry(None,label,[],context)
            self.data=dict(version=1,base=deepcopy(design),entries=[entry],cursor=entry['id'],head=entry['id'])
        self.index={e['id']:e for e in self.data['entries']}
        self.cache={}

    @staticmethod
    def entry(parent,label,changes,context):
        return dict(id='step-'+uuid4().hex,parent=parent,label=label,created_at=datetime.now(timezone.utc).isoformat(),source=context.get('source','manual'),changes=changes,context=deepcopy(context))

    def path(self,identifier=None):
        identifier=identifier or self.data['head'];result=[]
        while identifier:
            e=self.index[identifier];result.append(e);identifier=e['parent']
        return result[::-1]

    def at(self,identifier):
        if identifier in self.cache:return deepcopy(self.cache[identifier])
        data=deepcopy(self.data['base'])
        for entry in self.path(identifier):
            data=apply_changes(data,[HistoryChange.model_validate(c) for c in entry['changes']])
        self.cache[identifier]=data
        if len(self.cache)>8:self.cache.pop(next(iter(self.cache)))
        return deepcopy(data)

    def append(self,before,after,label,context=None):
        context=context or {};changes=differences(before,after)
        if not changes and not context.get('tool_actions'):return
        entry=self.entry(self.data['cursor'],label,changes,context)
        self.data['entries'].append(entry);self.index[entry['id']]=entry
        self.data['cursor']=self.data['head']=entry['id']
        self.cache[entry['id']]=deepcopy(after)
        if len(self.cache)>8:self.cache.pop(next(iter(self.cache)))

    def move(self,identifier):
        if identifier not in self.index:raise ValueError('기록 단계를 찾을 수 없습니다.')
        if identifier not in [e['id'] for e in self.path()]:self.data['head']=identifier
        self.data['cursor']=identifier


class Document:
    def __init__(self):
        self.design=None;self.journal=None;self.path=None;self.prompt='';self.dirty=False

    def project(self):
        if self.design is None:raise ValueError('스케치 또는 부품을 먼저 만드세요.')
        return Project(design=self.design,history=self.journal.data if self.journal else None,prompt=self.prompt)

    def commit(self,design,label,context=None,cursor=None):
        data=design.model_dump() if isinstance(design,Design) else deepcopy(design)
        if not cursor and context and context.get('journal_steps'):
            self.commit_steps(data,context);return
        if not self.journal:self.journal=Journal(data,label,context=context)
        elif cursor:self.journal.move(cursor)
        else:self.journal.append(self.design,data,label,context)
        self.design=data;self.dirty=True

    def commit_steps(self,data,context):
        """Install a verified AI transaction with independently restorable steps."""
        from .cad_tools import TOOL_LABELS
        common={k:deepcopy(v) for k,v in context.items() if k not in ('journal_steps','journal_base','tool_actions')}
        before=deepcopy(self.design if self.design is not None else context.get('journal_base'))
        if before is None:raise ValueError('AI 작업 기록의 시작 설계가 없습니다.')
        Design.model_validate(before)
        journal=Journal(data=self.journal.data) if self.journal else Journal(before,'AI 설계 시작',context=common)
        for row in context['journal_steps']:
            action=row['action'];changes=[HistoryChange.model_validate(c) for c in row['changes']]
            after=apply_changes(before,changes)
            Design.model_validate(after)
            title='AI '+TOOL_LABELS.get(action['tool'],action['tool'])+' · '+action['target']
            journal.append(before,after,title,{**common,'tool_actions':[action],'part_id':action['target']})
            before=after
        if before!=data:raise ValueError('AI 작업 기록과 최종 설계가 다릅니다. 다시 생성하세요.')
        # No mutation before the entire sequence and final snapshot match.
        self.journal=journal;self.design=deepcopy(data);self.dirty=True

    def load(self,project,path=None):
        project=project if isinstance(project,Project) else Project.model_validate(project)
        self.design=project.design.model_dump();self.prompt=project.prompt
        self.journal=Journal(data=project.history.model_dump()) if project.history else Journal(self.design,'프로젝트 가져오기',context={'source':'import'})
        self.path=Path(path) if path else None;self.dirty=False

    def write(self,path,*,autosave=False):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        # Pydantic emits compact UTF-8 bytes directly: keep every history step
        # and embedded asset without an indented string or a second encoding.
        data=_PROJECT_JSON.dump_json(self.project())
        temp=path.with_suffix('.'+uuid4().hex+'.tmp')
        try:
            with temp.open('xb') as stream:
                stream.write(data);stream.flush();os.fsync(stream.fileno())
            os.replace(temp,path)
        finally:
            try:temp.unlink(missing_ok=True)
            except OSError:pass  # Preserve the original write/replace failure.
        if not autosave:self.path=path;self.dirty=False


def read_project(path,*,max_bytes=MAX_PROJECT_READ_BYTES):
    """Read a checked project with a bounded default, adjustable by the caller."""
    path=Path(path)
    if max_bytes is not None and (type(max_bytes) is not int or max_bytes<=0):
        raise ValueError('프로젝트 읽기 한도는 양의 바이트 수 또는 None이어야 합니다.')
    def check_size(size):
        if max_bytes is not None and size>max_bytes:
            raise ValueError(f'프로젝트 파일은 {size/1024**2:.1f} MiB입니다. '
                f'현재 읽기 한도 {max_bytes/1024**2:g} MiB를 넘습니다. '
                '원본과 작업 기록은 변경되지 않았습니다. 더 큰 한도를 명시하여 다시 불러오세요.')
    check_size(path.stat().st_size)
    with path.open('rb') as stream:
        data=stream.read() if max_bytes is None else stream.read(max_bytes+1)
    check_size(len(data))
    return Project.model_validate_json(data.removeprefix(b'\xef\xbb\xbf'))
