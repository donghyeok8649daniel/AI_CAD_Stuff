from copy import deepcopy
import math
import numpy as np
import pytest

from cadstudio.models import Design,Extrusion,SavedSketch,WorkPlane
from cadstudio.kernel import build,preview
from cadstudio.sketch_frames import context_frame,work_plane_frame
from cadstudio.native.extrude import extrusion_candidate
from cadstudio.advanced_geometry import section_from_saved
from cadstudio.work_planes import edit_sketch_plane,plane_preview_sketch
from cadstudio.placement import move_selection
from cadstudio.parameters import set_binding
from cadstudio.native.document import Document,read_project


def profile():
    return Extrusion(sketch_mode='polygon',points=[dict(x=-10,y=-5),dict(x=10,y=-5),dict(x=10,y=5),dict(x=-10,y=5)],thickness=6).model_dump()


def assembly(plane=None):
    context=dict(work_plane=WorkPlane.model_validate(plane or {}).model_dump())
    raw=Design(sketches=[SavedSketch(id='s',name='Plane sketch',geometry=profile(),context=context)]).model_dump()
    raw=extrusion_candidate(raw,profile(),{**context,'sketch_id':'s'},'add','p','f')
    return Design.model_validate(raw).model_dump()


@pytest.mark.parametrize('plane,origin,normal',[('XY',[0,0,25],[0,0,1]),('XZ',[0,-25,0],[0,-1,0]),('YZ',[25,0,0],[1,0,0])])
def test_offset_uses_existing_base_plane_orientation(plane,origin,normal):
    d=Design.model_validate(assembly(dict(plane=plane,offset=25)))
    shape=build(d)[0]
    assert shape.Volume()==pytest.approx(1200)
    assert shape.Center().toTuple()==pytest.approx(np.array(origin)+3*np.array(normal))
    o,x,y=context_frame(d.sketches[0].context,d)
    assert o==pytest.approx(origin) and np.cross(x,y)==pytest.approx(normal)
    section=section_from_saved(d,d.sketches[0]);assert section.frame.origin==pytest.approx(origin)
    assert section.frame.normal==pytest.approx(normal)
    assert preview(d)['sketches'][0]['origin']==pytest.approx(origin)


@pytest.mark.parametrize('values,extents',[({},(0,6)),({'direction':-1},(-6,0)),({'symmetric':True},(-3,3)),({'reverse_depth':4},(-4,6))])
def test_tilted_sketch_display_and_actual_extrusion_share_plane(values,extents):
    raw=assembly(dict(offset=30,placement=dict(x=12,y=-7,rx=45)))
    raw['parts'][0]['geometry'].update(values);d=Design.model_validate(raw);shape=build(d)[0]
    normal=np.array([0,-math.sqrt(.5),math.sqrt(.5)]);origin=np.array([12,-7,30])
    signed=[(np.asarray(v.Center().toTuple())-origin)@normal for v in shape.Vertices()]
    assert (min(signed),max(signed))==pytest.approx(extents,abs=1e-7)
    assert shape.Volume()==pytest.approx(200*(extents[1]-extents[0]))
    record=preview(d)['sketches'][0]
    assert record['normal']==pytest.approx(normal)
    for row in record['lines']:
        assert all(abs((np.array(p)-origin)@normal)<1e-8 for p in row)


def test_plane_validation_rejects_ambiguous_support_and_out_of_range_origin():
    with pytest.raises(ValueError,match='동시에'):SavedSketch(id='s',geometry=profile(),context=dict(work_plane={},part_id='p'))
    with pytest.raises(ValueError,match='5,000'):work_plane_frame(dict(offset=4000,placement=dict(z=2000)))
    for value in (float('nan'),float('inf')):
        with pytest.raises(ValueError):work_plane_frame(dict(offset=value))
    assert 'work_plane' not in SavedSketch(id='s',geometry=profile()).model_dump()['context']


def test_edit_plane_moves_dependent_extrusion_without_modifying_sketch_or_geometry():
    raw=assembly();before=deepcopy(raw)
    moved=edit_sketch_plane(raw,'s',dict(offset=40,placement=dict(rx=90,x=5)))
    d=Design.model_validate(moved);shape=build(d)[0]
    assert shape.Center().toTuple()==pytest.approx((5,-3,40))
    assert shape.Volume()==pytest.approx(1200)
    assert raw==before and moved['parts'][0]['geometry']==before['parts'][0]['geometry']
    assert moved['sketches'][0]['geometry']==before['sketches'][0]['geometry']
    assert moved['parts'][0]['profile_sketch_id']=='s'
    assert '40 mm' in moved['sketches'][0]['context']['title']


def test_plane_edit_preserves_manual_relative_placement_and_unrelated_part():
    raw=assembly();raw['parts'].append(dict(id='other',name='Other',geometry=dict(kind='cylinder',diameter=10,height=4)))
    raw,_=move_selection(raw,['p'],translation=[10,0,0]);before=deepcopy(raw)
    result=edit_sketch_plane(raw,'s',dict(offset=20,placement=dict(rz=90)))
    assert result['parts'][0]['transform']['y']==pytest.approx(10)
    assert result['parts'][0]['transform']['z']==pytest.approx(20)
    assert result['parts'][1]==before['parts'][1]


def test_plane_edit_keeps_bound_and_grounded_parts_safe():
    raw=assembly();raw['parts'][0]['fixed']=True
    with pytest.raises(ValueError,match='고정'):edit_sketch_plane(raw,'s',dict(offset=10))
    result=edit_sketch_plane(raw,'s',dict(offset=10),allow_grounded=True)
    assert result['parts'][0]['fixed'] and result['parts'][0]['transform']['z']==10
    raw['parameters']={'x':'0'};set_binding(raw,['parts',0,'transform','x'],'x');before=deepcopy(raw)
    with pytest.raises(ValueError,match='변수'):edit_sketch_plane(raw,'s',dict(offset=10),allow_grounded=True)
    with pytest.raises(ValueError,match='변수'):move_selection(raw,['p'],translation=[0,0,10],allow_grounded=True)
    assert raw==before


def test_plane_edit_refuses_external_assembly_and_keeps_original():
    raw=assembly();raw['parts'].append(dict(id='other',name='Other',geometry=dict(kind='cylinder',diameter=10,height=4)))
    raw['mates']=[dict(id='j',parent='p',child='other',kind='rigid',parent_anchor='origin',child_anchor='origin')]
    raw=Design.model_validate(raw).model_dump();before=deepcopy(raw)
    with pytest.raises(ValueError,match='선택 밖'):edit_sketch_plane(raw,'s',dict(offset=10))
    assert raw==before


def test_plane_persists_and_history_restores_original(tmp_path):
    raw=assembly(dict(plane='XZ',offset=15,placement=dict(rz=12.345678901234)))
    doc=Document();doc.commit(Design.model_validate(raw),'Sketch on plane')
    changed=edit_sketch_plane(raw,'s',dict(offset=30,placement=dict(ry=15)))
    doc.commit(Design.model_validate(changed),'Edit plane');path=tmp_path/'plane.cad.json';doc.write(path)
    loaded=read_project(path)
    assert loaded.design.model_dump()==changed
    first,last=doc.journal.path()
    assert doc.journal.at(first['id'])==raw
    assert doc.journal.at(last['id'])==changed
    assert len(loaded.history.entries)==2


def test_preview_grid_has_no_solid_or_profile_and_does_not_become_part():
    d=Design(sketches=[plane_preview_sketch(dict(offset=200,placement=dict(rx=45)))])
    record=preview(d)
    assert not record['meshes'] and record['stats']['parts']==0
    assert record['sketches'][0]['regions']==[] and len(record['sketches'][0]['lines'])==22
    assert record['stats']['min'][2]>150


def test_work_plane_cannot_bypass_dependent_placement_update_with_dimension_binding():
    raw=assembly();before=deepcopy(raw)
    with pytest.raises(ValueError,match='작업 평면 편집'):
        set_binding(raw,['sketches','s','context','work_plane','offset'],'20')
    assert raw==before


def test_referenced_loft_plane_edit_requires_its_modeling_tool():
    from cadstudio.models import LoftGeometry,Part
    raw=assembly();d=Design.model_validate(raw);section=section_from_saved(d,d.sketches[0])
    other=section.model_copy(deep=True);other.sketch_id='';other.frame.origin=[0,0,20]
    raw['parts'].append(Part(id='loft',name='Loft',geometry=LoftGeometry(sections=[section,other])).model_dump())
    assert build(Design.model_validate(raw))[-1].Volume()==pytest.approx(4000)
    before=deepcopy(raw)
    with pytest.raises(ValueError,match='로프트'):edit_sketch_plane(raw,'s',dict(offset=10))
    assert raw==before
