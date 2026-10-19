"""Native document state and branching history, compatible with CAD JSON v2."""
from copy import deepcopy
from datetime import datetime,timezone
import json
import os
from pathlib import Path
from typing import Annotated
from uuid import uuid4
from pydantic import BeforeValidator,TypeAdapter,ValidationError
from ..models import Design,Project,HistoryChange
from ..history import apply_changes


MAX_PROJECT_READ_BYTES=512*1024*1024
_PROJECT_JSON=TypeAdapter(Project)


def _atomic_project_write(path,data,publish=None):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.'+uuid4().hex+'.tmp')
    try:
        with temp.open('xb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        if publish is None:os.replace(temp,path)
        else:return publish(temp,path)
    finally:
        try:temp.unlink(missing_ok=True)
        except OSError:pass  # Preserve the original write/replace failure.
    return True


def _project_payload_preflight(payload):
    # Pydantic has decoded this JSON object once. Inspect that same raw tree
    # before constructing models; do not decode or validate a second time.
    from ..pcb_compatibility import preflight,CURRENT_PROFILE,PCBCompatibilityError
    report=preflight(payload,CURRENT_PROFILE)
    if not report['compatible']:raise PCBCompatibilityError(report)
    return payload


_PROJECT_READ_JSON=TypeAdapter(Annotated[Project,BeforeValidator(_project_payload_preflight)])


def _plain_json_tree(value):
    # Public Journal callers may supply tuples, custom containers or shared
    # references. Path copying must not change their deepcopy semantics.
    # This is an optimization budget, not a project acceptance limit.
    pending=[iter((value,))];seen=set();remaining=100_000
    while pending:
        try:item=next(pending[-1])
        except StopIteration:
            pending.pop();continue
        remaining-=1
        if remaining<0:return False
        kind=type(item)
        if kind in (dict,list):
            identifier=id(item)
            if identifier in seen:return False
            seen.add(identifier)
            if kind is dict:
                if any(type(key) is not str for key in item):return False
                pending.append(iter(item.values()))
            else:pending.append(iter(item))
        elif kind not in (str,int,float,bool,type(None)):return False
    return True


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
    def __init__(self,design=None,label='설계 시작',data=None,context=None,*,_owned_data=False):
        context=context or {}
        if data:self.data=data if _owned_data else deepcopy(data)
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
        path_copy=type(data) in (dict,list) and _plain_json_tree(data)
        for entry in self.path(identifier):
            changes=[HistoryChange.model_validate(c) for c in entry['changes']]
            path_copy=path_copy and all(_plain_json_tree(change.after) for change in changes)
            data=apply_changes(data,changes,_path_copy=path_copy)
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
        context=self._history_bound_context(context)
        data=design.model_dump() if isinstance(design,Design) else deepcopy(design)
        if not cursor and context and context.get('journal_steps'):
            self.commit_steps(data,context);return
        if not self.journal:self.journal=Journal(data,label,context=context)
        elif cursor:self.journal.move(cursor)
        else:self.journal.append(self.design,data,label,context)
        self.design=data;self.dirty=True

    def commit_steps(self,data,context):
        """Install a verified AI transaction with independently restorable steps."""
        context=self._history_bound_context(context)
        from .cad_tools import TOOL_LABELS
        common={k:deepcopy(v) for k,v in context.items() if k not in ('journal_steps','journal_base','tool_actions')}
        before=deepcopy(self.design if self.design is not None else context.get('journal_base'))
        if before is None:raise ValueError('AI 작업 기록의 시작 설계가 없습니다.')
        Design.model_validate(before)
        if self.journal:
            # Saved records/base are append-only here. Give the candidate its
            # own cursor/head dictionary, entries list, index and cache without
            # cloning every historical geometry/context payload. The default
            # public Journal(data=...) constructor still owns a deep copy.
            candidate={**self.journal.data,'entries':list(self.journal.data['entries'])}
            journal=Journal(data=candidate,_owned_data=True)
        else:journal=Journal(before,'설계 시작',context=common)
        for row in context['journal_steps']:
            action=row['action'];changes=[HistoryChange.model_validate(c) for c in row['changes']]
            after=apply_changes(before,changes)
            Design.model_validate(after)
            title=TOOL_LABELS.get(action['tool'],action['tool'])+' · '+action['target']
            journal.append(before,after,title,{**common,'tool_actions':[action],'part_id':action['target']})
            before=after
        if before!=data:raise ValueError('AI 작업 기록과 최종 설계가 다릅니다. 다시 생성하세요.')
        # No mutation before the entire sequence and final snapshot match.
        # Allocate the final snapshot before publishing either state. If this
        # copy raises (for example MemoryError), keep the old design AND journal.
        final_design=deepcopy(data)
        self.journal=journal;self.design=final_design;self.dirty=True

    def _history_bound_context(self,context):
        if context and '_ai_history_binding' in context:
            from ..ai_work_history import require_history_binding
            require_history_binding(self,context['_ai_history_binding'])
            return {key:value for key,value in context.items() if key!='_ai_history_binding'}
        return context

    def load(self,project,path=None):
        project=project if isinstance(project,Project) else Project.model_validate(project)
        design=project.design.model_dump();prompt=project.prompt
        # model_dump owns fresh JSON containers. A second complete copy of the
        # large embedded history adds no isolation; standalone Journal callers
        # still get an independent copy by default.
        journal=Journal(data=project.history.model_dump(),_owned_data=True) if project.history else Journal(design,'프로젝트 가져오기',context={'source':'import'})
        resolved_path=Path(path) if path else None
        # Keep the currently open document intact if validation, allocation or
        # path conversion fails while constructing the incoming state.
        self.design=design;self.prompt=prompt;self.journal=journal;self.path=resolved_path;self.dirty=False

    def write(self,path,*,autosave=False):
        path=Path(path)
        # Pydantic emits compact UTF-8 bytes directly: keep every history step
        # and embedded asset without an indented string or a second encoding.
        data=_PROJECT_JSON.dump_json(self.project())
        _atomic_project_write(path,data)
        if not autosave:self.path=path;self.dirty=False

    def autosave_snapshot(self):
        """Own just the persisted state, without replaying history on the UI thread."""
        snapshot=Document()
        state=deepcopy(dict(design=self.design,history=self.journal.data if self.journal else None,prompt=self.prompt))
        snapshot.design=state['design'];snapshot.prompt=state['prompt']
        if state['history'] is not None:snapshot.journal=Journal(data=state['history'],_owned_data=True)
        return snapshot


def resolve_project_path(path):
    """Follow a migrated legacy filename only when the requested file is gone."""
    path=Path(path)
    if not path.exists() and path.name.lower().endswith('.cad.json'):
        migrated=path.with_name(path.name[:-9]+'.pcad')
        if migrated.is_file():return migrated
    return path


def read_project(path,*,max_bytes=MAX_PROJECT_READ_BYTES,fingerprint=None):
    """Read a checked project with a bounded default, adjustable by the caller."""
    path=resolve_project_path(path)
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
    try:
        project=_PROJECT_READ_JSON.validate_json(data.removeprefix(b'\xef\xbb\xbf'))
        if fingerprint is not None:
            from hashlib import sha256
            fingerprint(sha256(data).hexdigest())
        return project
    except ValidationError as exc:
        # BeforeValidator wraps ValueErrors. Preserve the machine-readable
        # compatibility report without parsing or running validation again.
        from ..pcb_compatibility import PCBCompatibilityError
        for error in exc.errors(include_url=False,include_input=False):
            original=error.get('ctx',{}).get('error')
            if isinstance(original,PCBCompatibilityError):raise original from exc
        raise
