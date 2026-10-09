"""Existing electrical editors cannot discard newly saved firmware bundles."""
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from cadstudio.electrical import ElectricalWorkspace
from cadstudio.firmware_bundle import create_bundle, verify_bundle_binding
from cadstudio.native.electrical_dialog import ElectricalDialog
from cadstudio.native.electrical_safety_dialog import ElectricalSafetyDialog


@pytest.fixture(scope='module')
def app():
    value=QApplication.instance() or QApplication([])
    value.setQuitOnLastWindowClosed(False)
    return value


def circuit():
    original=ElectricalWorkspace.model_validate(dict(nodes=['GND','PWR','LED'],components=[
        dict(id='pi',name='Existing Pi',kind='mcu',analysis_enabled=False,
             catalog_id='rpi4b',pinout_catalog_id='rpi4b',part_id='pi_body',part_registration=True,
             a='PWR',b='GND',signal_pins={'GPIO18':'LED'})]))
    bundle=create_bundle('User controller','raspberry_python',original,'pi',
        [dict(path='main.py',content='value = 0\n',role='source')],'main.py')
    data=original.model_dump(mode='json');data['firmware_bundles']=[bundle.model_dump(mode='json')]
    return ElectricalWorkspace.model_validate(data)


def dispose(widget,app):
    widget.reject();widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()


def test_power_dialog_rebuild_and_adopt_preserve_saved_bundle(app):
    original=circuit();before=original.model_dump(mode='json')
    dialog=ElectricalDialog(None,{'electrical':before})
    try:
        candidate=dialog.candidate()
        assert candidate.firmware_bundles==original.firmware_bundles
        assert verify_bundle_binding(candidate.firmware_bundles[0],candidate).status=='current'
        dialog.adopt_workspace(candidate)
        assert dialog.candidate().firmware_bundles==original.firmware_bundles
    finally:dispose(dialog,app)
    assert original.model_dump(mode='json')==before


def test_power_remove_and_demo_cannot_silently_detach_firmware(app,monkeypatch):
    original=circuit();warnings=[]
    monkeypatch.setattr(QMessageBox,'warning',lambda *args:warnings.append(args[2]))
    dialog=ElectricalDialog(None,{'electrical':original.model_dump(mode='json')})
    try:
        dialog.table.selectRow(0);dialog.remove();dialog.demo()
        assert len(dialog.components)==1 and len(warnings)==2
        assert dialog.candidate().firmware_bundles==original.firmware_bundles
    finally:dispose(dialog,app)


def test_rating_editor_keeps_bundle_and_reports_stale_after_operating_limit_edit(app):
    original=circuit();dialog=ElectricalSafetyDialog(None,original,'pi')
    try:
        dialog.inputs['max_voltage_v'].setText('5.25');dialog.accept()
        assert dialog.workspace.firmware_bundles==original.firmware_bundles
        assert verify_bundle_binding(dialog.workspace.firmware_bundles[0],dialog.workspace).status=='stale'
        assert original.components[0].safety is None
    finally:dispose(dialog,app)
