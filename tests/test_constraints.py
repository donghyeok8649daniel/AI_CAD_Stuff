import math
import numpy as np
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from cadstudio.catalog import preset
from cadstudio.constraints import solve_sketch, solve_assembly, anchors, transform_matrix
from cadstudio.models import Design, Extrusion
from cadstudio.kernel import build, preview, export
from cadstudio.server import app


def rectangle():
    return dict(kind="extrusion", thickness=5, points=[dict(x=0,y=0),dict(x=18,y=1),dict(x=19,y=9),dict(x=1,y=10)], constraints=[
        dict(kind="fixed",a=0,x=0,y=0),dict(kind="horizontal",a=0,b=1),dict(kind="vertical",a=1,b=2),
        dict(kind="horizontal",a=2,b=3),dict(kind="vertical",a=3,b=0),
        dict(kind="distance",a=0,b=1,value=20),dict(kind="distance",a=1,b=2,value=10)])


def test_sketch_solver_reaches_dimensions_and_full_rank():
    sketch=Extrusion.model_validate(rectangle())
    points,status=solve_sketch(sketch.points,sketch.constraints)
    assert np.allclose(points,[[0,0],[20,0],[20,10],[0,10]],atol=1e-5)
    assert status["dof"]==0 and status["max_error"]<1e-5
    design=Design(parts=[dict(id="r",name="Rectangle",geometry=sketch)])
    assert build(design)[0].Volume()==pytest.approx(1000,abs=1e-4)


def test_constraint_conflict_and_invalid_reference_rejected():
    data=rectangle();data["constraints"].append(dict(kind="fixed",a=1,x=30,y=0))
    with pytest.raises(ValidationError,match="충돌"):
        Extrusion.model_validate(data)
    data=rectangle();data["constraints"][0]["a"]=10
    with pytest.raises(ValidationError,match="참조"):
        Extrusion.model_validate(data)


def test_angle_constraint_and_partial_dof():
    data=rectangle();data["constraints"]=[dict(kind="fixed",a=0,x=0,y=0),dict(kind="angle",a=0,b=1,value=30),dict(kind="distance",a=0,b=1,value=20)]
    data['points'][2:]=[dict(x=30,y=30),dict(x=0,y=30)]
    g=Extrusion.model_validate(data)
    assert math.degrees(math.atan2(g.points[1].y,g.points[1].x))==pytest.approx(30,abs=1e-5)
    assert solve_sketch(g.points,g.constraints)[1]["dof"]==4


def test_sketch_endpoint_returns_solved_points_and_reports_conflict():
    with TestClient(app) as client:
        r=client.post('/api/sketch/solve',json=rectangle(),headers={'X-CAD-Request':'1'})
        assert r.status_code==200 and r.json()['status']['dof']==0
        data=rectangle();data['constraints'].append(dict(kind='fixed',a=1,x=30,y=0))
        assert client.post('/api/sketch/solve',json=data,headers={'X-CAD-Request':'1'}).status_code==422


def world_anchor(part,key):
    return np.array([part.transform.x,part.transform.y,part.transform.z])+transform_matrix(part.transform)@np.array(anchors(part.geometry)[key])


def test_assembly_joints_propagate_dimensions_and_angles():
    d=preset('robot_arm');assert solve_assembly(d)==dict(mates=4,grounded=1,dof=2)
    data=d.model_dump();data['parts'][1]['geometry']['hole_spacing']=84;data['mates'][0]['rz']=75
    d=Design.model_validate(data);base,a,b,pin1,pin2=d.parts
    assert np.allclose(world_anchor(base,'top'),world_anchor(a,'hole_1_bottom'))
    assert np.allclose(world_anchor(a,'hole_2_top')+[0,0,1],world_anchor(b,'hole_1_bottom'))
    assert np.allclose(world_anchor(a,'hole_2_bottom')+[0,0,-1],world_anchor(pin2,'origin'))
    assert b.transform.rz==pytest.approx(20)
    assert not preview(d)['stats']['collisions']


@pytest.mark.parametrize('problem',['cycle','grounded','duplicate','anchor'])
def test_assembly_rejects_conflicts(problem):
    data=preset('robot_arm').model_dump()
    if problem=='cycle':
        data['mates'][0]['parent']='link-2'
    elif problem=='grounded':data['parts'][1]['fixed']=True
    elif problem=='duplicate':data['mates'].append(dict(id='extra',parent='base',child='link-1'))
    else:data['mates'][0]['parent_anchor']='missing'
    with pytest.raises(ValidationError):Design.model_validate(data)


def face_design(normal,operation='add',rotate=False):
    data=preset('plate').model_dump();data['parts'][0]['geometry']['hole_count']=0
    d=Design.model_validate(data);info=preview(d)['meshes'][0]
    face=next(f for f in info['faces'] if f['planar'] and np.allclose(f['normal'],normal))
    sketch=dict(kind='extrusion',thickness=2,points=[dict(x=-4,y=-3),dict(x=4,y=-3),dict(x=4,y=3),dict(x=-4,y=3)])
    data['parts'][0]['features']=[dict(id='feature',face=face['index'],support_face_count=face['face_count'],normal=normal,operation=operation,sketch=sketch)]
    if rotate:data['parts'][0]['transform']=dict(x=20,y=30,z=15,rx=40,ry=20,rz=70)
    return data


@pytest.mark.parametrize('normal,operation,rotate', [([0,0,1],'add',False),([0,0,-1],'add',False),([0,0,1],'cut',False),([1,0,0],'cut',True)])
def test_face_features_boolean_volume_and_step_roundtrip(normal,operation,rotate,tmp_path):
    import cadquery as cq
    data=face_design(normal,operation,rotate);d=Design.model_validate(data)
    volume=80*60*6+(96 if operation=='add' else -96)
    assert build(d)[0].Volume()==pytest.approx(volume,abs=1e-5)
    path=tmp_path/'face.step';export(d,path,'step')
    assert cq.importers.importStep(str(path)).val().Volume()==pytest.approx(volume,abs=1e-5)
    mesh=preview(d)['meshes'][0]
    assert len(mesh['triangle_faces'])==len(mesh['triangles'])//3
    assert max(mesh['triangle_faces'])<len(mesh['faces'])


def test_stale_support_face_rejected():
    data=face_design([0,0,1]);data['parts'][0]['features'][0]['support_face_count']=100
    with pytest.raises(ValueError,match='면 구성'):build(Design.model_validate(data))


def test_curved_face_rejected():
    d=preset('cylinder');info=preview(d)['meshes'][0];face=next(f for f in info['faces'] if not f['planar'])
    data=d.model_dump();feature=face_design([0,0,1])['parts'][0]['features'][0]
    feature.update(face=face['index'],support_face_count=len(info['faces']))
    data['parts'][0]['features']=[feature]
    with pytest.raises(ValueError,match='평평한'):build(Design.model_validate(data))
