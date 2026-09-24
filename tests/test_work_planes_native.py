from copy import deepcopy
import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QPushButton
from cadstudio.models import Design
from cadstudio.native.work_plane import WorkPlaneDialog
from cadstudio.native.extrude import ExtrudeDialog
from test_placement_native import app,wait,dispose
from test_work_planes import assembly,profile


def test_plane_dialog_previews_grid_and_preserves_original_precision(app):
    raw=Design().model_dump();before=deepcopy(raw)
    plane=dict(plane='XZ',offset=23.123456789,placement=dict(x=12.123456789,rx=15.123456789))
    d=WorkPlaneDialog(None,raw,plane);d.resize(820,600);d.show()
    try:
        wait(app,lambda:d.checked is not None)
        checked,design=d.checked
        assert checked.offset==plane['offset'] and checked.placement.x==plane['placement']['x']
        assert checked.placement.rx==plane['placement']['rx']
        assert design.model_dump()==before and d.result['sketches'][-1]['id']=='work-plane-preview'
        assert d.apply_button.visibleRegion().contains(d.apply_button.rect())
        d.offset.setValue(40);wait(app,lambda:d.checked is not None)
        assert d.checked[0].offset==40 and d.checked[0].placement.x==plane['placement']['x']
    finally:dispose(app,d)
    assert raw==before


def test_bound_plane_edit_cannot_be_applied_in_native_preview(app):
    from cadstudio.parameters import set_binding
    raw=assembly();raw['parameters']={'pos':'0'};set_binding(raw,['parts',0,'transform','z'],'pos')
    d=WorkPlaneDialog(None,raw,sketch_id='s');d.show()
    try:
        d.offset.setValue(20);wait(app,lambda:not d.running and not d.timer.isActive())
        assert d.checked is None and not d.apply_button.isEnabled() and '변수' in d.status.text()
    finally:dispose(app,d)


def test_native_create_finish_extrude_edit_plane_and_undo(app,monkeypatch,tmp_path):
    from cadstudio.native import window
    from cadstudio.native.model_picker import LocalModelPicker
    monkeypatch.setattr(window,'DATA_DIR',tmp_path);monkeypatch.setattr(LocalModelPicker,'refresh',lambda self:None)
    w=window.MainWindow();w.show();errors=[];w.show_error=errors.append
    try:
        def choose(d):
            d.offset.setValue(30);d.fields['rx'].setValue(90);d.show();wait(app,lambda:d.checked is not None)
            d.accept();return 1
        monkeypatch.setattr(WorkPlaneDialog,'exec',choose)
        w.plane.setCurrentIndex(w.plane.findData('custom'));w.start_sketch('custom')
        assert w.sketching and w.document.design is None
        context=deepcopy(w.editor.context);assert context['work_plane']['offset']==30
        from cadstudio.native.geometry import to_entities
        w.finish_sketch(to_entities(profile()),context,'add');wait(app,lambda:not w.busy)
        assert not w.sketching and len(w.document.design['parts'])==0
        sketch_id=w.document.design['sketches'][0]['id']
        def extrude(d):
            d.depth.setExpression('8');d.show();wait(app,lambda:d.checked is not None)
            assert d.result['sketches'][0]['origin']==pytest.approx([0,0,30])
            assert d.result['sketches'][0]['normal']==pytest.approx([0,-1,0],abs=1e-8)
            d.accept();return 1
        monkeypatch.setattr(ExtrudeDialog,'exec',extrude)
        w.extrude_dialog(sketch_id=sketch_id);wait(app,lambda:not w.busy)
        assert w.result['stats']['volume']==pytest.approx(1600)
        before=deepcopy(w.document.design)
        def relocate(d):
            d.offset.setValue(50);wait(app,lambda:d.checked is not None);d.accept();return 1
        monkeypatch.setattr(WorkPlaneDialog,'exec',relocate)
        w.select_sketch(sketch_id)
        control=next(b for b in w.properties.findChildren(QPushButton) if b.text()=='작업 평면 · 위치 / 각도 편집');control.click();wait(app,lambda:not w.busy)
        assert w.document.design['parts'][0]['transform']['z']==pytest.approx(50)
        assert w.document.design['parts'][0]['geometry']==before['parts'][0]['geometry']
        after=deepcopy(w.document.design);w.undo();wait(app,lambda:not w.busy);assert w.document.design==before
        w.redo();wait(app,lambda:not w.busy);assert w.document.design==after
        w.select_sketch(sketch_id)
        reuse=next(b for b in w.properties.findChildren(QPushButton) if b.text()=='같은 평면에 새 스케치');reuse.click()
        assert w.sketching and 'sketch_id' not in w.editor.context and w.editor.context['work_plane']['offset']==50
        w.cancel_sketch();assert not errors
    finally:
        if w.sketching:w.cancel_sketch()
        w.document.dirty=False;w.close();QThreadPool.globalInstance().waitForDone(10000);app.processEvents()
