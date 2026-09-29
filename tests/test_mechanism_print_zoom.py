import math
import json
from copy import deepcopy
import pytest
from cadstudio.models import Design,SpurGear,DraftRequest
from cadstudio.kernel import build,construct,exact_bounds
from cadstudio.gears import add_gear_pair
from cadstudio.printing import prepare_print,export_print_stl
from cadstudio.joint_readiness import joint_readiness
from cadstudio.interference import exact_collisions
from cadstudio.assembly_motion import set_joint_motion


def test_real_gear_bore_shaft_and_invalid_dimensions():
    base=SpurGear();s=construct(base);box=exact_bounds(s)
    assert s.isValid() and len(s.Solids())==1
    assert box.xlen==pytest.approx(44,abs=1e-5) and box.zlen==pytest.approx(8,abs=1e-5)
    bore=construct(base.model_copy(update={'bore_diameter':8}))
    assert s.Volume()-bore.Volume()==pytest.approx(math.pi*16*8,abs=1e-4)
    shaft=construct(base.model_copy(update={'shaft_diameter':8,'shaft_length':10}))
    assert shaft.Volume()-s.Volume()==pytest.approx(math.pi*16*10,abs=1e-4)
    assert exact_bounds(shaft).zmin==pytest.approx(-10)
    for values in ({'teeth':17},{'teeth':20.5},{'backlash':1},{'bore_diameter':38},{'shaft_length':2},{'shaft_length':2,'shaft_diameter':8,'bore_diameter':3}):
        with pytest.raises(ValueError):SpurGear(**values)


@pytest.mark.parametrize('teeth',[(20,40),(18,27),(32,24)])
def test_real_gear_pair_motion_and_support_clearance(teeth):
    d=add_gear_pair(prefix='g-',teeth_a=teeth[0],teeth_b=teeth[1]);original=d.model_dump()
    for angle in [0,360/teeth[0]/4,360/teeth[0]/2,360/teeth[0]*.9,90,-90]:
        raw=deepcopy(original);set_joint_motion(raw,'g-drive',{'rz':angle});pose=Design.model_validate(raw);shapes=build(pose)
        hits=exact_collisions(pose,shapes);assert not hits,(angle,hits)
        assert (pose.parts[2].transform.rz-(d.motion_links[0].offset-angle*teeth[0]/teeth[1])+180)%360-180==pytest.approx(0,abs=1e-6)
        status=joint_readiness(pose,shapes,hits)
        assert status['g-drive']['state']=='ready' and status['g-driven']['state']=='ready'
    assert original==d.model_dump()


def test_joint_color_requires_actual_geometry_and_fails_closed():
    d=add_gear_pair(prefix='g-');raw=d.model_dump();raw['mates'][0]['x']=1
    pose=Design.model_validate(raw);shapes=build(pose)
    assert joint_readiness(pose,shapes,exact_collisions(pose,shapes))['g-drive']['state']=='blocked'
    raw=d.model_dump();raw['parts'][1]['geometry']['shaft_length']=0;raw['parts'][1]['geometry']['shaft_diameter']=0
    pose=Design.model_validate(raw);shapes=build(pose)
    assert joint_readiness(pose,shapes,[])['g-drive']['state']=='unverified'
    from cadstudio.joint_hardware import add_revolute_hardware
    physical,_=add_revolute_hardware(prefix='j-');shapes=build(physical)
    assert joint_readiness(physical,shapes,exact_collisions(physical,shapes))['j-rotation']['state']=='ready'


def test_print_per_part_rotation_position_overlap_and_stl(tmp_path):
    d=Design(parts=[dict(id=k,name=k,geometry=dict(kind='plate',length=20,width=10,thickness=3,hole_count=0)) for k in ('a','b')]);original=d.model_dump()
    poses={'a':dict(x=-20,y=10,rz=90),'b':dict(x=20,y=-10,rx=90)}
    prepared,result,warnings=prepare_print(d,['a','b'],placements=poses)
    assert not warnings and d.model_dump()==original
    a,b=map(exact_bounds,build(prepared))
    assert (a.xmin+a.xmax)/2==pytest.approx(-20) and a.ylen==pytest.approx(20)
    assert b.zlen==pytest.approx(10) and b.zmin==pytest.approx(0)
    path=tmp_path/'placed.stl';export_print_stl(prepared,path)
    from vtkmodules.vtkIOGeometry import vtkSTLReader
    reader=vtkSTLReader();reader.SetFileName(str(path));reader.Update();bounds=reader.GetOutput().GetBounds()
    assert bounds==pytest.approx((a.xmin,b.xmax,b.ymin,a.ymax,0,b.zmax),abs=1e-5)
    assert prepare_print(d,['a','b'],placements={'a':dict(x=0,y=0),'b':dict(x=0,y=0)})[2]
    assert prepare_print(d,['a'],placements={'a':dict(x=120,y=0)})[2]
    with pytest.raises(ValueError):prepare_print(d,['a'],placements={'a':dict(x=float('nan'))})


@pytest.mark.parametrize('parallel',[False,True])
@pytest.mark.parametrize('surface',[False,True])
def test_zoom_keeps_cursor_world_anchor(parallel,surface):
    from vtkmodules.vtkRenderingCore import vtkRenderer,vtkRenderWindow
    from cadstudio.native.navigation import zoom_camera,unproject
    renderer=vtkRenderer();window=vtkRenderWindow();window.SetSize(1000,700);window.AddRenderer(renderer)
    c=renderer.GetActiveCamera();c.SetPosition(100,-130,180);c.SetFocalPoint(0,0,0);c.SetViewUp(0,0,1);c.SetParallelProjection(parallel);c.SetParallelScale(60);c.SetClippingRange(1,1000)
    xy=(720,480);renderer.SetWorldPoint(0,0,30 if surface else 0,1);renderer.WorldToDisplay()
    p=unproject(renderer,*xy,renderer.GetDisplayPoint()[2]);before=c.GetParallelScale() if parallel else c.GetDistance()
    for factor in (1.18,1.18,1/1.18,1/1.18):
        zoom_camera(renderer,xy,factor,p if surface else None)
        renderer.SetWorldPoint(*p,1);renderer.WorldToDisplay()
        assert renderer.GetDisplayPoint()[:2]==pytest.approx(xy,abs=1e-6)
    assert (c.GetParallelScale() if parallel else c.GetDistance())==pytest.approx(before)


def test_ai_can_create_real_gears_and_motion_link():
    from cadstudio.native.cad_tools import execute_plan
    from cadstudio.native.cad_schema import plan_schema
    from cadstudio.native.cad_scope import Scope
    schema=plan_schema(allowed_tools=['create','joint','motion_link'],allowed_shapes=['spur_gear','plate'],new_parts=['base','a','b'])
    actions=[dict(tool='create',target='base',args=dict(name='base',geometry=dict(kind='plate',length=130,width=90,thickness=8,hole_count=0),transform={'z':-9}))]
    for identifier,teeth in [('a',20),('b',40)]:actions.append(dict(tool='create',target=identifier,args=dict(name=identifier,geometry=dict(kind='spur_gear',module=2,teeth=teeth,thickness=8),transform={'x':0 if identifier=='a' else 60})))
    for identifier,x,rz in [('a',0,0),('b',60,175.5)]:actions.append(dict(tool='joint',target='j-'+identifier,args=dict(kind='revolute',parent='base',child=identifier,x=x,z=9,rz=rz)))
    actions.append(dict(tool='motion_link',target='ratio',args=dict(driver='j-a',driven='j-b',ratio=-.5,offset=175.5)))
    plan=dict(summary='gear pair',actions=actions)
    reply=execute_plan(json.dumps(plan),DraftRequest(prompt='gear pair'))
    assert len(reply.design.motion_links)==1 and reply.design.parts[1].geometry.kind=='spur_gear'
    assert not exact_collisions(reply.design)
    assert joint_readiness(reply.design,build(reply.design),[])['j-a']['state']=='unverified'
    link=next(a for a in schema['properties']['actions']['items']['anyOf'] if a['properties']['tool']['const']=='motion_link')
    assert 'enum' not in link['properties']['target']
