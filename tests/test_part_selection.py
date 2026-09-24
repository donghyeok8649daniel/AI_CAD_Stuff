from copy import deepcopy
import numpy as np
import pytest
from cadstudio.models import Design,Part
from cadstudio.catalog import preset
from cadstudio.part_operations import group_parts,ungroup_parts,part_clipboard,paste_parts,delete_parts
from cadstudio.native.assembly_display import assembly_markers
from cadstudio.native.box_selection import rectangle_hit,projected_selection
from cadstudio.native.document import Document,read_project
from cadstudio.kernel import preview


def robot():return preset('robot_arm').model_dump()


def test_groups_preserve_solid_and_history(tmp_path):
    raw=robot();ids=[p['id'] for p in raw['parts']];doc=Document();doc.commit(raw,'開始')
    grouped,gid=group_parts(raw,ids,'腕');doc.commit(Design.model_validate(grouped),'group')
    assert grouped['parts']==raw['parts'] and grouped['mates']==raw['mates']
    doc.write(tmp_path/'group.cad.json');saved=read_project(tmp_path/'group.cad.json')
    assert saved.design.part_groups[0].part_ids==ids
    assert doc.journal.at(doc.journal.path()[-2]['id'])==raw
    assert not Design.model_validate(ungroup_parts(grouped,[ids[0]])).part_groups


def test_regroup_moves_members_without_duplicate_membership():
    raw=robot();ids=[p['id'] for p in raw['parts']];raw,_=group_parts(raw,ids)
    raw,_=group_parts(raw,ids[:2]);model=Design.model_validate(raw)
    assert len([i for g in model.part_groups for i in g.part_ids])==len(ids)
    raw['part_groups'].append(deepcopy(raw['part_groups'][0]))
    with pytest.raises(ValueError,match='그룹'):Design.model_validate(raw)


def test_assembly_clipboard_remaps_and_preserves_relative_geometry():
    raw=robot();ids=[p['id'] for p in raw['parts']];raw,_=group_parts(raw,ids)
    payload=part_clipboard(raw,ids);before=deepcopy(raw);data,new=paste_parts(raw,payload,42)
    model=Design.model_validate(data);assert raw==before
    assert len(model.parts)==len(ids)*2 and len(model.mates)==len(raw['mates'])*2
    for a,b in zip(model.parts[:len(ids)],model.parts[len(ids):]):
        assert b.transform.x==pytest.approx(a.transform.x+42)
        assert b.transform.y==pytest.approx(a.transform.y)
        assert b.geometry==a.geometry
    assert all({m.parent,m.child}<=set(new) for m in model.mates[len(raw['mates']):])
    assert set(model.part_groups[-1].part_ids)==set(new)
    assert preview(model)['stats']['volume']==pytest.approx(preview(Design.model_validate(raw))['stats']['volume']*2)


def test_delete_last_parts_empty_and_linked_source_detaches():
    raw=robot();ids=[p['id'] for p in raw['parts']];raw,_=group_parts(raw,ids)
    assert not Design.model_validate(delete_parts(raw,ids)).parts
    data=Design(parts=[Part(id='a',name='A',geometry={'kind':'plate','hole_count':0}),Part(id='b',name='B',geometry={'kind':'plate','hole_count':0},source_part_id='a')]).model_dump()
    result=Design.model_validate(delete_parts(data,['a']))
    assert len(result.parts)==1 and result.parts[0].source_part_id==''


def test_copy_bakes_variables_and_external_mates():
    raw=robot();pid=raw['parts'][1]['id'];raw['parameters']={'angle':'12'}
    payload=part_clipboard(raw,[pid]);assert not payload['mates'] and 'parameters' not in payload
    pasted,ids=paste_parts(None,payload);assert Design.model_validate(pasted).parts[0].id==ids[0]


def test_body_dependency_cannot_be_silently_broken():
    raw=Design(parts=[Part(id='a',name='A',geometry={'kind':'plate','hole_count':0}),Part(id='b',name='B',geometry={'kind':'plate','hole_count':0},features=[dict(id='cut',kind='solid',operation='boolean',tool_part_id='a',boolean_mode='cut')])]).model_dump()
    before=deepcopy(raw)
    with pytest.raises(ValueError,match='도구 부품'):part_clipboard(raw,['b'])
    with pytest.raises(ValueError,match='몸체 연산'):delete_parts(raw,['a'])
    assert raw==before
    data,new=paste_parts(raw,part_clipboard(raw,['a','b']))
    assert data['parts'][-1]['features'][0]['tool_part_id']==new[0]


def test_markers_follow_rotated_parent_and_face_frame():
    raw=Design(parts=[Part(id='a',name='A',geometry={'kind':'plate','hole_count':0},fixed=True,transform={'x':20,'ry':90}),Part(id='b',name='B',geometry={'kind':'plate','hole_count':0})],mates=[dict(id='joint',kind='revolute',parent='a',child='b',z=10)]).model_dump()
    marker=assembly_markers(raw)[0];assert marker['origin']==pytest.approx([30,0,0],abs=1e-7)
    assert np.array(marker['basis'])[:,2]==pytest.approx([1,0,0],abs=1e-7)
    frame=dict(face=0,face_count=6,origin=[0,0,5],normal=[1,0,0],x_direction=[0,1,0])
    raw['joint_frames']=[dict(mate_id='joint',parent=frame,child=frame)]
    marker=assembly_markers(raw)[0];assert marker['origin']==pytest.approx([25,0,-10],abs=1e-7)
    assert marker['b']==pytest.approx(marker['origin'])


def test_box_containment_crossing_and_no_bbox_false_positive():
    p=np.array([[0,0],[10,0],[0,10]])
    assert rectangle_hit(p,[[0,1,2]],np.array([-1,-1]),np.array([11,11]),True)
    assert not rectangle_hit(p,[[0,1,2]],np.array([1,1]),np.array([2,2]),True)
    assert rectangle_hit(p,[[0,1,2]],np.array([1,1]),np.array([2,2]),False)
    assert not rectangle_hit(p,[[0,1,2]],np.array([8,8]),np.array([9,9]),False)
    mesh={'a':dict(vertices=[[-.5,-.5,.5],[.5,-.5,.5],[0,.5,.5]],triangles=[[0,1,2]])}
    assert projected_selection(mesh,set(),np.eye(4),(200,100),(40,20),(160,80))==['a']
    assert projected_selection(mesh,{'a'},np.eye(4),(200,100),(40,20),(160,80))==[]


def test_internal_motion_links_and_closed_loops_survive_copy():
    from cadstudio.mechanisms import four_bar
    raw=four_bar().model_dump();ids=[p['id'] for p in raw['parts']]
    result,new=paste_parts(None,part_clipboard(raw,ids),15);model=Design.model_validate(result)
    assert len(model.loops)==1 and {model.loops[0].parent,model.loops[0].child}<=set(new)
    assert set(model.loops[0].passive_joints)<={m.id for m in model.mates}
    rows=assembly_markers(model);assert any(r['type']=='loop' for r in rows)
    raw=robot();moving=[m['id'] for m in raw['mates'] if m['kind']=='revolute']
    raw['motion_links']=[dict(id='ratio',driver=moving[0],driven=moving[1],ratio=2)]
    payload=part_clipboard(raw,[p['id'] for p in raw['parts']]);data,new=paste_parts(None,payload)
    model=Design.model_validate(data);assert model.motion_links[0].driver in {m.id for m in model.mates}
    assert model.motion_links[0].driven in {m.id for m in model.mates}


def test_face_sketch_support_is_frozen_before_support_body_deleted():
    from cadstudio.models import Extrusion
    from cadstudio.native.saved_sketches import sketch_frame
    raw=Design(parts=[Part(id='base',name='support',geometry={'kind':'plate','hole_count':0},transform={'x':50,'rz':45})],sketches=[dict(id='s',name='face',geometry=Extrusion(),context=dict(part_id='base',face=dict(index=0,planar=True,origin=[0,0,5],normal=[0,0,1],x_direction=[1,0,0],face_count=6)))]).model_dump()
    before=Design.model_validate(raw);expected=sketch_frame(before,before.sketches[0]);after=Design.model_validate(delete_parts(raw,['base']))
    actual=sketch_frame(after,after.sketches[0]);assert np.array(actual)==pytest.approx(np.array(expected))
    assert not after.sketches[0].context.part_id


def test_imported_asset_ids_and_profile_sketch_ids_are_independent():
    import cadquery as cq
    from cadstudio.imported import encode_shape
    from cadstudio.models import Extrusion
    asset=encode_shape(cq.Workplane().box(10,12,14).val(),'import')
    raw=Design(parts=[Part(id='a',name='import',geometry=dict(kind='imported',asset_id='asset')),Part(id='b',name='profile',geometry=Extrusion(),profile_sketch_id='s')],sketches=[dict(id='s',geometry=Extrusion())],assets={'asset':asset}).model_dump()
    data,ids=paste_parts(None,part_clipboard(raw,['a','b']))
    model=Design.model_validate(data)
    assert model.parts[0].geometry.asset_id!='asset' and model.parts[0].geometry.asset_id in model.assets
    assert model.parts[1].profile_sketch_id!='s' and model.parts[1].profile_sketch_id==model.sketches[0].id
    assert preview(model)['stats']['volume']==pytest.approx(preview(Design.model_validate(raw))['stats']['volume'])
