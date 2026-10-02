from copy import deepcopy
import pytest
from cadstudio.models import Design, Part
from test_placement_native import app, wait


def test_metadata_keeps_native_actors_and_history_geometry_changes_rebuild(app, monkeypatch, tmp_path):
    from cadstudio.native import window
    from cadstudio.native.model_picker import LocalModelPicker
    monkeypatch.setattr(window, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(LocalModelPicker, 'refresh', lambda _: None)
    w = window.MainWindow()
    w.show_error = lambda message: pytest.fail(message)
    w.show()
    try:
        raw = Design(parts=[Part(id='a',name='A',geometry=dict(kind='cylinder'))]).model_dump()
        w.apply_design(raw,'Base');wait(app, lambda:not w.busy)
        actor = w.viewport.actors['a'][0]
        original_preview = window.preview
        def must_not_remesh(_):raise AssertionError('Metadata remeshed')
        monkeypatch.setattr(window,'preview',must_not_remesh)
        raw = deepcopy(w.document.design)
        raw['parts'][0].update(name='Renamed',color='#FFD400',role='electrical')
        raw['electrical'] = dict(nodes=['GND'],components=[])
        w.apply_design(raw,'Metadata');wait(app, lambda:not w.busy)
        assert w.viewport.actors['a'][0] is actor
        assert w.viewport.meshes['a']['name'] == 'Renamed'
        w.undo();wait(app, lambda:not w.busy)
        assert w.viewport.actors['a'][0] is actor and w.document.design['parts'][0]['name']=='A'
        w.redo();wait(app, lambda:not w.busy)
        assert w.viewport.actors['a'][0] is actor and w.document.design['parts'][0]['name']=='Renamed'
        monkeypatch.setattr(window,'preview',original_preview)
        raw = deepcopy(w.document.design);raw['parts'][0]['geometry']['height'] += 5
        w.apply_design(raw,'Dimension');wait(app, lambda:not w.busy)
        assert w.viewport.actors['a'][0] is not actor
        assert w.result['meshes'][0]['bounds'][2] == pytest.approx(raw['parts'][0]['geometry']['height'])
    finally:
        w.document.dirty=False;w.close();app.processEvents()


def test_rejected_journal_keeps_preview_associated_with_committed_geometry(app, monkeypatch, tmp_path):
    from cadstudio.native import window
    from cadstudio.native.model_picker import LocalModelPicker
    monkeypatch.setattr(window, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(LocalModelPicker, 'refresh', lambda _: None)
    w = window.MainWindow()
    errors = []
    w.show_error = lambda message: errors.append(message)
    w.show()
    try:
        raw = Design(parts=[Part(id='a', name='Body', geometry=dict(kind='cylinder', height=10))]).model_dump()
        w.apply_design(raw, 'Baseline');wait(app, lambda:not w.busy)
        baseline = deepcopy(w.document.design)
        result = w.result
        actor = w.viewport.actors['a'][0]
        history = deepcopy(w.document.journal.data)
        serial = w.operation_serial
        rejected = deepcopy(baseline)
        rejected['parts'][0]['geometry']['height'] = 20
        # The empty history change cannot describe the candidate's new height.
        w.apply_design(rejected, 'Invalid journal', {
            'journal_steps': [{'action': {'tool': 'parameters', 'target': 'a'}, 'changes': []}],
        });wait(app, lambda:not w.busy)
        assert len(errors) == 1
        assert w.document.design == baseline
        assert w.document.journal.data == history
        assert w.operation_serial == serial
        assert w.result is result
        assert w.viewport.actors['a'][0] is actor
        assert w.result['meshes'][0]['bounds'][2] == pytest.approx(10)
        metadata = deepcopy(w.document.design)
        metadata['parts'][0].update(name='Renamed body', color='#abcdef')
        def must_not_remesh(_):raise AssertionError('Rejected transaction invalidated verified metadata reuse')
        monkeypatch.setattr(window, 'preview', must_not_remesh)
        w.apply_design(metadata, 'Metadata after rejection');wait(app, lambda:not w.busy)
        assert len(errors) == 1
        assert w.document.design['parts'][0]['geometry']['height'] == pytest.approx(10)
        assert w.result['meshes'][0]['bounds'][2] == pytest.approx(10)
        assert w.result['meshes'][0]['name'] == 'Renamed body'
        assert w.result['meshes'][0]['color'] == '#abcdef'
        assert w.viewport.actors['a'][0] is actor
    finally:
        w.document.dirty=False;w.close();app.processEvents()
