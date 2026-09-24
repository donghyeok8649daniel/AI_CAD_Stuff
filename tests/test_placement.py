from copy import deepcopy

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from cadstudio.catalog import preset
from cadstudio.constraints import transform_matrix
from cadstudio.kernel import build
from cadstudio.mechanisms import four_bar
from cadstudio.models import Design, Part
from cadstudio.placement import placement_selection, move_selection
from cadstudio.part_operations import group_parts
from cadstudio.native.document import Document


def loose_parts():
    return Design(parts=[Part(id='a',name='A',geometry={'kind':'cylinder','diameter':20,'height':10},transform={'x':20,'rz':35}),
                         Part(id='b',name='B',geometry={'kind':'plate','hole_count':0},transform={'x':-30,'z':20,'rx':90}),
                         Part(id='c',name='C',geometry={'kind':'cylinder'})]).model_dump()


def verify_delta(before,after,ids,translation,rotation,pivot):
    delta=Rotation.from_euler('xyz',rotation,degrees=True).as_matrix()
    original={p.id:p for p in Design.model_validate(before).parts}
    for p in Design.model_validate(after).parts:
        old=original[p.id]
        if p.id not in ids:assert p==old;continue
        expected=delta@(np.array([old.transform.x,old.transform.y,old.transform.z])-pivot)+pivot+translation
        assert [p.transform.x,p.transform.y,p.transform.z]==pytest.approx(expected,abs=1e-6)
        assert transform_matrix(p.transform)==pytest.approx(delta@transform_matrix(old.transform),abs=1e-7)
        assert p.geometry==old.geometry and p.features==old.features and p.fixed==old.fixed


def test_group_uses_one_world_pivot_and_preserves_undo():
    raw,_=group_parts(loose_parts(),['a','b']);before=deepcopy(raw)
    after,ids=move_selection(raw,['a','b'],[10,-5,7],[23,-40,75],[4,6,2])
    verify_delta(raw,after,ids,np.array([10,-5,7]),[23,-40,75],np.array([4,6,2]))
    assert raw==before and after['part_groups']==raw['part_groups']
    doc=Document();doc.commit(raw,'Start');doc.commit(after,'Move');entries=doc.journal.path()
    assert doc.journal.at(entries[-2]['id'])==raw and doc.journal.at(entries[-1]['id'])==after


@pytest.mark.parametrize('raw',[preset('robot_arm').model_dump(),four_bar().model_dump()])
def test_assembly_and_closed_loop_move_as_one_without_changing_joints(raw):
    before=deepcopy(raw);identifier=raw['parts'][-1]['id']
    after,ids=move_selection(raw,[identifier],[17,-25,6],[30,75,-40],[8,1,5],allow_grounded=True)
    assert len(ids)==len(raw['parts'])
    verify_delta(raw,after,ids,np.array([17,-25,6]),[30,75,-40],np.array([8,1,5]))
    assert raw==before
    for old,new in zip(raw['mates'],after['mates']):
        for key,value in old.items():
            assert new[key]==(pytest.approx(value,abs=1e-8) if isinstance(value,(int,float)) else value)
    for key in ('joint_frames','loops','motion_links'):
        assert after.get(key)==raw.get(key)
    assert sum(s.Volume() for s in build(Design.model_validate(after)))==pytest.approx(sum(s.Volume() for s in build(Design.model_validate(raw))),rel=1e-7)


def test_grounding_is_explicit_and_preserved():
    raw=preset('robot_arm').model_dump();ids=[raw['parts'][-1]['id']]
    with pytest.raises(ValueError,match='고정된 부품'):move_selection(raw,ids,[10,0,0])
    with pytest.raises(ValueError,match='선택 밖'):move_selection(raw,ids,[10,0,0],connected=False,allow_grounded=True)
    after,moved=move_selection(raw,ids,[10,0,0],allow_grounded=True)
    assert [p['fixed'] for p in after['parts']]==[p['fixed'] for p in raw['parts']]
    assert len(moved)==len(raw['parts'])


def test_position_parameter_is_not_silently_overridden():
    raw=loose_parts();raw['parameters']={'offset':'20'}
    raw['dimension_bindings']=[dict(path=['parts','a','transform','x'],expression='offset')]
    with pytest.raises(ValueError,match='변수'):move_selection(raw,['a'],[10,0,0])


def test_boolean_dependencies_move_together_with_volume_preserved():
    raw=Design(parts=[Part(id='a',name='Plate',geometry={'kind':'plate','length':60,'width':40,'thickness':10,'hole_count':0},
                          features=[dict(id='cut',kind='solid',operation='boolean',tool_part_id='b',boolean_mode='cut')]),
                     Part(id='b',name='Tool',geometry={'kind':'cylinder','diameter':8,'height':30},transform={'z':-10})]).model_dump()
    assert placement_selection(raw,['b'])==['a','b']
    with pytest.raises(ValueError,match='몸체 연산'):placement_selection(raw,['a'],False)
    old=build(Design.model_validate(raw));moved,ids=move_selection(raw,['a'],[40,10,-5],[30,45,90])
    new=build(Design.model_validate(moved))
    assert len(ids)==2 and [s.Volume() for s in new]==pytest.approx([s.Volume() for s in old],rel=1e-7)


@pytest.mark.parametrize('kwargs',[
    {'translation':[float('nan'),0,0]}, {'rotation':[1,2]}, {'pivot':[0,0,float('inf')]},
    {'translation':[5001,0,0]}, {'rotation':[361,0,0]}, {'pivot':[5001,0,0]}])
def test_invalid_values_do_not_mutate_design(kwargs):
    raw=loose_parts();before=deepcopy(raw)
    with pytest.raises(ValueError):move_selection(raw,['a'],**kwargs)
    assert raw==before


def test_gimbal_rotation_has_exact_equivalent_matrix_and_bounds_checked():
    raw=loose_parts();after,ids=move_selection(raw,['a'],rotation=[0,90,0])
    verify_delta(raw,after,ids,np.zeros(3),[0,90,0],np.zeros(3))
    raw['parts'][0]['transform']['x']=4999
    with pytest.raises(ValueError):move_selection(raw,['a'],[2,0,0])


def test_face_joint_frame_moves_with_parent_without_rewriting_frame():
    from cadstudio.native.assembly_display import assembly_markers
    frame=dict(face=0,face_count=6,origin=[0,0,5],normal=[1,0,0],x_direction=[0,1,0])
    raw=Design(parts=[Part(id='a',name='A',geometry={'kind':'plate','hole_count':0}),Part(id='b',name='B',geometry={'kind':'plate','hole_count':0})],
               mates=[dict(id='j',kind='revolute',parent='a',child='b',rz=30)],joint_frames=[dict(mate_id='j',parent=frame,child=frame)]).model_dump()
    old=np.array(assembly_markers(raw)[0]['origin']);after,_=move_selection(raw,['b'],[8,3,7],[0,0,90])
    new=np.array(assembly_markers(after)[0]['origin'])
    assert new==pytest.approx(Rotation.from_euler('z',90,degrees=True).apply(old)+[8,3,7])
    assert after['joint_frames']==raw['joint_frames']


@pytest.mark.parametrize('angle',[-120,-60,0,45,120,180])
def test_tilted_four_bar_still_drives_in_its_own_plane(angle):
    from cadstudio.constraints import solve_assembly
    raw=four_bar().model_dump();moved,_=move_selection(raw,['ground'],[30,25,10],[35,65,20],allow_grounded=True)
    model=Design.model_validate(moved);model.mates[0].rz=angle
    stats=solve_assembly(model)
    assert stats['closure_error_mm']<1e-5 and stats['dof']==1


def test_planar_closure_rejects_nonparallel_component_planes():
    raw=four_bar().model_dump();raw['mates'][-1]['rx']=20
    with pytest.raises(ValueError,match='서로 평행'):Design.model_validate(raw)
