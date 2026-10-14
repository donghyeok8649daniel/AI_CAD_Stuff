import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from copy import deepcopy
from types import SimpleNamespace
from PySide6.QtCore import QObject,Signal,QCoreApplication,QEvent,QPointF,Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication,QWidget,QComboBox,QStackedWidget
import pytest
from cadstudio.models import Design
from cadstudio.pcb import divider_example,pcb_digest,pad_positions
from cadstudio.native.document import Document
from cadstudio.native.pcb_workbench import PCBWorkbench,PCBComponentEditor


@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])


@pytest.fixture
def workbench(app):
    host=QWidget();host.document=Document();host.document.commit(Design(name='Test CAD',parts=[]),'base');host.codex_config=dict(model='fixture-model',executable='');host.cloud_effort=QComboBox();host.cloud_effort.addItem('medium','medium');host.ai_task=None
    widget=PCBWorkbench(host,host.document.design);host.stack=QStackedWidget(host);host.stack.addWidget(widget)
    widget.resize(1150,850);widget.show();app.processEvents()
    yield host,widget
    widget.alive=False;widget.stop_advice();host.close();host.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def test_qt_workspace_requires_explicit_apply_reparent_safe(workbench,app):
    host,w=workbench;old=deepcopy(host.document.design);packets=[];w.applyRequested.connect(packets.append)
    w.replace_project(divider_example());w.simulate();assert w.simulation_result['node_voltages_v']['OUT']['real']==2.5
    assert host.document.design==old and not packets
    w.request_apply(False);assert len(packets)==1 and not packets[0]['electrical'] and packets[0]['design']['parts']==old['parts']
    host.document.commit(packets[0]['design'],'PCB');w.document_changed(host.document.design);assert not w.dirty
    w.request_apply(True);assert len(packets)==2 and packets[-1]['design']['electrical']['components'][0]['id']=='pcb_V1'
    host.document.design['name']='other';w.request_apply(False);assert len(packets)==2 and 'Stale' in w.status.text()


def test_placement_routing_wrong_net_cancel_and_change_invalidate(workbench):
    host,w=workbench;w.replace_project(divider_example());w.simulate();w.move_component('R1',26,12)
    assert w.simulation_result is None and next(c for c in w.project.components if c.ref=='R1').x_mm==26
    w.replace_project(divider_example());raw=w.project.model_dump(mode='json');raw['tracks']=[];w.set_project(raw);w.route_button.setChecked(True)
    pads=pad_positions(w.project);start=pads[0];end=next(p for p in pads if p['net']==start['net'] and p['ref']!=start['ref']);wrong=next(p for p in pads if p['net']!=start['net'])
    before=len(w.project.tracks);w.route_click(dict(point=(start['x'],start['y']),pad=start));w.route_click(dict(point=(wrong['x'],wrong['y']),pad=wrong));assert len(w.project.tracks)==before
    w.route_click(dict(point=(8,5),pad=None));w.route_click(dict(point=(23,5),pad=None));w.route_click(dict(point=(end['x'],end['y']),pad=end));assert len(w.project.tracks)==before+1
    w.route_click(dict(point=(start['x'],start['y']),pad=start));w.route_click(dict(cancel=True));assert w.route is None
    packets=[];w.applyRequested.connect(packets.append);w.request_apply(True);assert not packets and 'Resolve' in w.status.text()


def test_component_editor_models_price_and_numeric_pins(workbench):
    _,w=workbench;w.replace_project(divider_example());c=w.project.components[1];dialog=PCBComponentEditor(w,c,w.project.nets)
    try:
        checked=dialog.candidate();assert checked.ref=='R1' and checked.model.resistance_ohm==1000
        dialog.pins.item(0,0).setText('1');dialog.pa.setText('1');assert dialog.candidate().pins[0].number=='1'
        dialog.price_status.setCurrentText('reference');dialog.amount.setText('0.1');dialog.currency.setText('USD');dialog.as_of.setText('2026-10-14');dialog.supplier.setText('Test fixture');dialog.price_source.setText('https://example.com/quote');dialog.accept();assert dialog.checked.quote.currency=='USD'
    finally:dialog.deleteLater()


class FakeTask(QObject):
    completed=Signal(object);failed=Signal(object)
    def __init__(self,fn,parent):super().__init__(parent);self.fn=fn;self.cancelled=False;self.started=False
    def start(self):self.started=True
    def cancel(self):self.cancelled=True


def test_advisory_explicit_cancel_stale_and_no_automatic_apply(workbench,monkeypatch,app):
    import cadstudio.native.ai_task as ai_task
    host,w=workbench;monkeypatch.setattr(ai_task,'AITask',FakeTask);w.replace_project(divider_example());packets=[];w.applyRequested.connect(packets.append)
    assert w.advice_task is None
    w.review();task=w.advice_task;assert task.started
    task.completed.emit((task,dict(answer='proposal')));app.processEvents();assert 'proposal' in w.advice.toPlainText() and not packets
    w.review();task=w.advice_task;w.stop_advice();assert task.cancelled;task.completed.emit((task,dict(answer='cancelled stale')));app.processEvents();assert 'cancelled stale' not in w.advice.toPlainText()
    w.review();task=w.advice_task;host.document.design['name']='changed';task.completed.emit((task,dict(answer='document stale')));app.processEvents();assert 'document stale' not in w.advice.toPlainText() and w.advice_task is None
    w.reload();w.review();task=w.advice_task;host.codex_config['model']='different';task.completed.emit((task,dict(answer='model stale')));app.processEvents();assert 'model stale' not in w.advice.toPlainText() and w.advice_task is None
    w.review();task=w.advice_task;w.replace_project(divider_example());assert task.cancelled;task.failed.emit((task,'late error'));app.processEvents();assert 'late error' not in w.advice.toPlainText()


def test_unsaved_draft_survives_external_doc_change_and_reload(workbench):
    host,w=workbench;w.replace_project(divider_example());sha=pcb_digest(w.project);oldbase=w.base_sha;host.document.design['name']='new'
    w.document_changed(host.document.design);assert pcb_digest(w.project)==sha and w.base_sha==oldbase and 'Stale' in w.status.text()
    w.reload();assert not w.dirty and not w.project.components


def test_canvas_mouse_drag_and_offscreen_pixels(workbench,app,tmp_path):
    host,w=workbench;w.replace_project(divider_example());canvas=w.canvas;canvas.resize(600,400);s,x,y=canvas.layout_transform();events=[];canvas.placementChanged.connect(lambda *args:events.append(args))
    pos=QPointF(x+25*s,y+10*s);press=QMouseEvent(QEvent.Type.MouseButtonPress,pos,pos,Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier);canvas.mousePressEvent(press)
    drop=QPointF(x+30*s,y+13*s);release=QMouseEvent(QEvent.Type.MouseButtonRelease,drop,drop,Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier);canvas.mouseReleaseEvent(release)
    assert events[-1]==('R1',30,13);app.processEvents();image=canvas.grab().toImage();assert not image.isNull();assert image.save(str(tmp_path/'pcb-canvas.png'))
