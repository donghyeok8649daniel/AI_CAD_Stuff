import time
from copy import deepcopy
import pytest
from PySide6.QtCore import QThreadPool,QEvent,Qt
from PySide6.QtWidgets import QApplication
from cadstudio.models import Design,Part,SolidFeature
from cadstudio.catalog import preset
from cadstudio.constraints import solve_assembly
from cadstudio.assembly_motion import prune_joint_references
from cadstudio.mechanisms import four_bar
from cadstudio.kernel import build,preview
from cadstudio.native.solid_dialog import SolidDialog,RevolveDialog
from cadstudio.native.feature_manager import FeatureManager
from cadstudio.native.motion_dialog import MotionDialog


def assembly(kind='revolute'):
    parts=[Part(id=i,name=i,fixed=i=='a',geometry={'kind':'cylinder','diameter':10,'height':5}) for i in 'abc']
    return Design(parts=parts,mates=[dict(id='ab',kind=kind,parent='a',child='b',z=10),dict(id='bc',kind=kind,parent='b',child='c',z=10)])


@pytest.mark.parametrize('kind,dof',[('pin_slot',4),('planar',6),('ball',6)])
def test_additional_joints_pose_and_dof(kind,dof):
    d=assembly(kind);assert solve_assembly(d)['dof']==dof
    assert d.parts[2].transform.z==20


def test_motion_link_and_limits_propagate_and_reject_cycles():
    raw=assembly().model_dump();raw['mates'][0]['rz']=20
    raw['mates'][1]['limits']={'rz':[-90,90]}
    raw['motion_links']=[dict(id='gear',driver='ab',driven='bc',ratio=-2,offset=5)]
    d=Design.model_validate(raw);assert d.mates[1].rz==-35 and solve_assembly(d)['dof']==1
    assert d.parts[2].transform.rz==pytest.approx(-15)
    raw['mates'][0]['rz']=50
    with pytest.raises(ValueError,match='운동 한계'):Design.model_validate(raw)
    raw['mates'][0]['rz']=20;raw['motion_links'].append(dict(id='cycle',driver='bc',driven='ab'))
    with pytest.raises(ValueError,match='순환'):Design.model_validate(raw)
    raw['mates']=raw['mates'][:1];prune_joint_references(raw);assert raw['motion_links']==[]
    Design.model_validate(raw)


def test_closed_loop_honors_passive_limits():
    d=four_bar();raw=d.model_dump()
    for m in raw['mates'][1:]:m['limits']={'rz':[m['rz']-2,m['rz']+2]}
    assert solve_assembly(Design.model_validate(raw))['closure_error_mm']<1e-4
    raw['mates'][0]['rz']+=30
    with pytest.raises(ValueError):Design.model_validate(raw)


@pytest.fixture(scope='module')
def app():
    global _APP
    _APP=QApplication.instance() or QApplication([]);_APP.setQuitOnLastWindowClosed(False)
    yield _APP
    assert QThreadPool.globalInstance().waitForDone(30000)


def wait(app,predicate):
    end=time.monotonic()+30
    while not predicate() and time.monotonic()<end:app.processEvents();time.sleep(.01)
    assert predicate()


def close(app,w):
    w.reject();assert QThreadPool.globalInstance().waitForDone(30000);app.processEvents();w.deleteLater();app.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()


def test_native_revolve_and_solid_selection_preview(app):
    w=RevolveDialog(None,Design().model_dump());w.show();wait(app,lambda:w.checked is not None);assert build(w.checked)[0].Volume()>0;close(app,w)
    d=preset('plate');d.parts[0].geometry.hole_count=0;raw=d.model_dump();face=next(f for f in preview(d)['meshes'][0]['faces'] if f['planar'] and f['normal'][2]>.9)
    w=SolidDialog(None,raw,d.parts[0].id,face=face);w.show();wait(app,lambda:w.checked is not None)
    assert build(w.checked)[0].Volume()<build(d)[0].Volume();candidate=w.checked.model_dump();close(app,w)
    w=FeatureManager(None,candidate,d.parts[0].id);w.show();wait(app,lambda:w.checked is not None);w.list.item(0).setCheckState(Qt.CheckState.Unchecked);wait(app,lambda:w.checked is not None)
    assert build(w.checked)[0].Volume()==pytest.approx(build(d)[0].Volume());close(app,w)
    # Reopening a feature must use its geometric reference, not a stale face index.
    candidate['parts'][0]['features'][0]['faces'][0]['index']=0
    w=SolidDialog(None,candidate,d.parts[0].id,feature_id=candidate['parts'][0]['features'][0]['id']);w.show();wait(app,lambda:w.checked is not None)
    assert w.faces.selectedItems()[0].data(Qt.ItemDataRole.UserRole)==face['index']
    assert build(w.checked)[0].Volume()==pytest.approx(build(Design.model_validate(candidate))[0].Volume());close(app,w)


def test_native_motion_dialog_and_empty_assembly(app):
    w=MotionDialog(None,Design().model_dump());w.show();wait(app,lambda:w.checked is not None);close(app,w)
    raw=assembly().model_dump();raw['mates'][0]['rz']=15;w=MotionDialog(None,raw);w.show();w.ratio.setValue(-2);w.add_link();wait(app,lambda:w.checked is not None)
    assert w.checked.mates[1].rz==-30
    check,low,high=w.limit_fields['rz'];check.setChecked(True);low.setValue(-10);high.setValue(10)
    wait(app,lambda:not w.running and not w.timer.isActive());assert w.checked is None and not w.apply_button.isEnabled();close(app,w)


def test_inspection_material_and_configuration_dialogs(app):
    from cadstudio.native.inspection_dialog import InspectionDialog,MaterialDialog
    from cadstudio.native.configuration_dialog import ConfigurationDialog
    raw=assembly().model_dump();w=MaterialDialog(None,raw,'a');w.show();wait(app,lambda:w.checked is not None);raw=w.checked.model_dump();close(app,w)
    w=InspectionDialog(None,raw,'a');w.show();wait(app,lambda:w.checked is not None)
    assert 'mm' in w.output.text();w.mode.setCurrentIndex(w.mode.findData('mass'));wait(app,lambda:w.checked is not None);assert 'kg' in w.output.text()
    w.mode.setCurrentIndex(w.mode.findData('section'));w.origin[2].setValue(2);wait(app,lambda:w.checked is not None);assert '단면적' in w.output.text();close(app,w)
    raw['parameters']={'diameter':'10'};raw['dimension_bindings']=[dict(path=['parts','a','geometry','diameter'],expression='diameter')];raw['configurations']={'small':{'diameter':'10'},'large':{'diameter':'25'}}
    w=ConfigurationDialog(None,raw);w.show();w.selector.setCurrentIndex(w.selector.findData('large'));wait(app,lambda:w.checked is not None);assert w.checked.parts[0].geometry.diameter==25;close(app,w)


def test_sheetmetal_dialog_and_hole_finish_editor(app):
    from cadstudio.native.sheetmetal_dialog import SheetMetalDialog
    from cadstudio.native.inspect_tools import HoleDialog
    from cadstudio.native.extrude import ExtrudeDialog
    w=SheetMetalDialog(None,Design().model_dump());w.show();wait(app,lambda:w.checked is not None);assert '전개 길이' in w.summary.text();w.flat.setChecked(True);wait(app,lambda:w.checked is not None);assert w.checked.parts[0].geometry.flat;close(app,w)
    d=preset('plate');d.parts[0].geometry.hole_count=0;face=next(f for f in preview(d)['meshes'][0]['faces'] if f['planar'] and f['normal'][2]>.9);w=HoleDialog(None,d.model_dump(),d.parts[0].id,face);w.through.setChecked(True);w.style.setCurrentIndex(w.style.findData('counterbore'));w.show();wait(app,lambda:w.checked is not None);raw=w.checked.model_dump();feature=raw['parts'][0]['features'][0];close(app,w)
    w=ExtrudeDialog(None,raw,feature['sketch'],dict(part_id=d.parts[0].id,feature_id=feature['id'],operation='cut',face=face,support_feature='base'));w.show();wait(app,lambda:w.checked is not None);assert w.hole_style.currentData()=='counterbore';close(app,w)
