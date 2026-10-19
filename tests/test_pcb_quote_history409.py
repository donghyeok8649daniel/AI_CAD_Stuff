"""New PCB quote provenance in the actual PCAD journal/save path; no native UI."""
from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cadstudio.models import Design
from cadstudio.native.document import Document, read_project
from cadstudio.pcb import PCBProject, PCBComponent, pcb_digest
from cadstudio.pcb_cost_workflow import (with_cost_inputs, read_cost_inputs,
    estimate_saved_cost, adopt_cost_proposal)


def saved_quote_board():
    board = PCBProject(components=[
        PCBComponent(ref='R1', mpn='Fixture-resistor', pins=[dict(number='1')],
                     quote=dict(status='reference', unit_price='10', currency='USD',
                                as_of='2026-01-01', supplier='Fixture supplier',
                                source_url='https://example.com/fixture-quote')),
        PCBComponent(ref='U1', mpn='Fixture-controller', pins=[dict(number='1')], x_mm=20),
    ])
    board = with_cost_inputs(board, dict(quantity_breaks={'R1':[
        dict(minimum_quantity=1, unit_price='3', currency='USD', status='reference',
             as_of='2026-01-01', supplier='Fixture supplier',
             source_url='https://example.com/fixture-tier')]}))
    proposal = dict(schema_version=1, base_sha256=pcb_digest(board), status='ai_estimate',
                    summary='Synthetic conditional estimate; no supplier or API request.',
                    rows=[dict(refs=['U1'], mpn='Fixture-controller', required_quantity=1,
                               purchase_quantity=1, minimum_unit_price='2', maximum_unit_price='4',
                               currency='USD', basis='Synthetic test assumption')])
    return adopt_cost_proposal(board, proposal)


def as_design(board):
    return Design(name='Quote history integration fixture', parts=[], pcb=board).model_dump()


def test_provenance_and_stale_records_survive_full_pcad_save_reopen_and_journal_replay(tmp_path):
    board = saved_quote_board()
    accepted = as_design(board)
    raw = board.model_dump(mode='json')
    for component in raw['components']:
        component['quote']['source_url'] = 'https://example.com/revised-source'
    changed = as_design(PCBProject.model_validate(raw))
    original = deepcopy(changed)
    document = Document()
    document.commit(Design(name='Quote history integration fixture', parts=[]), 'Base')
    document.commit(accepted, 'Adopt quoted fixture')
    accepted_id = document.journal.data['cursor']
    document.commit(changed, 'Change source without re-adoption')
    changed_id = document.journal.data['cursor']
    path = tmp_path / 'quote-history.pcad'
    document.write(path)
    loaded = Document()
    loaded.load(read_project(path), path)
    assert loaded.design == changed == original
    loaded.journal.cache.clear()
    replay_accepted = loaded.journal.at(accepted_id)
    replay_changed = loaded.journal.at(changed_id)
    before = estimate_saved_cost(replay_accepted['pcb'])
    after = estimate_saved_cost(replay_changed['pcb'])
    assert before['conditional_ranges'] == {'USD': {'minimum':'5.00', 'maximum':'7.00'}}
    assert not before['stale_quantity_breaks'] and len(before['used_ai_estimates']) == 1
    assert after['conditional_ranges'] == {'USD': {'minimum':'10.00', 'maximum':'10.00'}}
    assert set(after['stale_quantity_breaks']) == {'R1'}
    assert len(after['stale_ai_estimates']) == 1 and not after['used_ai_estimates']
    stored = read_cost_inputs(replay_changed['pcb'])
    assert stored.quantity_breaks and stored.accepted_ai_estimates
    assert stored.quantity_break_contexts and stored.accepted_ai_quote_contexts
    replay_accepted['pcb']['budget']['cost_inputs']['quantity_break_contexts'].clear()
    assert loaded.journal.at(accepted_id)['pcb']['budget']['cost_inputs']['quantity_break_contexts']
    assert loaded.design == original  # Public restored snapshots remain detached.
    assert not any(name in sys.modules for name in ('PySide6', 'vtkmodules', 'OCP', 'cadquery'))


def test_selected_quote_ancestor_and_new_branch_preserve_old_head_and_contexts(tmp_path):
    document = Document()
    accepted = as_design(saved_quote_board())
    document.commit(accepted, 'Accepted quote')
    accepted_id = document.journal.data['cursor']
    later = deepcopy(accepted)
    later['name'] = 'Previous head retained'
    document.commit(later, 'Earlier head')
    old_head = document.journal.data['head']
    document.commit(document.journal.at(accepted_id), 'Select ancestor', cursor=accepted_id)
    selected_path = tmp_path / 'selected-ancestor.pcad'
    document.write(selected_path)
    loaded = Document()
    loaded.load(read_project(selected_path), selected_path)
    assert loaded.journal.data['cursor'] == accepted_id and loaded.journal.data['head'] == old_head
    branch = deepcopy(loaded.design)
    branch['name'] = 'New quote branch'
    loaded.commit(branch, 'New branch')
    new_head = loaded.journal.data['head']
    loaded.journal.cache.clear()
    assert loaded.journal.index[new_head]['parent'] == accepted_id
    assert loaded.journal.at(old_head) == later
    for identifier in (accepted_id, old_head, new_head):
        restored = loaded.journal.at(identifier)
        assert read_cost_inputs(restored['pcb']).model_dump() == read_cost_inputs(accepted['pcb']).model_dump()
        assert not estimate_saved_cost(restored['pcb'])['stale_ai_estimates']
    branch_path = tmp_path / 'new-branch.pcad'
    loaded.write(branch_path)
    again = read_project(branch_path)
    assert [entry.id for entry in again.history.entries] == [entry['id'] for entry in loaded.journal.data['entries']]
    assert again.history.head == new_head and old_head in {entry.id for entry in again.history.entries}
