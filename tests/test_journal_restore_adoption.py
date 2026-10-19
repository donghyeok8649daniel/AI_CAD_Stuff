"""New actual Journal.at adoption regressions; no old comparison/GUI/kernel."""
from copy import deepcopy
import json
import sys
from types import SimpleNamespace
import pytest
from cadstudio.native import document as M
from cadstudio import history as H
from cadstudio.models import HistoryChange


def base():
    return dict(fixture='new-adoption-only',nodes=[dict(id='A',payload=dict(value=0,tags=['seed'])),dict(id='B',payload=dict(value=1,tags=['other']))])

def change(path,before,after,existed=True):
    return dict(path=path,operation='set',existed=existed,before=deepcopy(before),after=deepcopy(after))

def entry(identifier,parent,changes):
    return dict(id=identifier,parent=parent,label=identifier,created_at='2026-10-18T00:00:00Z',source='manual',context={},changes=changes)

def data_for(root,entries=()):
    rows=[entry('root',None,[]),*entries];head=rows[-1]['id']
    return dict(version=1,base=root,entries=rows,cursor=head,head=head)

def branch_data():
    return data_for(base(),[entry('trunk','root',[change(['nodes',0,'payload','value'],0,3),change(['nodes',0,'payload','tags'],['seed'],['trunk',dict(extra=[1,2])])]),
        entry('branch','trunk',[change(['nodes',0,'payload','tags',1,'extra',0],1,9)])])

def siblings():
    return data_for(base(),[entry('e'+str(i),'root',[change(['nodes',0,'payload','value'],0,i)]) for i in range(1,10)])

def root_like(value):return type(value) is dict and value.get('fixture')=='new-adoption-only'

def test_actual_cold_branch_and_warm_return_keep_two_root_copies_and_isolation(monkeypatch,record_property):
    journal=M.Journal(data=branch_data());before=deepcopy(journal.data)
    counts=dict(document_root=0,history_root=0,history_payload=0,validated_changes=0)
    def doc_copy(value):
        if root_like(value):counts['document_root']+=1
        return deepcopy(value)
    def history_copy(value):
        counts['history_root' if root_like(value) else 'history_payload']+=1
        return deepcopy(value)
    def validate(value):
        counts['validated_changes']+=1;return HistoryChange.model_validate(value)
    monkeypatch.setattr(M,'deepcopy',doc_copy);monkeypatch.setattr(H,'deepcopy',history_copy)
    monkeypatch.setattr(M,'HistoryChange',SimpleNamespace(model_validate=validate))
    restored=journal.at('branch')
    expected=base();expected['nodes'][0]['payload']=dict(value=3,tags=['trunk',dict(extra=[9,2])])
    assert restored==expected and journal.data==before
    assert counts==dict(document_root=2,history_root=0,history_payload=3,validated_changes=3)
    record_property('actual_cold_counts',json.dumps(counts,sort_keys=True))
    restored['nodes'][0]['payload']['tags'][1]['extra'][0]=999
    restored['nodes'][1]['payload']['tags'][0]='Returned untouched subtree mutation'
    assert journal.cache['branch']==expected and journal.data==before
    counts.update(document_root=0,history_root=0,history_payload=0,validated_changes=0)
    warm=journal.at('branch')
    assert warm==expected and counts==dict(document_root=1,history_root=0,history_payload=0,validated_changes=0)
    warm['nodes'][0]['payload']['tags'][0]='Another returned mutation'
    assert journal.cache['branch']==expected and journal.data==before
    record_property('actual_warm_counts',json.dumps(counts,sort_keys=True))
    assert not any(name in sys.modules for name in ('PySide6','vtkmodules','OCP','cadquery'))


def test_actual_cache_remains_eight_entry_fifo_and_warm_hit_never_reorders():
    journal=M.Journal(data=siblings());before=deepcopy(journal.data)
    for i in range(1,10):
        result=journal.at('e'+str(i));assert result['nodes'][0]['payload']['value']==i
        result['nodes'][1]['payload']['tags'][0]='Detached branch return'
        assert len(journal.cache)<=8 and journal.data==before
        assert all(v['nodes'][1]['payload']['tags']==['other'] for v in journal.cache.values())
    expected=['e'+str(i) for i in range(2,10)];assert list(journal.cache)==expected
    warm=journal.at('e2');warm['nodes'][0]['payload']['value']=-1
    assert list(journal.cache)==expected and journal.cache['e2']['nodes'][0]['payload']['value']==2
    journal.at('root');assert list(journal.cache)==[*expected[1:],'root'] and journal.data==before


def test_none_scalar_tuple_and_builtin_list_public_roots_preserve_value_type_and_independence():
    roots=[None,17,1.25,'scalar',True,('tuple',dict(nested=[1,2])),[dict(value=1)]]
    for value in roots:
        journal=M.Journal(data=data_for(value));before=deepcopy(journal.data)
        result=journal.at('root');assert result==value and type(result) is type(value)
        if isinstance(result,list):result[0]['value']=99
        elif isinstance(result,tuple):result[1]['nested'][0]=99
        assert journal.data==before and journal.cache['root']==value and journal.at('root')==value
    journal=M.Journal(data=data_for([dict(value=1)],[entry('list','root',[change([0,'value'],1,2)])]))
    result=journal.at('list');assert result==[dict(value=2)]
    result[0]['value']=99;assert journal.data['base']==[dict(value=1)] and journal.cache['list']==[dict(value=2)]


class CopySentryDict(dict):
    def copy(self):raise AssertionError('Custom root copy override must retain the deepcopy fallback.')
class CopySentryList(list):
    def copy(self):raise AssertionError('Custom root copy override must retain the deepcopy fallback.')


def test_custom_dict_and_list_subclass_roots_keep_original_deepcopy_type_contract():
    for root,path in [(CopySentryDict(value=dict(n=1)),['value','n']),(CopySentryList([dict(n=1)]),[0,'n'])]:
        journal=M.Journal(data=data_for(root,[entry('changed','root',[change(path,1,2)])]));before=deepcopy(journal.data)
        result=journal.at('changed')
        assert type(result) is type(root) and type(journal.cache['changed']) is type(root)
        node=result['value'] if isinstance(result,dict) else result[0];assert node['n']==2;node['n']=99
        assert journal.data==before
        cached=journal.cache['changed']['value'] if isinstance(root,dict) else journal.cache['changed'][0]
        assert cached['n']==2


@pytest.mark.parametrize('invalid', ['wrong-before','invalid-change'])
def test_early_history_validation_failure_preserves_existing_cache_and_stored_source(invalid):
    changes=[change(['nodes',0,'payload','value'],999,2)] if invalid=='wrong-before' else [dict(path=[],before=0,after=2)]
    journal=M.Journal(data=data_for(base(),[entry('bad','root',changes)]));journal.at('root')
    before=deepcopy(journal.data),deepcopy(journal.cache)
    with pytest.raises(ValueError):journal.at('bad')
    assert (journal.data,journal.cache)==before and 'bad' not in journal.cache


def test_after_payload_copy_failure_does_not_publish_intermediate_changes(monkeypatch):
    changes=[change(['nodes',0,'payload','value'],0,3),change(['inserted'],None,dict(copy_failure_marker=True,items=[1,2]),existed=False)]
    journal=M.Journal(data=data_for(base(),[entry('bad-copy','root',changes)]));journal.at('root')
    before=deepcopy(journal.data),deepcopy(journal.cache)
    def allocation_failure(value):
        if isinstance(value,dict) and value.get('copy_failure_marker') is True:raise MemoryError('Owned after-payload allocation failure')
        return deepcopy(value)
    monkeypatch.setattr(H,'deepcopy',allocation_failure)
    with pytest.raises(MemoryError,match='after-payload allocation'):journal.at('bad-copy')
    assert (journal.data,journal.cache)==before and 'bad-copy' not in journal.cache


def test_existing_final_return_copy_failure_cache_publication_caveat_is_preserved(monkeypatch):
    journal=M.Journal(data=siblings())
    for i in range(1,9):journal.at('e'+str(i))
    before=deepcopy(journal.data);old_cache=deepcopy(journal.cache);calls=0
    def fail_final_copy(value):
        nonlocal calls
        calls+=1
        if calls==2:raise MemoryError('Owned final outward copy failure')
        return deepcopy(value)
    monkeypatch.setattr(M,'deepcopy',fail_final_copy)
    with pytest.raises(MemoryError,match='final outward copy'):journal.at('e9')
    assert calls==2 and journal.data==before
    assert list(journal.cache)==['e'+str(i) for i in range(2,10)]
    assert all(journal.cache[k]==old_cache[k] for k in old_cache if k!='e1')
    assert journal.cache['e9']['nodes'][0]['payload']['value']==9
