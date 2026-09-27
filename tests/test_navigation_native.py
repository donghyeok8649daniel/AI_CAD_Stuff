from copy import deepcopy
import numpy as np
import pytest
from PySide6.QtCore import Qt,QPoint,QThreadPool
from PySide6.QtTest import QTest
from test_placement_native import app,wait,dispose
from cadstudio.models import Design,Part
from cadstudio.native.joint_hardware_dialog import JointHardwareDialog


def click_vtk(view,point):
    scale=view.widget.devicePixelRatioF();height=view.window.GetSize()[1]
    pos=QPoint(round(point[0]/scale),round((height-1-point[1])/scale))
    QTest.mouseClick(view.widget,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,pos);return pos


def test_group_exit_and_xyz_mouse_navigation(app,monkeypatch,tmp_path):
    from cadstudio.native import window
    from cadstudio.native.model_picker import LocalModelPicker
    monkeypatch.setattr(LocalModelPicker,'refresh',lambda self:None);monkeypatch.setattr(window,'DATA_DIR',tmp_path)
    w=window.MainWindow();w.resize(1100,760);w.show();w.activateWindow()
    raw=Design(parts=[Part(id='a',name='A',geometry=dict(kind='cylinder')),Part(id='b',name='B',geometry=dict(kind='cylinder'),transform=dict(x=60))],part_groups=[dict(id='g',name='AB',part_ids=['a','b'])]).model_dump()
    try:
        w.apply_design(raw,'fixture');wait(app,lambda:not w.busy)
        before=deepcopy(w.document.design);w.select_clicked_parts(['a']);assert len(w.selected_parts)==2
        w.actions['group_select'].trigger();assert not w.selected_parts and len(w.document.design['part_groups'])==1
        w.select_clicked_parts(['a']);assert w.selected_parts==['a']
        w.actions['isolate'].trigger();assert w.viewport.hidden=={'b'}
        w.actions['isolate'].trigger();assert not w.viewport.hidden
        w.viewport.visibility('b',False);w.actions['isolate'].trigger();w.actions['isolate'].trigger();assert w.viewport.hidden=={'b'}
        w.show_all_parts();assert not w.viewport.hidden
        w.actions['box_select'].trigger();w.viewport.widget.setFocus();QTest.keyClick(w.viewport.widget,Qt.Key.Key_Escape);app.processEvents()
        assert not w.selected_parts and w.viewport.orbit_mode and not w.viewport.box_mode
        assert w.actions['orbit'].isChecked() and not w.actions['box_select'].isChecked()
        v=w.viewport;camera=v.renderer.GetActiveCamera();v.set_view('iso');scale=camera.GetParallelScale();focus=camera.GetFocalPoint()
        for axis,index in [('x',0),('y',1),('z',2)]:
            v.set_view('iso');app.processEvents();points=v.axis_points();pos=points['origin']*.15+points[axis]*.85
            assert v.axis_at(pos)==axis
            click_vtk(v,pos);app.processEvents();direction=np.array(camera.GetPosition())-camera.GetFocalPoint();direction/=np.linalg.norm(direction)
            assert direction==pytest.approx(np.eye(3)[index],abs=1e-5)
            assert camera.GetFocalPoint()==pytest.approx(focus) and camera.GetParallelScale()==pytest.approx(scale)
            click_vtk(v,v.axis_points()['origin']);app.processEvents();direction=np.array(camera.GetPosition())-camera.GetFocalPoint();direction/=np.linalg.norm(direction)
            assert direction==pytest.approx(-np.eye(3)[index],abs=1e-5)
        v.set_view('iso');app.processEvents();points=v.axis_points();start=points['origin']*.2+points['x']*.8
        scale_px=v.widget.devicePixelRatioF();p=QPoint(round(start[0]/scale_px),round((v.window.GetSize()[1]-1-start[1])/scale_px));old=camera.GetPosition()
        QTest.mousePress(v.widget,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,p);QTest.mouseMove(v.widget,p+QPoint(18,12),20);QTest.mouseRelease(v.widget,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,p+QPoint(18,12));app.processEvents()
        assert camera.GetPosition()!=old and not w.selected_parts
        assert w.document.design==before
        w.actions['orbit'].trigger();assert not v.orbit_mode
        w.actions['box_select'].trigger();assert v.box_mode
    finally:w.document.dirty=False;w.close();QThreadPool.globalInstance().waitForDone(10000);app.processEvents()


def test_hardware_preview_dimensions_apply_visibility_and_cancel(app):
    raw=Design(parts=[]).model_dump();before=deepcopy(raw);d=JointHardwareDialog(None,raw);d.resize(850,620);d.show()
    try:
        wait(app,lambda:d.checked is not None);assert len(d.part_ids)==7 and not d.result['stats']['collisions']
        assert d.apply_button.isEnabled() and d.apply_button.visibleRegion().contains(d.apply_button.rect())
        d.inputs['shaft_diameter'].setValue(24);assert not d.apply_button.isEnabled()
        wait(app,lambda:d.checked is not None);assert next(p for p in d.checked.parts if p.name=='회전 축').geometry.diameter==24
        assert raw==before
    finally:dispose(app,d)


def test_exploded_dialog_restores_view_only(app):
    from cadstudio.joint_hardware import add_revolute_hardware
    from cadstudio.kernel import preview
    from cadstudio.native.part_inspection import ExplodedViewDialog
    model,_=add_revolute_hardware();result=preview(model);before=deepcopy(result)
    dialog=ExplodedViewDialog(None,result);dialog.show();app.processEvents()
    try:
        assert dialog.viewport.widget.isVisible() and dialog.viewport.widget.height()>150
        assert dialog.viewport.orbit_mode and not dialog.viewport.filter.isEnabled()
        dialog.distance.setValue(0);app.processEvents();assert dialog.viewport.result['stats']['bounds']==pytest.approx(result['stats']['bounds'])
        dialog.axis.setCurrentIndex(0);dialog.distance.setValue(50);app.processEvents();assert dialog.viewport.result['stats']['bounds'][0]>result['stats']['bounds'][0]+100
        assert result==before
    finally:dispose(app,dialog)
