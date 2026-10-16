from copy import deepcopy
import json
import pytest

from cadstudio.pcb import PCBProject, pcb_digest
from cadstudio.pcb_placement_aid import optimize_placement


def component(ref, x, y, net='N', **kwargs):
    return dict(ref=ref, x_mm=x, y_mm=y, body_width_mm=2, body_height_mm=2,
        pins=[dict(number='1', net=net, diameter_mm=.6)], **kwargs)


def board():
    return PCBProject(width_mm=60, height_mm=30, nets=['GND', 'N'],
        components=[component('J1', 5, 10), component('U1', 45, 10)])


def test_unwired_preview_improves_without_editing_input():
    project = board()
    before = project.model_dump(mode='json')
    result = optimize_placement(project, locked_refs=('J1',))
    assert result['can_apply'] and result['moved_refs'] == ['U1']
    assert result['base_sha256'] == pcb_digest(before)
    assert result['after_objective']['ratsnest_wirelength_mm'] < result['before_objective']['ratsnest_wirelength_mm']
    assert result['geometry_report']['no_new_findings'] is True
    assert not result['geometry_report']['after_body_findings']
    assert project.model_dump(mode='json') == before
    assert result['candidate']['components'][0] == before['components'][0]
    assert not result['manufacturing_qualified'] and not result['safety_approved'] and not result['physical_IO']
    json.dumps(result, allow_nan=False)


def test_exact_product_footprint_pad_rotation_and_net_preservation():
    raw = board().model_dump(mode='json')
    raw['components'][1].update(value='MCU', mpn='Fixture-product', footprint='Exact-pad-fixture', rotation_deg=37)
    raw['components'][1]['pins'][0].update(shape='roundrect', size_x_mm=.7, size_y_mm=.4, rotation_deg=18, roundrect_rratio=.3)
    original = deepcopy(raw)
    normalized = PCBProject.model_validate(raw).model_dump(mode='json')
    result = optimize_placement(raw, locked_refs=['J1'])
    assert result['can_apply']
    stripped = deepcopy(result['candidate'])
    for row, old in zip(stripped['components'], normalized['components']):
        row['x_mm'], row['y_mm'] = old['x_mm'], old['y_mm']
    assert stripped == normalized and raw == original


@pytest.mark.parametrize('copper', ['track', 'via'])
def test_existing_copper_nets_lock_components_and_preserve_copper(copper):
    raw = board().model_dump(mode='json')
    if copper == 'track':
        raw['tracks'] = [dict(id='T1', net='N', points=[dict(x_mm=5, y_mm=10), dict(x_mm=45, y_mm=10)])]
    else:
        raw['vias'] = [dict(id='V1', net='N', x_mm=5, y_mm=10, diameter_mm=.6, drill_mm=.3, layers=['F.Cu', 'B.Cu'])]
    original = PCBProject.model_validate(raw).model_dump(mode='json')
    result = optimize_placement(raw)
    assert result['status'] == 'blocked' and not result['can_apply'] and result['trials'] == 0
    assert result['candidate'] == original
    assert all('existing_copper_net_locked' in reasons for reasons in result['fixed_reasons'].values())


def test_any_zone_locks_every_component_without_refilling():
    raw = board().model_dump(mode='json')
    raw['zones'] = [dict(id='Z1', net='GND', layer='F.Cu', outline=[dict(x_mm=x, y_mm=y) for x, y in [(1, 1), (59, 1), (59, 29), (1, 29)]])]
    result = optimize_placement(raw)
    assert result['status'] == 'blocked' and not result['moved_refs']
    assert all('existing_zones_preserved_no_refill' in reasons for reasons in result['fixed_reasons'].values())
    assert result['candidate'] == PCBProject.model_validate(raw).model_dump(mode='json')


def test_selected_lock_and_mechanical_hole_remain_fixed():
    raw = board().model_dump(mode='json')
    raw['components'][0]['ref'] = 'H1'
    raw['components'][0]['footprint'] = 'MountingHole:MountingHole_3.2mm'
    result = optimize_placement(raw)
    assert 'mechanical_hole_preserved' in result['fixed_reasons']['H1']
    assert result['candidate']['components'][0] == raw['components'][0]
    all_locked = optimize_placement(raw, locked_refs=['H1', 'U1'])
    assert all_locked['status'] == 'blocked' and all_locked['candidate'] == raw


def test_rotated_large_body_is_checked_in_addition_to_small_pads():
    raw = board().model_dump(mode='json')
    raw['components'][0].update(body_width_mm=12, body_height_mm=4, rotation_deg=30, x_mm=12)
    result = optimize_placement(raw, locked_refs=['J1'])
    assert result['can_apply'] and result['geometry_report']['no_new_findings']
    assert not result['geometry_report']['after_body_findings']
    moved = result['candidate']['components'][1]
    assert abs(moved['x_mm'] - 12) > 2  # A pad-only placement could overlap the wide rotated body.


@pytest.mark.parametrize('trials', [0, 1, 2])
def test_budget_is_exact_and_input_always_unchanged(trials):
    raw = board().model_dump(mode='json')
    original = deepcopy(raw)
    result = optimize_placement(raw, locked_refs=['J1'], max_trials=trials)
    assert result['trials'] <= trials
    assert result['status'] == 'budget_exhausted' and result['budget_exhausted']
    assert raw == original
    assert not result['can_apply'] or result['after_objective']['ratsnest_wirelength_mm'] < result['before_objective']['ratsnest_wirelength_mm']


def test_deterministic_preview_and_no_imported_gui_or_cad_kernel():
    assert optimize_placement(board(), locked_refs=['J1']) == optimize_placement(board(), locked_refs=['J1'])
    # This module's functional imports stay in the planar PCB/data modules.
    import cadstudio.pcb_placement_aid as placement
    assert not any(name in placement.__dict__ for name in ('PySide6', 'vtk', 'cadquery', 'OCP'))


@pytest.mark.parametrize('budget', [-1, 2001, True, 1.2])
def test_bad_budget_rejected(budget):
    with pytest.raises(ValueError, match='max_trials'):
        optimize_placement(board(), max_trials=budget)


@pytest.mark.parametrize('locks', ['J1', ['missing'], [1]])
def test_bad_lock_references_are_not_silently_ignored(locks):
    with pytest.raises(ValueError):
        optimize_placement(board(), locked_refs=locks)


def test_complexity_limit_is_blocked_not_a_false_geometry_pass():
    raw = board().model_dump(mode='json')
    raw['components'][1]['pins'] = [dict(number=str(index), net='N', diameter_mm=.1, x_mm=(index % 8) * .12) for index in range(128)]
    result = optimize_placement(raw)
    assert result['status'] == 'blocked' and result['blocked_reason'] == 'inspection_complexity_limit'
    assert result['geometry_report']['no_new_findings'] is None
    assert result['geometry_report']['before_layout'] is None and not result['can_apply']
    assert result['candidate'] == PCBProject.model_validate(raw).model_dump(mode='json')
