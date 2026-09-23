from copy import deepcopy
import math
import time
import pytest
from PySide6.QtCore import Qt,QEvent,QThreadPool
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication,QPushButton
from PySide6.QtTest import QTest
from cadstudio.models import Extrusion,Design
from cadstudio.catalog import preset
from cadstudio.kernel import construct,preview
from cadstudio.sketch_engine import sketch_preview
from cadstudio.native import geometry as G
from cadstudio.native.profile_groups import group_regions
from cadstudio.native.document import Document,read_project
from cadstudio.native.sketch import SketchEditor


@pytest.fixture(scope='module')
def app():
    global _APP
    _APP=QApplication.instance() or QApplication([]);_APP.setQuitOnLastWindowClosed(False);yield _APP
    assert QThreadPool.globalInstance().waitForDone(10000)


def wait(app,fn):
    deadline=time.monotonic()+15
    while not fn() and time.monotonic()<deadline:app.processEvents();QTest.qWait(10)
    assert fn()


def grouped():
    entities=[G.circle(G.pt(-10,0),3),G.circle(G.pt(10,0),3)]
    return Extrusion(sketch_mode='entities',entities=entities,groups=[dict(id='holes',name='양쪽 구멍',entity_ids=[e['id'] for e in entities])],profiles=[0,1],thickness=5)


def test_groups_preserve_voids_and_disconnected_islands():
    g=Extrusion(sketch_mode='entities',entities=[G.circle(G.pt(0,0),10),G.circle(G.pt(0,0),3)])
    indices=group_regions(sketch_preview(g)['regions'],[e.id for e in g.entities]);assert indices==[0]
    g.profiles=indices;assert construct(g).Volume()==pytest.approx(math.pi*(100-9)*8)
    g=grouped();assert group_regions(sketch_preview(g)['regions'],g.groups[0].entity_ids)==[0,1]
    assert construct(g).Volume()==pytest.approx(2*math.pi*9*5)


def test_group_history_save_reopen_and_membership_validation(tmp_path):
    d=Document();g=grouped();raw=dict(name='그룹',parts=[],sketches=[dict(id='s1',geometry=g.model_dump())]);d.commit(Design.model_validate(raw),'그룹 만들기')
    raw['sketches'][0]['geometry']['groups'][0]['name']='새 그룹 이름';d.commit(Design.model_validate(raw),'그룹 이름 변경');path=tmp_path/'group.cad.json';d.write(path)
    loaded=read_project(path);assert loaded.design.sketches[0].geometry.groups[0].name=='새 그룹 이름'
    assert len(loaded.history.entries)==2
    raw['sketches'][0]['geometry']['groups'][0]['entity_ids']=['missing']
    with pytest.raises(ValueError,match='그룹'):Design.model_validate(raw)
    assert 'groups' not in Extrusion().model_dump()


def test_hover_recommends_regions_ctrl_click_and_group_undo(app):
    w=SketchEditor();w.resize(1000,680);w.show();w.start(grouped().model_dump());wait(app,lambda:w.preview is not None);w.canvas.fit();w.set_profiles([0]);app.processEvents()
    pos=w.canvas.screen(G.pt(10,0));app.sendEvent(w.canvas,QMouseEvent(QEvent.Type.MouseMove,pos,w.canvas.mapToGlobal(pos),Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier))
    assert w.canvas.hover_region==1
    # Click inside both circles away from their selectable centers.
    for x,modifier in [(-9,Qt.KeyboardModifier.NoModifier),(11,Qt.KeyboardModifier.ControlModifier)]:
        QTest.mouseClick(w.canvas,Qt.MouseButton.LeftButton,modifier,w.canvas.screen(G.pt(x,1)).toPoint())
    assert w.g['profiles']==[0,1]
    w.create_group('두 구멍');wait(app,lambda:w.preview is not None);assert len(w.g['groups'])==2
    w.use_group('add');assert w.g['profiles']==[0,1] and w.tabs.currentIndex()==3
    w.ungroup();assert len(w.g['groups'])==1;w.undo();assert len(w.g['groups'])==2
    w.stop();QThreadPool.globalInstance().waitForDone(5000);w.close()


def test_saved_group_reused_as_add_and_cut_on_face_with_history(app,monkeypatch,tmp_path):
    import cadstudio.native.window as module
    monkeypatch.setattr(module,'DATA_DIR',tmp_path)
    w=module.MainWindow(restore=False);w.show();d=preset('plate');d.parts[0].geometry.hole_count=0
    raw=d.model_dump();raw['sketches']=[dict(id='source',name='구멍 블록',geometry=grouped().model_dump())];w.apply_design(raw,'시작');wait(app,lambda:not w.busy)
    original=w.result['stats']['volume'];identifier=w.selected
    assert w.findChild(QPushButton,'partColorButton') is not None and w.actions['color'] in w.toolbar.actions()
    for operation in ('cut','add'):
        face=next(f for f in w.result['meshes'][0]['faces'] if f['planar'] and f['normal'][2]>.99 and f['origin'][2]==pytest.approx(d.parts[0].geometry.thickness))
        w.viewport.face=(identifier,face);w.reuse_sketch_on_face('source');wait(app,lambda:w.editor.preview is not None)
        e=w.editor;e.groups.setCurrentIndex(e.groups.findData('holes'))
        if operation=='add':
            e.use_group();e.mod.setCurrentIndex(e.mod.findData('move'));e.dx.setValue(0);e.dy.setValue(15);e.modify();wait(app,lambda:e.preview is not None)
        e.use_group(operation);e.depth.setValue(2);e.finish();wait(app,lambda:not w.busy)
        assert not w.sketching and any(s['id']=='source' for s in w.document.design['sketches']), (operation,e.status.text())
        expected=original-2*math.pi*9*2 if operation=='cut' else original
        # Reuse the same group at a different location for two connected bosses.
        assert w.result['stats']['volume']==pytest.approx(expected,rel=1e-6)
    path=tmp_path/'reuse.cad.json';w.document.write(path);loaded=read_project(path);assert len(loaded.design.parts[0].features)==2
    assert loaded.history.entries[-1].context['source_sketch_id']=='source'
    w.document.dirty=False;w.close();app.processEvents()
