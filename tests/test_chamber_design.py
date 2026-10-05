"""Exact geometry and truthful qualification of the humidity chamber draft."""
import math

import cadquery as cq
import pytest
from pydantic import ValidationError

from cadstudio.chamber_design import (
    ChamberRequirements, ChamberRodInterface, StaticChamberRodSeal, ParasiticForceInputs,
    build_chamber, chamber_rod_pose, estimate_parasitic_force,
    gauge_only_chamber_requirements, inspect_chamber_interfaces,
)
from cadstudio.kernel import build, exact_bounds
from cadstudio.models import Design, Part
from cadstudio.native.document import Document, read_project


@pytest.fixture(scope='module')
def full_chamber():
    return build_chamber(dict(
        protected_swept_bounds=dict(minimum_mm=[-30,-44,364.7], maximum_mm=[30,32,529.7]),
        static_rod_seals=[dict(id='upper',rod_diameter_mm=25,position_xy_mm=[0,6])],
        rod_interfaces=[dict(id='lower',face='bottom',rod_diameter_mm=25,position_xy_mm=[0,6],
            bellows_inner_diameter_mm=28,bellows_outer_diameter_mm=44,installed_length_mm=44)],
    ))


def shape_map(chamber):
    return dict(zip([p.id for p in chamber.parts], build(chamber.as_design())))


def test_full_grip_chamber_is_portable_valid_separate_solids_without_hidden_collision(full_chamber):
    chamber=full_chamber; shapes=shape_map(chamber)
    assert len(chamber.parts)==33 and len(chamber.assets)==33
    assert chamber.as_design().part_groups==[]
    assert len({p.id for p in chamber.parts})==len(chamber.parts)
    assert all(s.isValid() and len(s.Solids())==1 and s.Volume()>0 for s in shapes.values())
    protected=next(e.shape for e in chamber.envelopes if e.kind=='protected_swept_volume')
    assert all(s.intersect(protected).Volume()<1e-6 for s in shapes.values())
    assert chamber.collision_pairs==[]


def test_static_upper_rod_and_dynamic_lower_axis_are_world_coaxial(full_chamber):
    interfaces={item['id']:item for item in full_chamber.interfaces}
    assert interfaces['upper']['position_mm']==pytest.approx([0,0,545.7])
    assert interfaces['lower']['position_mm']==pytest.approx([0,0,348.7])
    assert interfaces['upper']['outward_axis']==[0,0,1]
    assert interfaces['lower']['outward_axis']==[0,0,-1]
    assert interfaces['upper']['stationary_rod_required']
    assert not next(p for p in full_chamber.parts if p.id==interfaces['lower']['moving_collar_part_id']).fixed
    assert not interfaces['lower']['automatic_deformation_supported']
    shapes=shape_map(full_chamber)
    for key in ('chamber-static-upper-cap','chamber-static-upper-oring',
                'chamber-rod-lower-fixed','chamber-rod-lower-moving','chamber-rod-lower-bellows'):
        b=exact_bounds(shapes[key])
        assert (b.xmin+b.xmax)/2==pytest.approx(0,abs=1e-7)
        assert (b.ymin+b.ymax)/2==pytest.approx(0,abs=1e-7)
    assert exact_bounds(shapes['chamber-static-upper-cap']).zmax==pytest.approx(547.7)
    assert exact_bounds(shapes['chamber-rod-lower-moving']).zmin==pytest.approx(298.7)


def test_static_oring_gland_has_real_radial_compression_and_preserves_section_area(full_chamber):
    interface=next(row for row in full_chamber.interfaces if row['kind']=='static_rod_seal')
    assert interface['radial_compression_fraction']==.2
    assert interface['gland_depth_mm']==pytest.approx(4.25)
    assert .6<interface['gland_fill_fraction']<.85
    shape=shape_map(full_chamber)['chamber-static-upper-oring']
    # Section thickness 3 mm compressed radially by 20%, axial thickness
    # adjusted to retain the original circular cross-section's area.
    area=math.pi*3**2/4
    expected_volume=area*2*math.pi*(12.5+2.4/2)
    assert shape.Volume()==pytest.approx(expected_volume,rel=1e-6)
    # A stationary nominal Ø25 rod touches the O-ring but cannot overlap it.
    rod=cq.Solid.makeCylinder(12.5,12,cq.Vector(0,0,537),cq.Vector(0,0,1))
    assert shape.intersect(rod).Volume()<1e-6
    assert not interface['leak_test_verified']


def test_real_port_bores_and_compressed_door_gasket_remain_open(full_chamber):
    shapes=shape_map(full_chamber);case=shapes['chamber-case']
    for row in full_chamber.interfaces:
        if row['kind']!='static_port': continue
        origin=cq.Vector(*row['position_mm']);axis=cq.Vector(*row['outward_axis'])
        bore=cq.Solid.makeCylinder(row['bore_diameter_mm']/2-.01,30,origin-axis*10,axis)
        assert case.intersect(bore).Volume()<1e-6
        assert shapes['chamber-port-'+row['id']].intersect(bore).Volume()<1e-6
        # User-entered seal width affects the actual ring, not only validation.
        rin=3+2+.2+.5; rout=rin+row['seal_width_mm']
        assert shapes['chamber-port-'+row['id']+'-seal'].Volume()==pytest.approx(math.pi*(rout**2-rin**2)*1.6,rel=1e-6)
    gasket=exact_bounds(shapes['chamber-door-seal'])
    assert gasket.ymax-gasket.ymin==pytest.approx(1.6)
    assert exact_bounds(shapes['chamber-door']).ymax==pytest.approx(gasket.ymin)


@pytest.mark.parametrize('stroke,distal_z',[(-5,303.7),(5,293.7)])
def test_bellows_pose_preserves_ids_and_clearance_at_both_motion_extrema(full_chamber,stroke,distal_z):
    moved=chamber_rod_pose(full_chamber,'lower',stroke)
    assert [p.id for p in moved.parts]==[p.id for p in full_chamber.parts]
    assert moved.requirements.rod_interfaces[0].current_stroke_mm==stroke
    assert full_chamber.requirements.rod_interfaces[0].current_stroke_mm==0
    b=exact_bounds(shape_map(moved)['chamber-rod-lower-moving'])
    assert b.zmin==pytest.approx(distal_z)
    envelope=next(e for e in moved.envelopes if e.kind=='bellows_motion')
    assert envelope.bounds_mm()[4:]==pytest.approx([293.7,348.7])
    assert b.zmin>=293.7-1e-7 and b.zmin-284.7>=9-1e-7


def test_unknown_load_inputs_never_become_zero_or_a_verified_rating():
    estimate=estimate_parasitic_force()
    assert estimate.pressure_force_n is None and estimate.spring_force_n is None
    assert estimate.conservative_force_bound_n is None and estimate.fraction_of_test_force is None
    assert set(estimate.unknown_inputs)==set(ParasiticForceInputs.model_fields)
    assert estimate.estimate_only


def test_supplied_parasitic_inputs_preserve_sign_and_convert_mm2_to_m2():
    result=estimate_parasitic_force(dict(pressure_differential_pa=-300,
        bellows_effective_area_mm2=600,bellows_spring_rate_n_per_mm=.1,
        bellows_deflection_from_free_mm=-3,seal_friction_n=.05,preload_n=-.02,test_force_n=100))
    assert result.pressure_force_n==pytest.approx(-.18)
    assert result.spring_force_n==pytest.approx(-.3)
    assert result.conservative_force_bound_n==pytest.approx(.55)
    assert result.fraction_of_test_force==pytest.approx(.0055)
    assert result.unknown_inputs==[]
    partial=estimate_parasitic_force(dict(pressure_differential_pa=0,bellows_effective_area_mm2=600))
    assert partial.pressure_force_n==0 and partial.conservative_force_bound_n is None


def test_seal_leak_pressure_and_life_qualification_are_never_invented(full_chamber):
    report=full_chamber.report()
    assert not report['leak_test_verified'] and not report['pressure_rating_verified']
    assert not report['bellows_life_verified']
    assert all(url.startswith('https://') for url in report['sources'])
    assert any('공급사' in warning for warning in report['warnings'])
    moving=next(row for row in report['interfaces'] if row['kind']=='moving_rod')
    assert not moving['supplier_stroke_verified']


def test_complete_chamber_embedded_brep_and_parameters_survive_project_history(tmp_path,full_chamber):
    before=Design(parts=[Part(id='specimen',name='연구 시편',geometry=dict(kind='cylinder',diameter=8,height=30),
        transform=dict(z=449))])
    unchanged=before.model_dump();candidate=full_chamber.append_to(before)
    assert before.model_dump()==unchanged
    doc=Document();doc.commit(before,'기존 설계')
    doc.commit(candidate,'챔버 추가',{'chamber_requirements':full_chamber.report()['requirements']})
    target=tmp_path/'습도 챔버.cad.json';doc.write(target)
    saved=read_project(target)
    assert saved.design.model_dump()==candidate.model_dump()
    assert len(saved.history.entries)==2
    assert saved.history.entries[-1].context['chamber_requirements']['rod_interfaces'][0]['face']=='bottom'
    rebuilt=build(saved.design)
    assert len(rebuilt)==34 and all(s.isValid() for s in rebuilt)
    with pytest.raises(ValueError,match='동일 챔버 ID'):
        full_chamber.append_to(candidate)


def test_drive_and_actual_installation_obstructions_are_reported(full_chamber):
    access=next(e for e in full_chamber.envelopes if e.kind=='tool_access');b=access.bounds_mm()
    blocker=Part(id='blocker',name='공구 접근 방해물',geometry=dict(kind='cylinder',diameter=2,height=2),
        transform=dict(x=(b[0]+b[1])/2,y=(b[2]+b[3])/2,z=(b[4]+b[5])/2))
    motor=Part(id='motor',name='챔버 내부 모터',geometry=dict(kind='cylinder',diameter=5,height=10),transform=dict(z=450))
    existing=Design(parts=[blocker,motor])
    hits=inspect_chamber_interfaces(full_chamber,existing,drive_part_ids=['motor'])
    assert any(row['part_id']=='motor' and row['kind']=='interior_volume' for row in hits)
    assert any(row['part_id']=='blocker' and row['kind']=='tool_access' for row in hits)
    with pytest.raises(ValueError,match='존재하지 않는 구동'):
        inspect_chamber_interfaces(full_chamber,existing,drive_part_ids=['missing'])
    with pytest.raises(ValueError,match='기존 조립 부품'):
        inspect_chamber_interfaces(full_chamber,existing,exclude_part_ids=['blocker'])


def test_small_gauge_preset_is_explicitly_unsealed_and_window_nuts_do_not_hit_flange():
    chamber=build_chamber(gauge_only_chamber_requirements(
        dict(minimum_mm=[-8,-8,495],maximum_mm=[8,8,525]),
        specimen_swept_diameter_mm=16,specimen_part_id='specimen'))
    apertures=[row for row in chamber.interfaces if row['kind']=='unsealed_specimen_aperture']
    assert len(chamber.parts)==26 and chamber.collision_pairs==[]
    assert len(apertures)==2 and all(row['open_leak_path'] and row['seal_status']=='unresolved' for row in apertures)
    assert any('열린 누설 경로' in value for value in chamber.warnings)
    assert all(p.fixed for p in chamber.parts)


@pytest.mark.parametrize('changes',[
    dict(stroke_min_mm=10,stroke_max_mm=-10),
    dict(current_stroke_mm=6),dict(bellows_inner_diameter_mm=12),
    dict(supplier_compressed_length_mm=46),dict(supplier_extended_length_mm=54),
])
def test_invalid_bellows_dimensions_and_supplier_motion_limits_reject(changes):
    with pytest.raises(ValidationError):ChamberRodInterface.model_validate(dict(id='rod',**changes))


def test_invalid_chamber_limits_cancel_before_any_candidate_or_asset_exists():
    bounds=dict(minimum_mm=[-30,-40,-60],maximum_mm=[30,40,60])
    with pytest.raises(ValidationError):
        ChamberRequirements.model_validate(dict(protected_swept_bounds=bounds,
            prefix='1234567890123456',rod_interfaces=[dict(id='12345678901234567890')]))
    with pytest.raises(ValidationError):
        ChamberRequirements.model_validate(dict(protected_swept_bounds=bounds,clearance_mm=[0,10,10]))
    def cancelled():raise RuntimeError('test cancellation')
    with pytest.raises(RuntimeError,match='test cancellation'):
        build_chamber(dict(protected_swept_bounds=bounds),check=cancelled)
    with pytest.raises(ValidationError):
        ParasiticForceInputs.model_validate(dict(seal_friction_n=-1))
    with pytest.raises(ValidationError,match='60~85%'):
        StaticChamberRodSeal.model_validate(dict(id='underfilled',cross_section_mm=.5,axial_gland_extra_mm=5))


def test_cancel_during_physical_collision_scan_never_mutates_the_requirements(full_chamber):
    source=full_chamber.requirements.model_dump(mode='json');unchanged=full_chamber.requirements.model_dump(mode='json')
    count=0
    def cancel_late():
        nonlocal count
        count+=1
        if count==60:raise RuntimeError('collision scan cancelled')
    with pytest.raises(RuntimeError,match='collision scan cancelled'):
        build_chamber(source,check=cancel_late)
    assert source==unchanged and count==60
