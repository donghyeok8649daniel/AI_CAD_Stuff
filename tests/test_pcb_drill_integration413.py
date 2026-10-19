"""New 413 host API/CLI drill integration; synthetic data and no GUI/kernel."""
from contextlib import redirect_stderr,redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path

import pytest
from cadstudio import pcb_drill_review as D,pcb_plugin as P,pcb_cli as CLI
from cadstudio import pcb_compatibility as C
from cadstudio.pcb import PCBProject,PCBComponent,PCBVia,pcb_digest
from cadstudio.models import Design,Project

SOURCE=Path(__file__).resolve().parents[1]
RULES=dict(minimum_gap_mm=.2,minimum_edge_mm=.2)


def board():
    return PCBProject(name='413 synthetic rotated board',width_mm=40,height_mm=35,layer_count=4,nets=['GND'],
        components=[PCBComponent(ref='J1',x_mm=10,y_mm=20,rotation_deg=90,fitted=False,pins=[
            dict(number='1',x_mm=2,y_mm=3,diameter_mm=1.4,drill_mm=.6,layers=['F.Cu','B.Cu'],net='GND'),
            dict(number='2',x_mm=-1,y_mm=0,diameter_mm=1,drill_mm=0,layers=['F.Cu'],net='GND')])],
        vias=[PCBVia(id='v1',x_mm=20,y_mm=10,diameter_mm=.7,drill_mm=.3,layers=['F.Cu','B.Cu'],net='GND')])


def invoke(args):
    stdout,stderr=StringIO(),StringIO()
    with redirect_stdout(stdout),redirect_stderr(stderr):code=CLI.main(args)
    return code,stdout.getvalue(),stderr.getvalue()


def write_json(tmp_path,raw,name='synthetic-source.pcbp'):
    path=tmp_path/name;path.write_text(json.dumps(raw,ensure_ascii=False),encoding='utf-8')
    return path,path.read_bytes()


@pytest.mark.parametrize('given',[{},dict(minimum_gap_mm=.2)],ids=['both-absent','edge-absent'])
def test_missing_rules_are_unavailable_in_producer_consumer_and_cli(tmp_path,given):
    raw=board().model_dump(mode='json');original=deepcopy(raw)
    result=P.execute('drill_review',raw,**given)
    assert result['status']=='UNAVAILABLE' and result['reasons'][0]['code']=='MISSING_DRILL_RULES'
    assert not result['data_modified'] and result['files_generated']==[] and raw==original
    # Consumer must not adopt a legacy null-rule review as a reviewed result.
    retained=P.execute('drill_review',raw,**RULES)
    for name in RULES:retained['rules'][name]=given.get(name)
    verified=P.execute('drill_review_verify',raw,review_report=retained)
    assert verified['status']=='UNAVAILABLE' and verified['reasons'][0]['code']=='MISSING_DRILL_RULES'
    source,before=write_json(tmp_path,raw);target=tmp_path/'missing-rules.json'
    args=['drill_review',str(source),'--output',str(target)]
    if 'minimum_gap_mm' in given:args+=['--drill-gap-mm',str(given['minimum_gap_mm'])]
    code,stdout,stderr=invoke(args)
    assert code==2 and not stdout and json.loads(stderr)['reasons'][0]['code']=='MISSING_DRILL_RULES'
    assert not target.exists() and source.read_bytes()==before


def test_rotated_pad_via_layers_and_explicit_rule_metadata_use_current_api(monkeypatch):
    assert Path(D.__file__).resolve()==SOURCE/'cadstudio/pcb_drill_review.py'
    assert Path(P.__file__).resolve()==SOURCE/'cadstudio/pcb_plugin.py'
    assert Path(CLI.__file__).resolve()==SOURCE/'cadstudio/pcb_cli.py'
    original_function=D.drill_review;calls=[]
    def spy(payload,**options):
        calls.append(deepcopy(options));return original_function(payload,**options)
    monkeypatch.setattr(D,'drill_review',spy)
    raw=board().model_dump(mode='json');before=deepcopy(raw)
    result=P.execute('drill_review',raw,**RULES)
    assert calls==[RULES] and raw==before and result['status']=='reviewed'
    holes={h['id']:h for h in result['holes']}
    assert holes['pad:J1:1']['center_mm']==pytest.approx([7,22])
    assert holes['pad:J1:1']['declared_copper_layers']==['F.Cu','B.Cu']
    assert holes['pad:J1:1']['component_fitted'] is False
    assert result['zero_drill_pad_ids']==['pad:J1:2']
    assert holes['via:v1']['expanded_copper_span']==['F.Cu','In1.Cu','In2.Cu','B.Cu']
    assert result['copper_layers']==['F.Cu','In1.Cu','In2.Cu','B.Cu'] and result['layer_count']==4
    assert result['source_pcb_sha256']==pcb_digest(board()) and result['units']=='mm'
    assert result['origin']['offset_mm']==[0.,0.] and result['origin']['machine_origin']=='UNAVAILABLE'
    assert result['rules']['minimum_gap_mm']==.2 and result['rules']['minimum_edge_mm']==.2
    assert result['manufacturing_qualified'] is False and result['actual_hardware_verified'] is False
    assert P.MANIFEST['permissions']==dict(automatic_execution=False,network=False,filesystem=False,hardware=False)


def test_truncated_findings_keep_totals_omissions_and_consumer_limits():
    p=PCBProject(width_mm=10,height_mm=10,nets=['GND'],vias=[
        PCBVia(id='v'+str(i),x_mm=.3+i*.15,y_mm=.3,diameter_mm=1,drill_mm=.8,net='GND') for i in range(3)])
    result=P.execute('drill_review',p.model_dump(mode='json'),minimum_gap_mm=.5,minimum_edge_mm=.5,max_findings=1)
    assert result['measurements']['hole_count']==3 and result['measurements']['pair_comparisons']==3
    assert result['findings_total']==6 and len(result['findings'])==1 and result['findings_omitted']==5
    assert result['findings_complete'] is False and result['declared_rule_violations_present'] is True
    verified=P.execute('drill_review_verify',p.model_dump(mode='json'),review_report=result)
    assert verified['status']=='verified_model_review_only' and verified['complete_finding_details'] is False
    assert verified['declared_rule_violations_present'] is True and verified['manufacturing_qualified'] is False


def test_consumer_rejects_stale_tampered_and_bool_as_numeric_reports():
    raw=board().model_dump(mode='json');review=P.execute('drill_review',raw,**RULES)
    changed=deepcopy(raw);changed['components'][0]['x_mm']+=1
    result=P.execute('drill_review_verify',changed,review_report=review)
    assert result['status']=='UNAVAILABLE' and result['reasons'][0]['code']=='SOURCE_MISMATCH'
    mutations=[lambda r:r['holes'][0]['center_mm'].__setitem__(0,True),
        lambda r:r['board'].__setitem__('width_mm',True),lambda r:r.__setitem__('findings_total',True),
        lambda r:r.__setitem__('schema_version',True),lambda r:r.__setitem__('max_findings',True)]
    for mutate in mutations:
        bad=deepcopy(review);mutate(bad)
        rejected=P.execute('drill_review_verify',raw,review_report=bad)
        assert rejected['status']=='UNAVAILABLE' and not rejected['data_modified']
    assert review==P.execute('drill_review',raw,**RULES)


def test_invalid_explicit_rules_never_become_zero_or_success():
    raw=board().model_dump(mode='json');before=deepcopy(raw)
    for options in (dict(minimum_gap_mm=True,minimum_edge_mm=.2),dict(minimum_gap_mm=.2,minimum_edge_mm=float('nan')),
                    dict(minimum_gap_mm=-1,minimum_edge_mm=.2),dict(minimum_gap_mm='not-a-distance',minimum_edge_mm=.2)):
        result=P.execute('drill_review',raw,**options)
        assert result['status']=='UNAVAILABLE' and result['reasons'][0]['code']=='INVALID_PCB_OR_RULE'
        assert not result['data_modified'] and result['files_generated']==[]
    zero=P.execute('drill_review',raw,minimum_gap_mm=0,minimum_edge_mm=0)
    assert zero['status']=='reviewed' and zero['rules']['minimum_gap_mm']==0 and zero['rules']['minimum_edge_mm']==0
    assert raw==before


def test_cli_producer_consumer_only_create_new_reports_and_keep_source(tmp_path):
    raw=board().model_dump(mode='json');source,before=write_json(tmp_path,raw,'synthetic-source.json')
    report_path=tmp_path/'new-review.json'
    base=['drill_review',str(source),'--drill-gap-mm','.2','--drill-edge-mm','.2']
    code,stdout,stderr=invoke(base+['--output',str(report_path)])
    assert code==0 and not stdout and not stderr
    review=json.loads(report_path.read_text(encoding='utf-8'));assert review['status']=='reviewed'
    retained=report_path.read_bytes();proof=tmp_path/'new-consumer-result.json'
    consume=['drill_review_verify',str(source),'--review-report',str(report_path)]
    code,stdout,stderr=invoke(consume+['--output',str(proof)])
    assert code==0 and not stdout and not stderr and json.loads(proof.read_text())['status']=='verified_model_review_only'
    for args in (base+['--output',str(report_path)],consume+['--output',str(source)]):
        code,stdout,stderr=invoke(args)
        assert code==2 and not stdout and json.loads(stderr)['status']=='blocked'
    assert source.read_bytes()==before and report_path.read_bytes()==retained


def test_cli_refuses_manufacturing_extensions_and_formats_without_fallback(tmp_path):
    source,before=write_json(tmp_path,board().model_dump(mode='json'))
    base=['drill_review',str(source),'--drill-gap-mm','.2','--drill-edge-mm','.2']
    for suffix in ('.gbr','.drl'):
        output=tmp_path/('not-manufacturing'+suffix)
        code,stdout,stderr=invoke(base+['--output',str(output)])
        assert code==2 and not stdout and json.loads(stderr)['reasons'][0]['code']=='UNSUPPORTED_OUTPUT_EXTENSION'
        assert not output.exists()
    for requested in ('gerber','excellon'):
        output=tmp_path/(requested+'.json')
        code,stdout,stderr=invoke(base+['--review-format',requested,'--output',str(output)])
        assert code==2 and not stdout and json.loads(stderr)['reasons'][0]['code']=='UNSUPPORTED_OUTPUT_FORMAT'
        assert not output.exists()
    assert source.read_bytes()==before


def test_drill_cli_merge_keeps_root_compatibility_raw_report_and_output_guards(tmp_path):
    raw=board().model_dump(mode='json');source,before=write_json(tmp_path,raw)
    code,stdout,stderr=invoke(['compatibility',str(source)])
    assert code==0 and not stderr and json.loads(stdout)['status']=='compatible' and json.loads(stdout)['validated']
    target=tmp_path/'owned-compatibility.json';target.write_bytes(b'KEEP OWNED REPORT')
    code,stdout,stderr=invoke(['compatibility',str(source),'--output',str(target)])
    assert code==2 and not stdout and json.loads(stderr)['status']=='blocked' and target.read_bytes()==b'KEEP OWNED REPORT'
    assert source.read_bytes()==before


def test_raw_source_and_host_journal_are_not_rewritten_or_silently_extracted(tmp_path):
    initial=Design(name='413 host journal',parts=[],pcb=board()).model_dump(mode='json')
    current=deepcopy(initial);current['pcb']['components'][0]['x_mm']=11.
    entry=lambda i,p,c:dict(id=i,parent=p,label=i,created_at='2026-10-18T00:00:00Z',source='manual',context={},changes=c)
    raw=dict(format='prompt-cad-project',version=2,design=current,prompt='',history=dict(version=1,base=initial,
        entries=[entry('start',None,[]),entry('moved','start',[dict(path=['pcb','components',0,'x_mm'],operation='set',existed=True,before=10.,after=11.)])],
        cursor='moved',head='moved'))
    before=deepcopy(raw);typed=Project.model_validate(raw);typed_before=typed.model_dump(mode='json')
    report=P.execute('drill_review',typed.design.pcb,**RULES)
    assert report['source_pcb_sha256']==pcb_digest(typed.design.pcb) and raw==before and typed.model_dump(mode='json')==typed_before
    source,source_bytes=write_json(tmp_path,raw,'synthetic-history.pcad');output=tmp_path/'not-extracted.json'
    code,stdout,stderr=invoke(['drill_review',str(source),'--drill-gap-mm','.2','--drill-edge-mm','.2','--output',str(output)])
    assert code==2 and not stdout and json.loads(stderr)['reasons'][0]['code']=='UNEXPECTED_DOCUMENT_KIND'
    assert not output.exists() and source.read_bytes()==source_bytes and raw==before
    exported=tmp_path/'new-preserved-history.pcad';C.write_compatible_export(raw,exported)
    assert json.loads(exported.read_text())==raw and source.read_bytes()==source_bytes
