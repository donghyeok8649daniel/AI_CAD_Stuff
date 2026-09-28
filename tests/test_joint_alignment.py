from copy import deepcopy
import numpy as np
import pytest
from cadstudio.models import Design,Part
from cadstudio.kernel import build,local_shape
from cadstudio.threads import cylinder_records
from cadstudio.joint_alignment import options,align,find_cylinder
from cadstudio.constraints import transform_matrix
from cadstudio.assembly_motion import set_joint_motion
from cadstudio.native.assembly_display import assembly_markers
from test_cad_tools import execute,action,create


def eccentric():
    return Design(parts=[Part(id='a',name='bearing',fixed=True,geometry=dict(kind='cylinder',diameter=30,bore_diameter=12.4,height=20),transform=dict(x=50,y=30,z=10,rx=70,ry=20,rz=30)),
                         Part(id='b',name='shaft',geometry=dict(kind='cylinder',diameter=12,height=20))],
                  mates=[dict(id='j',parent='a',child='b',kind='revolute',x=1.6,rx=15,limits={'rz':[-180,180]})])


def selected(raw):
    a,b=options(raw,'j');return next(r['index'] for r in a if r['internal']),b[0]['index']


@pytest.mark.parametrize('flipped',[False,True])
def test_real_cylinder_alignment_stays_concentric_through_rotation_and_reload(flipped):
    raw=eccentric().model_dump();before=deepcopy(raw);pi,ci=selected(raw);d,info=align(raw,'j',pi,ci,gap=20 if flipped else 0,angle=0,flipped=flipped)
    assert info['offset_mm']==pytest.approx(1.6) and info['tilt_deg']==pytest.approx(15)
    assert raw==before and d.mates[0].limits=={'rz':[-180,180]}
    for angle in (-160,-45,0,37,90,180):
        data=d.model_dump();set_joint_motion(data,'j',{'rz':angle});pose=Design.model_validate_json(Design.model_validate(data).model_dump_json());shapes=build(pose)
        assert shapes[0].intersect(shapes[1]).Volume()<1e-7
        cylinders=[next(r for r in cylinder_records(s) if (r.internal if i==0 else True)) for i,s in enumerate(shapes)]
        axis=np.array(cylinders[0].frame.normal);delta=np.array(cylinders[1].frame.origin)-cylinders[0].frame.origin
        assert np.linalg.norm(delta-axis*(axis@delta))<1e-7
        marker=assembly_markers(pose)[0];normal=np.array(marker['basis'])[:,2]
        assert abs(normal@axis)==pytest.approx(1)
        assert np.linalg.norm(np.cross(np.array(marker['origin'])-cylinders[0].frame.origin,axis))<1e-7
    data=d.model_dump();data['parts'][0]['geometry']['height']=30;changed=Design.model_validate(data);build(changed)
    assert changed.joint_frames[0].parent.origin==pytest.approx(d.joint_frames[0].parent.origin)


def test_ai_pad_uses_bounds_not_perforated_face_centroid_and_old_files_keep_geometry():
    # A distant bore shifts the bottom face centroid. The shaft must stay at x=0.
    profile=dict(sketch_mode='entities',entities=[dict(id='l'+str(i),kind='line',start=dict(x=a[0],y=a[1]),end=dict(x=b[0],y=b[1])) for i,(a,b) in enumerate(zip([(-16,-16),(166,-16),(166,16),(-16,16)],[(166,-16),(166,16),(-16,16),(-16,-16)]))]+[dict(id='hole',kind='circle',center=dict(x=150,y=0),radius=6.2)])
    reply=execute(action('create','arm',name='arm',geometry=dict(kind='extrusion',thickness=14,profile=profile)),action('pad','arm',face='-Z',profile=dict(circle=dict(diameter=12,center=[-75,0])),depth=22))
    d=reply.design;part=d.parts[0];shape=local_shape(d,part);shaft=next(r for r in cylinder_records(shape) if not r.internal)
    assert shaft.frame.origin[0]==pytest.approx(0,abs=1e-6)
    assert part.features[0].origin_mode=='face_bounds'
    data=d.model_dump();data['parts'][0]['features'][0].pop('origin_mode');old=Design.model_validate(data)
    assert next(r for r in cylinder_records(local_shape(old,old.parts[0])) if not r.internal).frame.origin[0]==pytest.approx(-1.5880825813)
    assert 'origin_mode' not in old.model_dump()['parts'][0]['features'][0]


@pytest.mark.parametrize('flipped',[False,True])
def test_ai_joint_uses_actual_axes_and_rejects_tilted_euler_shortcut(flipped):
    a=create('cylinder',target='bearing',diameter=30,height=20,bore_diameter=12.4);b=create('cylinder',target='shaft',diameter=12,height=20,bore_diameter=0)
    a['args']['transform']=dict(rx=75,ry=20)
    pc=dict(center=[0,0,0],direction=[0,0,1],diameter=12.4);cc=dict(center=[0,0,0],direction=[0,0,1],diameter=12)
    reply=execute(a,b,action('joint','j',kind='revolute',parent='bearing',child='shaft',parent_cylinder=pc,child_cylinder=cc,rz=45,z=20 if flipped else 0,flipped=flipped))
    assert len(reply.design.joint_frames)==1
    assert reply.design.joint_frames[0].flipped is flipped
    shapes=build(reply.design);assert shapes[0].intersect(shapes[1]).Volume()<1e-7
    with pytest.raises(ValueError,match='rx/ry'):execute(a,b,action('joint','j',kind='revolute',parent='bearing',child='shaft',rx=90))
    cc['center']=[1.5,0,0]
    with pytest.raises(ValueError,match='cylindrical axis'):execute(a,b,action('joint','j',kind='revolute',parent='bearing',child='shaft',parent_cylinder=pc,child_cylinder=cc))


def test_alignment_preserves_limits_and_rejects_planar_selection():
    raw=eccentric().model_dump();pi,ci=selected(raw)
    with pytest.raises(ValueError,match='운동 한계'):align(raw,'j',pi,ci,angle=190)
    d=Design.model_validate(raw);plane=next(i for i,f in enumerate(local_shape(d,d.parts[0]).Faces()) if f.geomType()=='PLANE')
    with pytest.raises(ValueError,match='원통'):align(raw,'j',plane,ci)
