"""Native motion editing must preserve exact lead relations and history."""
from copy import deepcopy
import time
import pytest
from PySide6.QtCore import QEvent,QThreadPool,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QPushButton
from cadstudio.models import Design,Part
from cadstudio.native.document import Document,read_project
from cadstudio.native.motion_dialog import MotionDialog,MotionNumber


def fixture_design():
    return Design(parts=[Part(id=i,name=i,fixed=i=='base',geometry={'kind':'cylinder','diameter':5,'height':5}) for i in ['base','screw','crosshead']],
        mates=[dict(id='screw-rotation',kind='revolute',parent='base',child='screw',x=20),
               dict(id='crosshead-slider',kind='slider',parent='base',child='crosshead',x=40,z=219.7,limits={'z':[214.7,224.7]})],
        motion_links=[dict(id='screw-lead',driver='screw-rotation',driver_axis='rz',driven='crosshead-slider',driven_axis='z',ratio=5/360,offset=219.7)])


@pytest.fixture(scope='module')
def app():
    app=QApplication.instance() or QApplication([]);app.setQuitOnLastWindowClosed(False)
    yield app
    assert QThreadPool.globalInstance().waitForDone(30000)


def ready(app,dialog):
    end=time.monotonic()+30
    while (dialog.checked is None or dialog.running or dialog.timer.isActive()) and time.monotonic()<end:
        app.processEvents();time.sleep(.01)
    assert dialog.checked is not None and dialog.apply_button.isEnabled()


def click(dialog,text):
    target=next(w for w in dialog.findChildren(QPushButton) if w.text()==text)
    QTest.mouseClick(target,Qt.MouseButton.LeftButton)


def dispose(app,dialog):
    if dialog.alive:dialog.reject()
    assert QThreadPool.globalInstance().waitForDone(30000)
    dialog.deleteLater();app.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()


def test_unchanged_native_link_confirmation_keeps_precision_and_history(app):
    design=fixture_design();document=Document();document.commit(design,'fixture');before=deepcopy(document.journal.data)
    dialog=MotionDialog(None,design.model_dump());dialog.show();dialog.links.setCurrentRow(0)
    assert float(dialog.ratio.text())==5/360 and float(dialog.offset.text())==219.7
    click(dialog,'선택한 연결 수정');ready(app,dialog);click(dialog,'설계에 적용')
    document.commit(dialog.checked,'unchanged confirmation')
    assert document.design==design.model_dump() and document.journal.data==before
    for angle,z in [(-360,214.7),(360,224.7)]:
        raw=deepcopy(document.design);raw['mates'][0]['rz']=angle
        assert Design.model_validate(raw).mates[1].z==z
    dispose(app,dialog)


def test_cancel_keeps_original_link_and_document(app):
    design=fixture_design();document=Document();document.commit(design,'fixture');before=deepcopy(document.journal.data)
    dialog=MotionDialog(None,document.design);dialog.show();dialog.links.setCurrentRow(0)
    dialog.ratio.setText(repr(4/360));click(dialog,'선택한 연결 수정');ready(app,dialog);click(dialog,'취소')
    assert document.design==design.model_dump() and document.journal.data==before
    dispose(app,dialog)


@pytest.mark.parametrize('text',['','1e'])
def test_incomplete_limit_invalidates_ready_preview(app,text):
    dialog=MotionDialog(None,fixture_design().model_dump());dialog.show()
    dialog.joint.setCurrentIndex(dialog.joint.findData('crosshead-slider'));ready(app,dialog)
    revision=dialog.revision;dialog.limit_fields['z'][1].setText(text)
    assert dialog.revision>revision and dialog.checked is None and not dialog.apply_button.isEnabled()
    dialog.timer.stop();dialog.calculate()
    assert dialog.checked is None and not dialog.apply_button.isEnabled()
    dispose(app,dialog)


def test_incomplete_limit_discards_inflight_preview(app):
    import threading
    dialog=MotionDialog(None,fixture_design().model_dump());dialog.show()
    dialog.joint.setCurrentIndex(dialog.joint.findData('crosshead-slider'));dialog.timer.stop()
    started=threading.Event();release=threading.Event();compute=dialog.checked_compute
    def blocked(raw,revision):
        started.set();assert release.wait(10);return compute(raw,revision)
    dialog.checked_compute=blocked;dialog.calculate();assert started.wait(10)
    dialog.limit_fields['z'][1].setText('1e');release.set()
    end=time.monotonic()+20
    while (dialog.running or dialog.timer.isActive()) and time.monotonic()<end:app.processEvents();time.sleep(.01)
    assert not dialog.running and dialog.checked is None and not dialog.apply_button.isEnabled()
    dispose(app,dialog)


def test_invalid_limit_switch_restores_the_labeled_joint(app):
    dialog=MotionDialog(None,fixture_design().model_dump());dialog.show()
    dialog.joint.setCurrentIndex(dialog.joint.findData('crosshead-slider'));ready(app,dialog)
    dialog.limit_fields['z'][1].setText('1e')
    dialog.joint.setCurrentIndex(dialog.joint.findData('screw-rotation'))
    assert dialog.joint.currentData()==dialog.limit_id=='crosshead-slider'
    assert set(dialog.limit_fields)=={'z'}
    dialog.limit_fields['z'][1].setText('214.5');ready(app,dialog)
    assert dialog.checked.mates[1].limits['z']==[214.5,224.7]
    assert dialog.checked.mates[0].limits=={}
    dispose(app,dialog)


def test_invalid_link_update_discards_inflight_preview_until_corrected(app):
    import threading
    dialog=MotionDialog(None,fixture_design().model_dump());dialog.show();dialog.timer.stop()
    started=threading.Event();release=threading.Event();compute=dialog.checked_compute
    def blocked(raw,revision):
        started.set();assert release.wait(10);return compute(raw,revision)
    dialog.checked_compute=blocked;dialog.calculate();assert started.wait(10)
    dialog.ratio.setText('1e');click(dialog,'선택한 연결 수정');release.set()
    end=time.monotonic()+20
    while (dialog.running or dialog.timer.isActive()) and time.monotonic()<end:app.processEvents();time.sleep(.01)
    assert not dialog.running and dialog.checked is None and not dialog.apply_button.isEnabled()
    dialog.ratio.setText(repr(5/360));click(dialog,'선택한 연결 수정');ready(app,dialog)
    assert dialog.checked.motion_links[0].ratio==5/360
    dispose(app,dialog)


def test_explicit_native_ratio_edit_saveopen_undo_redo(app,tmp_path):
    document=Document();document.commit(fixture_design(),'fixture');old=document.journal.data['cursor']
    dialog=MotionDialog(None,document.design);dialog.show();dialog.links.setCurrentRow(0)
    dialog.ratio.setText(repr(4/360));click(dialog,'선택한 연결 수정');ready(app,dialog);click(dialog,'설계에 적용')
    document.commit(dialog.checked,'explicit ratio edit');new=document.journal.data['cursor'];path=tmp_path/'precise-link.pcad';document.write(path)
    assert read_project(path).design.motion_links[0].ratio==4/360
    assert document.journal.at(old)['motion_links'][0]['ratio']==5/360
    assert document.journal.at(new)['motion_links'][0]['ratio']==4/360
    assert len(document.journal.data['entries'])==2
    dispose(app,dialog)


def test_legacy_five_decimal_ratio_fails_the_real_slider_end_limit():
    raw=fixture_design().model_dump();raw['motion_links'][0]['ratio']=.01389;raw['mates'][0]['rz']=360
    with pytest.raises(ValueError,match='운동 한계'):Design.model_validate(raw)


@pytest.mark.parametrize('value',[5/360,219.7,.12345678901234568,5e-324])
def test_widget_roundtrip_doubles_without_decimal_place_loss(app,value):
    widget=MotionNumber(value,-5000,5000)
    assert widget.value()==value
    widget.deleteLater()
