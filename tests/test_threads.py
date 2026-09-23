from copy import deepcopy
import math,time
import cadquery as cq
import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from cadstudio.models import Design,Part,ThreadFeature
from cadstudio.kernel import local_shape,preview,export,construct
from cadstudio.threads import cylinder_records,apply_thread,DEPTH_FACTOR
from cadstudio.parameters import set_binding
from cadstudio.native.document import Document,read_project


def threaded(internal=False,**settings):
    design=Design(parts=[Part(id='shaft',name='shaft',geometry=dict(kind='cylinder',diameter=12 if internal else 10,height=16,bore_diameter=5 if internal else 0))])
    part=design.parts[0];shape=local_shape(design,part)
    ref=next(r for r in cylinder_records(shape) if r.internal==internal)
    feature=ThreadFeature(id='thread',cylinder=ref,diameter=6 if internal else 10,pitch=1 if internal else 1.5,length=8,**settings)
    part.features.append(feature)
    return design,shape,feature


@pytest.mark.parametrize('internal',[False,True])
@pytest.mark.parametrize('handedness',['right','left'])
def test_real_threads_are_valid_cut_solids_and_clip_to_length(internal,handedness):
    d,base,f=threaded(internal,handedness=handedness,offset=2)
    shape=local_shape(d,d.parts[0]);assert shape.isValid() and len(shape.Solids())==1
    assert 0<shape.Volume()<base.Volume()
    removed=base.cut(shape);bb=removed.BoundingBox()
    assert bb.zmin==pytest.approx(2,abs=1e-4) and bb.zmax==pytest.approx(10,abs=1e-4)
    # A thread varies axially with angle; annular grooves fail this check.
    radial=f.diameter/2-DEPTH_FACTOR*f.pitch/2
    inside=[shape.isInside((radial,0,2+i*f.pitch/24)) for i in range(24)]
    assert any(inside) and not all(inside)


def test_handedness_reverses_helical_phase():
    right,_,f=threaded();left,_,_=threaded(handedness='left')
    a=local_shape(right,right.parts[0]);b=local_shape(left,left.parts[0]);r=f.diameter/2-DEPTH_FACTOR*f.pitch/2
    states=[(a.isInside((0,r,z)),b.isInside((0,r,z))) for z in (.13,.38,.63,.88,1.13,1.38)]
    assert any(x!=y for x,y in states)
    assert a.Volume()==pytest.approx(b.Volume(),rel=1e-4)


def test_reversed_end_and_arbitrary_local_axis():
    d,base,f=threaded(reverse=True,offset=1)
    cut=base.cut(local_shape(d,d.parts[0])).BoundingBox()
    assert cut.zmin==pytest.approx(7,abs=1e-4) and cut.zmax==pytest.approx(15,abs=1e-4)
    # Apply the same operation to a cylinder built along X, away from origin.
    source=cq.Solid.makeCylinder(5,16,cq.Vector(3,7,-2),cq.Vector(1,0,0));ref=cylinder_records(source)[0]
    feature=ThreadFeature(id='t',cylinder=ref,diameter=10,pitch=1.5,length=8,offset=2)
    removed=source.cut(apply_thread(source,feature)).BoundingBox()
    assert removed.xmin==pytest.approx(5,abs=1e-4) and removed.xmax==pytest.approx(13,abs=1e-4)


@pytest.mark.parametrize('internal',[False,True])
def test_clearance_removes_more_material(internal):
    d,_,_=threaded(internal);loose,_,_=threaded(internal,clearance=.1)
    assert local_shape(loose,loose.parts[0]).Volume()<local_shape(d,d.parts[0]).Volume()


def test_reference_staleness_rejected():
    d,_,_=threaded();d.parts[0].geometry.height=18
    with pytest.raises(ValueError,match='원통'):local_shape(d,d.parts[0])


def test_matching_bolt_and_tap_have_no_material_interference():
    shaft=cq.Solid.makeCylinder(3,4)
    nut=cq.Workplane('XY').circle(6).circle(2.5).extrude(4).val()
    a=ThreadFeature(id='a',cylinder=cylinder_records(shaft)[0],diameter=6,pitch=1,length=4,clearance=.02)
    b=ThreadFeature(id='b',cylinder=next(r for r in cylinder_records(nut) if r.internal),diameter=6,pitch=1,length=4,clearance=.02)
    assert apply_thread(shaft,a).intersect(apply_thread(nut,b)).Volume()<1e-5


@pytest.mark.parametrize('diameter,pitch,turns',[(2,.4,6),(5,.8,6),(12,1.75,6),(20,2.5,6),(48,5,6),(6,1,32)])
@pytest.mark.parametrize('internal',[False,True])
def test_small_large_and_maximum_length_threads(diameter,pitch,turns,internal):
    length=pitch*turns
    base=cq.Workplane('XY').circle(diameter if internal else diameter/2)
    if internal:base=base.circle(round(diameter-2*DEPTH_FACTOR*pitch,3)/2)
    shape=base.extrude(length).val();ref=next(r for r in cylinder_records(shape) if r.internal==internal)
    feature=ThreadFeature(id='t',cylinder=ref,diameter=diameter,pitch=pitch,length=length,clearance=.03)
    result=apply_thread(shape,feature)
    assert result.isValid() and len(result.Solids())==1 and result.Volume()<shape.Volume()


@pytest.mark.parametrize('patch',[{'length':.5},{'length':16,'offset':1},{'pitch':.25,'length':12},{'clearance':.9},{'diameter':11}])
def test_invalid_thread_inputs_rejected(patch):
    _,_,f=threaded();raw=f.model_dump();raw.update(patch)
    with pytest.raises(ValueError):ThreadFeature.model_validate(raw)


def test_hole_size_mismatch_rejected():
    _,_,f=threaded(True);raw=f.model_dump();raw['diameter']=10
    with pytest.raises(ValueError,match='바탕'):ThreadFeature.model_validate(raw)


def test_roundtrip_exact_export_history_and_parameters(tmp_path):
    d,base,f=threaded();doc=Document();plain=d.model_copy(deep=True);plain.parts[0].features=[];doc.commit(plain,'축')
    doc.commit(d,'나사산',{'feature':f.model_dump()});path=tmp_path/'thread.cad.json';doc.write(path)
    reopened=read_project(path).design;shape=local_shape(reopened,reopened.parts[0])
    assert reopened.parts[0].features[0]==f
    assert not Design.model_validate(doc.journal.at(doc.journal.path()[0]['id'])).parts[0].features
    export(reopened,tmp_path/'thread.step','step');imported=cq.importers.importStep(str(tmp_path/'thread.step')).val()
    # Reimported spline surfaces use different adaptive volume integration.
    assert imported.isValid() and imported.Volume(1e-9)==pytest.approx(shape.Volume(1e-9),rel=1e-6)
    export(reopened,tmp_path/'thread.stl','stl');assert (tmp_path/'thread.stl').stat().st_size>1000
    raw=d.model_dump();raw['parameters']={'길이':'6'};set_binding(raw,['parts','shaft','features','thread','length'],'길이')
    changed=Design.model_validate(raw);assert changed.parts[0].features[0].length==6
    assert local_shape(changed,changed.parts[0]).Volume()>shape.Volume()
    assert preview(changed)['meshes'][0]['valid']


@pytest.fixture(scope='module')
def app():
    global _APP
    _APP=QApplication.instance() or QApplication([]);_APP.setQuitOnLastWindowClosed(False);yield _APP
    assert QThreadPool.globalInstance().waitForDone(30000)


def wait(app,predicate):
    end=time.monotonic()+30
    while not predicate() and time.monotonic()<end:app.processEvents();QTest.qWait(15)
    assert predicate()


def test_native_dialog_picking_editing_validation_and_cancel(app):
    from cadstudio.native.threading_tool import ThreadDialog
    d,_,f=threaded();d.parts[0].features=[]
    dialog=ThreadDialog(None,d.model_dump(),'shaft');dialog.show()
    try:
        wait(app,lambda:dialog.checked is not None)
        assert dialog.refs and dialog.checked.parts[0].features[0].kind=='thread'
        dialog.fields['length'].setValue(100);wait(app,lambda:not dialog.running and not dialog.timer.isActive())
        assert dialog.checked is None and not dialog.apply_button.isEnabled()
        dialog.fields['length'].setValue(6);wait(app,lambda:dialog.checked is not None)
        result=dialog.checked.model_dump();fid=dialog.feature_id
    finally:dialog.reject()
    result['parameters']={'ねじ':'7'};set_binding(result,['parts','shaft','features',fid,'length'],'ねじ')
    dialog=ThreadDialog(None,result,'shaft',fid);dialog.show()
    try:
        wait(app,lambda:dialog.checked is not None)
        assert dialog.fields['length'].expression()=='ねじ' and len(dialog.checked.parts[0].features)==1
        dialog.hand.setCurrentIndex(1);wait(app,lambda:dialog.checked is not None)
        assert dialog.checked.parts[0].features[0].handedness=='left'
    finally:dialog.reject()
    dialog=ThreadDialog(None,result,'shaft',fid);dialog.reject()
    wait(app,lambda:not dialog.running);assert not dialog.alive
