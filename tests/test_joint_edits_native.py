from copy import deepcopy
import threading

import pytest
from PySide6.QtCore import Qt,QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QTreeWidgetItemIterator

from cadstudio.models import Design
from cadstudio.native.workflows import JointDriveDialog
from test_joint_edits import joint_design, linked_design
from test_placement_native import app,wait,dispose


def test_opening_joint_dialog_preserves_long_and_precise_original_position(app):
    raw=joint_design('slider',z=750.123456789).model_dump();before=deepcopy(raw)
    dialog=JointDriveDialog(None,raw,'hinge');dialog.show()
    try:
        wait(app,lambda:dialog.checked is not None)
        assert dialog.inputs[('hinge','z')].value()==pytest.approx(750.123457)
        assert dialog.candidate()==before
        assert dialog.checked.mates[0].z==750.123456789
        assert not dialog.apply_button.isEnabled()
        assert dialog.joint_filter.currentData()=='hinge'
        dialog.inputs[('hinge','z')].setValue(820.456789)
        wait(app,lambda:dialog.checked is not None)
        assert dialog.checked.mates[0].z==820.456789 and dialog.apply_button.isEnabled()
        assert raw==before and dialog.changed_axes=={('hinge','z')}
    finally:dispose(app,dialog)


def test_joint_motion_filter_and_driven_axis_preserve_other_values(app):
    current=linked_design();raw=current.model_dump();dialog=JointDriveDialog(None,raw,'hinge');dialog.resize(820,600);dialog.show()
    try:
        wait(app,lambda:dialog.checked is not None)
        assert dialog.groups['hinge'].isVisible() and not dialog.groups['follow'].isVisible()
        assert not dialog.inputs[('follow','rz')].isEnabled()
        dialog.inputs[('hinge','rz')].setValue(30.123456)
        wait(app,lambda:dialog.checked is not None)
        assert dialog.checked.mates[1].rz==pytest.approx(5-2*30.123456)
        assert dialog.candidate()['mates'][1]['rz']==raw['mates'][1]['rz']
        assert dialog.changed_axes=={('hinge','rz')}
        dialog.joint_filter.setCurrentIndex(0);app.processEvents()
        assert all(group.isVisible() for group in dialog.groups.values())
        assert dialog.apply_button.visibleRegion().contains(dialog.apply_button.rect())
    finally:dispose(app,dialog)


def test_narrow_joint_limits_keep_exact_spinbox_available_without_outside_slider_steps(app):
    raw=joint_design(rz=.025,limits={'rz':[.021,.029]}).model_dump()
    dialog=JointDriveDialog(None,raw);dialog.show()
    try:
        wait(app,lambda:dialog.checked is not None)
        assert not dialog.sliders[('hinge','rz')].isEnabled()
        assert dialog.candidate()['mates'][0]['rz']==.025
        dialog.inputs[('hinge','rz')].setValue(.026789)
        wait(app,lambda:dialog.checked is not None)
        assert dialog.checked.mates[0].rz==pytest.approx(.026789)
    finally:dispose(app,dialog)


def test_selected_joint_is_visible_in_ai_and_used_by_native_motion_dialog(app,monkeypatch,tmp_path):
    from cadstudio.native import window,local_ai
    from cadstudio.native.model_picker import LocalModelPicker
    monkeypatch.setattr(LocalModelPicker,'refresh',lambda self:None);monkeypatch.setattr(window,'DATA_DIR',tmp_path)
    w=window.MainWindow();w.resize(820,560);w.show();w.activateWindow();raw=linked_design().model_dump()
    entered=threading.Event();release=threading.Event();captured=[];errors=[];w.show_error=errors.append
    def fake(request,model,**kwargs):
        captured.append(request);entered.set();release.wait(5);kwargs['control'].check()
        return dict(design=request.current.model_dump(),summary='test',assumptions=[])
    monkeypatch.setattr(local_ai,'ollama_draft',fake)
    try:
        w.apply_design(raw,'assembly fixture');wait(app,lambda:not w.busy);before=deepcopy(w.document.design)
        it=QTreeWidgetItemIterator(w.tree);chosen=None
        while it.value():
            item=it.value();item.setExpanded(True);data=item.data(0,Qt.ItemDataRole.UserRole)
            if data==('mate','follow'):chosen=item
            it+=1
        assert chosen is not None;w.tree.setCurrentItem(chosen);app.processEvents()
        assert w.selected_joint=='follow' and w.selected_feature is None
        assert 'follow' in w.ai_target.text() and 'Follower' in w.ai_target.text()
        w.ai_dock.show();w.ai_dock.raise_();app.processEvents()
        assert w.ai_target.visibleRegion().contains(w.ai_target.rect())
        assert w.generate_button.visibleRegion().contains(w.generate_button.rect())
        w.provider.setCurrentIndex(w.provider.findData('ollama'));w.ollama_models.models.addItem('test','test')
        w.prompt.setPlainText('선택한 관절을 30도로');w.generate_draft();task=w.ai_task;assert entered.wait(3)
        assert captured[0].selected_joint=='follow'
        w.cancel_ai();release.set();task.thread.join(3);app.processEvents();assert w.document.design==before
        def execute(dialog):
            assert dialog.joint_filter.currentData()=='follow'
            dialog.joint_filter.setCurrentIndex(dialog.joint_filter.findData('hinge'))
            dialog.inputs[('hinge','rz')].setValue(30)
            wait(app,lambda:dialog.checked is not None);dialog.accept();return 1
        monkeypatch.setattr(JointDriveDialog,'exec',execute)
        w.drive_joints();wait(app,lambda:not w.busy)
        assert w.document.design['mates'][0]['rz']==30 and w.document.design['mates'][1]['rz']==-55
        assert w.document.journal.path()[-1]['context']['joint_values']==[dict(mate_id='hinge',axis='rz',value=30)]
        w.undo();wait(app,lambda:not w.busy);assert w.document.design==before
        assert w.selected_joint is None and 'follow' not in w.ai_target.text()
        assert not errors
    finally:
        release.set()
        if w.ai_task:w.cancel_ai()
        w.document.dirty=False;w.close();QThreadPool.globalInstance().waitForDone(10000);app.processEvents()
