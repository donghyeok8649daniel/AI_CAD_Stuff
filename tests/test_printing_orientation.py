"""Surface-based print recommendations, exact fit and reversible manual poses."""
from copy import deepcopy
from threading import Event, Thread

import cadquery as cq
import pytest

from cadstudio.imported import encode_shape
from cadstudio.kernel import build, exact_bounds
from cadstudio.models import Design, Part
import cadstudio.printing as printing


def imported(shape, identifier='body'):
    return Design(parts=[Part(id=identifier, name='Asymmetric body',
        geometry=dict(kind='imported', asset_id='fixture'), transform=dict(x=33, z=27, rz=37))],
        assets={'fixture': encode_shape(shape, 'Synthetic print fixture')})


def profile(points):
    return Design(parts=[Part(id='body', name='Overhanging profile', geometry=dict(kind='extrusion',
        thickness=12, points=[dict(x=x, y=y) for x,y in points]), transform=dict(x=100, rx=90, rz=90))])


@pytest.mark.parametrize('points', [
    [(0,0),(8,0),(8,16),(30,16),(30,20),(0,20)],
    [(-4,0),(4,0),(4,16),(15,16),(15,20),(-15,20),(-15,16),(-4,16)],
    [(0,0),(6,0),(6,16),(24,16),(24,22),(0,22)],
])
def test_asymmetric_l_t_geometry_reduces_real_downward_surface_demand(points):
    design = profile(points); before = design.model_dump()
    poses = {'body': dict(rx=90, ry=0, rz=0, x=-7, y=8)}; saved = deepcopy(poses)
    result = printing.recommend_print_orientations(design, ['body'], placements=poses)
    d = result['diagnostics']['body']; a,b = d['baseline'],d['recommended']
    assert a['overhang_area_mm2'] > 100 and a['support_proxy_mm3'] > 1000
    assert b['overhang_area_mm2'] < a['overhang_area_mm2'] / 10
    assert b['support_proxy_mm3'] < a['support_proxy_mm3'] / 10
    assert b['contact_area_mm2'] > a['contact_area_mm2']
    assert b['stable_contact'] and b['com_footprint_margin_mm'] > 0 and b['fits_bed']
    assert b['score'] < a['score'] and d['candidates_evaluated'] <= 49
    assert design.model_dump() == before and poses == saved
    assert result['placements']['body']['x'] == -7 and result['placements']['body']['y'] == 8
    assert result['method']['estimated_only'] and result['method']['overhang_angle_deg'] == 45
    # Recommendation is exact whole-body orientation, not a modified mesh.
    plates, previews, warnings = printing.prepare_print_plates(design, ['body'], placements=result['placements'])
    assert not warnings and len(plates) == 1
    assert previews[0]['stats']['volume'] == pytest.approx(build(design)[0].Volume())


def test_known_roof_projection_and_height_proxy_use_outward_normals():
    result = printing.recommend_print_orientations(profile([(0,0),(8,0),(8,16),(30,16),(30,20),(0,20)]),
        ['body'], placements={'body': dict(rx=90)})
    baseline = result['diagnostics']['body']['baseline']
    assert baseline['overhang_area_mm2'] == pytest.approx(22*12)
    assert baseline['support_proxy_mm3'] == pytest.approx(22*12*16)
    assert baseline['contact_area_mm2'] == pytest.approx(8*12)
    assert baseline['com_footprint_margin_mm'] < 0 and not baseline['stable_contact']


def test_cylinder_flat_end_preferred_over_small_curved_bed_contact():
    design = Design(parts=[Part(id='body', name='Cylinder', geometry=dict(kind='cylinder', diameter=12, height=20))])
    result = printing.recommend_print_orientations(design, ['body'], placements={'body': dict(ry=90)})
    a,b = (result['diagnostics']['body'][k] for k in ('baseline','recommended'))
    assert a['overhang_area_mm2'] > 0 and b['overhang_area_mm2'] == pytest.approx(0, abs=1e-8)
    # The .1mm near-bed band includes a finite curved strip; its area must
    # remain visibly smaller than the real flat cap, not a zero-area ideal.
    assert b['contact_area_mm2'] > 3*a['contact_area_mm2']
    assert b['contact_area_mm2'] == pytest.approx(36*3.141592653589793, rel=.01)
    assert b['stable_contact'] and b['stability_risk'] < a['stability_risk']
    assert b['size_mm'] == pytest.approx([12,12,20], abs=1e-6)


def test_oblique_planar_surface_is_candidate_beyond_quarter_turns():
    shape = cq.Workplane('XY').box(30,14,5).val().rotate((0,0,0),(0,1,0),23)
    result = printing.recommend_print_orientations(imported(shape), ['body'])
    d = result['diagnostics']['body']
    assert d['recommended']['contact_area_mm2'] == pytest.approx(30*14, abs=.02)
    assert d['recommended']['support_proxy_mm3'] == pytest.approx(0, abs=.01)
    assert d['recommended']['stable_contact']
    assert any(abs(angle/90-round(angle/90)) > .05 for angle in d['chosen'].values())


def test_exact_bed_fit_precedes_small_support_score_and_no_cut_oversize():
    design = Design(parts=[Part(id='body', name='Long plate', geometry=dict(kind='plate', length=35, width=12, thickness=4, hole_count=0))])
    result = printing.recommend_print_orientations(design, ['body'], bed=(15,40,10))
    assert not result['diagnostics']['body']['baseline']['fits_bed']
    best = result['diagnostics']['body']['recommended']
    assert best['fits_bed'] and best['size_mm'] == pytest.approx([12,35,4])
    _, previews, warnings = printing.prepare_print_plates(design, ['body'], bed=(15,40,10), placements=result['placements'])
    assert not warnings and previews[0]['stats']['volume'] == pytest.approx(35*12*4)
    nofit = printing.recommend_print_orientations(design, ['body'], bed=(3,3,3))
    assert not nofit['diagnostics']['body']['recommended']['fits_bed']
    assert nofit['warnings'] and '자르지' in nofit['warnings'][0]
    assert build(design)[0].Volume() == pytest.approx(35*12*4)


def test_current_tie_manual_after_auto_and_excluded_poses_are_preserved():
    raw = Design(parts=[Part(id='body', name='Plate', geometry=dict(kind='plate', length=20, width=10, thickness=3, hole_count=0)),
        Part(id='bolt', name='M4 bolt', geometry=dict(kind='cylinder', diameter=4, height=8))]).model_dump()
    saved = {'body': dict(rx=0,ry=0,rz=180,x=9,y=-8), 'bolt': dict(rx=123,x=11,y=12)}
    original = deepcopy(raw); before = deepcopy(saved)
    result = printing.recommend_print_orientations(raw, ['body','bolt'], placements=saved, exclude_fasteners=True)
    assert result['placements'] == saved and saved == before and raw == original
    assert result['excluded_ids'] == ['bolt'] and result['excluded_details'][0]['source'] == 'part_name_hint'
    assert set(result['diagnostics']) == {'body'}
    manual = deepcopy(result['placements']); manual['body'].update(rx=90,ry=0,rz=23,x=-20,y=19)
    plates, previews, warnings = printing.prepare_print_plates(raw, ['body','bolt'], placements=manual, exclude_fasteners=True)
    assert not warnings and previews[0]['print_placements']['body'] == manual['body']
    assert exact_bounds(build(plates[0])[0]).zlen == pytest.approx(10)
    assert result['placements'] == saved  # later manual edit does not mutate recommendation


def test_copy_recommendations_have_stable_ids_and_independent_manual_baselines():
    design = profile([(0,0),(8,0),(8,16),(30,16),(30,20),(0,20)])
    first = printing.recommend_print_orientations(design, ['body'], copies={'body':2})
    second = printing.recommend_print_orientations(design, ['body'], copies={'body':2})
    assert first == second and len(first['diagnostics']) == 2
    copy_id = next(k for k in first['placements'] if k != 'body')
    third = printing.recommend_print_orientations(design, ['body'], copies={'body':2}, placements={copy_id:dict(rx=90)})
    assert third['diagnostics'][copy_id]['baseline']['support_proxy_mm3'] > 1000
    assert third['diagnostics']['body']['baseline']['support_proxy_mm3'] == pytest.approx(0)


def test_actual_tessellation_cancel_returns_no_partial_poses(monkeypatch):
    design = profile([(0,0),(8,0),(8,16),(30,16),(30,20),(0,20)])
    before = design.model_dump(); poses={'body':dict(rx=90,x=4)}; saved=deepcopy(poses)
    event = Event(); calls=[]; original=cq.Shape.tessellate
    def tessellate(shape, *args):
        result=original(shape,*args); calls.append(len(result[1])); event.set(); return result
    monkeypatch.setattr(cq.Shape,'tessellate',tessellate)
    with pytest.raises(printing.PrintCancelled):
        printing.recommend_print_orientations(design,['body'],placements=poses,cancelled=event.is_set)
    assert calls and design.model_dump()==before and poses==saved
    assert printing.KERNEL_LOCK.acquire(blocking=False)
    printing.KERNEL_LOCK.release()


def test_bounded_time_and_mesh_failure_preserve_manual_pose(monkeypatch):
    design=profile([(0,0),(8,0),(8,16),(30,16),(30,20),(0,20)])
    poses={'body':dict(rx=90,x=17)}; saved=deepcopy(poses)
    clock=iter([0.,0.,0.,0.,1.])
    monkeypatch.setattr(printing.time,'monotonic',lambda:next(clock,1.))
    with pytest.raises(ValueError,match='시간 한도'):
        printing.recommend_print_orientations(design,['body'],placements=poses,max_seconds=.1)
    assert poses==saved
    monkeypatch.undo()
    original=cq.Shape.tessellate
    def excessive(shape,*args):
        vertices,triangles=original(shape,*args)
        return vertices,triangles*(50001//len(triangles)+1)
    monkeypatch.setattr(cq.Shape,'tessellate',excessive)
    with pytest.raises(ValueError,match='표면 계산 한도'):
        printing.recommend_print_orientations(design,['body'],placements=poses)
    assert poses==saved


def test_cancel_while_waiting_for_kernel_lock_never_builds(monkeypatch):
    locked, release, cancelled = Event(), Event(), Event()
    def owner():
        with printing.KERNEL_LOCK:
            locked.set(); release.wait(3)
    thread=Thread(target=owner); thread.start()
    try:
        assert locked.wait(1)
        monkeypatch.setattr(printing,'build',lambda *_:pytest.fail('cancelled wait reached geometry'))
        calls=[]
        def cancel():
            calls.append(1)
            if len(calls)>=4: cancelled.set()
            return cancelled.is_set()
        with pytest.raises(printing.PrintCancelled):
            printing.recommend_print_orientations(profile([(0,0),(10,0),(10,10),(0,10)]),['body'],cancelled=cancel)
    finally:
        release.set(); thread.join(2)
    assert len(calls)>=4 and not thread.is_alive()


def test_recommendation_keeps_unselected_boolean_tools_and_raw_mates_owned():
    raw=Design(parts=[Part(id='body',name='Bored plate',
        geometry=dict(kind='plate',length=20,width=20,thickness=5,hole_count=0),
        features=[dict(id='cut',kind='solid',operation='boolean',boolean_mode='cut',tool_part_id='tool')]),
        Part(id='tool',name='Unselected cutter',geometry=dict(kind='cylinder',diameter=4,height=20),transform=dict(z=-5))]).model_dump()
    raw['parts'][1]['transform']['x']=99
    raw['mates']=[dict(id='fixture-mate',kind='rigid',parent='body',child='tool',z=-5)]
    before=deepcopy(raw)
    result=printing.recommend_print_orientations(raw,['body'])
    plates,previews,warnings=printing.prepare_print_plates(raw,['body'],placements=result['placements'])
    assert raw==before and not warnings and [p.id for p in plates[0].parts]==['body']
    assert previews[0]['stats']['volume']==pytest.approx(2000-3.141592653589793*4*5)


@pytest.mark.parametrize('options', [
    {'placements':{'absent':{'rx':0}}}, {'placements':{'body':{'rx':float('nan')}}},
    {'overhang_angle':0}, {'overhang_angle':float('inf')}, {'max_seconds':0},
    {'max_seconds':True}, {'copies':{'body':0}}, {'exclude_fasteners':1},
])
def test_invalid_recommendation_options_rejected_before_build(monkeypatch,options):
    monkeypatch.setattr(printing,'build',lambda *_:pytest.fail('invalid option reached geometry'))
    with pytest.raises(ValueError):
        printing.recommend_print_orientations(profile([(0,0),(10,0),(10,10),(0,10)]),['body'],**options)


def test_empty_selection_all_excluded_and_initial_cancel_fail_closed():
    design=Design(parts=[Part(id='body',name='M4 nut',geometry=dict(kind='cylinder',diameter=4,height=8))])
    for ids in ([],['absent']):
        with pytest.raises(ValueError,match='선택'):printing.recommend_print_orientations(design,ids)
    with pytest.raises(ValueError,match='없습니다'):
        printing.recommend_print_orientations(design,['body'],exclude_fasteners=True)
    with pytest.raises(printing.PrintCancelled):
        printing.recommend_print_orientations(design,['body'],cancelled=lambda:True)
