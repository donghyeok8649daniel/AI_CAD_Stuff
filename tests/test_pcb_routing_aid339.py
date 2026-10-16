"""Tiny CLI-only routing fixtures; no original PCB, GUI, kernel or devices."""
from copy import deepcopy
import json

import pytest

from cadstudio.pcb import PCBProject, PCBComponent, PCBPin, PCBTrack, PCBVia, inspect_layout, pcb_digest, copper_layers, via_layers
from cadstudio.pcb_routing_aid import assess_routing


def pad(ref, net, x, y, layers=('F.Cu',), **kw):
    return PCBComponent(ref=ref, x_mm=x, y_mm=y,
        pins=[PCBPin(number='1', net=net, layers=list(layers), **kw)])


def simple():
    return PCBProject(width_mm=20, height_mm=12, edge_clearance_mm=.2,
        nets=['GND', 'N'], components=[pad('J1', 'N', 3, 4), pad('J2', 'N', 17, 8), pad('J3', 'N', 3, 8)])


def walls(*, four=False, through=False):
    # Grounded preserved copper closes a complete vertical separator on both
    # outer planes. Inner planes remain free; no mathematical claim follows.
    project = PCBProject(width_mm=20, height_mm=8, edge_clearance_mm=0,
        layer_count=4 if four else 2, nets=['GND', 'N'], components=[
            pad('G1', 'GND', 10, .5, ['F.Cu', 'B.Cu']),
            pad('G2', 'GND', 10, 7.5, ['F.Cu', 'B.Cu']),
            pad('N1', 'N', 3, 4, ['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu'] if four else ['F.Cu']),
            pad('N2', 'N', 17, 4, ['F.Cu', 'In1.Cu', 'In2.Cu', 'B.Cu'] if four else ['F.Cu'])],
        tracks=[PCBTrack(id='wall_'+layer[0], net='GND', layer=layer,
            points=[dict(x_mm=10, y_mm=.5), dict(x_mm=10, y_mm=7.5)]) for layer in ['F.Cu', 'B.Cu']])
    if through:
        project.vias = [PCBVia(id='v1', net='N', x_mm=3, y_mm=4), PCBVia(id='v2', net='N', x_mm=17, y_mm=4)]
    return project


def test_routes_all_three_net_pads_and_keeps_original_and_existing_copper():
    project = simple()
    project.tracks = [PCBTrack(id='existing', net='N', points=[dict(x_mm=3,y_mm=4),dict(x_mm=3,y_mm=6)])]
    original = deepcopy(project.model_dump(mode='json'))
    result = assess_routing(project)
    assert result['base_sha256'] == pcb_digest(project) and not result['original_modified']
    assert result['minimum_successful_tested_layers'] == 2 and not result['mathematical_minimum_proven']
    trial = result['trials'][0]
    assert trial['status'] == 'routed' and trial['connectivity_complete']
    assert trial['new_tracks'] >= 2 and trial['new_vias'] == 0
    candidate = PCBProject.model_validate(trial['candidate'])
    assert candidate.tracks[0] == project.tracks[0]
    assert candidate.components == project.components
    assert inspect_layout(candidate)['status'] == 'geometric_checks_passed'
    assert project.model_dump(mode='json') == original
    json.dumps(result, allow_nan=False)


def test_two_plane_separator_fails_then_four_has_qualified_geometric_via_candidate():
    project = walls(through=True)
    original = project.model_dump(mode='json')
    result = assess_routing(project, max_expansions=12000)
    assert [trial['layer_count'] for trial in result['trials']] == [2, 4, 6, 8]
    assert result['trials'][0]['status'] in ('blocked', 'budget_exhausted')
    higher = result['trials'][1]
    assert higher['status'] == 'partial' and higher['connectivity_complete']
    assert 'qualified_candidate' in higher and 'candidate' not in higher
    assert result['minimum_successful_tested_layers'] is None
    assert result['minimum_geometrically_routed_layers'] == 4
    candidate = PCBProject.model_validate(higher['qualified_candidate'])
    assert candidate.tracks[:2] == project.tracks and candidate.vias[:2] == project.vias
    assert all((v.diameter_mm,v.drill_mm)==(.6,.3) for v in candidate.vias[2:])
    assert any(track.layer in ('In1.Cu', 'In2.Cu') for track in candidate.tracks[2:])
    assert any(f['code']=='drill_checks_partial' for f in higher['geometric_check']['findings'])
    assert not result['mathematical_minimum_proven'] and result['unsupported_layer_candidates'] == []
    assert project.model_dump(mode='json') == original


def test_declared_nondrilled_four_plane_pads_can_strictly_route_inner_plane_model():
    # These are declared geometric bridges, not a claim of a fabricated pad.
    project = walls(four=True)
    result = assess_routing(project)
    trial = result['trials'][0]
    assert trial['status'] == 'routed' and result['minimum_successful_tested_layers'] == 4
    assert trial['geometric_check']['status'] == 'geometric_checks_passed'
    assert not result['mathematical_minimum_proven']


def test_no_via_template_or_explicit_inner_pad_access_is_not_invented():
    project = walls()
    result = assess_routing(project, max_expansions=5000)
    assert result['minimum_successful_tested_layers'] is None
    assert result['minimum_geometrically_routed_layers'] is None
    assert all(t['new_vias'] == 0 and 'candidate' not in t for t in result['trials'])
    assert not result['mathematical_minimum_proven']
    assert any(not b.get('via_template_available', True) for t in result['trials'] for b in t['blockers'])


def test_active_layer_does_not_silently_use_other_pad_planes():
    project = simple()
    project.components[1].pins[0].layers = ['B.Cu']
    result = assess_routing(project, active_layer='F.Cu', max_expansions=100)
    assert len(result['trials']) == 1
    trial = result['trials'][0]
    assert trial['scope'] == 'current-layer' and trial['routing_layers'] == ['F.Cu']
    assert not trial['connectivity_complete'] and 'candidate' not in trial
    assert result['minimum_successful_tested_layers'] is None


def test_budget_is_total_bounded_and_not_an_impossibility_verdict():
    result = assess_routing(walls(), max_expansions=2)
    assert result['total_expansions'] <= 2
    assert any(trial['status']=='budget_exhausted' for trial in result['trials'])
    assert result['minimum_successful_tested_layers'] is None
    assert result['mathematical_minimum_proven'] is False


def test_preexisting_clearance_errors_never_pass_by_unchanged_error_count():
    project = simple()
    project.components.append(pad('BAD', 'GND', 3, 4))
    before = project.model_dump(mode='json')
    result = assess_routing(project)
    assert all(t['status']=='blocked' and 'candidate' not in t for t in result['trials'])
    assert all(any(f['severity']=='error' for f in t['geometric_check']['findings']) for t in result['trials'])
    assert project.model_dump(mode='json') == before


def test_rotated_noncircular_pad_is_obstacle_and_candidate_rechecked():
    project = simple()
    project.components = project.components[:2]+[
        pad('ROT', 'GND', 10, 6, shape='rect', size_x_mm=5, size_y_mm=2, rotation_deg=37)]
    result = assess_routing(project, max_expansions=4000)
    for trial in result['trials']:
        if 'candidate' in trial:
            assert inspect_layout(PCBProject.model_validate(trial['candidate']))['status']=='geometric_checks_passed'
    assert not result['mathematical_minimum_proven']


def test_new_via_reuses_declared_geometry_and_remains_qualified_not_strict():
    project = simple()
    project.components = project.components[:2]+[pad('G', 'GND', 10, 10)]
    project.components[1].pins[0].layers=['B.Cu']
    project.vias=[PCBVia(id='declared',net='GND',x_mm=10,y_mm=10,diameter_mm=.8,drill_mm=.4)]
    result = assess_routing(project, max_expansions=6000)
    trial = result['trials'][0]
    assert trial['status']=='partial' and trial['connectivity_complete']
    assert trial['new_vias']>=1 and 'candidate' not in trial
    candidate=PCBProject.model_validate(trial['qualified_candidate'])
    assert candidate.vias[0]==project.vias[0]
    assert all((v.diameter_mm,v.drill_mm)==(.8,.4) for v in candidate.vias[1:])
    assert result['minimum_successful_tested_layers'] is None


def test_missing_fill_warning_never_becomes_strict_drc_success():
    raw=simple().model_dump(mode='json')
    raw['zones']=[dict(id='unfilled',net='GND',layer='F.Cu',outline=[
        dict(x_mm=x,y_mm=y) for x,y in [(1,1),(19,1),(19,11),(1,11)]])]
    result=assess_routing(PCBProject.model_validate(raw))
    assert result['minimum_successful_tested_layers'] is None
    assert result['minimum_geometrically_routed_layers']==2
    assert result['trials'][0]['status']=='partial' and 'qualified_candidate' in result['trials'][0]
    assert any(f['code']=='zone_fill_missing' for f in result['trials'][0]['geometric_check']['findings'])


def test_uncertain_fill_unrouted_warning_still_blocks_connectivity_success():
    project=simple();project.components=project.components[:2]
    project.components[1].pins[0].layers=['B.Cu']
    raw=project.model_dump(mode='json')
    raw['zones']=[dict(id='fractured',net='N',layer='F.Cu',outline=[
        dict(x_mm=x,y_mm=y) for x,y in [(1,1),(19,1),(19,11),(1,11)]],
        filled_polygons=[dict(points=[dict(x_mm=x,y_mm=y) for x,y in
            [(1,1),(5,1),(5,5),(1,5),(1,1),(2,2),(2,3),(3,3),(3,2),(2,2),(1,1)]])])]
    result=assess_routing(PCBProject.model_validate(raw),active_layer='F.Cu')
    trial=result['trials'][0]
    assert any(f['code']=='unrouted_net' and f['severity']=='warning' for f in trial['geometric_check']['findings'])
    assert not trial['connectivity_complete'] and 'qualified_candidate' not in trial and 'candidate' not in trial
    assert result['minimum_successful_tested_layers'] is result['minimum_geometrically_routed_layers'] is None


def test_oversized_contours_stop_before_existing_quadratic_drc(monkeypatch):
    import cadstudio.pcb_routing_aid as routing
    project=simple()
    # More than512 legal model segments, no real model or geometry load.
    project.tracks=[PCBTrack(id='s'+str(i),net='N',points=[dict(x_mm=3,y_mm=4),dict(x_mm=3,y_mm=5)]) for i in range(513)]
    monkeypatch.setattr(routing,'inspect_layout',lambda *_:pytest.fail('Unbounded DRC entered'))
    result=assess_routing(project)
    assert all(t['status']=='budget_exhausted' and t['geometric_check']['status']=='not_run_resource_limit' for t in result['trials'])
    assert result['total_expansions']==0 and result['minimum_successful_tested_layers'] is None


@pytest.mark.parametrize('kwargs', [dict(width_mm=float('nan')), dict(width_mm=0),
    dict(max_expansions=True), dict(max_expansions=0), dict(active_layer='In1.Cu')])
def test_invalid_search_inputs_fail_without_mutation(kwargs):
    project = simple(); before = project.model_dump(mode='json')
    with pytest.raises(ValueError):
        assess_routing(project, **kwargs)
    assert project.model_dump(mode='json') == before


def stacked_wall(count, *, leave_inner=None, vias=False):
    layers=copper_layers(dict(layer_count=count))
    # Explicit geometric multilayer pads only. This is not a fabrication claim.
    p=PCBProject(width_mm=20,height_mm=8,edge_clearance_mm=0,layer_count=count,nets=['GND','N'],
        components=[pad('G1','GND',10,.5,layers),pad('G2','GND',10,7.5,layers),
            pad('N1','N',3,4,['F.Cu'] if vias else layers,shape='roundrect',size_x_mm=1.8,size_y_mm=.8,rotation_deg=25),
            pad('N2','N',17,4,['F.Cu'] if vias else layers)],
        tracks=[PCBTrack(id='wall'+str(i),net='GND',layer=layer,points=[dict(x_mm=10,y_mm=.5),dict(x_mm=10,y_mm=7.5)])
            for i,layer in enumerate(layers) if layer!=leave_inner])
    if vias:p.vias=[PCBVia(id='v1',net='N',x_mm=3,y_mm=4),PCBVia(id='v2',net='N',x_mm=17,y_mm=4)]
    return p


@pytest.mark.parametrize('count,inner',[(6,'In3.Cu'),(8,'In5.Cu')])
def test_actual_six_eight_layer_models_route_declared_noncircular_inner_pad_access(count,inner):
    p=stacked_wall(count,leave_inner=inner);before=p.model_dump(mode='json')
    result=assess_routing(p,max_expansions=12000);trial=result['trials'][0]
    assert trial['status']=='routed' and trial['layer_count']==count
    assert result['minimum_successful_tested_layers']==count and not result['mathematical_minimum_proven']
    candidate=PCBProject.model_validate(trial['candidate'])
    assert any(t.layer==inner for t in candidate.tracks[len(p.tracks):])
    assert candidate.components==p.components and p.model_dump(mode='json')==before
    assert inspect_layout(candidate)['status']=='geometric_checks_passed'
    assert copper_layers(candidate)==['F.Cu',*['In'+str(i)+'.Cu' for i in range(1,count-1)],'B.Cu']
    endpoint=PCBVia(id='span',net='N',x_mm=3,y_mm=4)
    assert via_layers(candidate,endpoint)==copper_layers(candidate)


@pytest.mark.parametrize('count,next_count,free_inner',[(4,6,'In3.Cu'),(6,8,'In5.Cu')])
def test_real_larger_stack_trial_preserves_copper_and_never_promotes_drill_warning(count,next_count,free_inner):
    p=stacked_wall(count,vias=True);before=p.model_dump(mode='json')
    result=assess_routing(p,max_expansions=24000)
    larger=next(t for t in result['trials'] if t['layer_count']==next_count)
    assert larger['status']=='partial' and larger['connectivity_complete'] and 'candidate' not in larger
    candidate=PCBProject.model_validate(larger['qualified_candidate'])
    assert candidate.tracks[:len(p.tracks)]==p.tracks and candidate.vias[:2]==p.vias
    assert any(t.layer==free_inner for t in candidate.tracks[len(p.tracks):])
    assert all(via_layers(candidate,v)==copper_layers(candidate) for v in candidate.vias)
    assert result['minimum_successful_tested_layers'] is None and not result['mathematical_minimum_proven']
    assert result['total_expansions']<=24000 and p.model_dump(mode='json')==before


def test_six_layer_via_noncontiguous_span_is_not_rewritten_for_eight():
    p=stacked_wall(6,vias=True);p.vias[0].layers=copper_layers(p)
    result=assess_routing(p,max_expansions=1000)
    eight=result['trials'][-1]
    assert eight['layer_count']==8 and eight['status']=='blocked'
    assert eight['geometric_check']['status']=='not_run_incompatible_stack' and eight['new_tracks']==0
    assert p.vias[0].layers==['F.Cu','In1.Cu','In2.Cu','In3.Cu','In4.Cu','B.Cu']


def test_eight_current_layer_scope_and_inactive_inner_rejection():
    p=stacked_wall(8,leave_inner='In6.Cu')
    result=assess_routing(p,active_layer='In6.Cu')
    assert len(result['trials'])==1 and result['trials'][0]['status']=='routed'
    assert result['trials'][0]['routing_layers']==['In6.Cu'] and result['trials'][0]['scope']=='current-layer'
    raw=p.model_dump();raw['layer_count']=6
    with pytest.raises(ValueError):PCBProject.model_validate(raw)


@pytest.mark.parametrize('count,expected',[(2,'4c9b3213133a1597a4fe8b259af23661aff6d9cf0d4e777ea5dcc54632e21826'),
    (4,'556600760910e8321d9c794d20bb7ecda2ddff53feec8591d94dfaf5dddb8270')])
def test_two_four_serialization_matches_released338_tiny_golden_snapshots(count,expected):
    # Generated once from released338's untouched model using only this tiny
    # declarative fixture. No legacy app/project or current file is loaded here.
    raw=dict(name='Legacy fixture',layer_count=count,nets=['GND','N'],components=[dict(ref='J1',x_mm=4,y_mm=4,pins=[dict(number='1',net='N')])])
    p=PCBProject.model_validate(raw)
    assert pcb_digest(p)==expected and 'library_metadata' not in p.model_dump()['components'][0]
    assert pcb_digest(PCBProject.model_validate(p.model_dump()))==expected
