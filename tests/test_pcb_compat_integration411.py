"""411 host integration only: current Project, compatibility API/CLI/plugin.

These are new small host-bound fixtures, not the owner's 26+6 compatibility
checks. No Document read hook, Qt, geometry, provider, profile, or user file.
"""
import ast
from contextlib import redirect_stderr,redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import sys

import pytest
from cadstudio.models import Design,Project
from cadstudio.pcb import PCBProject,PCBComponent,pcb_digest
from cadstudio.pcb_cost_workflow import with_cost_inputs,adopt_cost_proposal
from cadstudio import pcb_compatibility as C
from cadstudio import pcb_cli as CLI
from cadstudio import pcb_plugin as P

SOURCE=Path(__file__).resolve().parents[1]
OLD='pcb-v1-pre407'


def boards():
    plain=PCBProject(name='411 host board',components=[
        PCBComponent(ref='R1',mpn='Fixture-R',pins=[dict(number='1')]),
        PCBComponent(ref='U1',mpn='Fixture-U',pins=[dict(number='1')],x_mm=20)])
    quoted=with_cost_inputs(plain,dict(quantity_breaks={'R1':[
        dict(minimum_quantity=1,unit_price='3',currency='USD',status='reference',
             as_of='2026-01-01',supplier='Owned fixture',source_url='https://example.com/owned-tier')]}))
    quoted=adopt_cost_proposal(quoted,dict(schema_version=1,base_sha256=pcb_digest(quoted),
        summary='Owned synthetic range, no provider or vendor request.',rows=[
            dict(refs=['U1'],mpn='Fixture-U',required_quantity=1,purchase_quantity=1,
                 minimum_unit_price='2',maximum_unit_price='4',currency='USD',basis='Owned integration fixture only')]))
    return plain,quoted


def history_payload():
    plain,quoted=boards()
    base=Design(name='411 history-only provenance',parts=[],pcb=plain).model_dump(mode='json')
    accepted=Design(name=base['name'],parts=[],pcb=quoted).model_dump(mode='json')
    def entry(identifier,parent,before=None,after=None):
        changes=[] if before is None else [dict(path=['pcb'],operation='set',existed=True,before=before,after=after)]
        return dict(id=identifier,parent=parent,label=identifier,created_at='2026-10-18T00:00:00Z',
                    source='manual',context={},changes=changes)
    return dict(format='prompt-cad-project',version=2,design=deepcopy(base),prompt='',history=dict(
        version=1,base=deepcopy(base),entries=[entry('start',None),entry('quote','start',base['pcb'],accepted['pcb']),
            entry('plain-again','quote',accepted['pcb'],base['pcb'])],cursor='plain-again',head='plain-again'))


def invoke(args):
    stdout,stderr=StringIO(),StringIO()
    with redirect_stdout(stdout),redirect_stderr(stderr):code=CLI.main(args)
    return code,stdout.getvalue(),stderr.getvalue()


def write_input(tmp_path,raw,name='owned-input.json'):
    path=tmp_path/name;path.write_text(json.dumps(raw,ensure_ascii=False),encoding='utf-8')
    return path,path.read_bytes()


def test_actual_host_project_history_accepts407_but_requires_capable_target():
    raw=history_payload();before=deepcopy(raw)
    checked=Project.model_validate(raw)
    assert checked.history.cursor=='plain-again' and len(checked.history.entries)==3
    assert not raw['design']['pcb']['budget'].get('cost_inputs')
    report=C.validate_payload(raw)
    assert report['validated'] and report['document_kind']=='project'
    assert C.FEATURE in report['required_features'] and C.PRICE_GUARD in report['required_features']
    assert any(row['path'].startswith('/history/') for row in report['feature_locations'])
    with pytest.raises(C.PCBCompatibilityError) as caught:C.validate_payload(raw,OLD)
    assert caught.value.report['status']=='blocked' and not caught.value.report['data_modified']
    assert any(reason['code']=='UNSUPPORTED_FEATURE' for reason in caught.value.report['reasons'])
    assert raw==before


def test_raw_export_preserves_explicit_tree_and_requires_a_new_destination(tmp_path):
    _,quoted=boards();raw=quoted.model_dump(mode='json')
    raw.update(layer_count=2,net_labels={},vias=[],zones=[])
    assert PCBProject.model_validate(raw).model_dump(mode='json')!=raw
    original=deepcopy(raw);destination=tmp_path/'new-raw.pcbp'
    result=C.write_compatible_export(raw,destination)
    assert result['validated'] and json.loads(destination.read_text(encoding='utf-8'))==raw==original
    kept=destination.read_bytes()
    with pytest.raises(C.PCBCompatibilityError) as caught:C.write_compatible_export(raw,destination)
    assert caught.value.code=='OUTPUT_EXISTS' and destination.read_bytes()==kept
    forbidden=tmp_path/'no-lossy-downgrade.pcbp'
    with pytest.raises(C.PCBCompatibilityError):C.write_compatible_export(raw,forbidden,OLD)
    assert not forbidden.exists() and raw==original


def test_cli_compatibility_supported_current_pcb_returns_a_validated_report(tmp_path):
    _,quoted=boards();path,source_bytes=write_input(tmp_path,quoted.model_dump(mode='json'))
    code,stdout,stderr=invoke(['compatibility',str(path)])
    assert code==0 and not stderr
    report=json.loads(stdout)
    assert report['compatible'] is True and report['status']=='compatible' and report['validated'] is True
    assert C.FEATURE in report['required_features'] and path.read_bytes()==source_bytes


def test_cli_compatibility_old_profile_is_structurally_blocked_without_output(tmp_path):
    _,quoted=boards();path,source_bytes=write_input(tmp_path,quoted.model_dump(mode='json'))
    code,stdout,stderr=invoke(['compatibility',str(path),'--target-profile',OLD])
    assert code==2 and not stdout
    report=json.loads(stderr)
    assert report['status']=='blocked' and not report['compatible']
    assert report['fields_removed']==[] and not report['automatic_migration']
    assert path.read_bytes()==source_bytes


def test_cli_compatibility_report_never_overwrites_an_existing_destination(tmp_path):
    _,quoted=boards();path,source_bytes=write_input(tmp_path,quoted.model_dump(mode='json'))
    destination=tmp_path/'existing-owned-report.json';destination.write_bytes(b'OWNED SENTINEL')
    code,stdout,stderr=invoke(['compatibility',str(path),'--output',str(destination)])
    assert code==2 and not stdout and json.loads(stderr)['status']=='blocked'
    assert destination.read_bytes()==b'OWNED SENTINEL' and path.read_bytes()==source_bytes


def test_host_cli_project_preflight_and_export_keep_historical_contexts(tmp_path):
    raw=history_payload();path,source_bytes=write_input(tmp_path,raw,'owned-history.pcad')
    code,stdout,stderr=invoke(['preflight',str(path)])
    assert code==0 and not stderr and json.loads(stdout)['validated']
    destination=tmp_path/'new-history.pcad'
    code,stdout,stderr=invoke(['export',str(path),'--output',str(destination)])
    assert code==0 and not stderr and json.loads(stdout)['status']=='exported'
    assert json.loads(destination.read_text(encoding='utf-8'))==raw
    blocked=tmp_path/'blocked-history.pcad'
    code,stdout,stderr=invoke(['export',str(path),'--output',str(blocked),'--target-profile',OLD])
    assert code==2 and not stdout and json.loads(stderr)['status']=='blocked'
    assert not blocked.exists() and path.read_bytes()==source_bytes


def test_host_api_cli_plugin_and_workbench_hooks_bind_without_gui_or_schema_side_effects(monkeypatch):
    assert Path(C.__file__).resolve()==SOURCE/'cadstudio/pcb_compatibility.py'
    assert Path(CLI.__file__).resolve()==SOURCE/'cadstudio/pcb_cli.py'
    assert Path(P.__file__).resolve()==SOURCE/'cadstudio/pcb_plugin.py'
    assert CLI.decode_compatible is C.decode_compatible and CLI.write_compatible_export is C.write_compatible_export
    code,stdout,stderr=invoke(['manifest']);assert code==0 and not stderr
    manifest=json.loads(stdout)
    assert 'compatibility' in manifest['commands']
    assert set(manifest['file_compatibility_profiles'])==set(C.PROFILES)
    assert manifest['permissions']==dict(automatic_execution=False,network=False,filesystem=False,hardware=False)
    assert manifest['geometry']['copper_layers']==[2,4,6,8]
    raw=history_payload();before=deepcopy(raw);original_manifest=deepcopy(P.MANIFEST)
    def forbidden(*a,**k):raise AssertionError('Read-only compatibility command must not construct PCBProject.')
    monkeypatch.setattr(P.PCBProject,'model_validate',forbidden)
    report=P.execute('compatibility',raw,target_profile=OLD)
    assert report['status']=='blocked' and not report['validated'] and raw==before and P.MANIFEST==original_manifest
    tree=ast.parse((SOURCE/'cadstudio/native/pcb_workbench.py').read_text(encoding='utf-8-sig'))
    cls=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='PCBWorkbench')
    methods={node.name:node for node in cls.body if isinstance(node,ast.FunctionDef)}
    for method,helper in [('load_file','decode_compatible'),('export_file','encode_compatible')]:
        assert any(isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id==helper for node in ast.walk(methods[method]))
    assert not any(name in sys.modules for name in ('PySide6','vtkmodules','OCP','cadquery'))


def test_nonpcb_labels_do_not_trigger_features_but_unknown_schema_remains_blocked(tmp_path):
    raw=dict(format='prompt-cad-project',version=2,design=Design(
        name='quantity_break_contexts accepted_ai_quote_contexts',parts=[]).model_dump(mode='json'))
    assert C.validate_payload(raw,OLD)['required_features']==[]
    plain,_=boards();future=plain.model_dump(mode='json');future['schema_version']=99
    original=deepcopy(future)
    with pytest.raises(C.PCBCompatibilityError) as caught:C.validate_payload(future)
    assert caught.value.code=='UNSUPPORTED_VERSION' and future==original
    path,before=write_input(tmp_path,future,'future-version.pcbp')
    code,stdout,stderr=invoke(['compatibility',str(path)])
    assert code==2 and not stdout and json.loads(stderr)['reasons'][0]['code']=='UNSUPPORTED_VERSION'
    assert path.read_bytes()==before


def test_empty_price_history_is_legacy_compatible_but_removed_saved_prices_are_blocked():
    plain,_=boards()
    empty=with_cost_inputs(plain,{})
    base=Design(name='Known empty price fields',parts=[],pcb=empty).model_dump(mode='json')
    def entry(identifier,parent,changes):
        return dict(id=identifier,parent=parent,label=identifier,created_at='2026-10-18T00:00:00Z',
                    source='manual',context={},changes=changes)
    def project(before,after,changes):
        return dict(format='prompt-cad-project',version=2,design=deepcopy(after),prompt='',history=dict(
            version=1,base=deepcopy(before),entries=[entry('start',None,[]),entry('empty','start',changes)],
            cursor='empty',head='empty'))
    changes=[dict(path=['pcb','budget','cost_inputs',key],operation='set',existed=True,
                  before=value,after=deepcopy(value)) for key,value in [('quantity_breaks',{}),('accepted_ai_estimates',[])]]
    raw=project(base,base,changes);original=deepcopy(raw)
    Project.model_validate(raw)
    report=C.validate_payload(raw,OLD)
    assert report['compatible'] and report['validated'] and report['required_features']==[] and raw==original
    # A removed old saved schedule still needs fail-closed price semantics.
    saved_pcb=deepcopy(base['pcb'])
    saved_pcb['budget']['cost_inputs']['quantity_breaks']={'R1':[dict(minimum_quantity=1,unit_price='3',currency='USD',
        as_of='2026-01-01',supplier='Owned fixture',source_url='https://example.com/owned-old-tier')]}
    saved=Design(name=base['name'],parts=[],pcb=PCBProject.model_validate(saved_pcb)).model_dump(mode='json')
    removed=[dict(path=['pcb','budget','cost_inputs','quantity_breaks'],operation='set',existed=True,
                  before=deepcopy(saved['pcb']['budget']['cost_inputs']['quantity_breaks']),after={})]
    raw=project(saved,base,removed);Project.model_validate(raw)
    with pytest.raises(C.PCBCompatibilityError) as caught:C.validate_payload(raw,OLD)
    assert C.PRICE_GUARD in caught.value.report['required_features']
    assert any(reason['code']=='POTENTIAL_STALE_PRICE_REVIVAL' for reason in caught.value.report['reasons'])
