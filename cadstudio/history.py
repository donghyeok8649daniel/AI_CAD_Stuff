"""Replay checked declarative changes. No commands, expressions or file paths execute."""
from collections import Counter
from copy import deepcopy
import math


def equivalent(a,b):
    if isinstance(a,(float,int)) and not isinstance(a,bool) and isinstance(b,(float,int)) and not isinstance(b,bool):
        return math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-8)
    if type(a) is not type(b):return False
    if isinstance(a,dict):return a.keys()==b.keys() and all(equivalent(a[k],b[k]) for k in a)
    if isinstance(a,list):return len(a)==len(b) and all(equivalent(x,y) for x,y in zip(a,b))
    return a==b


def apply_changes(design,changes):
    result=deepcopy(design)
    for change in changes:
        node=result
        for key in change.path:
            if isinstance(key,str) and key in {'__proto__','constructor','prototype'}:
                raise ValueError('작업 이력에 허용되지 않는 경로가 있습니다.')
        try:
            for key in change.path[:-1]:
                if isinstance(node,list) and (type(key) is not int or key<0):raise KeyError(key)
                node=node[key]
            key=change.path[-1]
            if isinstance(node,list):
                if type(key) is not int or key<0 or key>=len(node) or change.operation=='remove':raise KeyError(key)
                exists=True
            elif isinstance(node,dict):exists=key in node
            else:raise KeyError(key)
            if exists!=change.existed or (exists and not equivalent(node[key],change.before)):
                raise ValueError('작업 이력의 이전 값이 실제 설계와 일치하지 않습니다.')
            if change.operation=='remove':
                if not exists:raise KeyError(key)
                del node[key]
            else:node[key]=deepcopy(change.after)
        except (KeyError,IndexError,TypeError):
            raise ValueError('작업 이력이 존재하지 않는 설계 항목을 참조합니다.') from None
    return result


def validate_history(journal,current):
    from .models import Design
    entries=journal.entries
    ids=[entry.id for entry in entries]
    if len(set(ids))!=len(ids) or journal.cursor not in ids or journal.head not in ids:
        raise ValueError('작업 이력 ID 또는 현재 단계가 올바르지 않습니다.')
    if entries[0].parent is not None or entries[0].changes:
        raise ValueError('첫 작업 단계는 변경 없는 초기 설계여야 합니다.')
    parents={};states={};uses=Counter(e.parent for e in entries if e.parent is not None)
    cursor_design=None
    for index,entry in enumerate(entries):
        if index==0:data=journal.base.model_dump()
        else:
            if entry.parent not in parents:raise ValueError('작업 이력이 이전에 존재하지 않는 단계에 연결되었습니다.')
            data=apply_changes(states[entry.parent],entry.changes)
            # Every past state must still be a valid declarative design. Only current geometry is built.
            checked=Design.model_validate(data).model_dump()
            if not equivalent(checked,data):raise ValueError('작업 이력에 해석 결과와 다른 형상·구속 값이 있습니다.')
            uses[entry.parent]-=1
            if uses[entry.parent]==0:states.pop(entry.parent,None)
        if uses[entry.id]:states[entry.id]=data
        if entry.id==journal.cursor:cursor_design=data
        parents[entry.id]=entry.parent
    step=journal.head;ancestry=set()
    while step is not None:ancestry.add(step);step=parents[step]
    if journal.cursor not in ancestry:raise ValueError('현재 이력 단계가 선택한 작업 분기에 없습니다.')
    if not equivalent(cursor_design,current.model_dump()):
        raise ValueError('작업 이력의 현재 단계와 프로젝트 형상이 일치하지 않습니다.')
