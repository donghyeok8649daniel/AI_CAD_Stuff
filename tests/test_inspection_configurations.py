import math
import cadquery as cq
import pytest
from cadstudio.models import Design,Part,Material
from cadstudio.kernel import local_shape
from cadstudio.inspection import mass_properties,minimum_distance,angle_between,section
from cadstudio.configurations import apply_configuration


def test_measurement_and_mass_use_exact_geometry():
    a=cq.Workplane().box(10,20,30).val();b=a.translate((50,0,0));r=mass_properties(a,2700)
    assert r['mass_kg']==pytest.approx(.0162) and r['center_mm']==pytest.approx([0,0,0])
    assert r['inertia_kg_m2'][0][0]==pytest.approx(.0162*(.02**2+.03**2)/12)
    assert minimum_distance(a,b)['distance_mm']==pytest.approx(40)
    faces=a.Faces();first=next(f for f in faces if f.normalAt().x>.9);second=next(f for f in faces if f.normalAt().y>.9)
    assert angle_between(first,second)==pytest.approx(90)
    assert section(a,[0,0,0],[0,0,1]).Area()==pytest.approx(200)
    ring=cq.Workplane().circle(10).circle(5).extrude(20).val()
    assert section(ring,[0,0,10],[0,0,1]).Area()==pytest.approx(math.pi*75)


def test_configurations_drive_bound_dimensions_and_instances():
    d=Design(parts=[Part(id='a',name='a',geometry=dict(kind='cylinder',diameter=10,height=4)),Part(id='b',name='b',geometry=dict(kind='cylinder',diameter=10,height=4),source_part_id='a',transform=dict(x=50))],parameters={'D':'10'},dimension_bindings=[dict(path=['parts','a','geometry','diameter'],expression='D')],configurations={'large':{'D':'20'},'small':{'D':'10'}})
    large=apply_configuration(d.model_dump(),'large')
    assert large.parts[1].geometry.diameter==20 and large.parts[1].transform.x==50
    assert local_shape(large,large.parts[0]).Volume()==pytest.approx(local_shape(large,large.parts[1]).Volume())
    small=apply_configuration(large.model_dump(),'small');assert small.parts[1].geometry.diameter==10
    raw=d.model_dump();raw['parts'][0]['source_part_id']='b'
    with pytest.raises(ValueError,match='순환'):Design.model_validate(raw)
    raw=d.model_dump();raw['parameters']={}
    with pytest.raises(ValueError):Design.model_validate(raw)

def test_thin_wall_and_to_face_follow_parameter_changes():
    from cadstudio.topology import face_reference
    from cadstudio.models import Extrusion
    g=Extrusion(thickness=10,thin_wall=2,points=[dict(x=x,y=y) for x,y in [(0,0),(20,0),(20,30),(0,30)]])
    d=Design(parts=[Part(id='p',name='p',geometry=g)]);assert local_shape(d,d.parts[0]).Volume()==pytest.approx((600-16*26)*10)
    d=Design(parts=[Part(id='p',name='p',geometry={'kind':'plate','length':20,'width':20,'thickness':10,'hole_count':0})]);shape=local_shape(d,d.parts[0]);top=next(i for i,f in enumerate(shape.Faces()) if f.normalAt().z>.9);bottom=next(i for i,f in enumerate(shape.Faces()) if f.normalAt().z<-.9)
    raw=d.model_dump();raw['parts'][0]['features']=[dict(id='cut',face=top,normal=[0,0,1],reference=face_reference(shape,top).model_dump(),end_face=face_reference(shape,bottom).model_dump(),operation='cut',sketch=dict(kind='extrusion',thickness=3,sketch_mode='entities',entities=[dict(id='c',kind='circle',radius=2,center={'x':0,'y':0})]))]
    for thickness in (10,25):
        raw['parts'][0]['geometry']['thickness']=thickness;checked=Design.model_validate(raw);assert local_shape(checked,checked.parts[0]).Volume()==pytest.approx((400-math.pi*4)*thickness)


def test_counterbore_and_countersink_remove_analytic_volume():
    from cadstudio.topology import face_reference
    d=Design(parts=[Part(id='p',name='p',geometry=dict(kind='plate',length=30,width=30,thickness=10,hole_count=0))]);shape=local_shape(d,d.parts[0]);index=next(i for i,f in enumerate(shape.Faces()) if f.normalAt().z>.9)
    raw=d.model_dump();feature=dict(id='hole',face=index,normal=[0,0,1],reference=face_reference(shape,index).model_dump(),operation='cut',sketch=dict(kind='extrusion',thickness=10,sketch_mode='entities',entities=[dict(id='c',kind='circle',center=dict(x=0,y=0),radius=3)]),head_diameter=10,head_depth=3,head_angle=90)
    for finish,extra in [('counterbore',math.pi*(25-9)*3),('countersink',math.pi*2*(25+15+9)/3-math.pi*9*2)]:
        raw['parts'][0]['features']=[{**feature,'hole_finish':finish}];checked=Design.model_validate(raw);assert shape.Volume()-local_shape(checked,checked.parts[0]).Volume()==pytest.approx(math.pi*9*10+extra)


def test_opaque_assets_are_retained_outside_ai_context():
    from cadstudio.imported import encode_shape
    from cadstudio.planner import ai_design_context,parse_ai_reply
    import json
    asset=encode_shape(cq.Workplane().box(10,10,10).val(),'box');d=Design(parts=[Part(id='p',name='p',geometry={'kind':'imported','asset_id':'a'})],assets={'a':asset})
    context=ai_design_context(d);assert 'assets' not in context and asset.data not in str(context)
    reply=parse_ai_reply(json.dumps({'design':context,'summary':'keep','assumptions':[]}),d)
    assert reply.design.assets['a'].sha256==asset.sha256 and local_shape(reply.design,reply.design.parts[0]).Volume()==pytest.approx(1000)


def test_edge_reference_survives_source_dimension_edit():
    from cadstudio.advanced_geometry import edge_records
    from cadstudio.models import EdgeFeature
    shape=cq.Workplane().box(20,30,10).val();ref={k:v for k,v in edge_records(shape)[0].items() if k!='points'}
    from cadstudio.advanced_geometry import apply_edge_feature
    resized=cq.Workplane().box(30,40,20).val();result=apply_edge_feature(resized,EdgeFeature(id='round',edges=[ref],support_edge_count=12,size=1))
    assert result.isValid() and result.Volume()<resized.Volume()
