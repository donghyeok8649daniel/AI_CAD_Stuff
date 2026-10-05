"""The motor study stays explicit, asynchronous and separate from the CAD file."""
import csv
import json
import threading
import time

import pytest
import shiboken6
from PySide6.QtCore import QEvent, QThreadPool, QTimer
from PySide6.QtGui import QImage, QPaintDevice
from PySide6.QtWidgets import QApplication

from cadstudio.models import Design
from cadstudio.drive_simulation import simulate_drive, synthetic_drive_demo
from cadstudio.native import drive_simulation_dialog as module


@pytest.fixture(scope='module')
def app():
    instance=QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    return instance


def wait_for(app,predicate,timeout=8):
    deadline=time.monotonic()+timeout
    while not predicate() and time.monotonic()<deadline:
        app.processEvents()
        time.sleep(.002)
    app.processEvents()
    assert predicate(), 'Native drive study did not finish in the bounded test interval.'


def close_dialog(app,dialog):
    if shiboken6.isValid(dialog):
        dialog.reject()
    assert QThreadPool.globalInstance().waitForDone(3000)
    app.processEvents()
    if shiboken6.isValid(dialog):
        dialog.deleteLater()
    app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    app.processEvents()


def test_real_project_starts_without_invented_motor_constants_or_implicit_demo(app):
    original=Design(name='Unconfigured project')
    before=original.model_dump()
    dialog=module.DriveSimulationDialog(None,original)
    try:
        assert not dialog.virtual_demo
        assert callable(dialog.metric) and callable(dialog.plot.metric)
        assert dialog.metric(QPaintDevice.PaintDeviceMetric.PdmWidth)>0
        assert dialog.plot.metric(QPaintDevice.PaintDeviceMetric.PdmHeight)>0
        assert all(dialog.inputs[key].value()==0 for key in (
            'resistance_ohm','inductance_h','torque_constant_nm_per_a',
            'back_emf_v_per_rad_s','inertia_kg_m2','current_limit_a','voltage_limit_fraction'))
        assert dialog.encoder_ticks.value()==0
        assert dialog.result is None
        assert not dialog.csv_button.isEnabled()
        dialog.start_simulation()
        assert not dialog.running and dialog.result is None
        assert dialog.status.text()
        assert original.model_dump()==before
    finally:close_dialog(app,dialog)


def test_plot_selector_cannot_shadow_qpaintdevice_metric_and_show_close_is_safe(app):
    dialog=module.DriveSimulationDialog(None,Design())
    try:
        dialog.show();app.processEvents()
        assert callable(dialog.metric)
        assert dialog.metric(QPaintDevice.PaintDeviceMetric.PdmWidth)==dialog.width()
        assert dialog.metric(QPaintDevice.PaintDeviceMetric.PdmHeight)==dialog.height()
        assert callable(dialog.plot.metric)
        assert dialog.metric_combo.count()==5
        snapshot=dialog.plot.grab()
        image=snapshot.toImage().copy()
        pixel_values=len(set(bytes(image.constBits())))
        assert pixel_values>20, f'Empty-state plot not rendered: {pixel_values} channel values.'
        assert not dialog.plot.paint_error
    finally:close_dialog(app,dialog)


def test_virtual_demo_is_explicit_and_input_si_roundtrip_preserves_original_cad(app):
    original=Design(name='Original real project')
    before=original.model_dump()
    dialog=module.DriveSimulationDialog(None,original)
    try:
        dialog.load_virtual_demo()
        expected_design,expected_spec=synthetic_drive_demo()
        assert dialog.virtual_demo
        assert '가상' in dialog.mode_status.text() or 'Virtual' in dialog.mode_status.text()
        actual=dialog.settings()
        for key in expected_spec.model_fields:
            value=getattr(expected_spec,key)
            if isinstance(value,float):
                assert getattr(actual,key)==pytest.approx(value,abs=1e-9)
            else:
                assert getattr(actual,key)==value
        assert dialog.inputs['inductance_h'].value()==pytest.approx(expected_spec.inductance_h*1000)
        assert 'mH' in dialog.inputs['inductance_h'].suffix()
        assert dialog.simulation_design()==expected_design
        assert original.model_dump()==before
    finally:close_dialog(app,dialog)


def test_supply_overrides_are_local_and_registered_component_ids_are_preserved(app):
    design,spec=synthetic_drive_demo()
    before=design.model_dump()
    dialog=module.DriveSimulationDialog(None,design)
    try:
        dialog.set_spec(spec)
        dialog.supply_voltage.setValue(11.5)
        dialog.supply_resistance.setValue(.25)
        candidate=dialog.simulation_design()
        source=next(item for item in candidate.electrical.components if item.id==spec.source_id)
        assert source.voltage_v==11.5 and source.internal_resistance_ohm==.25
        assert source.part_id==next(item for item in design.electrical.components if item.id==spec.source_id).part_id
        assert design.model_dump()==before
        assert dialog.design.model_dump()==before
        assert not dialog.virtual_demo
    finally:close_dialog(app,dialog)


def test_worker_is_off_ui_thread_and_gui_remains_responsive_during_run(app,monkeypatch):
    design,spec=synthetic_drive_demo()
    result=simulate_drive(design,spec)
    entered=threading.Event()
    released=threading.Event()
    worker_threads=[]
    ui_thread=threading.get_ident()
    def compute(*args,**kwargs):
        worker_threads.append(threading.get_ident())
        entered.set()
        assert released.wait(3)
        return result
    monkeypatch.setattr(module,'simulate_drive',compute)
    dialog=module.DriveSimulationDialog(None,Design())
    try:
        dialog.load_virtual_demo()
        pulses=[]
        dialog.start_simulation()
        QTimer.singleShot(0,lambda:pulses.append('ui'))
        wait_for(app,lambda:entered.is_set() and bool(pulses))
        assert dialog.running and not dialog.run_button.isEnabled()
        assert worker_threads==[worker_threads[0]] and worker_threads[0]!=ui_thread
        released.set()
        wait_for(app,lambda:not dialog.running)
        assert dialog.result is result
        assert dialog.plot.traces and dialog.result.points
        assert dialog.csv_button.isEnabled()
        dialog.show();app.processEvents()
        assert not dialog.plot.paint_error
        snapshot=dialog.plot.grab()
        image=snapshot.toImage().copy()
        pixel_values=len(set(bytes(image.constBits())))
        assert image.size().width()>300
        assert pixel_values>35, f'Blank native plot: {pixel_values} unique channel values.'
    finally:
        released.set()
        close_dialog(app,dialog)


def test_demo_csv_and_report_bind_to_calculated_inputs_and_reject_stale_export(app,tmp_path):
    dialog=module.DriveSimulationDialog(None,Design())
    try:
        dialog.load_virtual_demo()
        dialog.start_simulation()
        wait_for(app,lambda:not dialog.running)
        assert dialog.result is not None and dialog.result.points
        csv_path=dialog.write_csv(tmp_path/'trace.csv')
        with csv_path.open(encoding='utf-8-sig',newline='') as stream:
            rows=list(csv.DictReader(stream))
        assert len(rows)==len(dialog.result.points)
        assert all(row['virtual_demo']=='1' for row in rows)
        assert float(rows[-1]['speed_rpm'])==pytest.approx(dialog.result.points[-1].speed_rpm)
        report_path=dialog.export_report(tmp_path/'conditions.json')
        report=json.loads(report_path.read_text(encoding='utf-8'))
        assert report['virtual_demo'] is True
        assert report['conditions']==dialog.checked_spec.model_dump()
        assert report['result']==dialog.result.model_dump()
        assert 'no firmware/FOC' in report['model_scope']
        dialog.inputs['target_rpm'].setValue(dialog.inputs['target_rpm'].value()+100)
        assert not dialog.csv_button.isEnabled() and not dialog.report_button.isEnabled()
        with pytest.raises(ValueError):dialog.write_csv(tmp_path/'stale.csv')
        assert dialog.export_report(tmp_path/'stale.json') is None
        assert not (tmp_path/'stale.json').exists()
    finally:close_dialog(app,dialog)


def test_close_cancels_pending_worker_and_disconnects_destroyed_dialog(app,monkeypatch):
    design,spec=synthetic_drive_demo()
    result=simulate_drive(design,spec)
    entered=threading.Event()
    observed_cancel=threading.Event()
    def compute(*args,cancel_event,**kwargs):
        entered.set()
        assert cancel_event.wait(3)
        observed_cancel.set()
        return result
    monkeypatch.setattr(module,'simulate_drive',compute)
    dialog=module.DriveSimulationDialog(None,Design())
    dialog.load_virtual_demo()
    dialog.start_simulation()
    wait_for(app,entered.is_set)
    dialog.reject()
    assert dialog._cancel.is_set()
    dialog.deleteLater()
    app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    wait_for(app,observed_cancel.is_set)
    assert QThreadPool.globalInstance().waitForDone(3000)
    app.processEvents()
    assert not shiboken6.isValid(dialog)
    assert dialog.result is None


def test_calculation_failure_restores_controls_without_mutating_original(app,monkeypatch):
    def fail(*args,**kwargs):raise ValueError('Measured motor constants required.')
    monkeypatch.setattr(module,'simulate_drive',fail)
    original=Design(name='Protected')
    before=original.model_dump()
    dialog=module.DriveSimulationDialog(None,original)
    try:
        dialog.load_virtual_demo()
        dialog.start_simulation()
        wait_for(app,lambda:not dialog.running)
        assert dialog.run_button.isEnabled() and dialog.demo_button.isEnabled()
        assert not dialog.cancel_button.isEnabled()
        assert 'Measured motor constants' in dialog.status.text()
        assert original.model_dump()==before
    finally:close_dialog(app,dialog)
