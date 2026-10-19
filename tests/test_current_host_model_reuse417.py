"""417: actual current synchronous PCAD adoption, no optional model-return patch."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest
from pydantic import TypeAdapter
from cadstudio.models import Project
from cadstudio.native import document as M
from cadstudio import history as H,pcb_compatibility as C
from cadstudio.ai_work_history import capture_history_binding,history_binding_matches

FIXTURE=Path('C:/Users/keidi/Documents/Codex/2026-10-14/prompt-cad-pcb-plugin/outputs/pcb-composition407-411-20261018/examples/COMBINED_SYNTHETIC.pcad')
FIXTURE_SHA='dffcece827c4fb00aa1a91ba7a0f38ec08cfb84c11711146e8859299ad4bb3a3'


def owned_fixture(tmp_path):
    data=FIXTURE.read_bytes();assert hashlib.sha256(data).hexdigest()==FIXTURE_SHA
    target=tmp_path/'owned-composition-synthetic.pcad';target.write_bytes(data)
    return target,data,json.loads(data)


def no_heavy_imports():
    assert not any(key in sys.modules for key in ('PySide6','vtkmodules','OCP','cadquery'))


def test_actual_read_project_to_same_typed_model_load_has_one_parse_gate_and_history_pass(tmp_path,monkeypatch,record_property):
    path,source_bytes,raw=owned_fixture(tmp_path)
    counts=dict(adapter_validate_json=0,preflight=0,full_history_validation=0)
    actual_json=TypeAdapter.validate_json;actual_gate=C.preflight;actual_history=H.validate_history
    def parse(adapter,*args,**kwargs):
        assert adapter is M._PROJECT_READ_JSON
        counts['adapter_validate_json']+=1;return actual_json(adapter,*args,**kwargs)
    def gate(*args,**kwargs):
        counts['preflight']+=1;return actual_gate(*args,**kwargs)
    def history(*args,**kwargs):
        counts['full_history_validation']+=1;return actual_history(*args,**kwargs)
    def forbidden(*args,**kwargs):
        raise AssertionError('Current host read/load must not decode or construct Project a second time.')
    monkeypatch.setattr(TypeAdapter,'validate_json',parse)
    monkeypatch.setattr(C,'preflight',gate)
    monkeypatch.setattr(H,'validate_history',history)
    monkeypatch.setattr(C,'decode_compatible',forbidden)
    monkeypatch.setattr(C,'validate_payload',forbidden)
    monkeypatch.setattr(Project,'model_validate',classmethod(forbidden))
    parsed=M.read_project(path)
    assert isinstance(parsed,Project)
    document=M.Document();document.load(parsed,path)
    assert counts==dict(adapter_validate_json=1,preflight=1,full_history_validation=1)
    # model_dump copies have retained every current field and full journal.
    assert parsed.model_dump(mode='json')==raw
    assert document.design==raw['design'] and document.journal.data==raw['history']
    assert document.prompt==raw.get('prompt','') and document.path==path and document.dirty is False
    assert len(document.journal.data['entries'])==5 and document.design['pcb']['layer_count']==6
    costs=document.design['pcb']['budget']['cost_inputs'];original=raw['design']['pcb']['budget']['cost_inputs']
    for field in ('quantity_break_contexts','accepted_ai_quote_contexts'):
        assert len(costs[field])==1 and costs[field]==original[field]
    assert path.read_bytes()==source_bytes and FIXTURE.read_bytes()==source_bytes
    no_heavy_imports()
    record_property('actual_validation_counts',json.dumps(counts,sort_keys=True))
    record_property('fixture_source_sha256',FIXTURE_SHA)
    record_property('source_bytes_preserved',True)


def test_adopted_document_owns_copies_and_current_draft_binding_ignores_stale_caller_model(tmp_path,record_property):
    path,source_bytes,caller_raw=owned_fixture(tmp_path)
    caller_model=M.read_project(path);document=M.Document();document.load(caller_model,path)
    adopted_design=deepcopy(document.design);adopted_journal=deepcopy(document.journal.data)
    binding=capture_history_binding(document)
    # These are caller-owned objects, not reusable approval tokens or caches.
    caller_model.design.name='Caller changed typed model after adoption'
    caller_model.design.pcb.components[0].x_mm+=3
    caller_model.design.pcb.budget.cost_inputs.quantity_break_contexts.clear()
    caller_model.history.base.name='Caller changed historical base'
    caller_model.history.entries[0].label='Caller changed historical metadata'
    caller_raw['design']['pcb']['components'][0]['x_mm']+=7
    caller_raw['history']['entries'][0]['label']='Caller changed decoded raw tree'
    caller_raw['design']['pcb']['budget']['cost_inputs']['accepted_ai_quote_contexts'].clear()
    assert document.design==adopted_design and document.journal.data==adopted_journal
    assert history_binding_matches(document,binding)
    # A real edit binds the next draft to current Document/journal, not parsed model identity.
    changed=deepcopy(document.design);changed['pcb']['components'][0]['x_mm']+=.5
    document.commit(changed,'417 owned synthetic edit')
    assert not history_binding_matches(document,binding)
    assert capture_history_binding(document)['current_design_sha256']!=binding['current_design_sha256']
    before_reject=deepcopy(document.design),deepcopy(document.journal.data)
    stale_draft=deepcopy(adopted_design);stale_draft['name']='Stale draft must not be adopted'
    with pytest.raises(ValueError,match='설계 또는 작업 이력'):
        document.commit(stale_draft,'Must reject old draft',dict(_ai_history_binding=binding,source='openai'))
    assert (document.design,document.journal.data)==before_reject
    assert len(document.journal.data['entries'])==6 and document.design['pcb']['components'][0]['x_mm']==changed['pcb']['components'][0]['x_mm']
    assert path.read_bytes()==source_bytes and FIXTURE.read_bytes()==source_bytes
    no_heavy_imports()
    record_property('caller_mutations_do_not_alias_document',True)
    record_property('old_draft_binding_rejected_after_current_document_edit',True)
    record_property('source_bytes_preserved',True)
