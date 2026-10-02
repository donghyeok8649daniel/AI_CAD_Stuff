"""Session-scoped baseline reuse never removes candidate or cancellation checks."""
from copy import deepcopy

import pytest

from cadstudio import interference
from cadstudio.kernel import preview
from cadstudio.models import Design, DraftRequest, Part
from cadstudio.native import draft_repair
from cadstudio.native.cad_scope import Scope
from cadstudio.native.cad_tools import ToolReply
from cadstudio.native.local_ai import DraftCancelled, DraftControl


def blocks(x=8):
    return Design(parts=[
        Part(id='a', name='A', geometry=dict(kind='plate', length=10, width=10, thickness=5, hole_count=0)),
        Part(id='b', name='B', geometry=dict(kind='plate', length=10, width=10, thickness=5, hole_count=0),
             transform=dict(x=x)),
    ])


def review(state, design, check=lambda: None):
    result = ToolReply(design=design, summary='Candidate', assumptions=[])
    verified = preview(result.design)
    return state.check(result, verified, '{}', Scope(tools=('transform',), shapes=('plate',)), check)


def count_baselines(monkeypatch):
    calls = []
    original = draft_repair.exact_collisions
    def compute(design, check=lambda: None):
        calls.append(design.model_dump())
        return original(design, check=check)
    monkeypatch.setattr(draft_repair, 'exact_collisions', compute)
    return calls


def test_repeated_candidates_reuse_one_baseline_but_measure_every_candidate(monkeypatch):
    baseline_calls = count_baselines(monkeypatch)
    candidate_calls = []
    original = interference.exact_collisions
    def candidate(design, shapes=None, check=lambda: None):
        candidate_calls.append(design.model_dump())
        return original(design, shapes, check)
    monkeypatch.setattr(interference, 'exact_collisions', candidate)
    request = DraftRequest(prompt='Maintain the two bodies', current=blocks(8))
    before = request.model_dump()
    state = draft_repair.DraftRepair(request)
    same = review(state, blocks(8))
    reduced = review(state, blocks(9))
    assert same['validation']['existing'][0]['volume'] == pytest.approx(100)
    assert reduced['validation']['existing'][0]['volume'] == pytest.approx(50)
    assert same['validation']['status'] == reduced['validation']['status'] == 'ready'
    with pytest.raises(ValueError, match='overlap_local_mm'):
        review(state, blocks(7))
    assert state.best['result']['validation']['collisions'][0]['volume'] == pytest.approx(150)
    assert len(baseline_calls) == 1
    assert len(candidate_calls) == 3
    assert request.model_dump() == before
    # A caller's edited report cannot poison the session's exact baseline cache.
    same['validation']['existing'][0]['volume'] = 999
    with pytest.raises(ValueError, match='overlap_local_mm'):
        review(state, blocks(7))
    assert len(baseline_calls) == 1 and len(candidate_calls) == 4
    second_session = draft_repair.DraftRepair(request)
    review(second_session, blocks(8))
    assert len(baseline_calls) == 2


@pytest.mark.parametrize('change', ['dimension', 'pose', 'feature', 'mate'])
def test_geometry_mutation_invalidates_baseline_collision_cache(monkeypatch, change):
    calls = count_baselines(monkeypatch)
    request = DraftRequest(prompt='Inspect original bodies', current=blocks(8))
    state = draft_repair.DraftRepair(request)
    review(state, blocks(8))
    raw = request.current.model_dump()
    if change == 'dimension':
        raw['parts'][0]['geometry']['length'] = 12
    elif change == 'pose':
        raw['parts'][1]['transform']['x'] = 7
    elif change == 'feature':
        raw['parts'][0]['features'] = [dict(id='union', kind='solid', operation='boolean',
                                           tool_part_id='b', boolean_mode='union')]
    else:
        raw['parts'][0]['fixed'] = True
        raw['mates'] = [dict(id='join', kind='rigid', parent='a', child='b', x=8)]
    request.current = Design.model_validate(raw)
    before = request.model_dump()
    result = review(state, request.current.model_copy(deep=True))
    assert result['validation']['status'] == 'ready'
    assert len(calls) == 2
    assert request.model_dump() == before


def test_metadata_reuses_baseline_but_removed_baseline_does_not_grandfather_overlap(monkeypatch):
    calls = count_baselines(monkeypatch)
    request = DraftRequest(prompt='Inspect', current=blocks(8))
    state = draft_repair.DraftRepair(request)
    review(state, blocks(8))
    request.current.parts[0].name = 'Renamed'
    request.current.parts[0].color = '#abcdef'
    request.current.parts[0].role = 'structure'
    review(state, request.current.model_copy(deep=True))
    assert len(calls) == 1
    request.current = None
    with pytest.raises(ValueError, match='overlap_local_mm'):
        review(state, blocks(8))
    assert state._baseline_collision_cache is None


def test_baseline_build_isolated_even_if_shape_solver_mutates_its_input(monkeypatch):
    request = DraftRequest(prompt='Inspect', current=blocks(8))
    before = request.model_dump()
    original = draft_repair.exact_collisions
    def compute(design, check=lambda: None):
        assert design is not request.current
        result = original(design, check=check)
        design.parts[0].transform.x = 1000
        return result
    monkeypatch.setattr(draft_repair, 'exact_collisions', compute)
    result = review(draft_repair.DraftRepair(request), blocks(8))
    assert result['validation']['existing'][0]['volume'] == pytest.approx(100)
    assert request.model_dump() == before


def test_cancel_before_baseline_and_after_exact_work_never_publishes_a_cache(monkeypatch):
    calls = count_baselines(monkeypatch)
    request = DraftRequest(prompt='Inspect', current=blocks(8))
    state = draft_repair.DraftRepair(request)
    control = DraftControl();control.cancel()
    with pytest.raises(DraftCancelled):
        review(state, blocks(8), control.check)
    assert not calls and state.best is None
    control = DraftControl()
    original = draft_repair.exact_collisions
    def cancel_after_work(design, check=lambda: None):
        result = original(design, check=check)
        control.cancel()
        return result
    monkeypatch.setattr(draft_repair, 'exact_collisions', cancel_after_work)
    with pytest.raises(DraftCancelled):
        review(state, blocks(8), control.check)
    assert len(calls) == 1 and state._baseline_collision_cache is None and state.best is None
    monkeypatch.setattr(draft_repair, 'exact_collisions', original)
    review(state, blocks(8))
    assert len(calls) == 2


def test_cancel_after_assessment_on_warm_cache_stays_cancelled(monkeypatch):
    calls = count_baselines(monkeypatch)
    state = draft_repair.DraftRepair(DraftRequest(prompt='Inspect', current=blocks(8)))
    review(state, blocks(8))
    control = DraftControl()
    original = draft_repair.assess
    def cancelled(*args, **kwargs):
        result = original(*args, **kwargs)
        control.cancel()
        return result
    monkeypatch.setattr(draft_repair, 'assess', cancelled)
    with pytest.raises(DraftCancelled):
        review(state, blocks(8), control.check)
    assert len(calls) == 1 and state.best is None


def test_changed_request_during_computation_falls_back_to_new_exact_baseline(monkeypatch):
    request = DraftRequest(prompt='Inspect', current=blocks(8))
    state = draft_repair.DraftRepair(request)
    original = draft_repair.exact_collisions
    def mutate_after_work(design, check=lambda: None):
        result = original(design, check=check)
        request.current.parts[1].transform.x = 12  # The baseline is now clear.
        return result
    monkeypatch.setattr(draft_repair, 'exact_collisions', mutate_after_work)
    with pytest.raises(ValueError, match='overlap_local_mm'):
        review(state, blocks(8))
    assert state.best['result']['validation']['collisions'][0]['volume'] == pytest.approx(100)
    assert state._baseline_collision_cache is None


def test_joint_travel_remains_an_exact_check_on_each_accepted_candidate(monkeypatch):
    from test_interference import moved, swing
    calls = count_baselines(monkeypatch)
    travel_calls = []
    original = draft_repair.check_joint_travel
    def travel(*args, **kwargs):
        travel_calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(draft_repair, 'check_joint_travel', travel)
    before = swing()
    state = draft_repair.DraftRepair(DraftRequest(prompt='Move the joint', current=before))
    for _ in range(2):
        with pytest.raises(ValueError, match='관절 구동 중 간섭'):
            review(state, moved(before, 90))
    assert len(calls) == 1 and len(travel_calls) == 2
    assert state.best['result']['validation']['travel']['blocked']
