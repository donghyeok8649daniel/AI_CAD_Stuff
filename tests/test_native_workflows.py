from copy import deepcopy
import math
import numpy as np
import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from cadstudio.models import Design,Part
from cadstudio.catalog import preset
from cadstudio.kernel import preview
from cadstudio.constraints import transform_matrix
from cadstudio.native.workflows import (SpecimenDialog,RobotDialog,JointDriveDialog,FaceJointDialog,frame_record)
from cadstudio.native.document import Document,read_project
from cadstudio.native.widgets import apply_theme


@pytest.fixture(scope='module')
def app():
    app=QApplication.instance() or QApplication([]);apply_theme(app)
    yield app
    QThreadPool.globalInstance().waitForDone();app.processEvents()


def wait_dialog(dialog):
    for _ in range(300):
        QApplication.processEvents()
        if not dialog.running and not dialog.timer.isActive():break
        QTest.qWait(20)
    assert not dialog.running and not dialog.timer.isActive(),dialog.status.text()


def two_parts():
    return Design(parts=[Part(id='base',name='base',geometry={'kind':'cylinder','diameter':30,'height':10},fixed=True),Part(id='child',name='child',geometry={'kind':'plate','length':20,'width':16,'thickness':4,'hole_count':0},transform={'x':80})])


def face_pair(design):
    result=preview(design)
    first=next(f for f in result['meshes'][0]['faces'] if f['planar'] and f['normal'][2]>.99)
    second=next(f for f in result['meshes'][1]['faces'] if f['planar'] and f['normal'][2]<-.99)
    return ('base',first),('child',second)


def test_actual_face_joint_axes_and_parameter_change_follow_face(app,tmp_path):
    base=two_parts();first,second=face_pair(base);dialog=FaceJointDialog(None,base.model_dump(),first,second)
    try:
        dialog.timer.stop();dialog.angle.setValue(35);dialog.gap.setValue(2);raw=dialog.candidate();d=Design.model_validate(raw);r=preview(d);child=d.parts[1];assert child.transform.z==pytest.approx(12);assert child.transform.rz==pytest.approx(35)
        binding=d.joint_frames[0];pa=transform_matrix(d.parts[0].transform)@np.array(binding.parent.origin)+[0,0,0];ca=transform_matrix(child.transform)@np.array(binding.child.origin)+[child.transform.x,child.transform.y,child.transform.z];assert ca-pa==pytest.approx([0,0,2])
        doc=Document();doc.commit(d,'face joint');raw=d.model_dump();raw['parts'][0]['geometry']['height']=25;changed=Design.model_validate(raw);preview(changed);assert changed.parts[1].transform.z==pytest.approx(27);doc.commit(changed,'base height');path=tmp_path/'joint.cad.json';doc.write(path);assert read_project(path).design.parts[1].transform.z==pytest.approx(27)
    finally:dialog.reject()


def test_joint_frame_normals_follow_rotated_parent(app):
    d=two_parts();first,second=face_pair(d);raw=d.model_dump();raw['parts'][0]['transform'].update(x=10,y=20,z=30,rx=50,ry=20,rz=35);dialog=FaceJointDialog(None,raw,first,second)
    try:
        candidate=Design.model_validate(dialog.candidate());preview(candidate);binding=candidate.joint_frames[0];parent,child=candidate.parts;pr=transform_matrix(parent.transform);cr=transform_matrix(child.transform);assert cr@binding.child.normal==pytest.approx(-(pr@binding.parent.normal),abs=1e-7)
        pp=pr@binding.parent.origin+np.array([parent.transform.x,parent.transform.y,parent.transform.z]);cp=cr@binding.child.origin+np.array([child.transform.x,child.transform.y,child.transform.z]);assert cp==pytest.approx(pp,abs=1e-7)
    finally:dialog.reject()


def test_robot_dimensions_recompute_pins_and_preserve_other_parts(app):
    raw=preset('robot_arm').model_dump();raw['parts'].append(Part(id='other',name='other',geometry={'kind':'cylinder'},transform={'x':250}).model_dump());dialog=RobotDialog(None,raw)
    try:
        dialog.inputs['l1'].setValue(140);dialog.inputs['l2'].setValue(90);dialog.inputs['thickness'].setValue(10);dialog.inputs['gap'].setValue(2);d=Design.model_validate(dialog.candidate());r=preview(d);parts={p.id:p for p in d.parts};assert len(d.parts)==6 and parts['other'].transform.x==250;assert parts['link-1'].geometry.hole_spacing==140;assert parts['pin-2'].geometry.height==22
        p=parts['link-1'];rotation=transform_matrix(p.transform);anchor=rotation@np.array([70,0,0])+[p.transform.x,p.transform.y,p.transform.z];pin=parts['pin-2'];assert [pin.transform.x,pin.transform.y,pin.transform.z]==pytest.approx(anchor)
    finally:dialog.reject()


def test_joint_drive_moves_descendants_and_keeps_input_design_unchanged(app):
    raw=preset('robot_arm').model_dump();before=deepcopy(raw);dialog=JointDriveDialog(None,raw)
    try:
        dialog.inputs[('shoulder','rz')].setValue(80);dialog.inputs[('elbow','rz')].setValue(-20);d=Design.model_validate(dialog.candidate());preview(d);parts={p.id:p for p in d.parts};assert parts['link-1'].transform.rz==pytest.approx(80);assert parts['link-2'].transform.rz==pytest.approx(60);assert parts['pin-2'].transform.x==pytest.approx(94*math.cos(math.radians(80)));assert raw==before
    finally:dialog.reject()


def test_specimen_preview_refuses_invalid_dimensions_then_recovers(app):
    dialog=SpecimenDialog(None)
    try:
        dialog.show();dialog.inputs['gauge_diameter'].setValue(25);wait_dialog(dialog);assert dialog.checked is None and not dialog.apply_button.isEnabled()
        dialog.inputs['gauge_diameter'].setValue(7);dialog.inputs['gauge_length'].setValue(35);wait_dialog(dialog);assert dialog.checked is not None and dialog.apply_button.isEnabled();assert dialog.checked.parts[0].geometry.gauge_diameter==7;assert 'mm²' in dialog.metrics.text()
    finally:dialog.reject();QThreadPool.globalInstance().waitForDone();app.processEvents()
