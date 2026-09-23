import math
from copy import deepcopy
import cadquery as cq
import pytest
from cadstudio.models import Design,Part,Extrusion,ModelSection,RevolveGeometry,SolidFeature
from cadstudio.kernel import construct,local_shape,build,preview,exact_bounds
from cadstudio.native.extrude import extrusion_candidate
from cadstudio.topology import face_reference,resolve_face
from cadstudio.solid_tools import apply_operation
from cadstudio.imported import encode_shape,decode_shape,import_asset
from cadstudio.native.document import Document,read_project


def rectangle(w=20,h=10,**kwargs):
    return Extrusion(points=[dict(x=x,y=y) for x,y in [(0,0),(w,0),(w,h),(0,h)]],**kwargs)


def test_shared_sketch_rebuilds_multiple_extrusions_without_changing_depth(tmp_path):
    g=rectangle();d=Design(sketches=[dict(id='sk',geometry=g.model_dump())]);raw=d.model_dump()
    for identifier,depth in [('a',4),('b',11)]:
        raw=extrusion_candidate(raw,g.model_copy(update={'thickness':depth}).model_dump(),{'sketch_id':'sk'},'add',identifier,'unused')
    d=Design.model_validate(raw);assert [s.Volume() for s in build(d)]==pytest.approx([800,2200])
    doc=Document();doc.commit(d,'two extrusions');raw=d.model_dump();raw['sketches'][0]['geometry']=rectangle(30).model_dump();updated=Design.model_validate(raw)
    assert [s.Volume() for s in build(updated)]==pytest.approx([1200,3300]);doc.commit(updated,'edit source');doc.write(tmp_path/'shared.cad.json')
    assert [s.Volume() for s in build(read_project(tmp_path/'shared.cad.json').design)]==pytest.approx([1200,3300])
    raw['sketches']=[]
    with pytest.raises(ValueError,match='원본 스케치'):Design.model_validate(raw)


def test_linked_base_edit_updates_the_source():
    g=rectangle();raw=Design(sketches=[dict(id='s',geometry=g)],parts=[Part(id='p',name='p',geometry=g,profile_sketch_id='s')]).model_dump()
    raw=extrusion_candidate(raw,rectangle(31).model_dump(),{'edit_base':True,'part_id':'p'},'add','p','unused')
    d=Design.model_validate(raw);assert d.sketches[0].geometry.points[1].x==31 and local_shape(d,d.parts[0]).Volume()==pytest.approx(31*10*g.thickness)


def test_revolve_annulus_and_partial_revolution():
    profile=Extrusion(points=[dict(x=x,y=y) for x,y in [(5,0),(15,0),(15,20),(5,20)]])
    for angle in (90,360):
        g=RevolveGeometry(profile=ModelSection(sketch=profile),angle=angle)
        assert construct(g).Volume()==pytest.approx(math.pi*(15**2-5**2)*20*angle/360)


@pytest.mark.parametrize('kwargs,low,high',[({'symmetric':True},-5,5),({'reverse_depth':3},-3,10),({'direction':-1,'reverse_depth':3},-10,3)])
def test_two_sided_extrusion_extents(kwargs,low,high):
    shape=construct(rectangle(thickness=10,**kwargs));b=exact_bounds(shape)
    assert (b.zmin,b.zmax)==pytest.approx((low,high));assert shape.Volume()==pytest.approx(200*(high-low))


def test_taper_uses_actual_solid_geometry():
    g=rectangle(20,20,thickness=5,taper=5);shape=construct(g);assert shape.isValid() and shape.Volume()<2000


def test_face_reference_recovers_reordered_and_resized_faces():
    shape=cq.Workplane('XY').box(20,30,10,centered=(True,True,False)).val();index=next(i for i,f in enumerate(shape.Faces()) if f.normalAt().z>.9);ref=face_reference(shape,index)
    grown=cq.Workplane('XY').box(25,35,20,centered=(True,True,False)).val();i,face=resolve_face(grown,ref)
    assert face.Center().z==pytest.approx(20)
    ref.index=0;assert resolve_face(grown,ref)[1].Center().z==pytest.approx(20)


def test_dynamic_through_cut_survives_thickness_change():
    d=Design(parts=[Part(id='p',name='p',geometry=dict(kind='plate',length=30,width=30,thickness=5,hole_count=0))]);shape=local_shape(d,d.parts[0]);index=next(i for i,f in enumerate(shape.Faces()) if f.normalAt().z>.9);ref=face_reference(shape,index)
    raw=d.model_dump();raw['parts'][0]['features']=[dict(id='hole',face=index,normal=[0,0,1],reference=ref.model_dump(),operation='cut',through_all=True,sketch=dict(kind='extrusion',thickness=5,sketch_mode='entities',entities=[dict(id='circle',kind='circle',center=dict(x=0,y=0),radius=3)]))]
    for thickness in (5,40):
        raw['parts'][0]['geometry']['thickness']=thickness;d=Design.model_validate(raw)
        assert local_shape(d,d.parts[0]).Volume()==pytest.approx((900-math.pi*9)*thickness)


def test_shell_and_draft_have_analytic_effect():
    shape=cq.Workplane('XY').box(20,30,10,centered=(True,True,False)).val();top=next(i for i,f in enumerate(shape.Faces()) if f.normalAt().z>.9)
    shell=apply_operation(shape,SolidFeature(id='shell',operation='shell',faces=[face_reference(shape,top)],size=2))
    assert shell.Volume()==pytest.approx(6000-16*26*8)
    side=next(i for i,f in enumerate(shape.Faces()) if f.normalAt().x>.9)
    draft=apply_operation(shape,SolidFeature(id='draft',operation='draft',faces=[face_reference(shape,side)],angle=3))
    assert draft.isValid() and draft.Volume()!=pytest.approx(shape.Volume())


@pytest.mark.parametrize('op,count',[('mirror',2),('linear_pattern',6),('circular_pattern',4)])
def test_body_patterns_and_mirror(op,count):
    shape=cq.Workplane('XY').box(2,2,2).val().translate((10,0,0))
    f=SolidFeature(id='p',operation=op,count=3 if op=='linear_pattern' else 4,count_y=2 if op=='linear_pattern' else 1,direction=[1,0,0] if op=='mirror' else [0,0,1],spacing=[30,30,0])
    result=apply_operation(shape,f);assert len(result.Solids())==count and result.Volume()==pytest.approx(8*count)


def test_split_plane_and_side_selection():
    shape=cq.Workplane('XY').box(20,20,20).val()
    all_sides=apply_operation(shape,SolidFeature(id='s',operation='split'));assert len(all_sides.Solids())==2
    positive=apply_operation(shape,SolidFeature(id='s',operation='split',keep_side='positive'))
    assert positive.Volume()==pytest.approx(4000) and exact_bounds(positive).zmin==pytest.approx(0)


def test_boolean_follows_tool_transform_and_rejects_cycles():
    raw=Design(parts=[Part(id='p',name='p',geometry=dict(kind='plate',length=20,width=20,thickness=10,hole_count=0),features=[SolidFeature(id='cut',operation='boolean',boolean_mode='cut',tool_part_id='tool')]),Part(id='tool',name='tool',geometry=dict(kind='cylinder',diameter=4,height=20),transform=dict(x=3,z=-5))]).model_dump();d=Design.model_validate(raw)
    assert local_shape(d,d.parts[0]).Volume()==pytest.approx(4000-math.pi*4*10)
    raw['parts'][1]['features']=[SolidFeature(id='cycle',operation='boolean',tool_part_id='p').model_dump()]
    d=Design.model_validate(raw)
    with pytest.raises(ValueError,match='순환'):local_shape(d,d.parts[0])


def test_imported_step_is_portable_and_tampering_is_rejected(tmp_path):
    shape=cq.Workplane('XY').box(12,13,14).val();path=tmp_path/'vendor.step';cq.exporters.export(shape,str(path));asset=import_asset(path);path.unlink()
    d=Design(parts=[Part(id='p',name='import',geometry=dict(kind='imported',asset_id='a'))],assets={'a':asset});assert local_shape(d,d.parts[0]).Volume()==pytest.approx(12*13*14)
    doc=Document();doc.commit(d,'import');doc.write(tmp_path/'portable.cad.json');assert local_shape(read_project(tmp_path/'portable.cad.json').design,d.parts[0]).Volume()==pytest.approx(2184)
    with pytest.raises(ValueError,match='해시'):decode_shape(asset.data,'0'*64)


def test_suppressed_operation_does_not_change_the_shape():
    p=Part(id='p',name='p',geometry=dict(kind='plate',length=20,width=20,thickness=10,hole_count=0),features=[SolidFeature(id='s',operation='shell',suppressed=True)])
    d=Design(parts=[p]);assert local_shape(d,d.parts[0]).Volume()==pytest.approx(4000)


def test_iges_and_stl_import_keep_real_faces(tmp_path):
    from OCP.IGESControl import IGESControl_Writer
    shape=cq.Workplane().box(10,20,30).val();iges=tmp_path/'part.igs';writer=IGESControl_Writer('MM',0);writer.AddShape(shape.wrapped);writer.ComputeModel();assert writer.Write(str(iges))
    stl=tmp_path/'part.stl';cq.exporters.export(shape,str(stl))
    for path in (iges,stl):
        asset=import_asset(path);restored=decode_shape(asset.data,asset.sha256);assert restored.isValid() and restored.Area()==pytest.approx(shape.Area(),rel=1e-5)
