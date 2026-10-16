"""New external-frame adapter and file-only UI checks; old suites are not run."""
import ast
from copy import deepcopy
from pathlib import Path
import sys
import pytest
from cadstudio.pcb import PCBProject,pcb_digest
from cadstudio.pcb_pin_alignment import align_components,pose_from_xyz_rpy


def component(ref,x,pin_x,layer='F.Cu',rotation=0):
    return dict(ref=ref,x_mm=x,y_mm=10,rotation_deg=rotation,body_width_mm=2,body_height_mm=2,
        pins=[dict(number=str(index),net='GND',x_mm=pin_x,y_mm=(index-1)*2,diameter_mm=.5,layers=[layer]) for index in (1,2)],
        library_metadata=dict(manufacturer='Synthetic',model=ref,source_url='https://example.org/frame-fixture',revision='fixture',pin1_number='1',mounted_side='F',orientation_reference='+X fixture datum',
            body_height_mm=1,service_clearance_mm=0,geometry_complete_declared=True,footprint_review_state='source_reviewed',reviewed_by='Synthetic author',reviewed_date='2026-10-17',review_note='Synthetic fixture, no manufacturer or hardware claim',
            pin_specs=[dict(number=str(index),role='ground',operating_min_v=0,operating_max_v=0) for index in (1,2)]))


def boards(rotation=0):
    host=PCBProject(width_mm=100,height_mm=100,nets=['GND'],components=[component('J1',10,-5,'B.Cu')])
    target=PCBProject(width_mm=100,height_mm=100,nets=['GND'],components=[component('J2',25,5,rotation=rotation)])
    return host,target


def record(target,pose=None):
    return dict(units='mm',target_project_sha256=pcb_digest(target),target_board_to_host=pose or pose_from_xyz_rpy(0,0,0,0,0,0),
        host_plane_verified=True,source_plane_verified=True,basis='Synthetic datum frame only',reviewed_by='Fixture author',reviewed_date='2026-10-17')


def align(host,target,registration,**kwargs):
    return align_components(host,'J1','J2',[dict(source_pin=str(index),target_pin=str(index),net_compatibility='compatible') for index in (1,2)],
        mating=dict(source_normal=[0,0,1],target_normal=[0,0,1],source_side='bottom',target_side='top',allowed_side_pairs=[['bottom','top']],stand_off_height_mm=0,insertion_depth_mm=0,keying_verified=True),
        constraints=dict(max_pin_error_mm=.01,pitch_tolerance_mm=.01,normal_tolerance_deg=.1,tolerances_verified=True),
        verification={side:dict(footprint_verified=True,pin_map_verified=True) for side in ('source','target')},
        target_project=target,target_registration=registration,**kwargs)


def test_explicit_reviewed_external_frame_allows_practical_coplanar_candidate():
    host,target=boards();before=deepcopy((host.model_dump(mode='json'),target.model_dump(mode='json')))
    output=align(host,target,record(target))
    assert output['can_apply'] and output['status']=='aligned_preview' and output['target_registration']['status']=='registered'
    assert output['candidate']['components'][0]['x_mm']==pytest.approx(35)
    assert output['candidate']['components'][0]['y_mm']==pytest.approx(10)
    assert 'External target body/PCB is not included' in output['geometry_report']['scope']
    assert (host.model_dump(mode='json'),target.model_dump(mode='json'))==before
    assert output['preview_only'] and not output['mechanical_mating_safety_verified']


def test_registration_composes_saved_target_component_not_bare_board_origin():
    host,target=boards(rotation=90)
    output=align(host,target,record(target,pose_from_xyz_rpy(75,-10,0,0,0,90)))
    assert output['can_apply']
    assert output['source_assembly_world_pose']['translation_xyz_mm']==pytest.approx([55,15,0],abs=1e-7)
    for row,expected in zip(output['source_assembly_world_pose']['rotation'],[[-1,0,0],[0,-1,0],[0,0,1]]):assert row==pytest.approx(expected,abs=1e-7)
    assert abs(output['candidate']['components'][0]['rotation_deg'])==pytest.approx(180)
    assert output['source_pin_world_xyz_mm']['1']==pytest.approx([60,15,0])


@pytest.mark.parametrize('mutation',['digest','basis','reviewer','plane','height','tilt','missing_pose'])
def test_unknown_mismatched_or_nonplanar_registration_stays_preview_only(mutation):
    host,target=boards();registration=record(target)
    if mutation=='digest':registration['target_project_sha256']='0'*64
    elif mutation=='basis':registration['basis']=''
    elif mutation=='reviewer':registration['reviewed_by']=''
    elif mutation=='plane':registration['source_plane_verified']=False
    elif mutation=='height':registration['target_board_to_host']=pose_from_xyz_rpy(0,0,1,0,0,0)
    elif mutation=='tilt':registration['target_board_to_host']=pose_from_xyz_rpy(0,0,0,20,0,0)
    else:registration.pop('target_board_to_host')
    output=align(host,target,registration)
    assert output['candidate'] is None and not output['can_apply']
    assert output['status'] in ('assembly_preview','nonplanar_preview')
    assert output['target_registration']['status']!='registered'


def test_custom_target_pose_cannot_conflict_with_board_registration():
    host,target=boards();output=align(host,target,record(target),target_world_pose=pose_from_xyz_rpy(25,10,0,0,0,0))
    assert output['status']=='rejected' and output['candidate'] is None


@pytest.mark.parametrize('obstacle',['track','zone','body'])
def test_registered_external_path_retains_source_copper_zone_and_host_body_guards(obstacle):
    host,target=boards();raw=host.model_dump(mode='json')
    if obstacle=='track':raw['tracks']=[dict(id='T1',net='GND',layer='B.Cu',points=[dict(x_mm=5,y_mm=10),dict(x_mm=5,y_mm=12)])]
    elif obstacle=='zone':raw['zones']=[dict(id='Z1',net='GND',layer='F.Cu',outline=[dict(x_mm=x,y_mm=y) for x,y in [(1,1),(99,1),(99,99),(1,99)]])]
    else:raw['components'].append(component('BLOCK',35,0))
    host=PCBProject.model_validate(raw);before=host.model_dump(mode='json');output=align(host,target,record(target))
    assert output['candidate'] is None and not output['can_apply'] and output['status']=='blocked'
    assert host.model_dump(mode='json')==before


def test_external_registration_dialog_is_blank_explicit_and_reset_on_reference_change():
    path=Path(__file__).parents[1]/'cadstudio/native/pcb_alignment_dialog.py';text=path.read_text(encoding='utf-8-sig');tree=ast.parse(text)
    assert "('x','X mm'),('y','Y mm'),('z','Z mm'),('roll','Roll °'),('pitch','Pitch °'),('yaw','Yaw °')" in text
    assert "field.setPlaceholderText('빈칸 = 등록 미확인 / Unknown')" in text
    assert "target_project_sha256=pcb_digest(self.external)" in text
    assert 'pose_from_xyz_rpy(*coordinates)' in text and 'all(value is not None for value in coordinates)' in text
    assert 'setChecked(True)' not in text
    reset=next(node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef) and node.name=='reset_mapping')
    reset_text=ast.unparse(reset)
    assert 'self.registration_values.values()' in reset_text and 'self.registration_enabled, self.host_plane, self.source_plane' in reset_text
    assert 'self.registration_reviewer.clear()' in reset_text and 'self.registration_date.clear()' in reset_text
    assert not any(name in sys.modules for name in ('PySide6','vtkmodules','OCP','cadquery'))
