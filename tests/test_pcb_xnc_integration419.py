"""Nine new host XNC integration purposes; synthetic data, no native window.

The profile and complete ASCII expectation below are independent hand-written
test declarations. They are not a real shop profile or machine qualification.
"""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import sys

from cadstudio import pcb_cli as CLI, pcb_plugin as P, pcb_excellon_export as X
from cadstudio import pcb_compatibility as C
from cadstudio.models import Design, Project
from cadstudio.native.document import Document, read_project
from cadstudio.pcb import PCBProject, pcb_digest


SOURCE = Path(__file__).resolve().parents[1]
LAYERS = ['F.Cu', 'In1.Cu', 'In2.Cu', 'In3.Cu', 'In4.Cu', 'B.Cu']


def board():
    return PCBProject(name='419 synthetic six-layer declaration', width_mm=30,
        height_mm=25, layer_count=6, nets=['GND'], components=[dict(
            ref='J1', x_mm=8, y_mm=7, fitted=False, pins=[dict(number='1',
                x_mm=.125, y_mm=.5, diameter_mm=1.2, drill_mm=.6,
                layers=['F.Cu', 'B.Cu'], net='GND')])], vias=[dict(
            id='v1', net='GND', x_mm=14.25, y_mm=6.75, diameter_mm=.7,
            drill_mm=.3, layers=['F.Cu', 'B.Cu'])]).model_dump(mode='json')


def declared_profile(raw):
    # Authoritative only inside this synthetic fixture. Nothing is inferred
    # from exporter output, catalog hardware or an actual board/shop process.
    return dict(schema_version=1,
        dialect='ucamco-xnc-2021.11-circular-metric-pth',
        source_pcb_sha256=pcb_digest(raw), units='mm',
        origin=dict(kind='pcb-design', offset_mm=['0', '0'], rotation_deg='0',
            mirror_x=False, mirror_y=False),
        coordinate_format=dict(notation='explicit-decimal', mode='absolute',
            decimal_places=3, rounding='ROUND_HALF_EVEN',
            maximum_numeric_rounding_error_mm='0'),
        diameter_semantics='model_drill_mm_declared_finished_hole_mm',
        copper_layers=list(LAYERS), declared_drill_span=['F.Cu', 'B.Cu'],
        plating='Plated', profile_basis='Synthetic caller declaration only; not a shop acceptance.',
        tools=[dict(number='01', diameter_mm='0.6', function='ComponentDrill'),
            dict(number='02', diameter_mm='0.3', function='ViaDrill')],
        hole_tools={'pad:J1:1': '01', 'via:v1': '02'})


def expected_ascii(raw):
    return (
        'M48\n'
        '; DECLARED CAD TO CAM DATA - NOT MACHINE QUALIFIED\n'
        '; SOURCE_PCB_SHA256 ' + pcb_digest(raw) + '\n'
        '; #@! TF.FileFunction,Plated,1,6,PTH\n'
        'METRIC\n'
        '; #@! TA.AperFunction,ComponentDrill\n'
        'T01C0.6\n'
        '; #@! TA.AperFunction,ViaDrill\n'
        'T02C0.3\n'
        '%\n'
        'G05\n'
        'T01\n'
        '; SOURCE pad:J1:1\n'
        'X8.125Y7.500\n'
        'T02\n'
        '; SOURCE via:v1\n'
        'X14.250Y6.750\n'
        'M30\n'
    ).encode('ascii')


def invoke(args):
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err): code = CLI.main(args)
    return code, out.getvalue(), err.getvalue()


def store(tmp_path, value, name):
    path = tmp_path / name
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    return path


def unavailable(result, code):
    assert result['status'] == 'UNAVAILABLE'
    assert result['reasons'][0]['code'] == code
    assert result['files_generated'] == [] and result['data_modified'] is False
    assert result['manufacturing_qualified'] is False


def test_six_layer_declared_program_matches_independent_ascii_literal():
    assert Path(X.__file__).resolve() == SOURCE / 'cadstudio/pcb_excellon_export.py'
    assert Path(CLI.__file__).resolve() == SOURCE / 'cadstudio/pcb_cli.py'
    assert Path(P.__file__).resolve() == SOURCE / 'cadstudio/pcb_plugin.py'
    raw = board(); profile = declared_profile(raw)
    original, declared = deepcopy(raw), deepcopy(profile)
    result = P.execute('excellon_prepare', raw, profile=profile)
    expected = expected_ascii(raw)
    assert result['status'] == 'prepared_declared_cad_data'
    assert result['xnc_text'].encode('ascii') == expected
    assert result['xnc_bytes'] == len(expected) and result['xnc_sha256'] == sha256(expected).hexdigest()
    assert [row['source_id'] for row in result['traceability']] == ['pad:J1:1', 'via:v1']
    assert result['traceability'][0]['component_fitted'] is False
    assert result['traceability'][1]['source_copper_layers'] == ['F.Cu', 'B.Cu']
    assert result['profile']['copper_layers'] == LAYERS
    assert result['plating']['verified'] == 'UNAVAILABLE'
    assert result['drill_span']['verified_depth'] == 'UNAVAILABLE'
    assert result['files_generated'] == [] and result['data_modified'] is False
    assert result['manufacturing_qualified'] is result['machine_program_qualified'] is result['actual_hardware_verified'] is False
    assert raw == original and profile == declared
    assert not any(name in sys.modules for name in ('PySide6.QtWidgets', 'vtk', 'cadquery', 'OCP'))


def test_cli_preview_is_json_and_export_is_ascii_with_exclusive_new_paths(tmp_path):
    raw = board(); source = store(tmp_path, raw, 'board.pcbp')
    profile = store(tmp_path, declared_profile(raw), 'explicit-profile.json')
    source_before, profile_before = source.read_bytes(), profile.read_bytes()
    preview, actual = tmp_path / 'preview.json', tmp_path / 'declared.xnc'
    option = ['--excellon-profile', str(profile)]
    code, out, err = invoke(['excellon_prepare', str(source), *option, '--output', str(preview)])
    assert code == 0 and not out and not err
    assert json.loads(preview.read_text())['status'] == 'prepared_declared_cad_data'
    code, out, err = invoke(['excellon_export', str(source), *option, '--output', str(actual)])
    assert code == 0 and not err and json.loads(out)['status'] == 'written_declared_cad_data'
    assert actual.read_bytes() == expected_ascii(raw) and b'\r' not in actual.read_bytes()
    preview_before, actual_before = preview.read_bytes(), actual.read_bytes()
    for command, destination in (('excellon_prepare', preview), ('excellon_export', actual)):
        code, out, err = invoke([command, str(source), *option, '--output', str(destination)])
        assert code == 2 and not out and json.loads(err)['status'] in ('blocked', 'UNAVAILABLE')
    for command, destination in (('excellon_prepare', tmp_path/'not-preview.xnc'), ('excellon_export', tmp_path/'not-xnc.drl')):
        code, out, err = invoke([command, str(source), *option, '--output', str(destination)])
        assert code == 2 and not out and json.loads(err)['status'] == 'UNAVAILABLE'
        assert not destination.exists()
    assert preview.read_bytes() == preview_before and actual.read_bytes() == actual_before
    assert source.read_bytes() == source_before and profile.read_bytes() == profile_before


def test_missing_profile_fails_closed_before_any_output(tmp_path):
    raw = board(); before = deepcopy(raw)
    unavailable(X.prepare_declared_xnc(raw, None), 'PROFILE_REQUIRED')
    unavailable(P.execute('excellon_prepare', raw), 'PROFILE_REQUIRED')
    source = store(tmp_path, raw, 'board.pcbp'); saved = source.read_bytes()
    for command, suffix in (('excellon_prepare', '.json'), ('excellon_export', '.xnc')):
        output = tmp_path / ('missing-' + command + suffix)
        code, out, err = invoke([command, str(source), '--output', str(output)])
        assert code == 2 and not out
        unavailable(json.loads(err), 'PROFILE_REQUIRED')
        assert not output.exists()
    assert raw == before and source.read_bytes() == saved


def test_xnc_cli_merge_retains_selected_compatibility_profile_and_required_rules(tmp_path):
    raw = board()
    raw['budget']['cost_inputs'] = {'quantity_break_contexts': {}}
    host = Project(design=Design(name='419 compatibility host', parts=[], pcb=raw)).model_dump(mode='json')
    # Keep explicit context-map presence in the supplied raw tree, even empty.
    host['design']['pcb']['budget']['cost_inputs']['quantity_break_contexts'] = {}
    path = store(tmp_path, host, 'synthetic-host.pcad'); original = path.read_bytes()
    code, out, err = invoke(['compatibility', str(path), '--target-profile', C.CURRENT_PROFILE])
    report = json.loads(out)
    assert code == 0 and not err and report['validated'] is True
    assert report['document_kind'] == 'project' and report['target_profile'] == C.CURRENT_PROFILE
    output = tmp_path / 'legacy.json'
    code, out, err = invoke(['compatibility', str(path), '--target-profile', 'pcb-v1-pre407', '--output', str(output)])
    assert code == 2 and not out and json.loads(err)['target_profile'] == 'pcb-v1-pre407'
    assert json.loads(err)['reasons'][0]['code'] == 'UNSUPPORTED_FEATURE' and not output.exists()
    output.write_bytes(b'PRESERVE OWNED COMPATIBILITY REPORT')
    code, out, err = invoke(['compatibility', str(path), '--output', str(output)])
    assert code == 2 and not out and json.loads(err)['status'] == 'blocked'
    assert output.read_bytes() == b'PRESERVE OWNED COMPATIBILITY REPORT' and path.read_bytes() == original
    pcb_path = store(tmp_path, board(), 'rules-board.pcbp'); missing = tmp_path / 'not-reviewed.json'
    code, out, err = invoke(['drill_review', str(pcb_path), '--drill-gap-mm', '0', '--output', str(missing)])
    assert code == 2 and not out
    unavailable(json.loads(err), 'MISSING_DRILL_RULES')
    assert not missing.exists()


def test_artifact_adoption_cannot_reuse_changed_source_profile_or_qualification():
    raw = board(); profile = declared_profile(raw); artifact = X.prepare_declared_xnc(raw, profile)
    before = deepcopy(artifact)
    checked = X.verify_declared_xnc_artifact(raw, profile, artifact)
    assert checked['status'] == 'verified_declared_cad_data_only' and not checked['filesystem_state_checked']
    shifted = deepcopy(raw); shifted['vias'][0]['x_mm'] += 1
    unavailable(X.verify_declared_xnc_artifact(shifted, profile, artifact), 'PROFILE_SOURCE_MISMATCH')
    changed_profile = deepcopy(profile); changed_profile['profile_basis'] += ' Revised declaration.'
    unavailable(X.verify_declared_xnc_artifact(raw, changed_profile, artifact), 'EXPORT_CONTENT_MISMATCH')
    overclaim = deepcopy(artifact); overclaim['machine_program_qualified'] = True
    unavailable(X.verify_declared_xnc_artifact(raw, profile, overclaim), 'EXPORT_CONTENT_MISMATCH')
    assert artifact == before and not checked['manufacturing_qualified']


def test_finished_hole_role_and_explicit_numeric_budget_control_emission():
    raw = board(); profile = declared_profile(raw); before = deepcopy(raw)
    wrong_role = deepcopy(profile); wrong_role['tools'][0]['function'] = 'ViaDrill'
    unavailable(X.prepare_declared_xnc(raw, wrong_role), 'TOOL_FUNCTION_MISMATCH')
    wrong_diameter = deepcopy(profile); wrong_diameter['tools'][0]['diameter_mm'] = '0.7'
    unavailable(X.prepare_declared_xnc(raw, wrong_diameter), 'FINISHED_DIAMETER_MISMATCH')
    no_rounding = deepcopy(profile); no_rounding['coordinate_format']['decimal_places'] = 2
    unavailable(X.prepare_declared_xnc(raw, no_rounding), 'COORDINATE_PRECISION_LOSS')
    explicit_budget = deepcopy(no_rounding)
    explicit_budget['coordinate_format']['maximum_numeric_rounding_error_mm'] = '0.005'
    emitted = X.prepare_declared_xnc(raw, explicit_budget)
    assert emitted['status'] == 'prepared_declared_cad_data'
    assert emitted['traceability'][0]['emitted_xy_mm'] == ['8.12', '7.50']
    assert [Decimal(v) for v in emitted['traceability'][0]['numeric_rounding_error_mm']] == [Decimal('0.005'), Decimal('0')]
    assert emitted['physical_tolerance'] == 'UNAVAILABLE' and raw == before


def test_explicit_host_pcb_use_preserves_six_layers_original_file_and_full_branches(tmp_path):
    initial = Design(name='419 saved host', parts=[], pcb=board()).model_dump(mode='json')
    def step(identifier, parent, title, after=None):
        return dict(id=identifier, parent=parent, label=title, created_at='2026-10-18T00:00:00Z', source='manual',
            context={'fixture': 'synthetic only'}, changes=[] if after is None else [dict(
                path=['name'], operation='set', existed=True, before=initial['name'], after=after)])
    original = Project.model_validate(dict(format='prompt-cad-project', version=2, design=initial,
        prompt='Keep the saved context.', history=dict(version=1, base=initial,
            entries=[step('root', None, 'saved start'), step('a', 'root', 'retained branch A', 'branch A'),
                step('b', 'root', 'retained branch B', 'branch B')], cursor='root', head='a')))
    doc = Document(); doc.load(original); first = tmp_path / 'synthetic-original.pcad'; doc.write(first)
    original_bytes = first.read_bytes(); loaded = Document(); loaded.load(read_project(first), first)
    snapshot = deepcopy(loaded.project().model_dump(mode='json'))
    explicit_pcb = loaded.design['pcb']; profile = declared_profile(explicit_pcb)
    artifact = X.write_declared_xnc_new(explicit_pcb, profile, tmp_path / 'host-declared.xnc')
    assert artifact['status'] == 'written_declared_cad_data' and explicit_pcb['layer_count'] == 6
    assert loaded.project().model_dump(mode='json') == snapshot and first.read_bytes() == original_bytes
    saved = tmp_path / 'preserved-copy.pcad'; loaded.write(saved)
    reopened = read_project(saved).model_dump(mode='json')
    assert reopened == snapshot
    assert [row['id'] for row in reopened['history']['entries']] == ['root', 'a', 'b']
    assert (reopened['history']['cursor'], reopened['history']['head']) == ('root', 'a')
    # The PCB-only CLI cannot silently extract a board from an entire PCAD.
    output = tmp_path / 'not-silently-extracted.xnc'; profile_file = store(tmp_path, profile, 'host-profile.json')
    code, out, err = invoke(['excellon_export', str(first), '--excellon-profile', str(profile_file), '--output', str(output)])
    assert code == 2 and not out and json.loads(err)['reasons'][0]['code'] == 'UNEXPECTED_DOCUMENT_KIND'
    assert not output.exists() and first.read_bytes() == original_bytes


def test_control_semicolon_and_unicode_source_ids_are_rejected_before_output(tmp_path):
    valid = board(); profile = declared_profile(valid)
    for field in ('ref', 'pin', 'via'):
        for value in ('BAD\nM30', 'BAD\n', 'BAD;T99', 'BAD\x01', '\ubcf4\ub4dc'):
            raw = deepcopy(valid)
            if field == 'ref': raw['components'][0]['ref'] = value
            elif field == 'pin': raw['components'][0]['pins'][0]['number'] = value
            else: raw['vias'][0]['id'] = value
            before = deepcopy(raw)
            unavailable(X.prepare_declared_xnc(raw, profile), 'INVALID_PROFILE_OR_PCB')
            destination = tmp_path / ('rejected-' + field + '.xnc')
            unavailable(X.write_declared_xnc_new(raw, profile, destination), 'INVALID_PROFILE_OR_PCB')
            assert not destination.exists() and raw == before


def test_manifest_distinguishes_declared_xnc_candidate_from_machine_approval():
    manifest = P.MANIFEST; candidate = manifest['excellon_candidate']
    assert 'excellon_prepare' in manifest['commands']
    assert candidate['explicit_profile_required'] is True and candidate['machine_program_qualified'] is False
    assert candidate['dialect'] == 'ucamco-xnc-2021.11-circular-metric-pth'
    assert manifest['permissions'] == dict(automatic_execution=False, network=False, filesystem=False, hardware=False)
    # A blanket denial of all Excellon output contradicts the declared-data
    # workflow. Qualification must remain explicitly separate from generation.
    limits = ' '.join(manifest['limits']).lower()
    assert 'excellon machine output is unavailable' not in limits
    assert 'declared' in limits and 'xnc' in limits and 'machine' in limits
    assert 'qualification' in limits or 'qualified' in limits
