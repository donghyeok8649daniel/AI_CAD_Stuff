"""Native electrical editing and joint range checks in an isolated Qt process."""

import threading
import time
from copy import deepcopy

import pytest
from PySide6.QtCore import QEvent, QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from cadstudio.native.document import read_project
from cadstudio.native.electrical_dialog import CatalogDialog, ComponentDialog, ElectricalDialog
from cadstudio.native.workflows import JointDriveDialog
from test_joint_edits import joint_design


@pytest.fixture(scope='module')
def app():
    qt = QApplication.instance() or QApplication([])
    qt.setQuitOnLastWindowClosed(False)
    yield qt
    assert QThreadPool.globalInstance().waitForDone(10000)
    qt.processEvents()


def wait(app, predicate, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    assert predicate(), 'Native UI operation did not finish in time'


@pytest.fixture
def graphics_free(monkeypatch):
    """Exercise real Qt controls and CAD kernel without opening a Win32 GL surface.

    Geometry still runs through the exact kernel; only drawing is suppressed.
    The test must not set Qt's platform globally during pytest collection,
    because other native tests exercise a real Windows VTK window.
    """
    from cadstudio.native.viewport import CADViewport

    class NoDraw:
        def __init__(self, original):
            self.original = original

        def Render(self):
            pass

        def __getattr__(self, name):
            return getattr(self.original, name)

    monkeypatch.setattr(CADViewport, 'initialize', lambda self: setattr(self, 'initialized', True))
    monkeypatch.setattr(CADViewport, 'shutdown', lambda self: setattr(self, 'closed', True))

    def prepare(viewport):
        viewport.window = NoDraw(viewport.window)
        # A hidden widget has no showEvent; initialize the existing no-GL stub.
        viewport.initialize()

    return prepare


def test_component_form_and_demo_show_real_voltage_drop(app):
    form = ComponentDialog(None, [], None)
    try:
        form.kind.setCurrentIndex(form.kind.findData('wire'))
        form.name.setText('motor feed')
        form.a.setText('SWPLUS')
        form.b.setText('MPLUS')
        form.inputs['length_mm'].setValue(1000)
        form.inputs['cross_section_mm2'].setValue(.5)
        candidate = form.candidate()
        assert candidate['kind'] == 'wire'
        assert candidate['length_mm'] == 1000
        assert candidate['cross_section_mm2'] == pytest.approx(.5)
        assert candidate['a'] == 'SWPLUS' and candidate['b'] == 'MPLUS'
    finally:
        form.reject()

    dialog = ElectricalDialog(None, None)
    try:
        dialog.demo()
        assert len(dialog.components) == 4
        assert '정상 상태' in dialog.report.toPlainText()
        assert '노드 전압' in dialog.report.toPlainText()
        assert '모터 기동' in dialog.report.toPlainText()
        assert '회로 계산을 완료하지 못했습니다' not in dialog.report.toPlainText()
        dialog.accept()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert len(dialog.workspace.components) == 4
    finally:
        dialog.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_wire_open_toggle_and_mcu_signal_pin_editor(app):
    wire = ComponentDialog(None, [], dict(id='w1',name='신호선',kind='wire',a='SIGNAL_A',b='INPUT',
        length_mm=50,cross_section_mm2=.5,closed=False))
    try:
        assert not wire.wire_connected.isChecked()
        assert not wire.candidate()['closed']
        wire.wire_connected.setChecked(True)
        assert wire.candidate()['closed']
    finally:
        wire.reject()

    mcu = ComponentDialog(None, [], dict(id='u1',name='제어기',kind='mcu',a='VCC',b='GND',
        rated_voltage_v=5,rated_current_a=.1,signal_pins={'GPIO1':'SIGNAL_A'}))
    try:
        assert 'VCC' in mcu.a_caption.text() and '리턴' in mcu.b_caption.text()
        assert mcu.candidate()['signal_pins']=={'GPIO1':'SIGNAL_A'}
        mcu.signal_pins.setPlainText('GPIO1=SIGNAL_A\nGPIO2=INPUT')
        assert mcu.candidate()['signal_pins']=={'GPIO1':'SIGNAL_A','GPIO2':'INPUT'}
        mcu.signal_pins.setPlainText('GPIO1=SIGNAL_A\nGPIO1=INPUT')
        with pytest.raises(ValueError,match='중복'):
            mcu.candidate()
    finally:
        mcu.reject()


def test_electrical_report_shows_open_wire_and_mcu_connectivity(app):
    design=dict(parts=[],electrical=dict(name='MCU 연결 검사',components=[
        dict(id='b1',name='가상 5 V',kind='battery',a='BATPLUS',b='GND',voltage_v=5),
        dict(id='w1',name='MCU 공급선',kind='wire',a='BATPLUS',b='VCC',length_mm=50,
             cross_section_mm2=.5,closed=False),
        dict(id='u1',name='제어기',kind='mcu',a='VCC',b='GND',rated_voltage_v=5,
             rated_current_a=.1,signal_pins={'GPIO1':'SIGNAL_A'})]))
    dialog=ElectricalDialog(None,design)
    try:
        assert 'SIGNAL_A' in dialog.candidate().nodes
        assert '단선' in dialog.table.item(1,5).text()
        report=dialog.report.toPlainText()
        assert 'FAIL · MCU 공급선: 전선 단선' in report
        assert 'FAIL · 제어기: VCC' in report
        assert 'FAIL · 제어기 GPIO1' in report
        assert '펌웨어' not in report  # The report makes connectivity claims, not behavior claims.
    finally:
        dialog.reject()


def test_catalog_search_only_prefills_confirmed_model_values(app, monkeypatch):
    from cadstudio.electrical_catalog import get_catalog_entry
    from cadstudio.electrical import ElectricalComponent

    catalog=CatalogDialog(None,'Raspberry Pi 4')
    try:
        assert catalog.entries and catalog.entries[0].catalog_id=='rpi4b'
        assert catalog.use_button.isEnabled()
        catalog.query.setText('STM32 Nucleo')
        catalog.search()
        assert catalog.entries and catalog.entries[0].reference_only
        assert not catalog.use_button.isEnabled()
        assert 'https://' in catalog.details.toPlainText()
    finally:
        catalog.reject()

    def select_pi(self):
        self.entry=get_catalog_entry('rpi4b')
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(CatalogDialog,'exec',select_pi)
    form=ComponentDialog(None,[])
    try:
        form.select_catalog()
        candidate=form.candidate()
        assert candidate['kind']=='mcu'
        assert candidate['catalog_id']=='rpi4b'
        assert candidate['source_url'].startswith('https://www.raspberrypi.com/')
        assert candidate['rated_voltage_v']==5
        assert candidate['rated_current_a']==0  # PSU recommendation is not board current.
        pending=ElectricalComponent.model_validate(candidate)
        assert not pending.analysis_enabled  # Registration is valid; DC use is still pending.
        with pytest.raises(ValueError):ElectricalComponent.model_validate(dict(candidate,analysis_enabled=True))
        form.inputs['rated_current_a'].setValue(.35)
        form.analysis_enabled.setChecked(True)
        entered=ElectricalComponent.model_validate(form.candidate())
        assert entered.catalog_id=='rpi4b' and entered.analysis_enabled
    finally:
        form.reject()

    def select_wire(self):
        self.entry=get_catalog_entry('alpha_3050')
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(CatalogDialog,'exec',select_wire)
    wire=ComponentDialog(None,[])
    try:
        wire.select_catalog()
        candidate=wire.candidate()
        assert candidate['kind']=='wire'
        assert candidate['length_mm']==0 and candidate['cross_section_mm2']==0
        with pytest.raises(ValueError):ElectricalComponent.model_validate(candidate)
    finally:
        wire.reject()


def test_blank_window_electrical_save_recovery_and_undo(app, graphics_free, monkeypatch, tmp_path):
    from cadstudio.native import window
    from cadstudio.native.model_picker import LocalModelPicker

    monkeypatch.setattr(window, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(LocalModelPicker, 'refresh', lambda self: None)
    w = window.MainWindow(restore=False)
    graphics_free(w.viewport)
    errors = []
    w.show_error = errors.append
    try:
        wait(app, lambda: w.viewport.initialized)
        assert w.document.design is None

        def first_edit(dialog):
            dialog.demo()
            assert '노드 전압' in dialog.report.toPlainText()
            dialog.accept()
            return dialog.result()

        monkeypatch.setattr(ElectricalDialog, 'exec', first_edit)
        w.electrical_dialog()
        wait(app, lambda: not w.busy and w.document.design is not None)
        first = deepcopy(w.document.design)
        assert not first['parts'] and len(first['electrical']['components']) == 4
        assert any(entry['context'].get('tool') == 'electrical' for entry in w.document.journal.path())
        assert w.autosave.is_file() and w.autosave.parent == tmp_path

        save_path = tmp_path / 'circuit.cad.json'
        w.document.write(save_path)
        assert read_project(save_path).design.electrical.components[2].kind == 'wire'

        def edit_wire(component_dialog):
            assert component_dialog.kind.currentData() == 'wire'
            component_dialog.inputs['length_mm'].setValue(1000)
            component_dialog.accept()
            return component_dialog.result()

        monkeypatch.setattr(ComponentDialog, 'exec', edit_wire)

        def second_edit(dialog):
            dialog.table.selectRow(2)
            dialog.edit()
            assert '1000 mm' in dialog.table.item(2, 5).text()
            assert '노드 전압' in dialog.report.toPlainText()
            dialog.accept()
            return dialog.result()

        monkeypatch.setattr(ElectricalDialog, 'exec', second_edit)
        w.electrical_dialog()
        wait(app, lambda: not w.busy and w.document.design['electrical']['components'][2]['length_mm'] == 1000)
        second = deepcopy(w.document.design)
        assert second != first
        w.undo()
        wait(app, lambda: not w.busy and w.document.design == first)
        w.redo()
        wait(app, lambda: not w.busy and w.document.design == second)

        w.open_project(save_path, recovery=True)
        wait(app, lambda: not w.busy and w.document.design == first)
        assert not errors
    finally:
        w.document.dirty = False
        w.close()
        assert QThreadPool.globalInstance().waitForDone(10000)
        app.processEvents()


def test_joint_range_button_checks_both_directions_without_changing_design(app, graphics_free):
    raw = joint_design('revolute', z=30, limits={'rz': [-4, 4]}).model_dump()
    before = deepcopy(raw)
    dialog = JointDriveDialog(None, raw, 'hinge')
    graphics_free(dialog.viewport)
    try:
        wait(app, lambda: dialog.viewport.initialized)
        wait(app, lambda: dialog.checked is not None)
        assert dialog.range_axis.currentData() == ('hinge', 'rz')
        assert dialog.survey_button.isEnabled()
        dialog.survey_button.click()
        wait(app, lambda: dialog.range_running)
        wait(app, lambda: not dialog.range_running and '음의 방향' in dialog.range_report.text())
        report = dialog.range_report.text()
        assert '양의 방향' in report and '설정 한계' in report
        assert '-4°' in report and '4°' in report
        assert raw == before and not dialog.apply_button.isEnabled()
    finally:
        dialog.reject()
        assert QThreadPool.globalInstance().waitForDone(10000)
        app.processEvents()


def test_joint_range_cancel_then_pose_change_discards_stale_worker(app, graphics_free, monkeypatch):
    from cadstudio import interference

    raw = joint_design('revolute', z=30, limits={'rz': [-4, 4]}).model_dump()
    started = threading.Event()
    release = threading.Event()

    def slow_survey(*args, check, **kwargs):
        started.set()
        release.wait(10)
        check()
        return dict(current=0, samples=1,
                    negative=dict(blocked=False, requested=-4),
                    positive=dict(blocked=False, requested=4))

    monkeypatch.setattr(interference, 'survey_joint_drive', slow_survey)
    dialog = JointDriveDialog(None, raw, 'hinge')
    graphics_free(dialog.viewport)
    try:
        wait(app, lambda: dialog.viewport.initialized)
        wait(app, lambda: dialog.checked is not None)
        dialog.survey_button.click()
        assert started.wait(3)
        assert not dialog.range_cancel.isHidden() and dialog.range_running
        dialog.range_cancel.click()
        assert '취소 중' in dialog.range_report.text()
        dialog.inputs[('hinge', 'rz')].setValue(1)
        release.set()
        wait(app, lambda: not dialog.range_running and dialog.checked is not None)
        assert '설정 한계 -4' not in dialog.range_report.text()
        assert '양의 방향:' not in dialog.range_report.text()
        assert dialog.range_cancel.isHidden()
        assert dialog.survey_button.isEnabled()
    finally:
        release.set()
        dialog.reject()
        assert QThreadPool.globalInstance().waitForDone(10000)
        app.processEvents()
