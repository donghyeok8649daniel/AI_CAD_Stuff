import pytest
from datetime import date
from PySide6.QtCore import QCoreApplication,QEvent,Qt,QTimer
from PySide6.QtWidgets import QApplication,QDialog
from PySide6.QtTest import QTest
from cadstudio.native.force_acquisition_dialog import ForceAcquisitionDialog,MeasurementComponentDialog
from cadstudio.native.electrical_dialog import ComponentDialog,ElectricalDialog
from cadstudio.electrical import ElectricalWorkspace
from cadstudio.measurement_specs import AdcMeasurement
from cadstudio.models import Design
from cadstudio.native.document import Document,read_project
from cadstudio.native.widgets import STYLE
from test_force_acquisition import synthetic_chain


@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])


def close(dialog,app):
    dialog.close();dialog.deleteLater();app.processEvents();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()


def test_native_check_button_explains_pending_and_save_keeps_local_changes(app):
    workspace=synthetic_chain();before=workspace.model_dump();dialog=ForceAcquisitionDialog(None,dict(electrical=before))
    try:
        assert dialog.selectors['adc_id'].currentData()=='adc'
        dialog.frequency.setText('2');QTest.mouseClick(dialog.check_button,Qt.MouseButton.LeftButton);app.processEvents()
        assert dialog.result.status=='pending' and '실물' in dialog.report.toPlainText()
        assert dialog.result.metrics['samples_per_cycle']==2000
        assert workspace.model_dump()==before and dialog.accepted_workspace is None
        QTest.mouseClick(dialog.save_button,Qt.MouseButton.LeftButton);app.processEvents()
        assert dialog.result.status=='pending' and dialog.result.hardware_verified is False
        assert dialog.accepted_workspace.force_chain.target_frequency_hz==2 and dialog.result is not None
        assert dialog.accepted_workspace.components==workspace.components and workspace.model_dump()==before
    finally:close(dialog,app)


def test_unknown_fields_are_blank_and_do_not_insert_guessed_adc_settings(app):
    workspace=synthetic_chain();component=workspace.components[3];component.measurement=AdcMeasurement()
    dialog=MeasurementComponentDialog(None,component,workspace,'adc')
    try:
        assert dialog.fields['gain'].text()==dialog.fields['sample_rate_sps'].text()==''
        candidate=dialog.candidate();assert candidate.gain is None and candidate.usable_bandwidth_hz is None
        dialog.fields['gain'].setText('nan');dialog.accept();assert dialog.measurement is None and dialog.error.text()
    finally:close(dialog,app)


def test_changed_source_specs_are_user_declared_and_official_catalog_identity_remains(app):
    workspace=synthetic_chain();component=workspace.components[3]
    dialog=MeasurementComponentDialog(None,component,workspace,'adc')
    try:
        dialog.fields['gain'].setText('32');dialog.accept()
        assert dialog.measurement.gain==32 and dialog.measurement.provenance=='user_entered'
        assert component.measurement.gain==64 and component.catalog_id=='ti_ads131m04'
    finally:close(dialog,app)


def test_native_user_measured_calibration_is_local_and_can_be_cleared(app):
    workspace=synthetic_chain();component=workspace.components[2]
    dialog=MeasurementComponentDialog(None,component,workspace,'load_cell')
    try:
        dialog.calibration_points.setPlainText('1000, 0\n21000, 100');dialog.calibrate()
        assert dialog.candidate().calibration.scale_n_per_count==pytest.approx(.005)
        assert component.measurement.calibration.status=='uncalibrated'
        dialog.clear_calibration();assert dialog.candidate().calibration.status=='uncalibrated'
    finally:close(dialog,app)


def test_generic_electrical_editor_preserves_measurement_and_chain(app):
    workspace=synthetic_chain();component=workspace.components[3]
    dialog=ComponentDialog(None,[],component.model_dump())
    try:
        assert dialog.candidate()['measurement']==component.measurement.model_dump()
    finally:close(dialog,app)
    editor=ElectricalDialog(None,dict(electrical=workspace.model_dump(),parts=[]))
    try:
        candidate=editor.candidate()
        assert candidate.force_chain==workspace.force_chain
        assert candidate.components[3].measurement==component.measurement
    finally:close(editor,app)


def test_native_blank_workspace_open_review_cancel_does_not_create_design(app):
    dialog=ForceAcquisitionDialog(None,dict(parts=[]))
    try:
        dialog.check();assert dialog.result.status=='pending'
        assert dialog.workspace.force_chain is None and dialog.accepted_workspace is None
        dialog.reject();assert dialog.accepted_workspace is None
    finally:close(dialog,app)


def test_modal_native_check_save_completes_without_worker_or_profile_mutation(app):
    workspace=synthetic_chain();before=workspace.model_dump();dialog=ForceAcquisitionDialog(None,dict(electrical=before))
    try:
        QTimer.singleShot(0,dialog.accept)
        assert dialog.exec()==QDialog.DialogCode.Accepted
        assert dialog.accepted_workspace.force_chain==workspace.force_chain and dialog.result.status=='pending'
        assert workspace.model_dump()==before
    finally:close(dialog,app)


def test_setup_scroll_keeps_save_visible_at_six_hundred_pixels_with_app_style(app):
    previous=app.styleSheet();app.setStyleSheet(STYLE)
    workspace=synthetic_chain();before=workspace.model_dump();dialog=ForceAcquisitionDialog(None,dict(electrical=before))
    try:
        dialog.resize(1000,600);dialog.show();app.processEvents()
        assert dialog.height()==600 and dialog.minimumSizeHint().height()<600
        assert dialog.save_button.mapTo(dialog,dialog.save_button.rect().bottomRight()).y()<600
        scroll=dialog.setup_scroll.verticalScrollBar()
        assert scroll.maximum()>0
        scroll.setValue(scroll.maximum());app.processEvents()
        QTest.mouseClick(dialog.save_button,Qt.MouseButton.LeftButton);app.processEvents()
        assert dialog.accepted_workspace.force_chain==workspace.force_chain and workspace.model_dump()==before
    finally:
        close(dialog,app);app.setStyleSheet(previous)


def test_native_calibration_dates_survive_document_commit_save_reopen_undo_redo(app,tmp_path):
    workspace=synthetic_chain();component=workspace.components[2]
    initial=Design(name='Synthetic measurement history',parts=[],electrical=workspace)
    document=Document();document.commit(initial,'Reference registration')
    base=document.journal.data['cursor']
    dialog=MeasurementComponentDialog(None,component,workspace,'load_cell')
    try:
        dialog.calibration_points.setPlainText('1000, 0\n21000, 100');dialog.calibrate()
        dialog.calibration['calibrated_at']='2026-10-06';dialog.accept()
        edited=initial.model_copy(deep=True);edited.electrical.components[2].measurement=dialog.measurement
        document.commit(edited,'Measured calibration')
        head=document.journal.data['cursor'];project=document.project()
        assert project.history.entries[-1].changes
        calibration=project.design.electrical.components[2].measurement.calibration
        assert calibration.calibrated_at==date(2026,10,6) and calibration.scale_n_per_count==pytest.approx(.005)
        path=tmp_path/'measurement-dated.cad.json';document.write(path)
        reopened=Document();reopened.load(read_project(path),path)
        assert reopened.design==document.design
        assert reopened.design['electrical']['components'][2]['measurement']['source_checked_at']=='2026-10-06'
        assert reopened.design['electrical']['components'][2]['measurement']['calibration']['calibrated_at']=='2026-10-06'
        reopened.commit(reopened.journal.at(base),'Undo',cursor=base)
        assert reopened.project().design.electrical.components[2].measurement.calibration.status=='uncalibrated'
        reopened.commit(reopened.journal.at(head),'Redo',cursor=head)
        assert reopened.project().design.electrical.components[2].measurement.calibration.calibrated_at==date(2026,10,6)
        reopened.write(path)
        assert read_project(path).history==reopened.project().history
        assert component.measurement.calibration.status=='uncalibrated'
    finally:close(dialog,app)
