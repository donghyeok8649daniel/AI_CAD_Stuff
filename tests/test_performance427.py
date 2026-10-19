"""Preserve real geometry, topology and safety checks while avoiding repeated UI work."""
import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import cadquery as cq
import pytest
from cadstudio.models import Design,Part
from cadstudio import kernel as K
from cadstudio.interference import _intersection_volume,exact_collisions
from cadstudio.imported import encode_shape


@pytest.fixture(autouse=True)
def caches():
    from cadstudio.interference import _collision_cache
    _collision_cache.clear()
    K.set_preview_quality('auto')
    K._part_mesh_cache.clear();K._preview_mesh_cache.clear()
    K._live_local_shapes.clear();K._part_cached.cache_clear();K._build_cached.cache_clear()
    yield
    _collision_cache.clear()
    K._part_mesh_cache.clear();K._preview_mesh_cache.clear()
    K._live_local_shapes.clear();K._part_cached.cache_clear();K._build_cached.cache_clear()
    K.set_preview_quality('auto')


def test_exact_pair_reuse_requires_current_geometry_pose_and_native_stamp(monkeypatch):
    from cadstudio import interference as I
    d=Design(parts=[Part(id=i,name=i,geometry=dict(kind='plate',length=10,width=10,thickness=5,hole_count=0),
        transform=dict(x=x)) for i,x in [('a',0),('b',5)]])
    calls=[];original=I._intersection_volume
    def tracked(a,b):calls.append(1);return original(a,b)
    monkeypatch.setattr(I,'_intersection_volume',tracked)
    shapes=K.build(d);first=I.exact_collisions(d,shapes);second=I.exact_collisions(d,shapes)
    assert first==second and len(calls)==1
    changed=d.model_copy(deep=True);changed.parts[1].geometry.length=12
    moved=K.build(changed);hit=I.exact_collisions(changed,moved)
    assert len(calls)==2 and hit[0]['volume']==pytest.approx(300)
    # An external native mutation must not retain the constructor's stamp.
    moved[1].move(cq.Location(cq.Vector(20,0,0)))
    assert I._checked_shape_key(changed.parts[1],moved[1]) is None
    assert not I.exact_collisions(changed,moved)
    # Untagged native operands supplied by callers always calculate afresh.
    external=[cq.Workplane('XY').box(10,10,5).val() for _ in range(2)]
    I.exact_collisions(d,external);I.exact_collisions(d,external)
    assert len(calls)==4


def test_hot_weak_geometry_cache_cannot_accept_changed_asset_bytes_claiming_an_old_sha():
    original=encode_shape(cq.Workplane('XY').box(4,5,6).val(),'original')
    d=Design(parts=[Part(id='p',name='p',geometry=dict(kind='imported',asset_id='asset'))],assets={'asset':original})
    held=K.build(d)
    replacement=encode_shape(cq.Workplane('XY').box(10,11,12).val(),'replacement')
    corrupt=d.model_copy(deep=True);corrupt.assets['asset'].data=replacement.data
    assert corrupt.assets['asset'].sha256==d.assets['asset'].sha256
    with pytest.raises(ValueError):K.build(corrupt)
    assert held[0].Volume()==pytest.approx(120)


def test_exact_pair_reuse_keeps_current_wire_scope_callbacks_and_nonfinite_rejection(monkeypatch):
    from cadstudio import interference as I
    from cadstudio.part_product import ProductMetadata,ProductSpec
    d=Design(parts=[Part(id=i,name=i,geometry=dict(kind='cylinder',diameter=8,height=10)) for i in ['a','b']])
    shapes=K.build(d);assert I.exact_collisions(d,shapes)
    d.parts[1].product=ProductMetadata(specs=[ProductSpec(label='간섭 분류',value='유연 전선')])
    checks=[];completed=[]
    assert not I.exact_collisions(d,shapes,check=lambda:checks.append(1),completed=lambda:completed.append(1))
    assert checks==completed==[1]
    d.parts[1].product=None;assert I.exact_collisions(d,shapes)
    I._collision_cache.clear();monkeypatch.setattr(I,'_intersection_volume',lambda *_:float('nan'))
    with pytest.raises(ValueError,match='간섭 체적'):I.exact_collisions(d,shapes)
    assert not I._collision_cache


def test_picking_spatial_index_preserves_normal_output_triangle_ids_without_rendering():
    from vtkmodules.vtkFiltersSources import vtkSphereSource
    from vtkmodules.vtkFiltersCore import vtkPolyDataNormals
    from vtkmodules.vtkCommonDataModel import vtkStaticCellLocator
    source=vtkSphereSource();source.SetThetaResolution(60);source.SetPhiResolution(40);source.Update()
    normals=vtkPolyDataNormals();normals.SetInputData(source.GetOutput());normals.SetFeatureAngle(35);normals.SplittingOn();normals.ConsistencyOn();normals.AutoOrientNormalsOn();normals.Update()
    data=normals.GetOutput();locator=vtkStaticCellLocator();locator.SetDataSet(data);locator.BuildLocator()
    assert data.GetNumberOfCells()==source.GetOutput().GetNumberOfCells()
    for identifier in [10,300,1000,2000,4000]:
        points=data.GetCell(identifier).GetPoints()
        center=[sum(points.GetPoint(i)[axis] for i in range(3))/3 for axis in range(3)]
        assert locator.FindCell(center)==identifier


def test_display_sampling_does_not_change_real_stl_export(tmp_path):
    import struct
    d=Design(parts=[Part(id='wire',name='wire',geometry=dict(kind='sweep'))])
    with K.KERNEL_LOCK,K.local_shape_session():
        K.set_preview_quality('fine');K._preview_meshes(d,K.build(d));K.export(d,tmp_path/'fine.stl','stl')
        K.set_preview_quality('fast');K._preview_meshes(d,K.build(d));K.export(d,tmp_path/'fast.stl','stl')
    a=(tmp_path/'fine.stl').read_bytes();b=(tmp_path/'fast.stl').read_bytes()
    assert struct.unpack_from('<I',a,80)==struct.unpack_from('<I',b,80)
    assert a[84:]==b[84:]  # Ignore the optional exporter header, compare every facet.


def frozen_meshes():
    path=Path(__file__).resolve().parents[3]/'release340-r2/source/cadstudio/kernel.py'
    tree=ast.parse(path.read_text(encoding='utf-8-sig'))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_preview_meshes')
    namespace=dict(K.__dict__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(path),'exec'),namespace)
    return namespace['_preview_meshes']


def without_attestation(meshes):
    return [{k:v for k,v in mesh.items() if k!='_display_input_key'} for mesh in meshes]


def design():
    asset=encode_shape(cq.Workplane('XY').box(8,9,10).edges('|Z').fillet(.7).val(),'rounded')
    return Design(parts=[
        Part(id='plate',name='plate',geometry=dict(kind='plate',length=20,width=15,thickness=4,hole_count=2,hole_pitch_x=10,hole_diameter=3)),
        Part(id='cyl',name='cyl',geometry=dict(kind='cylinder',height=12,diameter=6),transform=dict(x=35,rx=17,ry=25,rz=61)),
        Part(id='asset',name='asset',geometry=dict(kind='imported',asset_id='asset'),transform=dict(x=60,y=5,rz=33)),
        Part(id='wire',name='wire',geometry=dict(kind='sweep'),transform=dict(x=150)),
    ],assets={'asset':asset})


def test_flat_payload_and_topology_match_real_frozen340_mesh_function_exactly():
    d=design()
    with K.KERNEL_LOCK,K.local_shape_session():
        shapes=K.build(d);expected=frozen_meshes()(d,shapes);actual=K._preview_meshes(d,shapes)
    assert without_attestation(actual)==expected
    assert all(m['valid'] for m in actual)


def test_one_part_edit_reuses_others_but_invalidates_changed_geometry_pose_and_asset():
    d=design()
    with K.KERNEL_LOCK,K.local_shape_session():K._preview_meshes(d,K.build(d))
    before=K._part_mesh_cache.info();changed=d.model_copy(deep=True)
    changed.parts[0].geometry.thickness=6;changed.parts[1].transform.x+=5
    with K.KERNEL_LOCK,K.local_shape_session():
        shapes=K.build(changed);actual=K._preview_meshes(changed,shapes);expected=frozen_meshes()(changed,shapes)
    assert without_attestation(actual)==expected and K._part_mesh_cache.info()['hits']-before['hits']==2
    updated=changed.model_copy(deep=True)
    updated.assets['asset']=encode_shape(cq.Workplane('XY').box(5,6,7).val(),'changed')
    with K.KERNEL_LOCK,K.local_shape_session():
        shapes=K.build(updated);assert without_attestation(K._preview_meshes(updated,shapes))==frozen_meshes()(updated,shapes)


def test_cache_hit_returns_owned_metadata_and_keeps_current_names_colors_and_cancel():
    d=design()
    with K.KERNEL_LOCK,K.local_shape_session():
        shapes=K.build(d);first=K._preview_meshes(d,shapes)
        first[0]['faces'][0]['reference']['area']=-100
        d.parts[0].name='renamed';d.parts[0].color='#123456'
        second=K._preview_meshes(d,shapes)
        assert second[0]['name']=='renamed' and second[0]['color']=='#123456'
        assert second[0]['faces'][0]['reference']['area']>0
        def cancelled():raise RuntimeError('cancelled')
        with pytest.raises(RuntimeError,match='cancelled'):K._preview_meshes(d,shapes,check=cancelled)
    assert K._part_mesh_cache.info()['compressed_bytes']<=64*1024**2


def test_bounded_mesh_scan_keeps_live_entries_and_releases_obsolete_poses():
    from cadstudio.preview_cache import MeshCache
    cache=MeshCache(max_bytes=2000,max_entries=2,max_raw_bytes=4000)
    assert cache.put('a',dict(value=1),evict=False) and cache.put('b',dict(value=2),evict=False)
    assert not cache.put('c',dict(value=3),evict=False)
    assert cache.get('a')==dict(value=1) and cache.get('b')==dict(value=2)
    cache.retain({'b','c'})
    assert cache.get('a') is None and cache.put('c',dict(value=3),evict=False)


def test_boolean_tool_relative_pose_remains_in_part_mesh_identity():
    raw=Design(parts=[Part(id='a',name='a',geometry=dict(kind='plate',length=10,width=10,thickness=10,hole_count=0)),
        Part(id='b',name='b',geometry=dict(kind='cylinder',height=20,diameter=4),transform=dict(x=2))]).model_dump()
    raw['parts'][0]['features']=[dict(id='cut',kind='solid',operation='boolean',tool_part_id='b',boolean_mode='cut')]
    a=Design.model_validate(raw)
    with K.KERNEL_LOCK,K.local_shape_session():first=K._preview_meshes(a,K.build(a))
    raw['parts'][1]['transform']['x']=3;b=Design.model_validate(raw)
    with K.KERNEL_LOCK,K.local_shape_session():
        shapes=K.build(b);second=K._preview_meshes(b,shapes);expected=frozen_meshes()(b,shapes)
    assert without_attestation(second)==expected and first[0]['vertices']!=second[0]['vertices']


def test_edit_one_of_forty_parts_builds_only_the_changed_local_shape():
    d=Design(parts=[Part(id=f'p{i}',name=f'p{i}',geometry=dict(kind='plate',length=20+i*.1,width=8,thickness=3,hole_count=0),
        transform=dict(x=i*40)) for i in range(40)])
    first=K.build(d);before=K._part_cached.cache_info().misses
    changed=d.model_copy(deep=True);changed.parts[-1].geometry.length+=.33
    second=K.build(changed)
    assert K._part_cached.cache_info().misses-before==1
    assert all(first[i]._cadstudio_local_shape is second[i]._cadstudio_local_shape for i in range(39))
    assert second[-1]._cadstudio_local_shape is not first[-1]._cadstudio_local_shape


def test_weak_geometry_index_owns_no_native_shape_after_bounded_builds_release():
    import gc,weakref
    d=Design(parts=[Part(id='p',name='p',geometry=dict(kind='plate',length=23,width=7,thickness=2,hole_count=0))])
    shapes=K.build(d);reference=weakref.ref(shapes[0]._cadstudio_local_shape)
    K._build_cached.cache_clear();K._part_cached.cache_clear();del shapes;gc.collect()
    assert reference() is None and len(K._live_local_shapes)==0


def test_display_quality_is_explicit_persistent_and_does_not_relax_small_assembly_default(tmp_path):
    from cadstudio import preview_quality as Q
    assert Q.tolerances('auto',100,'sweep')==Q.tolerances('fine',391,'sweep')==(.04,.12)
    assert Q.tolerances('auto',391,'sweep')==(.08,.24)
    assert Q.tolerances('auto',391,'plate')==(.04,.12)
    with pytest.raises(ValueError):K.set_preview_quality('hidden')
    path=tmp_path/'quality.json';assert Q.load(path)=='auto'
    Q.save(path,'fine');assert Q.load(path)=='fine'
    path.write_text('{bad',encoding='utf-8');assert Q.load(path)=='auto'


def test_large_wire_display_uses_fewer_triangles_but_same_exact_topology_and_export_inputs():
    parts=[Part(id=f'p{i}',name='plate',geometry=dict(kind='plate',length=10,width=10,thickness=2,hole_count=0),
        transform=dict(x=500+i*30)) for i in range(100)]
    wire=Part(id='wire',name='wire',geometry=dict(kind='sweep',path=dict(points=[[0,0,0],[80,40,30],[200,-25,60]],smooth=True)))
    d=Design(parts=[wire,*parts]);before=d.model_dump();K.set_preview_quality('fine')
    with K.KERNEL_LOCK,K.local_shape_session():
        shapes=K.build(d);fine=K._preview_meshes(d,shapes)
        volume=shapes[0].Volume();bounds=K.exact_bounds(shapes[0]);reference=fine[0]['faces']
        K.set_preview_quality('auto');auto=K._preview_meshes(d,shapes)
        assert len(auto[0]['triangles'])<len(fine[0]['triangles'])
        assert auto[0]['faces']==reference and auto[0]['volume']==pytest.approx(volume)
        assert K.exact_bounds(shapes[0]).xlen==bounds.xlen and shapes[0].isValid()
        K.set_preview_quality('fine');restored=K._preview_meshes(d,shapes)
        assert restored==fine
    assert d.model_dump()==before


@pytest.mark.parametrize('offset',[0,2,5,10,12])
def test_serial_exact_common_matches_cadquery_parallel_operation(offset):
    a=cq.Workplane('XY').box(10,10,10).faces('>Z').workplane().hole(3).val()
    b=cq.Workplane('XY').cylinder(12,4).val().translate((offset,0,0))
    assert _intersection_volume(a,b)==pytest.approx(a.intersect(b).Volume(),rel=1e-10,abs=1e-8)
    compound=cq.Compound.makeCompound([a,a.translate((25,0,0))])
    assert _intersection_volume(compound,b)==pytest.approx(compound.intersect(b).Volume(),rel=1e-10,abs=1e-8)


def test_cache_never_reuses_collision_verdict_after_pose_change():
    d=Design(parts=[Part(id=i,name=i,geometry=dict(kind='plate',length=10,width=10,thickness=5,hole_count=0),
        transform=dict(x=x)) for i,x in [('a',0),('b',30)]])
    assert not K.preview(d)['stats']['collisions']
    d.parts[1].transform.x=5
    result=K.preview(d)
    assert result['stats']['collisions'][0]['volume']==pytest.approx(250)


def viewport_method(name):
    path=Path(K.__file__).with_name('native')/'viewport.py';tree=ast.parse(path.read_text(encoding='utf-8-sig'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='CADViewport')
    return next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)


def test_picker_reuses_only_visible_actor_indices_and_zoom_uses_same_path():
    class Picker:
        def __init__(self):self.locators=[]
        def AddLocator(self,value):self.locators.append(value)
    class Actor:
        def __init__(self,visible):self.visible=visible
        def GetVisibility(self):return self.visible
    namespace={'vtkCellPicker':Picker}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[viewport_method('body_picker')],type_ignores=[])),'actual_picker_ast','exec'),namespace)
    actor=Actor(True);hidden=Actor(False);locator=object()
    picker=namespace['body_picker'](SimpleNamespace(pick_locators={actor:locator,hidden:object()}))
    assert picker.locators==[locator]
    assert 'self.body_picker()' in ast.unparse(viewport_method('zoom_at_cursor'))
    source=ast.unparse(viewport_method('load'))
    assert 'locator.SetDataSet(normals.GetOutput())' in source and 'old_locators' in source


def test_native_edit_shares_only_unchanged_verified_bulk_arrays_and_reports_live_collisions():
    d=design();first=K.preview(d);old_vertices=list(first['meshes'][0]['vertices'])
    edited=d.model_copy(deep=True);edited.parts[0].geometry.thickness+=.1
    progress=[];second=K.preview(edited,previous=(d,first),progress=progress.append)
    for index in range(1,len(d.parts)):
        assert second['meshes'][index]['vertices'] is first['meshes'][index]['vertices']
        assert second['meshes'][index] is not first['meshes'][index]
    assert second['meshes'][0]['vertices'] is not first['meshes'][0]['vertices']
    assert first['meshes'][0]['vertices']==old_vertices
    assert any('간섭 검사' in text for text in progress)
    # A result from a different baseline cannot opt into sharing.
    invalid={**first,'_geometry_key':'invalid'}
    third=K.preview(edited,previous=(d,invalid))
    assert third['meshes'][1]['vertices'] is not first['meshes'][1]['vertices']


def test_actual_viewport_retains_actors_only_for_identical_bulk_arrays():
    load=viewport_method('load')
    start=next(i for i,n in enumerate(load.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='retained' for t in n.targets))
    nodes=load.body[start:start+2]
    shared=[0,0,0];triangles=[0,0,0];actor=object()
    host=SimpleNamespace(meshes={'a':dict(vertices=shared,triangles=triangles),'b':dict(vertices=[0],triangles=triangles)},actors={'a':actor,'b':object()})
    namespace={'self':host,'result':dict(meshes=[dict(id='a',vertices=shared,triangles=triangles),dict(id='b',vertices=[0],triangles=triangles)])}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'actual_retained_actors','exec'),namespace)
    assert namespace['retained']=={'a':actor}


@pytest.mark.parametrize('failure',[False,True])
def test_actual_manual_save_keeps_boolean_contract_and_live_state_on_failure(tmp_path,failure):
    path=Path(K.__file__).with_name('native')/'window.py';tree=ast.parse(path.read_text(encoding='utf-8-sig'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MainWindow')
    node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='save')
    class Loop:
        def __init__(self,parent):self.quit_called=False
        def quit(self):self.quit_called=True
        def exec(self):assert self.quit_called
    from cadstudio.native.document import Document,read_project
    doc=Document();doc.commit(Design(name='original'),'start');doc.path=tmp_path/'manual.pcad'
    captured=[];errors=[]
    def run(work,done,message,failed):
        assert doc.dirty
        try:
            if failure:raise OSError('owned failure')
            done(work())
        except Exception as exc:failed(str(exc))
    window=SimpleNamespace(document=doc,busy=False,sketching=False,run=run,title=lambda:None,message=captured.append,show_error=errors.append)
    namespace={'Path':Path,'QEventLoop':Loop}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'actual_save_ast','exec'),namespace)
    assert namespace['save'](window) is (not failure)
    if failure:assert doc.dirty and errors and not doc.path.exists()
    else:assert not doc.dirty and read_project(doc.path).design.name=='original'
