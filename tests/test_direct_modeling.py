from ai_transport import cad_transport
from copy import deepcopy
import json,math,time
import pytest
import httpx
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QThreadPool,Qt
from PySide6.QtTest import QTest
from cadstudio.models import Design,Part,Extrusion,DraftRequest
from cadstudio.catalog import preset
from cadstudio.parameters import parameter_values,expression_value,set_binding
from cadstudio.sketch_engine import sketch_status
from cadstudio.kernel import preview,construct
from cadstudio.native import geometry as G
from cadstudio.native.document import Document,read_project


@pytest.fixture(scope='module')
def app():
    global _APP
    _APP=QApplication.instance() or QApplication([]);_APP.setQuitOnLastWindowClosed(False);yield _APP
    assert QThreadPool.globalInstance().waitForDone(15000)


def wait(app,fn):
    deadline=time.monotonic()+20
    while not fn() and time.monotonic()<deadline:app.processEvents();QTest.qWait(15)
    assert fn()


def circle():return Extrusion(sketch_mode='entities',entities=[dict(id='circle',kind='circle',center=dict(x=0,y=0),radius=5)])


def test_linked_dimensions_recompute_and_history_roundtrip(tmp_path):
    raw=preset('cylinder').model_dump();pid=raw['parts'][0]['id'];raw['parameters']={'두께':'5','폭':'두께*4'}
    set_binding(raw,['parts',pid,'geometry','diameter'],'폭');set_binding(raw,['parts',pid,'geometry','height'],'두께')
    first=Design.model_validate(raw);doc=Document();doc.commit(first,'변수 정의');raw['parameters']['두께']='7';second=Design.model_validate(raw);doc.commit(second,'변수 변경')
    assert second.parts[0].geometry.diameter==28 and second.parts[0].geometry.height==7
    assert preview(second)['stats']['volume']==pytest.approx(math.pi*14**2*7)
    path=tmp_path/'variables.cad.json';doc.write(path);loaded=read_project(path);assert loaded.design.parameters['두께']=='7'
    old=Design.model_validate(doc.journal.at(doc.journal.path()[0]['id']));assert old.parts[0].geometry.diameter==20
    raw['parameters']['폭']='두께/0'
    with pytest.raises(ValueError):Design.model_validate(raw)


def test_sketch_dimension_and_depth_expressions_follow_variables():
    g=circle().model_dump();g['entity_constraints']=[dict(id='dia',kind='diameter',a='circle',value=10,expression='폭')];g['thickness_expression']='두께*2'
    raw=dict(parts=[dict(id='p',name='원통',geometry=g)],parameters={'폭':'12','두께':'3'})
    d=Design.model_validate(raw);assert d.parts[0].geometry.entities[0].radius==pytest.approx(6);assert d.parts[0].geometry.thickness==6
    raw['parameters']['폭']='20';d=Design.model_validate(raw);assert construct(d.parts[0].geometry).Volume()==pytest.approx(math.pi*100*6)
    assert 'parameters' not in preset('cylinder').model_dump() and 'direction' not in Extrusion().model_dump()


@pytest.mark.parametrize('expression',["__import__('os').system('whoami')",'x.y','[1][0]','2**100','1/0','sqrt(-1)'])
def test_expression_language_rejects_unsafe_or_invalid_input(expression):
    with pytest.raises(ValueError):expression_value(expression)


def test_expression_units_dependencies_and_cycles():
    assert expression_value('2 cm + 5 mm')==25
    assert parameter_values({'길이':'폭*2','폭':'3'})=={'폭':3,'길이':6}
    with pytest.raises(ValueError,match='순환'):parameter_values({'a':'b','b':'a'})


def test_redundant_and_conflicting_constraints_are_distinct():
    g=circle().model_dump();g['entity_constraints']=[dict(id='radius',kind='radius',a='circle',value=5),dict(id='diameter',kind='diameter',a='circle',value=10)]
    status=sketch_status(Extrusion.model_validate(g));assert status['redundant_constraints']==['diameter'] and status['dof']==2
    g['entity_constraints'][1]['value']=15
    with pytest.raises(ValueError,match='구속 충돌.*radius.*diameter'):Extrusion.model_validate(g)
    # Two independent constraints of the same kind are not redundant.
    g=circle().model_dump();g['entities'].append(dict(id='other',kind='circle',center=dict(x=20,y=0),radius=4));g['entity_constraints']=[dict(id='r1',kind='radius',a='circle',value=5),dict(id='r2',kind='radius',a='other',value=4)]
    assert sketch_status(Extrusion.model_validate(g))['redundant_constraints']==[]


def test_free_placement_points_lines_closed_regions_then_constraints(app):
    from cadstudio.native.sketch import SketchEditor
    e=SketchEditor();e.resize(1040,720);e.show();e.start();e.free.setChecked(True)
    e.set_tool('point');e.input_point(G.pt(.1234,.5678));e.set_tool('line');e.input_point(G.pt(0,0));e.input_point(G.pt(7.123,0));e.finish_drawing()
    e.set_tool('rectangle');e.input_point(G.pt(20.17,21.19));e.input_point(G.pt(35.31,37.41));e.finish_drawing();wait(app,lambda:e.preview is not None)
    assert len(e.g['entities'])==6 and not e.g['entity_constraints'];assert len(e.preview['regions'])==1
    point=e.g['entities'][0];assert point['position']==G.pt(.1234,.5678)
    e.g['entity_constraints']=[dict(id='fix',kind='fixed',a=point['id'],a_point='start',x=0,y=0)];e.solve();wait(app,lambda:not e.solving);assert e.g['entities'][0]['position']['x']==pytest.approx(0,abs=1e-6)
    e.stop();e.close()


def test_auto_constraints_do_not_overconstrain_a_rectangle_at_origin(app):
    from cadstudio.native.sketch import SketchEditor
    e=SketchEditor();e.start();e.set_tool('rectangle');e.input_point(G.pt(0,0));e.input_point(G.pt(30,20));e.finish_drawing();wait(app,lambda:e.preview is not None)
    assert not e.constraint_status['redundant_constraints'] and e.constraint_status['dof']==2
    e.stop();e.close()


def test_3d_saved_profile_extrude_drag_reverse_and_filters(app):
    from cadstudio.native.extrude import ExtrudeDialog
    from cadstudio.native.viewport import CADViewport
    raw=Design(parts=[],sketches=[dict(id='s',geometry=circle().model_dump())]).model_dump();r=preview(Design.model_validate(raw));v=CADViewport();v.resize(900,620);v.show();v.load(r);app.processEvents()
    selected=[];v.profile_selected.connect(lambda *args:selected.append(args));v.set_view('top');actor=next(iter(v.profile_actors));v.renderer.SetWorldPoint(1,1,0,1);v.renderer.WorldToDisplay();x,y,_=v.renderer.GetDisplayPoint();v.pick(x,y);assert selected==[('s',0)]
    dlg=ExtrudeDialog(None,raw,raw['sketches'][0]['geometry'],dict(plane='XY'),0);dlg.show();wait(app,lambda:dlg.checked is not None)
    assert dlg.handle and dlg.checked.parts[0].geometry.thickness==8
    dlg.dragged(-12.5);wait(app,lambda:dlg.checked is not None);g=dlg.checked.parts[0].geometry;assert g.direction==-1 and g.thickness==12.5;assert construct(g).BoundingBox().zmin==pytest.approx(-12.5)
    # Dragging the actual screen-projected arrow changes depth, without a kernel call.
    handle=dlg.handle;handle.drag=(handle.display(handle.center),-12.5,handle.display(handle.center+handle.normal)-handle.display(handle.center),handle.pixel_scale());handle.move(handle.drag[0]+(30,40));handle.release();assert dlg.depth.value()!=12.5
    wait(app,lambda:dlg.checked is not None)
    v.load(dlg.result);v.set_selection_mode('point');assert v.pick_objects and all(len(ref[1]['points'])==1 for ref in v.pick_objects.values());v.set_selection_mode('edge');assert all('length' in ref[1] for ref in v.pick_objects.values());v.set_selection_mode('face');assert not v.pick_objects
    dlg.reject();v.shutdown();v.close();wait(app,lambda:not dlg.running)


def test_face_profile_cut_and_existing_feature_depth(app):
    from cadstudio.native.extrude import ExtrudeDialog
    d=preset('plate');d.parts[0].geometry.hole_count=0;raw=d.model_dump();mesh=preview(d)['meshes'][0];face=next(f for f in mesh['faces'] if f['planar'] and f['normal'][2]>.99);ctx=dict(part_id=d.parts[0].id,face=face,support_feature='base',operation='cut')
    dlg=ExtrudeDialog(None,raw,circle().model_dump(),ctx,0);dlg.show();wait(app,lambda:dlg.checked is not None);assert dlg.checked.parts[0].features[-1].operation=='cut';assert dlg.result['stats']['volume']<preview(d)['stats']['volume'];result=dlg.checked.model_dump();fid=dlg.feature_id;dlg.reject()
    ctx['feature_id']=fid;dlg=ExtrudeDialog(None,result,result['parts'][0]['features'][-1]['sketch'],ctx,0);dlg.show();dlg.depth.setValue(2);wait(app,lambda:dlg.checked is not None);assert len(dlg.checked.parts[0].features)==1 and dlg.checked.parts[0].features[0].sketch.thickness==2;dlg.reject()


def test_ai_context_omits_only_display_caches_restores_them_and_honors_deadline():
    from cadstudio.native.local_ai import ollama_context,ollama_draft
    d=preset('plate');face=next(f for f in preview(d)['meshes'][0]['faces'] if f['planar']);raw=d.model_dump();raw['sketches']=[dict(id='s',geometry=circle().model_dump(),context=dict(part_id=d.parts[0].id,face=face))];d=Design.model_validate(raw)
    compact=ollama_context(d);assert 'outline' not in compact['sketches'][0]['context']['face']
    def handle(request):
        assert request.extensions['timeout']['read']==900
        from cadstudio.native.cad_tools import context
        assert json.loads(json.loads(request.content)['messages'][1]['content'])['current_design']==context(d)
        return httpx.Response(200,json=dict(done=True,message=dict(content=json.dumps(dict(summary='색상',actions=[dict(tool='appearance',target=d.parts[0].id,args=dict(color='#112233'))])))))
    result=ollama_draft(DraftRequest(prompt='색상 변경',current=d),'test',cad_transport(handle),deadline=900)
    assert result['design']['sketches'][0]['context']['face']['outline']==face['outline']
    from cadstudio.native.local_ai import restore_sketch_display
    changed=Design.model_validate(compact);changed.parts[0].geometry.width+=1;restore_sketch_display(changed,d)
    assert changed.sketches[0].context.face.outline==[]


def test_main_window_extrusion_commit_and_parameter_preserving_copy(app,monkeypatch,tmp_path):
    import cadstudio.native.window as module
    from cadstudio.native.extrude import ExtrudeDialog
    from PySide6.QtWidgets import QDialog
    monkeypatch.setattr(module,'DATA_DIR',tmp_path)
    def accept_checked(dialog):
        dialog.show();wait(app,lambda:dialog.checked is not None);dialog.accept();return QDialog.DialogCode.Accepted
    monkeypatch.setattr(ExtrudeDialog,'exec',accept_checked)
    w=module.MainWindow(restore=False);w.show();raw=Design(parts=[],sketches=[dict(id='s',geometry=circle().model_dump(),context=dict(operation='add'))]).model_dump();w.apply_design(raw,'스케치');wait(app,lambda:not w.busy);w.select_profile_3d('s',0);w.extrude_dialog();wait(app,lambda:not w.busy)
    assert len(w.document.design['parts'])==1 and w.document.journal.path()[-1]['context']['tool']=='extrude-3d'
    raw=deepcopy(w.document.design);pid=raw['parts'][0]['id'];raw['parameters']={'height':'15'};set_binding(raw,['parts',pid,'geometry','thickness'],'height');w.apply_design(raw,'변수 연결');wait(app,lambda:not w.busy)
    w.extrude_dialog();wait(app,lambda:not w.busy);assert w.document.design['parts'][0]['geometry']['thickness_expression']=='height'
    # Scalar primitive dimensions copy stable-ID bindings with the new part.
    raw=preset('cylinder').model_dump();pid=raw['parts'][0]['id'];raw['parameters']={'d':'20'};set_binding(raw,['parts',pid,'geometry','diameter'],'d');w.apply_design(raw,'치수 연결');wait(app,lambda:not w.busy);w.select_part(pid);w.duplicate_part();wait(app,lambda:not w.busy);assert len(w.document.design['dimension_bindings'])==2
    w.delete_part();wait(app,lambda:not w.busy);assert len(w.document.design['dimension_bindings'])==1
    w.document.dirty=False;w.close()
