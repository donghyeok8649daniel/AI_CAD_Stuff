from copy import deepcopy
import json
import math

import httpx
import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from cadstudio.assembly_motion import set_joint_motion, motion_controls
from cadstudio.constraints import solve_assembly, transform_matrix
from cadstudio.kernel import build
from cadstudio.mechanisms import four_bar
from cadstudio.models import Design, DraftRequest, Part
from cadstudio.native.cad_tools import context, messages
from cadstudio.native.cad_scope import scope_messages
from cadstudio.native.document import Document
from test_cad_tools import execute, action


def joint_design(kind='revolute', **values):
    return Design(parts=[Part(id='base',name='Base',fixed=True,geometry={'kind':'plate','hole_count':0}),
                         Part(id='arm',name='Arm',geometry={'kind':'plate','hole_count':0})],
                  mates=[dict(id='hinge',kind=kind,parent='base',child='arm',**values)])


def edit(current, identifier='hinge', **values):
    return execute(action('edit_joint',identifier,**values),current=current)


@pytest.mark.parametrize('kind,values', [('revolute',{'rz':45}),('slider',{'z':750.1234567}),
    ('cylindrical',{'rz':-60,'z':30}),('planar',{'x':10,'y':15,'rz':60}),
    ('ball',{'rx':20,'ry':30,'rz':40}),('pin_slot',{'x':25,'rz':-30})])
def test_motion_preserves_joint_identity_geometry_and_history(kind,values):
    current=joint_design(kind);before=current.model_dump();reply=edit(current,**values)
    assert current.model_dump()==before
    assert len(reply.design.parts)==2 and len(reply.design.mates)==1
    mate=reply.design.mates[0]
    assert mate.id=='hinge' and mate.kind==kind and mate.parent=='base' and mate.child=='arm'
    for key,value in values.items():assert getattr(mate,key)==pytest.approx(value)
    assert [p.geometry for p in reply.design.parts]==[p.geometry for p in current.parts]
    assert [s.Volume() for s in build(reply.design)]==pytest.approx([s.Volume() for s in build(current)])
    assert reply.design.parts[0]==current.parts[0]
    doc=Document();doc.commit(current,'start');doc.commit(reply.design,'AI motion',dict(journal_steps=reply.journal_steps))
    entries=doc.journal.path();assert doc.journal.at(entries[-2]['id'])==before
    assert entries[-1]['context']['tool_actions'][0]['tool']=='edit_joint'


def test_face_joint_uses_its_existing_frame_and_keeps_non_motion_offsets():
    raw=joint_design(rz=10,x=3,y=4,z=5).model_dump()
    raw['parts'][0]['transform'].update(x=20,y=-30,z=40,rx=35,ry=65,rz=-20)
    from cadstudio.kernel import local_shape
    from cadstudio.native.cad_tools import _face
    from cadstudio.topology import face_reference
    base=Design.model_validate(raw);shape=local_shape(base,base.parts[0]);index,_,plane=_face(shape,'+X')
    frame=dict(face=index,face_count=len(shape.Faces()),origin=list(plane.origin.toTuple()),
               normal=list(plane.zDir.toTuple()),x_direction=list(plane.xDir.toTuple()),reference=face_reference(shape,index).model_dump())
    raw['joint_frames']=[dict(mate_id='hinge',parent=frame,child=frame,flipped=True)]
    current=Design.model_validate(raw);changed=edit(current,rz=75).design
    assert changed.joint_frames==current.joint_frames
    assert (changed.mates[0].x,changed.mates[0].y,changed.mates[0].z)==(3,4,5)
    basis=np.column_stack([frame['x_direction'],np.cross(frame['normal'],frame['x_direction']),frame['normal']])
    parent=transform_matrix(changed.parts[0].transform)
    expected=parent@basis@Rotation.from_euler('z',75,degrees=True).as_matrix()@np.diag([1,-1,-1])@basis.T
    assert transform_matrix(changed.parts[1].transform)==pytest.approx(expected,abs=1e-8)
    assert all(shape.isValid() for shape in build(changed))


def linked_design():
    raw=joint_design(rz=10).model_dump()
    raw['parts'].append(Part(id='follower',name='Follower',geometry={'kind':'cylinder'}).model_dump())
    raw['mates'].append(dict(id='follow',kind='revolute',parent='arm',child='follower'))
    raw['motion_links']=[dict(id='ratio',driver='hinge',driver_axis='rz',driven='follow',driven_axis='rz',ratio=-2,offset=5)]
    return Design.model_validate(raw)


def test_driving_joint_updates_linked_follower_and_exposes_control_source():
    current=linked_design();changed=edit(current,rz=30).design
    assert changed.mates[1].rz==-55 and changed.motion_links==current.motion_links
    axes=context(current)['mates'][1]['motion_axes']
    assert axes['rz']['driven_by']=='hinge.rz' and axes['rz']['ratio']==-2
    with pytest.raises(ValueError,match='구동 관절'):edit(current,'follow',rz=60)


def test_linked_follower_limit_also_blocks_driver_transaction():
    raw=linked_design().model_dump();raw['mates'][1]['limits']={'rz':[-30,30]}
    current=Design.model_validate(raw);before=current.model_dump()
    with pytest.raises(ValueError,match='운동 한계'):edit(current,rz=45)
    assert current.model_dump()==before


@pytest.mark.parametrize('angle', [-60,45,120])
def test_closed_loop_input_recomputes_passive_angles_and_preserves_loop(angle):
    current=four_bar();before=current.model_dump();changed=edit(current,'input',rz=angle).design
    assert changed.mates[0].rz==pytest.approx(angle) and changed.loops==current.loops
    assert solve_assembly(changed)['closure_error_mm']<1e-5
    assert all(shape.isValid() for shape in build(changed))
    assert current.model_dump()==before
    with pytest.raises(ValueError,match='loop closure'):edit(current,'passive-a',rz=20)


@pytest.mark.parametrize('values', [dict(rz=91),dict(rz=-91),dict(rz=True),dict(rz=float('nan')),
    dict(rz='30'),dict(rx=10),dict(x=4),dict(kind='rigid'),dict(limits={'rz':[-180,180]}),{}])
def test_invalid_axis_limit_or_connection_changes_rejected_atomically(values):
    current=joint_design(limits={'rz':[-90,90]});before=current.model_dump()
    with pytest.raises(ValueError):edit(current,**values)
    assert current.model_dump()==before


def test_invalid_joint_patch_does_not_apply_earlier_valid_axis():
    raw=joint_design('cylindrical').model_dump();before=deepcopy(raw)
    with pytest.raises(ValueError):set_joint_motion(raw,'hinge',{'rz':40,'z':5001})
    assert raw==before
    with pytest.raises(ValueError,match='ID'):set_joint_motion(raw,'missing',{'rz':20})
    with pytest.raises(ValueError,match='강체'):edit(joint_design('rigid'),rz=20)


def test_selected_joint_and_units_are_sent_in_both_planning_stages():
    request=DraftRequest(prompt='이 관절을 30도로',current=joint_design(rz=15,limits={'rz':[-60,90]}),selected_joint='hinge')
    for produce in (messages,scope_messages):
        data=json.loads(produce(request)[1]['content']);assert data['selected_joint']=='hinge'
        assert data['current_design']['mates'][0]['motion_axes']['rz']==dict(value=15,unit='deg',limits=[-60,90])


@pytest.mark.parametrize('provider',['ollama','openai'])
def test_provider_can_move_existing_joint_and_preserve_other_design_data(provider):
    from cadstudio.native.local_ai import ollama_draft
    from cadstudio.native.cloud_ai import generate
    from test_cloud_planner import answer
    current=joint_design(limits={'rz':[-90,90]});calls=[]
    scope=dict(intent='edit',tools=['edit_joint'],shapes=[],new_parts=[],connections=[])
    plan=dict(summary='관절 각도 편집',actions=[action('edit_joint','hinge',rz=45)])
    def handle(request):
        calls.append(json.loads(request.content));data=scope if len(calls)==1 else plan
        return answer(data) if provider=='openai' else httpx.Response(200,json={'done':True,'message':{'content':json.dumps(data)}})
    request=DraftRequest(prompt='선택 관절을 45도로 회전',current=current,selected_joint='hinge')
    kwargs=dict(transport=httpx.MockTransport(handle),deadline=None)
    result=generate(request,'gpt-6-astra',api_key='test-placeholder',**kwargs) if provider=='openai' else ollama_draft(request,'test',**kwargs)
    assert len(calls)==2 and result['design']['mates'][0]['rz']==45
    assert result['design']['mates'][0]['limits']=={'rz':[-90,90]}
    assert len(result['journal_steps'])==1
