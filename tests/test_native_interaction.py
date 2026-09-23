"""Regress the actual Qt clicks that v2.0's numeric-input smoke missed."""
from copy import deepcopy
import math
import pytest
from PySide6.QtCore import Qt, QThreadPool, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from cadstudio.native.sketch import SketchEditor
from cadstudio.native.widgets import apply_theme
from cadstudio.native import geometry as G
from cadstudio.native.picking import infer, nearest_curve
from cadstudio.models import Extrusion, Design
from cadstudio.native.document import Document, read_project
from cadstudio.kernel import preview, export


@pytest.fixture(scope='module')
def app():
    app=QApplication.instance() or QApplication([])
    app.setStyle('Fusion');apply_theme(app)
    yield app
    QThreadPool.globalInstance().waitForDone();app.processEvents()


@pytest.fixture
def editor(app):
    e=SketchEditor();e.start();e.solve_timer.stop();e.resize(1000,680);e.show();app.processEvents();e.solve_timer.stop()
    yield e
    e.solve_timer.stop();QThreadPool.globalInstance().waitForDone();app.processEvents();e.solve_timer.stop();e.close();e.deleteLater();app.processEvents()


def load(e,entities):
    e.start(Extrusion(sketch_mode='entities',entities=entities).model_dump(),context={'face':None});e.solve_timer.stop();e.canvas.fit();e.set_tool('select')


def click(e,p,mod=Qt.KeyboardModifier.NoModifier):
    QTest.mouseClick(e.canvas,Qt.MouseButton.LeftButton,mod,e.canvas.screen(p).toPoint())


@pytest.mark.parametrize('size',[(820,560),(1024,600),(1280,720),(1600,900)])
def test_finish_always_visible_at_small_window_sizes(editor,app,size):
    editor.resize(*size);app.processEvents()
    b=editor.finish_button
    assert b.isVisible() and b.isEnabled()
    assert editor.rect().contains(b.mapTo(editor,b.rect().topLeft()))
    assert editor.rect().contains(b.mapTo(editor,b.rect().bottomRight()))
    assert editor.size().width() <= size[0]
    assert editor.size().height() <= size[1]
    assert editor.canvas.width()>=280 and editor.canvas.height()>=180


def test_click_endpoints_retains_exact_anchor_and_two_points_on_same_line(editor):
    line=G.line(G.pt(-25,-10),G.pt(30,15));load(editor,[line])
    click(editor,line['end'])
    assert editor.ca.currentData()==line['id'] and editor.ap.currentData()=='end'
    editor.refresh()
    assert editor.ap.currentData()=='end'
    click(editor,line['start'],Qt.KeyboardModifier.ControlModifier)
    assert editor.ca.currentData()==editor.cb.currentData()==line['id']
    assert editor.ap.currentData()=='end' and editor.bp.currentData()=='start'
    editor.quick_dimension()
    assert editor.value.value()==pytest.approx(math.dist([-25,-10],[30,15]),abs=1e-5)
    assert 'mm' in editor.selection_label.text()


def test_hover_projects_point_and_auto_constraint_survives_solve(editor):
    line=G.line(G.pt(-30,-10),G.pt(30,20));load(editor,[line]);editor.grid_snapping.setChecked(False);editor.set_tool('point')
    target=G.at(line,.27);near=editor.canvas.screen(target)+QPointF(1,3)
    # Deliver to our test widget directly. QTest.mouseMove uses the desktop
    # cursor on Windows and may instead hit an unrelated foreground window.
    QApplication.sendEvent(editor.canvas,QMouseEvent(QEvent.Type.MouseMove,near,editor.canvas.mapToGlobal(near),Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier))
    assert editor.canvas.hover and editor.canvas.hover[0]['id']==line['id']
    assert editor.canvas.snap and editor.canvas.snap['type']=='선 위'
    QTest.mouseClick(editor.canvas,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,near.toPoint())
    point=next(e for e in editor.g['entities'] if e['kind']=='point')
    assert any(c['kind']=='point_on' and c['a']==point['id'] and c['b']==line['id'] for c in editor.g['entity_constraints'])
    solved=Extrusion.model_validate(editor.g)
    p=next(e for e in solved.entities if e.kind=='point').position
    assert abs((p.y+10)*60-(p.x+30)*30)<1e-5


def test_hover_prioritizes_endpoint_midpoint_intersection_and_origin(editor):
    a=G.line(G.pt(-20,10),G.pt(20,10));b=G.line(G.pt(7,-20),G.pt(7,30));load(editor,[a,b])
    for p,kind in [(a['end'],'끝점'),(G.pt(0,10),'중간점'),(G.pt(7,10),'교점'),(G.pt(0,0),'원점')]:
        editor.canvas.world(editor.canvas.screen(p)+QPointF(1,1),True)
        assert editor.canvas.snap['type']==kind
        assert G.dist(editor.canvas.snap['p'],p)<1e-7


def test_snap_toggle_and_leave_remove_recommendation(editor):
    line=G.line(G.pt(-20,10),G.pt(20,10));load(editor,[line]);editor.snapping.setChecked(False)
    editor.canvas.world(editor.canvas.screen(line['end']),True)
    assert editor.canvas.snap is None
    editor.canvas.leaveEvent(None)
    assert editor.canvas.hover is None and editor.canvas.cursor is None


def test_finish_open_line_emits_save_instead_of_extrusion(editor):
    load(editor,[G.line(G.pt(0,0),G.pt(20,5))]);saved=[];extruded=[]
    editor.finished_requested.connect(lambda *args:saved.append(args));editor.apply_requested.connect(lambda *args:extruded.append(args))
    QTest.mouseClick(editor.finish_button,Qt.MouseButton.LeftButton)
    assert len(saved)==1 and not extruded
    assert len(saved[0][0]['entities'])==1


def test_dimension_units_and_click_fixed_endpoint(editor):
    line=G.line(G.pt(-10,10),G.pt(20,15));load(editor,[line]);click(editor,line['end']);editor.origin_constraint()
    constraint=editor.g['entity_constraints'][-1]
    assert constraint['a_point']=='end' and constraint['x']==constraint['y']==0
    for w in [editor.x,editor.y,editor.depth,editor.dx,editor.dy,editor.amount,editor.text_size]:assert w.suffix()==' mm'
    assert editor.degrees.suffix()==' °'
    assert all(w.suffix()==' mm' for _,w,kind in editor.property_inputs if kind=='number')
    editor.kind.setCurrentIndex(editor.kind.findData('angle'));assert editor.value.suffix()==' °'
    editor.kind.setCurrentIndex(editor.kind.findData('distance'));assert editor.value.suffix()==' mm'


def test_ctrl_a_and_delete_are_undoable(editor):
    load(editor,[G.line(G.pt(-20,-10),G.pt(20,-10)),G.circle(G.pt(0,15),5)])
    QTest.keyClick(editor.canvas,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier)
    assert len(editor.selected)==2
    QTest.keyClick(editor.canvas,Qt.Key.Key_Delete);assert not editor.g['entities']
    QTest.keyClick(editor.canvas,Qt.Key.Key_Z,Qt.KeyboardModifier.ControlModifier);assert len(editor.g['entities'])==2


def test_saved_open_sketch_preview_project_and_history(tmp_path):
    g=Extrusion(sketch_mode='entities',entities=[G.line(G.pt(0,0),G.pt(20,10))])
    d=Design(sketches=[dict(id='sketch-1',geometry=g,context={'plane':'XZ'})])
    r=preview(d);assert r['stats']['parts']==0 and r['stats']['valid']
    assert r['stats']['max']==pytest.approx([20,0,10])
    doc=Document();doc.commit(d,'open sketch');raw=d.model_dump();raw['sketches'][0]['geometry']['entities'][0]['end']['x']=30
    doc.commit(Design.model_validate(raw),'edit endpoint');path=tmp_path/'open.cad.json';doc.write(path)
    loaded=read_project(path);assert len(loaded.history.entries)==2 and loaded.design.sketches[0].geometry.entities[0].end.x==30
    with pytest.raises(ValueError,match='입체 형상'):export(d,tmp_path/'empty.step','step')


def test_curve_projection_is_exact():
    circle=G.circle(G.pt(5,3),10);q=nearest_curve(circle,G.pt(14,8),[]);assert G.dist(q,circle['center'])==pytest.approx(10)
    arc=G.arc(G.pt(0,0),10,0,90);q=nearest_curve(arc,G.pt(-11,1),[]);assert G.dist(q,G.pt(0,10))<1e-7
    ellipse=G.entity('ellipse',center=G.pt(0,0),radius_x=20,radius_y=10,rotation=0);q=nearest_curve(ellipse,G.pt(14,8),[]);assert (q['x']/20)**2+(q['y']/10)**2==pytest.approx(1)


def test_local_command_can_add_first_solid_without_losing_open_sketch():
    from cadstudio.planner import local_draft
    from cadstudio.models import DraftRequest
    g=Extrusion(sketch_mode='entities',entities=[G.line(G.pt(0,0),G.pt(20,10))])
    d=Design(sketches=[dict(id='s',geometry=g)])
    result=local_draft(DraftRequest(prompt='원통 직경 30 높이 20',current=d))
    assert len(result['design']['parts'])==1 and len(result['design']['sketches'])==1


def test_single_line_dimension_references_survive_solver_refresh(editor):
    line=G.line(G.pt(-20,5),G.pt(30,5));load(editor,[line]);click(editor,G.pt(-5,5));editor.quick_dimension();editor.refresh()
    assert editor.ca.currentData()==editor.cb.currentData()==line['id']
    assert editor.ap.currentData()=='start' and editor.bp.currentData()=='end'
    editor.value.setValue(65);editor.add_constraint();solved=Extrusion.model_validate(editor.g)
    raw=solved.entities[0].model_dump();assert G.dist(raw['start'],raw['end'])==pytest.approx(65,abs=1e-5)
