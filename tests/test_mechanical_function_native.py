from copy import deepcopy
import pytest
from PySide6.QtWidgets import QDialog, QLabel
from cadstudio.models import Design, Part
from cadstudio.native.document import read_project
from cadstudio.native.mechanical_function_dialog import MechanicalFunctionDialog
from test_placement_native import app, wait


def test_mixed_selection_defaults_to_preservation(app):
    parts = [dict(mechanical_function='fastener'), dict(mechanical_function='actuator')]
    dialog = MechanicalFunctionDialog(None, parts)
    try:
        assert dialog.function.currentData() is None
        assert dialog.function.findData('joint_support') >= 0
        assert dialog.function.findData('unspecified') >= 0
        assert parts == [dict(mechanical_function='fastener'), dict(mechanical_function='actuator')]
    finally:
        dialog.reject(); dialog.deleteLater(); app.processEvents()


def test_native_classification_cancel_save_undo_and_geometry_reuse(app, monkeypatch, tmp_path):
    from cadstudio.native import window
    from cadstudio.native.model_picker import LocalModelPicker
    monkeypatch.setattr(window, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(LocalModelPicker, 'refresh', lambda _: None)
    w = window.MainWindow()
    w.show_error = lambda message: pytest.fail(message)
    w.show()
    try:
        design = Design(parts=[Part(id='bolt', name='Bolt', geometry=dict(kind='cylinder'), role='structure', color='#f2f2f2'),
                              Part(id='motor', name='Motor', geometry=dict(kind='cylinder'), transform=dict(x=50), role='electrical', color='#FFD400')])
        w.apply_design(design.model_dump(), 'Baseline'); wait(app, lambda:not w.busy)
        w.select_parts(['bolt', 'motor'])
        baseline = deepcopy(w.document.project().model_dump(mode='json'))
        actors = {key: value[0] for key, value in w.viewport.actors.items()}
        def no_remesh(_): raise AssertionError('Function declaration remeshed the CAD')
        monkeypatch.setattr(window, 'preview', no_remesh)
        def cancel(dialog):
            dialog.function.setCurrentIndex(dialog.function.findData('actuator'))
            return QDialog.DialogCode.Rejected
        monkeypatch.setattr(MechanicalFunctionDialog, 'exec', cancel)
        w.actions['mechanical_function'].trigger()
        assert w.document.project().model_dump(mode='json') == baseline
        def accept(dialog):
            dialog.function.setCurrentIndex(dialog.function.findData('fastener'))
            return QDialog.DialogCode.Accepted
        monkeypatch.setattr(MechanicalFunctionDialog, 'exec', accept)
        w.select_parts(['bolt']); w.actions['mechanical_function'].trigger(); wait(app, lambda:not w.busy)
        def motor(dialog):
            dialog.function.setCurrentIndex(dialog.function.findData('actuator'))
            return QDialog.DialogCode.Accepted
        monkeypatch.setattr(MechanicalFunctionDialog, 'exec', motor)
        w.select_parts(['motor']); w.actions['mechanical_function'].trigger(); wait(app, lambda:not w.busy)
        changed = deepcopy(w.document.design)
        assert changed['parts'][0]['mechanical_function'] == 'fastener'
        assert changed['parts'][1]['mechanical_function'] == 'actuator'
        assert 'electrical' not in changed or changed['electrical'] == baseline['design'].get('electrical')
        for old, new in zip(baseline['design']['parts'], changed['parts']):
            assert {k:v for k,v in new.items() if k!='mechanical_function'} == old
        assert all(w.viewport.actors[key][0] is actor for key,actor in actors.items())
        assert w.findChild(QLabel, 'partMechanicalFunction') is not None
        path = tmp_path/'functions.pcad'; w.document.write(path)
        assert read_project(path).design.model_dump() == changed
        w.undo(); wait(app, lambda:not w.busy)
        assert 'mechanical_function' not in w.document.design['parts'][1]
        assert w.document.design['parts'][0]['mechanical_function'] == 'fastener'
        w.redo(); wait(app, lambda:not w.busy)
        assert w.document.design == changed
        assert all(w.viewport.actors[key][0] is actor for key,actor in actors.items())
    finally:
        w.document.dirty=False; w.close(); app.processEvents()
