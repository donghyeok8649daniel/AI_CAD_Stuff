"""423 finite declaration-draft integration: new synthetic source only."""
from contextlib import redirect_stderr,redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
from cadstudio import pcb_excellon_declarations as D,pcb_excellon_split as X,pcb_excellon_export as U,pcb_cli as CLI,pcb_plugin as P
from cadstudio.models import Design
from cadstudio.pcb import PCBProject,PCBComponent,PCBVia,pcb_digest


def board(partial=False):
    return PCBProject(name='423 owned declaration source',width_mm=35,height_mm=30,layer_count=4,nets=['GND'],components=[
        PCBComponent(ref='DNP',fitted=False,x_mm=8,y_mm=10,rotation_deg=180,pins=[
            dict(number='A',x_mm=1,y_mm=2,diameter_mm=2,drill_mm=1,net='GND',layers=['F.Cu','B.Cu']),
            dict(number='Z',diameter_mm=1.2,drill_mm=0,net='GND',layers=['F.Cu'])])],vias=[
        PCBVia(id='VC',x_mm=18.25,y_mm=16.5,diameter_mm=.8,drill_mm=.4,net='GND',layers=['F.Cu','In1.Cu'] if partial else ['F.Cu','B.Cu'])]).model_dump(mode='json')


def manual_profile(draft):
    # Caller-entered fixture declarations, independent of net/fitted inference.
    profile=deepcopy(draft['caller_profile_skeleton'])
    profile.update(units='mm',origin=dict(kind='pcb-design',offset_mm=['0','0'],rotation_deg='0',mirror_x=False,mirror_y=False),
        coordinate_format=dict(notation='explicit-decimal',mode='absolute',decimal_places=3,rounding='ROUND_HALF_EVEN',maximum_numeric_rounding_error_mm='0.000000001'),
        diameter_semantics='model_drill_mm_declared_finished_hole_mm',profile_basis='Synthetic caller declaration only; no physical plating or manufacturing evidence.',
        tools=[dict(number='21',diameter_mm='1.0',function='ComponentDrill'),dict(number='22',diameter_mm='0.4',function='ViaDrill')])
    explicit={'pad:DNP:A':('NPTH','21'),'via:VC':('PTH','22')}
    for row in profile['assignments']:
        row['plating'],row['tool']=explicit[row['source_id']];row['declared_drill_span']=['F.Cu','B.Cu']
    return profile


def invoke(args):
    out,err=StringIO(),StringIO()
    with redirect_stdout(out),redirect_stderr(err):code=CLI.main(args)
    return code,out.getvalue(),err.getvalue()


def test_source_inventory_stable_ids_and_caller_nulls_do_not_imply_a_profile():
    raw=board();before=deepcopy(raw)
    result=P.execute('excellon_split_declaration_draft',raw)
    assert result==D.split_declaration_draft(raw) and raw==before
    assert result['status']=='REQUIRES_CALLER_DECLARATIONS' and result['source_pcb_sha256']==pcb_digest(raw)
    assert result['source_hole_count']==2 and result['zero_drill_pad_ids']==['pad:DNP:Z']
    rows={r['source_id']:r for r in result['source_inventory']}
    assert list(rows)==['pad:DNP:A','via:VC'] and rows['pad:DNP:A']['component_fitted'] is False
    assert rows['pad:DNP:A']['source_kind']=='pad' and rows['pad:DNP:A']['source_model_drill_mm']=='1.0'
    xy=list(map(float,rows['pad:DNP:A']['source_xy_mm']));assert abs(xy[0]-7)<1e-12 and abs(xy[1]-8)<1e-12
    assert rows['via:VC']['source_expanded_copper_span']==['F.Cu','In1.Cu','In2.Cu','B.Cu']
    assert rows['via:VC']['source_model_drill_mm']=='0.4' and rows['via:VC']['source_net']=='GND'
    skeleton=result['caller_profile_skeleton'];assert skeleton['source_pcb_sha256']==result['source_pcb_sha256']
    assert skeleton['copper_layers']==['F.Cu','In1.Cu','In2.Cu','B.Cu']
    for field in ('units','origin','coordinate_format','diameter_semantics','profile_basis','tools'):assert skeleton[field] is None
    for row in skeleton['assignments']:
        assert row['source_id'] in rows and row['plating'] is None and row['tool'] is None and row['declared_drill_span'] is None
    assert result['files_generated']==[] and result['automatic_export'] is False and result['exportability']=='UNAVAILABLE'
    assert all(result[k] is False for k in ('manufacturing_qualified','machine_program_qualified','actual_hardware_verified'))
    assert result['physical_plating']==result['physical_finished_hole_interpretation']==result['physical_depth']=='UNAVAILABLE'


def test_unfilled_draft_cannot_export_and_partial_span_blocker_keeps_every_source_hole(tmp_path):
    raw=board();draft=D.split_declaration_draft(raw)
    for index,unfilled in enumerate((draft,draft['caller_profile_skeleton'])):
        result=X.prepare_split_xnc(raw,unfilled);assert result['status']=='UNAVAILABLE'
        destination=tmp_path/('no'+str(index));written=X.write_split_xnc_package_new(raw,unfilled,destination)
        assert written['status']=='UNAVAILABLE' and written['files_generated']==[] and not destination.exists()
    partial=board(partial=True);partial_before=deepcopy(partial);partial_draft=D.split_declaration_draft(partial)
    assert {r['source_id'] for r in partial_draft['source_inventory']}=={'pad:DNP:A','via:VC'}
    assert partial_draft['source_blockers']==[dict(code='UNSUPPORTED_VIA_SPAN',source_id='via:VC')]
    row=next(r for r in partial_draft['source_inventory'] if r['source_id']=='via:VC')
    assert row['source_copper_layers']==row['source_expanded_copper_span']==['F.Cu','In1.Cu']
    declared=manual_profile(partial_draft);target=tmp_path/'partial-refused'
    result=X.write_split_xnc_package_new(partial,declared,target)
    assert result['status']=='UNAVAILABLE' and result['reasons'][0]['code']=='UNSUPPORTED_VIA_SPAN'
    assert not target.exists() and not list(tmp_path.glob('.*.partial-*')) and partial==partial_before


def test_manual_declarations_stale_binding_and_cli_exclusive_json_and_unrelated_flags(tmp_path):
    raw=board();draft=D.split_declaration_draft(raw);profile=manual_profile(draft)
    assert X.prepare_split_xnc(raw,profile)['status']=='prepared_declared_split_cad_data'
    changed=deepcopy(raw);changed['name']='Changed current source identity'
    assert X.prepare_split_xnc(changed,profile)['reasons'][0]['code']=='PROFILE_SOURCE_MISMATCH'
    assert D.split_declaration_draft(changed)['source_pcb_sha256']!=draft['source_pcb_sha256']
    assert P.execute('excellon_split_declaration_draft',raw,profile=profile)['reasons'][0]['code']=='UNSUPPORTED_REQUEST_OPTION'
    source=tmp_path/'source.json';source.write_text(json.dumps(raw),encoding='utf-8');before=source.read_bytes()
    output=tmp_path/'draft.json'
    code,out,err=invoke(['excellon_split_declaration_draft',str(source),'--output',str(output)])
    assert code==0 and not out and not err and json.loads(output.read_text())==draft
    retained=output.read_bytes();code,out,err=invoke(['excellon_split_declaration_draft',str(source),'--output',str(output)])
    assert code==2 and not out and json.loads(err)['status']=='blocked' and output.read_bytes()==retained
    fabrication=tmp_path/'not-output.xnc';code,out,err=invoke(['excellon_split_declaration_draft',str(source),'--output',str(fabrication)])
    assert code==2 and not out and json.loads(err)['reasons'][0]['code']=='UNSUPPORTED_DRAFT_OUTPUT_EXTENSION' and not fabrication.exists()
    profile_path=tmp_path/'manual.json';profile_path.write_text(json.dumps(profile),encoding='utf-8');profile_bytes=profile_path.read_bytes()
    for options in (['--excellon-profile',str(profile_path)],['--review-format','gerber']):
        target=tmp_path/'unrelated.json';code,out,err=invoke(['excellon_split_declaration_draft',str(source),*options,'--output',str(target)])
        assert code==2 and not out and json.loads(err)['status']=='blocked' and not target.exists()
    assert source.read_bytes()==before and profile_path.read_bytes()==profile_bytes


def test_new_declaration_dispatch_keeps_mixed_uniform_and_host_guard_payloads(tmp_path):
    raw=board();original=deepcopy(raw);draft=P.execute('excellon_split_declaration_draft',raw);profile=manual_profile(draft)
    mixed=P.execute('excellon_split_prepare',raw,profile=profile)
    assert mixed['status']=='prepared_declared_split_cad_data' and set(mixed['xnc_files'])=={'PTH.xnc','NPTH.xnc'}
    assert set(mixed['manifest']['all_source_hole_ids'])=={'pad:DNP:A','via:VC'}
    uniform={k:deepcopy(v) for k,v in profile.items() if k not in ('dialect','assignments')}
    uniform.update(dialect=U.DIALECT,plating='Plated',declared_drill_span=['F.Cu','B.Cu'],hole_tools={'pad:DNP:A':'21','via:VC':'22'})
    result=P.execute('excellon_prepare',raw,profile=uniform)
    assert result['status']=='prepared_declared_cad_data' and {r['source_id'] for r in result['traceability']}=={'pad:DNP:A','via:VC'}
    project=dict(design=Design(name='423 temporary host payload',parts=[],pcb=PCBProject.model_validate(raw)).model_dump(mode='json'))
    path=tmp_path/'project.json';path.write_text(json.dumps(project),encoding='utf-8');before=path.read_bytes()
    code,out,err=invoke(['compatibility',str(path)])
    assert code==0 and not err and json.loads(out)['validated'] and json.loads(out)['document_kind']=='project'
    report=tmp_path/'keep.json';report.write_bytes(b'KEEP')
    code,out,err=invoke(['compatibility',str(path),'--output',str(report)])
    assert code==2 and not out and report.read_bytes()==b'KEEP'
    missing=P.execute('drill_review',raw,minimum_gap_mm=.2)
    assert missing['status']=='UNAVAILABLE' and missing['reasons'][0]['code']=='MISSING_DRILL_RULES'
    assert raw==original and path.read_bytes()==before
