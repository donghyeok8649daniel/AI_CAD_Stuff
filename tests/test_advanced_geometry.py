import math
import pytest
import cadquery as cq
from cadstudio.models import (Design,Part,SweepGeometry,SweepPath,LoftGeometry,EdgeFeature,ModelSection,ModelFrame,Extrusion,SavedSketch,circle_profile)
from cadstudio.kernel import construct,preview,local_shape,export
from cadstudio.advanced_geometry import edge_records
from cadstudio.native.document import Document,read_project
from cadstudio.mechanisms import four_bar
from cadstudio.constraints import solve_assembly


def test_straight_sweep_exact_volume():
    shape=construct(SweepGeometry(path=SweepPath(points=[[0,0,0],[0,0,60]])))
    assert shape.isValid() and len(shape.Solids())==1
    assert shape.Volume()==pytest.approx(math.pi*5**2*60,rel=1e-7)


def test_loft_conical_frustum_and_surface_export(tmp_path):
    shape=construct(LoftGeometry())
    assert shape.Volume()==pytest.approx(math.pi*50*(20**2+20*10+10**2)/3,rel=1e-7)
    d=Design(parts=[Part(id='surface',name='곡면',geometry=LoftGeometry(solid=False))])
    result=preview(d)
    assert result['stats']['volume']==0 and not result['meshes'][0]['solid']
    path=tmp_path/'surface.step';export(d,path,'step')
    imported=cq.importers.importStep(str(path)).val()
    assert imported.isValid() and not imported.Solids() and imported.Faces()


def test_open_curve_surface_loft():
    sketch=Extrusion(sketch_mode='entities',entities=[dict(id='line',kind='line',start=dict(x=-10,y=0),end=dict(x=10,y=0))])
    g=LoftGeometry(solid=False,sections=[ModelSection(sketch=sketch),ModelSection(sketch=sketch,frame=ModelFrame(origin=[0,0,50]))])
    shape=construct(g)
    assert shape.Area()==pytest.approx(1000) and not shape.Solids()


def test_edge_fillet_exact_removed_volume_and_history(tmp_path):
    d=Design(parts=[Part(id='box',name='box',geometry=dict(kind='plate',length=40,width=30,thickness=20,hole_count=0))])
    shape=local_shape(d,d.parts[0]);refs=edge_records(shape)
    edge=next(r for r in refs if abs(r['length']-20)<1e-6 and abs(r['center'][2]-10)<1e-6)
    ref={k:v for k,v in edge.items() if k!='points'}
    doc=Document();doc.commit(d,'base')
    d.parts[0].features=[EdgeFeature(id='round',size=2,edges=[ref],support_edge_count=len(refs))]
    rounded=local_shape(d,d.parts[0])
    assert shape.Volume()-rounded.Volume()==pytest.approx(20*4*(1-math.pi/4),rel=1e-6)
    doc.commit(d,'3D fillet',{'edges':[ref]});path=tmp_path/'fillet.cad.json';doc.write(path)
    reloaded=read_project(path).design
    assert local_shape(reloaded,reloaded.parts[0]).Volume()==pytest.approx(rounded.Volume())
    d.parts[0].geometry.length=50
    grown=local_shape(d,d.parts[0]);assert grown.Volume()==pytest.approx(50*30*20-20*4*(1-math.pi/4))
    # Legacy references have no normalized location and still require reselection.
    old={k:v for k,v in ref.items() if k not in ('relative_center','tangent')}
    d.parts[0].features=[EdgeFeature(id='legacy',size=2,edges=[old],support_edge_count=len(refs))]
    with pytest.raises(ValueError,match='모서리'):
        local_shape(d,d.parts[0])


def test_saved_sketch_dimension_drives_sweep():
    sketch=SavedSketch(id='profile',geometry=circle_profile(5))
    g=SweepGeometry(profile=ModelSection(sketch=sketch.geometry,sketch_id='profile'),path=SweepPath(points=[[0,0,0],[0,0,60]]))
    d=Design(parts=[Part(id='sweep',name='스윕',geometry=g)],sketches=[sketch])
    before=preview(d)['stats']['volume']
    d.sketches[0].geometry=circle_profile(10)
    assert preview(d)['stats']['volume']==pytest.approx(before*4)
    d.sketches=[]
    with pytest.raises(ValueError,match='삭제'):
        preview(d)


@pytest.mark.parametrize('angle',[-120,-60,0,45,120,180])
def test_four_bar_closure_follows_driving_angle(angle):
    d=four_bar();d.mates[0].rz=angle
    stats=solve_assembly(d)
    assert stats['closure_error_mm']<1e-5 and stats['dof']==1
    assert d.mates[0].rz==angle


def test_impossible_closure_is_rejected():
    d=four_bar();d.mates[0].rz=180
    d.parts[-1].geometry.hole_spacing=20;d.parts[-1].geometry.length=36
    with pytest.raises(ValueError,match='닫을 수 없습니다'):
        solve_assembly(d)
