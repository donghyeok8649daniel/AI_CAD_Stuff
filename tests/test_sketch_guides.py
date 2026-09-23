import json,math,time
import numpy as np
import pytest
from PySide6.QtCore import QThreadPool,Qt,QPointF
from PySide6.QtWidgets import QApplication,QTreeWidgetItem
from PySide6.QtTest import QTest
from cadstudio.native import geometry as G
from cadstudio.native.picking import infer
from cadstudio.native.sketch_guides import contact_candidates,line_inference
from cadstudio.models import Extrusion,EntityConstraint,Design,Part
from cadstudio.sketch_engine import values,curve,solve_entities,constraint_residual


def samples(es):return {e['id']:[[G.at(e,t/64) for t in range(65)]] for e in es}


def test_empty_grid_crossing_does_not_hide_a_curve_point():
    line=G.line(G.pt(-20,.2),G.pt(20,.2));s=infer(G.pt(3.04,.22),[line],samples([line]),[],.5,1)
    assert s['type']!='격자 교점' and s['p']['y']==pytest.approx(.2)


@pytest.mark.parametrize('kind',['circle','arc','ellipse','spline'])
def test_tangent_and_normal_recommendations_are_on_exact_curves(kind):
    e=G.circle(G.pt(0,0),10) if kind=='circle' else G.arc(G.pt(0,0),10,-160,320) if kind=='arc' else G.entity('ellipse',center=G.pt(0,0),radius_x=10,radius_y=5,rotation=0) if kind=='ellipse' else G.entity('spline',points=[G.pt(-10,0),G.pt(0,8),G.pt(10,0)],style='fit',closed=False)
    es=Extrusion(sketch_mode='entities',entities=[e]).model_dump()['entities'];e=es[0];start=G.pt(20,3)
    candidates=contact_candidates(json.dumps(es,sort_keys=True),20,3)
    assert candidates
    for snap in candidates:
        line=G.line(start,snap['p']);line['id']='created'
        c=EntityConstraint(id='guide',kind=snap['constraint'],a=line['id'],a_point='end',b=e['id'])
        assert np.max(np.abs(constraint_residual(c,{e['id']:e,line['id']:line})))<1e-5
        found=line_inference(snap['p'],start,es,samples(es),.01,snap['constraint'])
        assert found and found['constraint']==snap['constraint']


def test_normal_is_solved_against_a_fixed_circle():
    circle=G.circle(G.pt(0,0),10);line=G.line(G.pt(23,5),G.pt(9,3))
    g=Extrusion(sketch_mode='entities',entities=[circle,line]);cs=[EntityConstraint(id='fixed',kind='fixed',a=circle['id'],a_point='all',reference=values(circle)),EntityConstraint(id='start',kind='fixed',a=line['id'],a_point='start',x=23,y=5),EntityConstraint(id='normal',kind='normal',a=line['id'],a_point='end',b=circle['id'])]
    solved,status=solve_entities(g.entities,cs);end=solved[1].end
    assert math.hypot(end.x,end.y)==pytest.approx(10,abs=1e-5)
    assert abs(end.x*5-end.y*23)<1e-4 and status['dof']==0
    assert not status['redundant_constraints']


def test_perpendicular_mode_recommends_a_parallel_offset_normal_direction():
    line=G.line(G.pt(-10,0),G.pt(10,0));start=G.pt(3,5)
    snap=line_inference(G.pt(3.01,15),start,[line],samples([line]),.1,'perpendicular')
    assert snap['constraint']=='perpendicular' and snap['p']==G.pt(3,15)


@pytest.fixture(scope='module')
def app():
    global _APP
    _APP=QApplication.instance() or QApplication([]);_APP.setQuitOnLastWindowClosed(False);yield _APP
    assert QThreadPool.globalInstance().waitForDone(20000)


@pytest.fixture
def editor(app):
    from cadstudio.native.sketch import SketchEditor
    e=SketchEditor();e.start();e.solve_timer.stop();e.resize(1040,700);e.show();app.processEvents();e.solve_timer.stop()
    yield e
    e.stop();QThreadPool.globalInstance().waitForDone(15000);app.processEvents();e.close()


def test_reference_face_intersection_is_suggested_and_persistently_constrained(editor):
    a=G.line(G.pt(-20,10),G.pt(20,10));b=G.line(G.pt(3,-20),G.pt(3,30));a['id']='edge-0';b['id']='edge-1'
    editor.start(context={'face':{'projected_entities':[a,b]}});editor.solve_timer.stop();editor.set_tool('point');editor.canvas.scale=20
    p=editor.canvas.world(editor.canvas.screen(G.pt(3,10))+QPointF(.1,.2))
    assert editor.canvas.snap['type']=='교점'
    editor.input_point(p);editor.solve_timer.stop();g=Extrusion.model_validate(editor.g)
    assert len(g.entities)==3 and len([e for e in g.entities if e.construction])==2
    assert len([c for c in g.entity_constraints if c.kind=='point_on'])==2
    assert len(editor.reference_entities())==0
    assert len(Extrusion.model_validate_json(g.model_dump_json()).entity_constraints)==4


def test_arc_midpoint_recommendation_and_constraint(editor):
    arc=G.arc(G.pt(5,8),10,20,120);editor.start(Extrusion(sketch_mode='entities',entities=[arc]).model_dump());editor.solve_timer.stop();editor.set_tool('point');editor.canvas.scale=20
    p=editor.canvas.world(editor.canvas.screen(G.at(arc,.5))+QPointF(.1,.1));assert editor.canvas.snap['type']=='중간점'
    editor.input_point(p);editor.solve_timer.stop();assert any(c['kind']=='midpoint' for c in editor.g['entity_constraints'])
    Extrusion.model_validate(editor.g)


def test_reference_circle_center_is_imported_and_constrained(editor):
    circle=G.circle(G.pt(7,11),9);circle['id']='edge-0'
    editor.start(context={'face':{'projected_entities':[circle]}});editor.solve_timer.stop();editor.set_tool('point');editor.canvas.scale=20
    p=editor.canvas.world(editor.canvas.screen(G.pt(7,11))+QPointF(.1,.1))
    assert editor.canvas.snap['type']=='중심점'
    editor.input_point(p);editor.solve_timer.stop();g=Extrusion.model_validate(editor.g)
    assert len(g.entities)==2 and g.entities[0].construction
    assert any(c.kind=='coincident' and c.b_point=='center' for c in g.entity_constraints)


@pytest.mark.parametrize('mode,end',[('parallel',G.pt(13,5)),('perpendicular',G.pt(3,15))])
def test_reference_direction_without_contact_imports_its_constraint_target(editor,mode,end):
    line=G.line(G.pt(-20,0),G.pt(20,0));line['id']='edge-0'
    editor.start(context={'face':{'projected_entities':[line]}});editor.solve_timer.stop();editor.set_tool('line');editor.canvas.scale=20;editor.grid_snapping.setChecked(False)
    editor.guide_mode.setCurrentIndex(editor.guide_mode.findData(mode));editor.input_point(G.pt(3,5))
    p=editor.canvas.world(editor.canvas.screen(end));assert editor.canvas.snap['constraint']==mode
    editor.input_point(p);editor.solve_timer.stop();g=Extrusion.model_validate(editor.g)
    assert len(g.entities)==2 and any(c.kind==mode and c.b=='ref-edge-0' for c in g.entity_constraints)
    _,status=solve_entities(g.entities,g.entity_constraints);assert not status['redundant_constraints']


@pytest.mark.parametrize('mode',['normal','tangent'])
def test_drawing_recommendation_adds_a_valid_persistent_relation(editor,mode):
    circle=G.circle(G.pt(0,0),10);editor.start(Extrusion(sketch_mode='entities',entities=[circle]).model_dump());editor.solve_timer.stop();editor.set_tool('line');editor.guide_mode.setCurrentIndex(editor.guide_mode.findData(mode));editor.grid_snapping.setChecked(False);editor.canvas.scale=20
    start=G.pt(23,5);editor.input_point(start)
    snap=next(s for s in contact_candidates(json.dumps(editor.g['entities'],sort_keys=True),23,5) if s['constraint']==mode)
    end=editor.canvas.world(editor.canvas.screen(snap['p']))
    assert editor.canvas.snap['constraint']==mode
    editor.input_point(end);editor.solve_timer.stop();g=Extrusion.model_validate(editor.g)
    assert any(c.kind==mode for c in g.entity_constraints)
    _,status=solve_entities(g.entities,g.entity_constraints);assert not status['redundant_constraints']
    editor.free.setChecked(True);editor.canvas.world(editor.canvas.screen(snap['p']));assert editor.canvas.snap is None


def test_quick_perpendicular_and_midpoint_controls(editor):
    a=G.line(G.pt(0,0),G.pt(10,0));b=G.line(G.pt(0,3),G.pt(0,12));editor.start(Extrusion(sketch_mode='entities',entities=[a,b]).model_dump());editor.solve_timer.stop()
    editor.select_reference(a['id'],None);editor.select_reference(b['id'],None,True);editor.refresh_selection();editor.quick_constraint('perpendicular');editor.solve_timer.stop()
    assert any(c['kind']=='perpendicular' for c in editor.g['entity_constraints'])
    assert {'접선','법선','중간점','직각'}.issubset({a.text() for a in editor.quick_constraints.menu().actions()})


def test_edit_toolbar_targets_selected_feature_not_base(app,tmp_path,monkeypatch):
    from cadstudio.native.window import MainWindow
    from cadstudio.native.document import Document
    from cadstudio.kernel import preview
    from cadstudio.native.inspect_tools import HoleDialog
    monkeypatch.setattr('cadstudio.native.window.DATA_DIR',tmp_path)
    w=MainWindow(restore=False);d=Design(parts=[Part(id='p',name='plate',geometry=dict(kind='plate',length=30,width=30,thickness=10,hole_count=0))]);result=preview(d);face=next(f for f in result['meshes'][0]['faces'] if f['planar'] and f['normal'][2]>.9)
    dialog=HoleDialog(None,d.model_dump(),'p',face);raw=dialog.candidate();dialog.reject();d=Design.model_validate(raw);w.document.commit(d,'hole');w.selected='p';w.rebuild_tree()
    node=QTreeWidgetItem(w.tree,['test']);node.setData(0,Qt.ItemDataRole.UserRole,('feature','p',d.parts[0].features[0].id));w.tree.setCurrentItem(node)
    captured=[];monkeypatch.setattr(w,'start_sketch',lambda **kwargs:captured.append(kwargs));w.edit_sketch()
    assert captured and captured[0]['context']['feature_id']==d.parts[0].features[0].id
    w.document.dirty=False;w.close()
