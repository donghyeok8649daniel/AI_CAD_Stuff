from copy import deepcopy
import time
import numpy as np
import pytest
from PySide6.QtCore import Qt,QThreadPool,QEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from cadstudio.catalog import preset
from cadstudio.models import Extrusion,Design
from cadstudio.kernel import preview,build
from cadstudio.sketch_engine import sketch_status,sketch_preview
from cadstudio.native.geometry import line,pt,circle
from cadstudio.native.sketch import SketchEditor
from cadstudio.native.modelling import ModellingDialog,EdgeFinishDialog,ClosureDialog
from cadstudio.native.inspect_tools import HoleDialog,MeasurementDialog
from cadstudio.native.studies import RobotStudy,TensileStudy,DrawingDialog
from cadstudio.native.picking import infer
from cadstudio.mechanisms import four_bar


@pytest.fixture(scope='module')
def app():
    global _APP
    _APP=QApplication.instance() or QApplication([]);app=_APP;app.setQuitOnLastWindowClosed(False);yield app
    assert QThreadPool.globalInstance().waitForDone(10000)
    app.processEvents()


def close(app,w):
    if isinstance(w,SketchEditor):w.stop();w.close()
    else:w.reject()
    QThreadPool.globalInstance().waitForDone();app.processEvents();w.deleteLater();app.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()


def wait(app,condition):
    deadline=time.monotonic()+30
    while not condition() and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
    assert condition()


def test_entity_color_comes_from_solver_nullspace(app):
    a=line(pt(0,0),pt(20,0));b=circle(pt(40,20),5)
    cons=[dict(id='origin',kind='fixed',a=a['id'],a_point='start',x=0,y=0),dict(id='horizontal',kind='horizontal',a=a['id']),dict(id='length',kind='distance',a=a['id'],a_point='start',b=a['id'],b_point='end',value=20)]
    g=Extrusion(sketch_mode='entities',entities=[a,b],entity_constraints=cons);status=sketch_status(g)
    assert status['entity_dof'][a['id']]==0 and status['entity_dof'][b['id']]==3
    w=SketchEditor();w.start(g.model_dump());w.solve_timer.stop();w.constraint_status=status
    assert w.entity_state(a['id'])=='constrained' and w.entity_state(b['id'])=='free';close(app,w)


def test_line_selection_prepares_closed_profile_extrusion(app):
    es=[line(pt(-20,-10),pt(20,-10)),line(pt(20,-10),pt(20,10)),line(pt(20,10),pt(-20,10)),line(pt(-20,10),pt(-20,-10))]
    g=Extrusion(sketch_mode='entities',entities=es);w=SketchEditor();w.start(g.model_dump());w.solve_timer.stop();w.preview=sketch_preview(g);w.regions.addItem('영역',0);w.resize(1000,680);w.show();app.processEvents();w.canvas.fit();w.solve_timer.stop()
    QTest.mouseClick(w.canvas,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,w.canvas.screen(pt(5,-10)).toPoint());QTest.keyClick(w.canvas,Qt.Key.Key_E)
    assert w.tabs.currentIndex()==3 and w.g['profiles']==[0]
    close(app,w)


def test_grid_curve_and_grid_point_snap():
    a=line(pt(0,3),pt(30,18));samples={a['id']:[[a['start'],a['end']]]}
    hit=infer(pt(10.1,8.2),[a],samples,[],1,10)
    assert hit['type']=='격자·곡선 교점' and hit['p']==pytest.approx(pt(10,8))
    assert infer(pt(30.1,30.2),[],{},[],1,10)['p']==pt(30,30)
    assert infer(pt(30.1,30.2),[],{},[],1) is None


@pytest.mark.parametrize('kind',['sweep','loft'])
def test_modelling_preview_and_edit(app,kind):
    w=ModellingDialog(None,None,kind);w.show();wait(app,lambda:w.checked is not None)
    first=w.checked;assert build(first)[0].Solids();raw=first.model_dump();close(app,w)
    w=ModellingDialog(None,raw,kind,part_id=raw['parts'][0]['id']);w.timer.stop();assert w.candidate()['parts'][0]['geometry']==raw['parts'][0]['geometry'];close(app,w)


def test_edge_finish_and_hole_actual_geometry(app):
    d=preset('plate');d.parts[0].geometry.hole_count=0;raw=d.model_dump();w=EdgeFinishDialog(None,raw,d.parts[0].id);w.timer.stop();w.toggle_edge(0);w.timer.stop();candidate=Design.model_validate(w.candidate());assert build(candidate)[0].Volume()<build(d)[0].Volume();close(app,w)
    face=next(f for f in preview(d)['meshes'][0]['faces'] if f['planar'] and f['normal'][2]>.99);w=HoleDialog(None,raw,d.parts[0].id,face);w.timer.stop();w.diameter.setValue(10);w.through.setChecked(True);w.timer.stop();shape=build(Design.model_validate(w.candidate()))[0]
    assert build(d)[0].Volume()-shape.Volume()==pytest.approx(np.pi*25*d.parts[0].geometry.thickness,rel=1e-6);close(app,w)


def test_closure_dialog_roundtrip(app):
    d=four_bar();w=ClosureDialog(None,d.model_dump(),d.loops[0].id);w.timer.stop();checked=Design.model_validate(w.candidate());assert checked.loops[0].passive_joints==d.loops[0].passive_joints;close(app,w)


def test_measurement_uses_exact_cad_coordinates(app):
    d=preset('cylinder');w=MeasurementDialog(None,d.model_dump());w.mode.setCurrentIndex(1);w.pick(0);assert 'mm' in w.output.text();assert w.edges[0]['length']>0;close(app,w)


@pytest.mark.parametrize('cls,kind',[(RobotStudy,'robot_arm'),(TensileStudy,'flat_specimen'),(DrawingDialog,'plate')])
def test_native_studies_calculate_render_and_save(app,cls,kind):
    d=preset(kind);w=cls(None,d.model_dump());w.show();w.calculate();wait(app,lambda:not w.running)
    assert w.checked is not None,w.status.text()
    assert not w.grab().isNull()
    if cls is DrawingDialog:assert w.svg_widget.renderer().isValid()
    if cls is RobotStudy:w.slider.setValue(150);assert w.viewport.actors['link-2'][0].GetUserMatrix() is not None
    w.accept();assert Design.model_validate(w.candidate).studies[-1].kind==w.kind
    close(app,w)


def test_model_picker_async_discovery_preserves_selection(app,monkeypatch):
    import cadstudio.native.model_picker as module
    monkeypatch.setattr(module,'discover_models',lambda:['another:model','qwen3:8b'])
    w=module.LocalModelPicker();w.refresh();wait(app,lambda:not w.running);assert w.model_name()=='qwen3:8b'
    w.models.setCurrentIndex(0);w.refresh();wait(app,lambda:not w.running);assert w.model_name()=='another:model'
    monkeypatch.setattr(module,'discover_models',lambda:[]);w.refresh();wait(app,lambda:not w.running);assert not w.model_name();w.deleteLater();app.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def test_fit_dialog_tracks_selected_diameter(app):
    from cadstudio.native.fit_dialog import FitDialog
    d=preset('cylinder');w=FitDialog(None,d.model_dump());assert not w.inputs['shaft_nominal'].isEnabled();assert w.output['shaft']['nominal']==30
    w.inputs['shaft_lower'].setValue(.1);assert not w.save_button.isEnabled();w.inputs['shaft_lower'].setValue(-.02);w.accept();assert Design.model_validate(w.candidate).studies[-1].kind=='fit';close(app,w)


def test_interference_view_contains_exact_overlap(app):
    from cadstudio.native.inspect_tools import interference_data,InterferenceDialog
    d=preset('cylinder');p=d.parts[0].model_copy(deep=True);p.id='other';p.transform.z=10;d.parts.append(p)
    result,overlaps=interference_data(d.model_dump());assert len(overlaps)==1;assert overlaps[0]['volume']==pytest.approx(np.pi*15**2*10)
    w=InterferenceDialog(None,result,overlaps);assert w.list.count()==1 and w.highlights[0].GetVisibility();close(app,w)
