"""Small adapter-only fixtures; frozen core fixture suite is intentionally not run."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
import pytest

from cadstudio.pcb import PCBProject, pcb_digest
from cadstudio.pcb_pin_alignment import align_components, compose_target_pose, CORE_SHA256

GOLDEN=json.loads((Path(__file__).parent/'fixtures/pin_alignment_world339.json').read_text(encoding='utf-8'))
VERIFICATION={side:dict(footprint_verified=True,pin_map_verified=True) for side in ('source','target')}
MATING=dict(source_normal=[0,0,1],target_normal=[0,0,1],source_side='bottom',target_side='top',
    allowed_side_pairs=[['bottom','top']],stand_off_height_mm=0,insertion_depth_mm=0,keying_verified=True)
CONSTRAINTS=dict(max_pin_error_mm=.01,pitch_tolerance_mm=.01,normal_tolerance_deg=.1,tolerances_verified=True,fixed_mounts=[])


def component(ref,x,y,pins,*,body_width=2,body_height=2):
    roles={'drive':'power_out','accept':'power_in','ground':'ground','passive':'passive'}
    specs=[dict(number=number,logical_pin_key=number,role=roles[pin['voltage_role']],
        operating_min_v=pin['voltage_range_v'][0],operating_max_v=pin['voltage_range_v'][1],
        source_url='https://example.org/synthetic-pin-drawing',condition='Synthetic adapter fixture, not a real product') for number,pin in pins.items()]
    return dict(ref=ref,value='Synthetic only',mpn='Fixture part',footprint='Frozen-fixture-local-pads',
        x_mm=x,y_mm=y,body_width_mm=body_width,body_height_mm=body_height,
        pins=[dict(number=number,net=pin['net'],x_mm=pin['xyz'][0],y_mm=pin['xyz'][1],diameter_mm=.5) for number,pin in pins.items()],
        library_metadata=dict(manufacturer='Synthetic fixture',model=ref,source_url='https://example.org/synthetic-pin-drawing',
            revision='fixture-r1',pin1_number=next(iter(pins)),mounted_side='F',orientation_reference='+X fixture datum',
            body_height_mm=1,service_clearance_mm=0,geometry_complete_declared=True,
            footprint_review_state='source_reviewed',reviewed_by='Synthetic fixture author',reviewed_date='2026-10-16',
            review_note='Synthetic complete declaration; no manufacturer verification claim',pin_specs=specs))


def golden_board():
    request=GOLDEN['request']
    return PCBProject(width_mm=300,height_mm=300,nets=['GND']+[pin['net'] for side in ('source','target') for pin in request[side]['pins'].values()],
        components=[component('SOURCE',50,60,request['source']['pins']),component('TARGET',100,200,request['target']['pins'])])


def simple_board():
    source={'1':dict(xyz=[-5,0,0],net='GND',voltage_role='ground',voltage_range_v=[0,0]),
        '2':dict(xyz=[-5,2,0],net='GND',voltage_role='ground',voltage_range_v=[0,0])}
    target={number:{**pin,'xyz':[5,pin['xyz'][1],0]} for number,pin in source.items()}
    first=component('J1',10,10,source)
    # Separate copper layers are deliberate: same-layer coincident pads must be rejected.
    for pin in first['pins']:pin['layers']=['B.Cu']
    first['library_metadata']['mounted_side']='B'
    return PCBProject(width_mm=60,height_mm=30,nets=['GND'],components=[first,component('J2',25,10,target)])


def run(project=None,**kwargs):
    return align_components(project or simple_board(),'J1','J2',
        [dict(source_pin=number,target_pin=number,net_compatibility='compatible') for number in ('1','2')],
        mating=kwargs.pop('mating',MATING),constraints=kwargs.pop('constraints',CONSTRAINTS),
        verification=kwargs.pop('verification',VERIFICATION),**kwargs)


def test_vendor_core_is_byte_exact_frozen_r1_not_reimplemented():
    core=Path(__file__).parents[1]/'cadstudio/_pcb_pin_alignment_core_r1.py'
    assert sha256(core.read_bytes()).hexdigest()==CORE_SHA256


def test_golden_local_target_world_composition_and_delta_without_flattening():
    board=golden_board();before=board.model_dump(mode='json');request=GOLDEN['request']
    output=align_components(board,'SOURCE','TARGET',request['mapping'],mating=request['mating'],constraints=request['constraints'],
        verification=VERIFICATION,target_world_pose=GOLDEN['target_assembly_world_pose'])
    assert output['core_status']=='aligned_preview'
    assert output['status']=='nonplanar_preview' and output['candidate'] is None and not output['can_apply']
    for key in ('rotation','translation_xyz_mm'):
        actual=output['source_local_to_target_local'][key]
        expected=GOLDEN['expected_core_source_local_to_target_local'][key]
        if key=='rotation':
            for a,b in zip(actual,expected):assert a==pytest.approx(b,abs=1e-8)
        else:assert actual==pytest.approx(expected,abs=1e-8)
    assert output['source_assembly_world_pose']['translation_xyz_mm']==pytest.approx([80,210,13])
    for number,expected in GOLDEN['expected_source_pin_world_xyz_mm'].items():
        assert output['source_pin_world_xyz_mm'][number]==pytest.approx(expected,abs=1e-8)
    delta=output['source_world_delta'];old=[50,60,0]
    assert [sum(a*b for a,b in zip(row,old))+t for row,t in zip(delta['rotation'],delta['translation_xyz_mm'])]==pytest.approx([80,210,13])
    assert board.model_dump(mode='json')==before
    assert output['preview_only'] and not output['mechanical_mating_safety_verified'] and not output['manufacturing_verified']
    json.dumps(output,allow_nan=False)


def test_coplanar_candidate_changes_only_whole_component_pose_and_preserves_original():
    board=simple_board();before=board.model_dump(mode='json')
    output=run(board)
    assert output['status']=='aligned_preview' and output['can_apply'] and output['moved_refs']==['J1']
    assert output['base_sha256']==pcb_digest(board)
    assert output['candidate']['components'][0]['x_mm']==pytest.approx(35)
    restored=deepcopy(output['candidate'])
    for field in ('x_mm','y_mm','rotation_deg'):restored['components'][0][field]=before['components'][0][field]
    assert restored==before and board.model_dump(mode='json')==before
    assert output['geometry_report'] and not output['geometry_report']['after_bodies']


@pytest.mark.parametrize('missing',['verification','metadata','review','voltage'])
def test_catalog_or_unverified_declarations_cannot_become_verified_placement(missing):
    raw=simple_board().model_dump(mode='json');kwargs={}
    if missing=='verification':kwargs['verification']={}
    elif missing=='metadata':raw['components'][0].pop('library_metadata')
    elif missing=='review':raw['components'][0]['library_metadata'].update(footprint_review_state='user_declared',reviewed_by='')
    else:raw['components'][0]['library_metadata']['pin_specs'][0]['operating_max_v']=None
    output=run(raw,**kwargs)
    assert output['candidate'] is None and not output['can_apply'] and output['core_status']=='unverified'
    assert output['declarations']['source']['gender']=='unknown'


@pytest.mark.parametrize('kind',['track','via','zone'])
def test_existing_copper_is_never_removed_or_invalidated(kind):
    raw=simple_board().model_dump(mode='json')
    if kind=='track':raw['tracks']=[dict(id='T1',net='GND',points=[dict(x_mm=20,y_mm=20),dict(x_mm=25,y_mm=20)])]
    elif kind=='via':raw['vias']=[dict(id='V1',net='GND',x_mm=20,y_mm=20,diameter_mm=.6,drill_mm=.3,layers=['F.Cu','B.Cu'])]
    else:raw['zones']=[dict(id='Z1',net='GND',layer='F.Cu',outline=[dict(x_mm=x,y_mm=y) for x,y in [(1,1),(59,1),(59,29),(1,29)]])]
    before=deepcopy(raw);output=run(raw)
    assert output['status']=='blocked' and output['candidate'] is None
    assert any(row['code']=='EXISTING_COPPER_LOCK' for row in output['issues']) and raw==before


def test_geometric_overlap_blocks_even_if_pin_core_is_aligned():
    raw=simple_board().model_dump(mode='json')
    for row in raw['components']:row['body_width_mm']=12
    output=run(raw)
    assert output['core_status']=='aligned_preview' and output['status']=='blocked' and output['candidate'] is None
    assert output['geometry_report']['after_bodies']


def test_external_target_project_returns_only_assembly_preview():
    board=golden_board().model_dump(mode='json');request=GOLDEN['request']
    source=deepcopy(board);source['components']=source['components'][:1]
    target=deepcopy(board);target['components']=target['components'][1:]
    before=deepcopy((source,target))
    output=align_components(source,'SOURCE','TARGET',request['mapping'],mating=request['mating'],constraints=request['constraints'],
        verification=VERIFICATION,target_project=target,target_world_pose=GOLDEN['target_assembly_world_pose'])
    assert output['status']=='assembly_preview' and output['target_external'] and output['candidate'] is None
    assert output['source_assembly_world_pose']['translation_xyz_mm']==pytest.approx([80,210,13])
    assert (source,target)==before


def test_reflection_and_unbounded_mapping_rejected_without_mutation():
    pose=dict(rotation=[[-1,0,0],[0,1,0],[0,0,1]],translation_xyz_mm=[0,0,0])
    with pytest.raises(ValueError):compose_target_pose(pose,pose)
    output=align_components(simple_board(),'J1','J2',[dict(source_pin='1',target_pin='1')]*33)
    assert output['status']=='rejected' and output['candidate'] is None


def test_unknown_mating_height_remains_unverified_not_inferred_from_body_or_catalog():
    mating=deepcopy(MATING);mating.pop('stand_off_height_mm')
    output=run(mating=mating)
    assert output['core_status']=='underdetermined' and output['candidate'] is None
    assert 'stand_off_height_mm' not in output['declarations']['mating']
    assert output['declarations']['source']['contact_height'].startswith('unknown')


def test_no_gui_kernel_or_native_imports():
    assert not any(name in sys.modules for name in ('PySide6','vtkmodules','OCP','cadquery'))


def test_same_layer_coincident_pads_remain_blocked_not_hidden_as_mating():
    raw=simple_board().model_dump(mode='json')
    for pin in raw['components'][0]['pins']:pin['layers']=['F.Cu']
    output=run(raw)
    assert output['core_status']=='aligned_preview' and output['status']=='blocked' and output['candidate'] is None
    assert any(row['code']=='pad_collision' for row in output['geometry_report']['after']['findings'])


def test_proper_three_dimensional_flip_is_previewed_never_flattened():
    mating=deepcopy(MATING)
    mating.update(source_side='top',allowed_side_pairs=[['top','top']])
    output=run(mating=mating)
    assert output['core_status']=='aligned_preview' and output['status']=='nonplanar_preview'
    assert output['core']['transform']['determinant']==pytest.approx(1)
    assert output['candidate'] is None and not output['can_apply']


@pytest.mark.parametrize('target_x,may_apply',[(30,False),(25,True)])
def test_same_host_custom_target_pose_must_match_actual_saved_component(target_x,may_apply):
    board=simple_board();before=board.model_dump(mode='json')
    pose=dict(rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_xyz_mm=[target_x,10,0])
    output=run(board,target_world_pose=pose)
    assert output['core_status']=='aligned_preview' and output['can_apply'] is may_apply
    if not may_apply:
        assert output['candidate'] is None and output['status']=='assembly_preview'
        assert any(row['code']=='TARGET_HOST_POSE_UNDECLARED' for row in output['issues'])
    else:
        assert output['candidate']['components'][0]['x_mm']==pytest.approx(35)
    assert board.model_dump(mode='json')==before
