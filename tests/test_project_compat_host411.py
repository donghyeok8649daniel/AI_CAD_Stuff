"""New host preflight integration; one native document parser and no GUI."""
from copy import deepcopy
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from pydantic import ValidationError
from cadstudio.models import Design, Project
from cadstudio.native import document as D
from cadstudio import history as H
from cadstudio import pcb_compatibility as C


def project_tree():
    design = Design(name='Compatibility host fixture', parts=[]).model_dump(mode='json')
    return dict(format='prompt-cad-project', version=2, design=design, prompt='',
                history=dict(version=1, base=deepcopy(design),
                    entries=[dict(id='root', parent=None, label='Fixture root',
                                  created_at='2026-10-18T00:00:00Z', source='manual',
                                  changes=[], context={})], cursor='root', head='root'))


def write_tree(tmp_path, raw, name='input.pcad', bom=False):
    path = tmp_path/name
    path.write_bytes((b'\xef\xbb\xbf' if bom else b'') + json.dumps(raw, ensure_ascii=False).encode('utf-8'))
    return path


def test_host_light_scan_once_history_once_without_other_decode_or_validation(tmp_path, monkeypatch):
    raw = project_tree()
    path = write_tree(tmp_path, raw)
    calls = []
    scan = C.preflight
    history_validation = H.validate_history
    def counted(payload, target_profile):
        before = deepcopy(payload)
        result = scan(payload, target_profile)
        assert payload == before == raw
        calls.append(('scan', id(payload), target_profile))
        return result
    def checked_history(*args, **kwargs):
        calls.append(('history',))
        return history_validation(*args, **kwargs)
    def no_extra(*args, **kwargs):
        raise AssertionError('No second JSON decode or full Project validation allowed')
    monkeypatch.setattr(C, 'preflight', counted)
    monkeypatch.setattr(C, 'decode_compatible', no_extra)
    monkeypatch.setattr(C, 'validate_payload', no_extra)
    monkeypatch.setattr(D.json, 'loads', no_extra)
    monkeypatch.setattr(Project, 'model_validate', no_extra)
    monkeypatch.setattr(H, 'validate_history', checked_history)
    loaded = D.read_project(path)
    assert loaded.design.name == raw['design']['name']
    assert [call[0] for call in calls] == ['scan', 'history']
    assert calls[0][2] == C.CURRENT_PROFILE
    assert path.read_bytes() == json.dumps(raw, ensure_ascii=False).encode('utf-8')


@pytest.mark.parametrize('scope', ['project', 'design', 'history', 'base-pcb'])
def test_unsupported_versions_keep_machine_report_and_stop_before_history(tmp_path, monkeypatch, scope):
    raw = project_tree()
    if scope == 'project':
        raw['version'] = 99; expected = '/version'
    elif scope == 'design':
        raw['design']['schema_version'] = 99; expected = '/design/schema_version'
    elif scope == 'history':
        raw['history']['version'] = 99; expected = '/history/version'
    else:
        raw['history']['base']['pcb'] = {'schema_version':99}; expected = '/history/base/pcb/schema_version'
    path = write_tree(tmp_path, raw)
    def no_history(*args, **kwargs):
        raise AssertionError('Unsupported input cannot reach costly history replay')
    monkeypatch.setattr(H, 'validate_history', no_history)
    with pytest.raises(C.PCBCompatibilityError) as error:
        D.read_project(path)
    assert error.value.code == 'UNSUPPORTED_VERSION'
    assert any(reason['path'] == expected for reason in error.value.report['reasons'])
    assert error.value.report['data_modified'] is False
    assert error.value.report['fields_removed'] == []


def test_history_only_context_is_found_before_unsupported_target_adopts_anything(tmp_path, monkeypatch):
    raw = project_tree()
    raw['history']['entries'][0]['changes'] = [dict(path=['pcb','budget','cost_inputs','quantity_break_contexts'],
        operation='set', existed=False, before=None, after={'U1':'a'*64})]
    path = write_tree(tmp_path, raw)
    monkeypatch.setattr(C, 'CURRENT_PROFILE', 'pcb-v1-pre407')
    with pytest.raises(C.PCBCompatibilityError) as error:
        D.read_project(path)
    report = error.value.report
    assert report['target_profile'] == 'pcb-v1-pre407'
    assert any(reason['code'] == 'UNSUPPORTED_FEATURE' for reason in report['reasons'])
    assert any('/history/entries/0/changes/0/' in location['path'] for location in report['feature_locations'])
    assert json.loads(path.read_bytes()) == raw  # No repair, stripping or down-conversion.


def test_supported_407_maps_are_retained_and_dump_path_does_not_scan_again(tmp_path, monkeypatch):
    from cadstudio.pcb import PCBProject, PCBComponent
    from cadstudio.pcb_cost_workflow import with_cost_inputs
    board = with_cost_inputs(PCBProject(components=[PCBComponent(ref='U1', mpn='Host411', pins=[dict(number='1')])]),
        dict(quantity_breaks={'U1':[dict(minimum_quantity=1, unit_price='2', currency='USD',
             as_of='2026-10-18', supplier='Synthetic supplier', source_url='https://example.invalid/411')]}))
    raw = dict(design=Design(parts=[], pcb=board).model_dump(mode='json'))
    path = write_tree(tmp_path, raw)
    loaded = D.read_project(path)
    assert loaded.design.pcb.budget.cost_inputs.quantity_break_contexts
    document = D.Document(); document.load(loaded)
    def no_read_scan(*args, **kwargs):
        raise AssertionError('Read-only preflight adapter cannot be used by normal project/dump construction')
    monkeypatch.setattr(C, 'preflight', no_read_scan)
    output = tmp_path/'saved.pcad'; document.write(output)
    saved = json.loads(output.read_bytes())
    assert saved['design']['pcb']['budget']['cost_inputs']['quantity_break_contexts'] == raw['design']['pcb']['budget']['cost_inputs']['quantity_break_contexts']


def test_schema_failures_still_reject_without_mutating_the_open_document(tmp_path):
    document = D.Document(); document.commit(Design(name='Current work', parts=[]), 'Current')
    before = deepcopy(document.__dict__)
    raw = project_tree(); raw['design']['unknown_future_field'] = {'do_not_drop': True}
    path = write_tree(tmp_path, raw)
    with pytest.raises(ValidationError):
        incoming = D.read_project(path)
        document.load(incoming, path)
    assert document.design == before['design'] and document.journal.data == before['journal'].data
    assert document.path == before['path'] and document.dirty == before['dirty']
    assert json.loads(path.read_bytes()) == raw


def test_bom_and_size_guard_run_before_the_single_read_adapter(tmp_path, monkeypatch):
    raw = project_tree(); path = write_tree(tmp_path, raw, bom=True)
    length = path.stat().st_size
    calls = []
    scan = C.preflight
    def counted(*args, **kwargs):
        calls.append(True); return scan(*args, **kwargs)
    monkeypatch.setattr(C, 'preflight', counted)
    with pytest.raises(ValueError, match='MiB'):
        D.read_project(path, max_bytes=length-1)
    assert calls == []
    assert D.read_project(path, max_bytes=length).design.name == raw['design']['name']
    assert calls == [True]
    assert not any(name.startswith(('PySide6','vtkmodules','OCP','cadquery')) for name in sys.modules)
