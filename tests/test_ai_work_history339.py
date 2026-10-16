"""Synthetic journal/data checks only; no GUI, kernel, provider or real PCAD."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import ast
import json
import sys
import pytest

from cadstudio.models import Design, DraftRequest, ReferenceMaterial
from cadstudio.native.document import Document, differences, read_project
from cadstudio.ai_work_history import (capture_history_binding, history_binding_matches,
    require_history_binding, summarize_work_history, validate_work_history_reference)
from cadstudio.references import reference_payload, reference_message


def document():
    doc = Document()
    doc.commit(Design(name='Fixture base', parts=[]), 'AI legacy root', {'source': 'import'})
    return doc


def edit(doc, name, label=None, context=None):
    raw = deepcopy(doc.design)
    raw['name'] = name
    doc.commit(raw, label or name, context)


def ai_step(doc, *, binding=None):
    raw = deepcopy(doc.design)
    raw['name'] = 'Verified appended design'
    context = dict(source='openai', provider='codex', tool='prompt', summary='Fixture metadata only',
        prompt='continue the loaded file', journal_base=deepcopy(doc.design),
        journal_steps=[dict(action=dict(tool='parameter', target='global', args={}), changes=differences(doc.design, raw))])
    if binding is not None:
        context['_ai_history_binding'] = binding
    return raw, context


def test_reopen_summary_append_undo_save_reopen_retains_all_old_ids_and_branches(tmp_path):
    doc = document()
    edit(doc, 'Old branch')
    old_branch = doc.journal.data['cursor']
    root = doc.journal.data['entries'][0]['id']
    doc.commit(doc.journal.at(root), 'restore', cursor=root)
    edit(doc, 'Current branch')
    original_entries = deepcopy(doc.journal.data['entries'])
    file = tmp_path / 'owned-fixture.pcad'
    doc.write(file)
    loaded = Document()
    loaded.load(read_project(file), file)
    binding = capture_history_binding(loaded)
    summary = json.loads(summarize_work_history(loaded, binding=binding).text)
    assert summary['branch_points'] == 1 and summary['inactive_entries'] == 1
    assert old_branch not in {row['id'] for row in summary['steps']}
    assert summary['cursor'] == summary['head'] == loaded.journal.data['cursor']
    assert loaded.journal.data['entries'] == original_entries
    raw, context = ai_step(loaded, binding=binding)
    loaded.commit(raw, '설계 명령 적용', context)
    assert loaded.journal.data['entries'][:len(original_entries)] == original_entries
    assert len(loaded.journal.data['entries']) == len(original_entries) + 1
    newest = loaded.journal.data['entries'][-1]
    assert newest['parent'] == binding['cursor'] and not newest['label'].startswith('AI ')
    assert '_ai_history_binding' not in newest['context']
    loaded.commit(loaded.journal.at(binding['cursor']), 'undo', cursor=binding['cursor'])
    full_history = deepcopy(loaded.journal.data)
    assert newest['id'] in loaded.journal.index
    loaded.write(file)
    reopened = Document()
    reopened.load(read_project(file), file)
    assert reopened.journal.data == full_history
    assert reopened.journal.data['entries'][:len(original_entries)] == original_entries


def test_context_is_bounded_metadata_only_and_credentials_redacted():
    doc = document()
    edit(doc, 'Changed', context=dict(tool='firmware', provider='codex', prompt='api_key=sk-example-secret-value-123',
        summary='A factual earlier edit', geometry={'payload': 'GEOMETRY_SENTINEL' * 3000},
        firmware_code='CODE_SENTINEL' * 3000, credentials={'password': 'PRIVATE_SENTINEL'},
        tool_actions=[dict(tool='dimensions', target='specimen', args={'code': 'ACTION_CODE_SENTINEL'})]))
    saved = deepcopy(doc.journal.data)
    ref = summarize_work_history(doc)
    assert len(ref.text) <= 12000
    assert all(text not in ref.text for text in ['GEOMETRY_SENTINEL', 'CODE_SENTINEL', 'PRIVATE_SENTINEL', 'ACTION_CODE_SENTINEL', 'sk-example'])
    assert 'credential-like text omitted' in ref.text
    assert json.loads(ref.text)['steps'][-1]['changed_paths'] == [['name']]
    assert doc.journal.data == saved
    validate_work_history_reference(ref)


def test_recent_active_ancestry_and_character_budget_are_honest():
    doc = document()
    for index in range(45):
        edit(doc, str(index), label=('Long history metadata ' * 7)[:160], context=dict(prompt='x' * 3000))
    ref = summarize_work_history(doc, max_chars=2500)
    raw = json.loads(ref.text)
    assert len(ref.text) <= 2500 and raw['included_entries'] <= 24
    assert raw['omitted_ancestry_entries'] > 0 and ref.truncated
    assert raw['total_entries'] == raw['active_ancestry_entries'] == 46
    assert raw['steps'][-1]['id'] == doc.journal.data['cursor']
    assert raw['included_entries'] + raw['omitted_ancestry_entries'] == 46


def test_auto_history_keeps_eight_user_references_and_full_user_budget():
    doc = document()
    refs = [ReferenceMaterial(name='file' + str(index), source='local:file' + str(index),
        sha256=sha256(str(index).encode()).hexdigest(), text=str(index) * 7500) for index in range(8)]
    request = DraftRequest(prompt='Continue', current=doc.design, references=refs, work_history=summarize_work_history(doc))
    payload = reference_payload(request)
    assert len(request.references) == 8 and sum(len(ref.text) for ref in request.references) == 60000
    assert len(payload) == 9 and [row['name'] for row in payload[:8]] == [ref.name for ref in refs]
    assert payload[-1]['source'] == 'cadstudio:work-history'
    assert json.loads(reference_message(request))['reference_materials'] == payload
    assert DraftRequest.model_validate(request.model_dump()).work_history.text == request.work_history.text
    with pytest.raises(ValueError):
        DraftRequest(prompt='bad', references=refs + refs[:1])


@pytest.mark.parametrize('change', ['cursor', 'head', 'metadata', 'append', 'replace_journal', 'design'])
def test_local_binding_rejects_stale_journal_even_without_operation_serial(change):
    doc = document()
    edit(doc, 'Second')
    binding = capture_history_binding(doc)
    assert history_binding_matches(doc, binding)
    if change == 'cursor':
        doc.journal.data['cursor'] = doc.journal.data['entries'][0]['id']
    elif change == 'head':
        doc.journal.data['head'] = doc.journal.data['entries'][0]['id']
    elif change == 'metadata':
        doc.journal.data['entries'][0]['label'] = 'Edited earlier label'
    elif change == 'append':
        edit(doc, 'Third')
    elif change == 'replace_journal':
        from cadstudio.native.document import Journal
        doc.journal = Journal(data=doc.journal.data)
    else:
        doc.design['name'] = 'Changed current design'
    assert not history_binding_matches(doc, binding)
    with pytest.raises(ValueError, match='작업 이력'):
        require_history_binding(doc, binding)


def test_late_document_commit_guard_is_atomic_and_keeps_old_history():
    doc = document()
    binding = capture_history_binding(doc)
    raw, context = ai_step(doc, binding=binding)
    doc.journal.data['entries'][0]['label'] = 'Changed during verification worker'
    saved = deepcopy((doc.design, doc.journal.data, doc.prompt, doc.dirty))
    with pytest.raises(ValueError):
        doc.commit(raw, 'must not apply', context)
    assert (doc.design, doc.journal.data, doc.prompt, doc.dirty) == saved


def test_new_document_and_legacy_requests_stay_compatible_without_auto_history():
    doc = Document()
    assert summarize_work_history(doc) is None
    request = DraftRequest(prompt='offline local dimensions')
    assert 'work_history' not in request.model_dump()
    assert reference_payload(request) == []
    binding = capture_history_binding(doc)
    assert history_binding_matches(doc, binding)


@pytest.mark.parametrize('mutation', ['oversized', 'bad_hash', 'geometry_context', 'too_many_steps', 'wrong_source'])
def test_work_history_field_rejects_invalid_or_unbounded_payload(mutation):
    ref = summarize_work_history(document()).model_dump()
    if mutation == 'oversized':
        ref['text'] = 'x' * 12001
    elif mutation == 'bad_hash':
        ref['sha256'] = '0' * 64
    elif mutation == 'wrong_source':
        ref['source'] = 'local:masquerading-reference'
    else:
        raw = json.loads(ref['text'])
        if mutation == 'geometry_context':
            raw['steps'][0]['context']['summary'] = {'code': 'not permitted'}
        else:
            raw['steps'] *= 25
            raw['included_entries'] = len(raw['steps'])
        ref['text'] = json.dumps(raw)
        ref['sha256'] = sha256(ref['text'].encode()).hexdigest()
    with pytest.raises(ValueError):
        DraftRequest(prompt='bad work history', work_history=ref)



def test_scope_and_plan_payloads_both_include_autohistory_as_untrusted_reference(monkeypatch):
    from cadstudio.native import cad_scope, cad_tools
    # Geometry context has its own kernel checks; isolate it for this metadata-only contract.
    monkeypatch.setattr(cad_scope, "context", lambda design: {"name": design.name})
    monkeypatch.setattr(cad_tools, "context", lambda design: {"name": design.name})
    from cadstudio.references import GUIDANCE
    doc = document()
    edit(doc, 'Saved design edited before this request')
    request = DraftRequest(prompt='Continue this file', current=doc.design, work_history=summarize_work_history(doc))
    for builder in (cad_scope.scope_messages, cad_tools.messages):
        packet = builder(request)
        assert GUIDANCE in packet[0]['content']
        payload = json.loads(packet[1]['content'])
        assert payload['reference_materials'][-1]['sha256'] == request.work_history.sha256
        metadata = json.loads(payload['reference_materials'][-1]['text'])
        assert metadata['cursor'] == doc.journal.data['cursor']
        assert metadata['steps'][-1]['label'] == 'Saved design edited before this request'


def test_verified_multistep_batch_appends_from_undo_cursor_without_resetting_branch():
    doc = document()
    edit(doc, 'Earlier active stage')
    cursor = doc.journal.data['cursor']
    edit(doc, 'Existing later branch')
    head = doc.journal.data['head']
    doc.commit(doc.journal.at(cursor), 'undo', cursor=cursor)
    binding = capture_history_binding(doc)
    summary = json.loads(summarize_work_history(doc).text)
    assert summary['cursor'] == cursor and summary['head'] == head
    assert summary['steps'][-1]['id'] == cursor
    original = deepcopy(doc.journal.data['entries'])
    middle, final = deepcopy(doc.design), deepcopy(doc.design)
    middle['name'] = 'First verified step'
    final['name'] = 'Second verified step'
    context = dict(source='openai', provider='codex', _ai_history_binding=binding,
        journal_base=deepcopy(doc.design), journal_steps=[
            dict(action=dict(tool='parameter', target='global', args={}), changes=differences(doc.design, middle)),
            dict(action=dict(tool='parameter', target='global', args={}), changes=differences(middle, final))])
    doc.commit(final, '설계 명령 적용', context)
    assert doc.journal.data['entries'][:len(original)] == original
    new = doc.journal.data['entries'][len(original):]
    assert len(new) == 2 and new[0]['parent'] == cursor and new[1]['parent'] == new[0]['id']
    assert doc.journal.at(new[0]['id']) == middle and doc.journal.at(new[1]['id']) == final
    assert head in doc.journal.index and doc.journal.data['head'] == new[1]['id']
    assert all('_ai_history_binding' not in row['context'] and not row['label'].startswith('AI ') for row in new)


def test_window_hooks_keep_repair_binding_and_guard_registration_without_gui_import():
    path = Path(__file__).parents[1] / 'cadstudio/native/window.py'
    text = path.read_text(encoding='utf-8')
    ast.parse(text)
    assert "history_binding=deepcopy(repair_draft['history_binding'])" in text
    assert "if provider!='local':request.work_history=summarize_work_history" in text
    assert "if provider=='local':request.work_history=None" in text
    assert 'context=dict(_ai_history_binding=history_binding' in text
    assert 'require_canonical_executable(executable)' in text
    assert "self.document.prompt=draft['prompt']" not in text
    chat = (path.parent / 'ai_chat.py').read_text(encoding='utf-8')
    assert 'if request.references or request.work_history is not None:' in chat
    assert not any(name in sys.modules for name in ('PySide6', 'vtkmodules', 'OCP', 'cadquery'))


@pytest.mark.parametrize('legacy_action', [dict(tool=None,target='part'),dict(tool='legacy',target={'id':'part'})])
def test_legacy_json_action_values_do_not_block_history_context(legacy_action):
    doc=document()
    edit(doc,'Legacy imported history',context=dict(tool_actions=[legacy_action]))
    saved=deepcopy(doc.journal.data)
    request=DraftRequest(prompt='Continue old valid project',work_history=summarize_work_history(doc))
    summary=json.loads(reference_payload(request)[0]['text'])
    action=summary['steps'][-1]['context']['tool_actions'][0]
    assert all(isinstance(value,str) for value in action.values())
    assert doc.journal.data==saved
    assert not any(name in sys.modules for name in ('PySide6','vtkmodules','OCP','cadquery'))
