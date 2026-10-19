"""421 new current-host split-XNC integration, independent four-hole oracle."""
from contextlib import redirect_stderr,redirect_stdout
from copy import deepcopy
from decimal import Decimal
from io import StringIO
import hashlib,json,re
from pathlib import Path
import pytest
from cadstudio import pcb_excellon_split as X,pcb_excellon_export as U,pcb_plugin as P,pcb_cli as CLI
from cadstudio.pcb import PCBProject,PCBComponent,PCBVia,pcb_digest
from cadstudio.models import Design

TOOLS={'01':(Decimal('.6'),'ComponentDrill'),'02':(Decimal('.8'),'ComponentDrill'),'03':(Decimal('.3'),'ViaDrill')}
MANUAL={
    'PTH.xnc':{'pad:J1:2':('01',Decimal('10'),Decimal('14')),'via:VA':('03',Decimal('23.125'),Decimal('9.5'))},
    'NPTH.xnc':{'pad:J1:1':('02',Decimal('11'),Decimal('17')),'via:VB':('03',Decimal('31'),Decimal('26'))}}


def fixture():
    p=PCBProject(name='421 four-hole owned board',width_mm=45,height_mm=40,layer_count=4,nets=['GND'],components=[
        PCBComponent(ref='J1',x_mm=12,y_mm=15,rotation_deg=90,fitted=False,pins=[
            dict(number='1',x_mm=2,y_mm=1,diameter_mm=1.6,drill_mm=.8,net='GND',layers=['F.Cu','B.Cu']),
            dict(number='2',x_mm=-1,y_mm=2,diameter_mm=1.4,drill_mm=.6,net='GND',layers=['F.Cu','B.Cu']),
            dict(number='3',diameter_mm=1,drill_mm=0,net='GND',layers=['F.Cu'])])],vias=[
        PCBVia(id='VA',net='GND',x_mm=23.125,y_mm=9.5,diameter_mm=.7,drill_mm=.3),
        PCBVia(id='VB',net='GND',x_mm=31,y_mm=26,diameter_mm=.7,drill_mm=.3)])
    profile=dict(schema_version=1,dialect=X.DIALECT,source_pcb_sha256=pcb_digest(p),units='mm',
        origin=dict(kind='pcb-design',offset_mm=['0','0'],rotation_deg='0',mirror_x=False,mirror_y=False),
        coordinate_format=dict(notation='explicit-decimal',mode='absolute',decimal_places=3,rounding='ROUND_HALF_EVEN',maximum_numeric_rounding_error_mm='0.000000001'),
        diameter_semantics='model_drill_mm_declared_finished_hole_mm',copper_layers=['F.Cu','In1.Cu','In2.Cu','B.Cu'],
        profile_basis='New synthetic software fixture caller declarations only, no physical plating evidence.',
        tools=[dict(number='03',diameter_mm='0.3',function='ViaDrill'),dict(number='02',diameter_mm='0.8',function='ComponentDrill'),dict(number='01',diameter_mm='0.6',function='ComponentDrill')],
        assignments=[dict(source_id=identifier,plating=filename[:-4],tool=tool,declared_drill_span=['F.Cu','B.Cu'])
            for filename,rows in MANUAL.items() for identifier,(tool,x,y) in rows.items()])
    return p.model_dump(mode='json'),profile


def canonical(raw):return json.dumps(raw,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
def digest(data):return hashlib.sha256(data).hexdigest()

def invoke(args):
    out,err=StringIO(),StringIO()
    with redirect_stdout(out),redirect_stderr(err):code=CLI.main(args)
    return code,out.getvalue(),err.getvalue()

def inputs(tmp_path,raw,profile):
    source=tmp_path/'board.json';source.write_bytes(canonical(raw))
    declaration=tmp_path/'profile.json';declaration.write_bytes(canonical(profile))
    return source,declaration,source.read_bytes(),declaration.read_bytes()


def parse_independent(text):
    # Handwritten oracle above, no producer helpers, _holes or quantizer used.
    tools={};hits={};function=None;selected=None;source_id=None
    lines=text.splitlines();assert lines[0]=='M48' and 'METRIC' in lines and lines[-1]=='M30'
    for index,line in enumerate(lines,1):
        if line.startswith('; #@! TA.AperFunction,'):function=line.split(',')[-1]
        elif re.fullmatch(r'T[0-9]{2}C[0-9]+(?:\.[0-9]+)?',line):
            number,diameter=line[1:].split('C');tools[number]=(Decimal(diameter),function)
        elif re.fullmatch(r'T[0-9]{2}',line):selected=line[1:]
        elif line.startswith('; SOURCE '):source_id=line[len('; SOURCE '):]
        elif line.startswith('X'):
            match=re.fullmatch(r'X([+-]?[0-9]+\.[0-9]+)Y([+-]?[0-9]+\.[0-9]+)',line);assert match and selected in tools and source_id not in hits
            hits[source_id]=(selected,Decimal(match[1]),Decimal(match[2]));source_id=None
    assert source_id is None
    return tools,hits


def test_current_api_cli_split_export_matches_manual_partition_and_package_bindings(tmp_path):
    raw,profile=fixture();original=deepcopy(raw),deepcopy(profile)
    prepared=P.execute('excellon_split_prepare',raw,profile=profile)
    assert prepared['status']=='prepared_declared_split_cad_data'
    source,decl,source_bytes,decl_bytes=inputs(tmp_path,raw,profile)
    preview=tmp_path/'preview.json';target=tmp_path/'p'
    code,out,err=invoke(['excellon_split_prepare',str(source),'--excellon-profile',str(decl),'--output',str(preview)])
    assert code==0 and not out and not err and json.loads(preview.read_text())==prepared
    code,out,err=invoke(['excellon_split_export',str(source),'--excellon-profile',str(decl),'--output',str(target)])
    assert code==0 and not err and json.loads(out)['published'] is True
    assert {p.name for p in target.iterdir()}=={'PTH.xnc','NPTH.xnc','manifest.json','COMPLETE.json'}
    manifest=json.loads((target/'manifest.json').read_bytes());complete=json.loads((target/'COMPLETE.json').read_bytes())
    all_ids=set()
    for filename,expected in MANUAL.items():
        text=(target/filename).read_text(encoding='ascii');tools,hits=parse_independent(text)
        assert tools==TOOLS and hits==expected
        classification='Plated,1,4,PTH' if filename=='PTH.xnc' else 'NonPlated,1,4,NPTH'
        assert '; #@! TF.FileFunction,'+classification in text
        assert not (all_ids & set(hits));all_ids.update(hits)
        row=next(r for r in manifest['files'] if r.get('filename')==filename)
        assert set(row['source_ids'])==set(expected) and row['hit_count']==2
        assert row['sha256']==digest((target/filename).read_bytes()) and row['bytes']==len((target/filename).read_bytes())
    assert all_ids==set(manifest['all_source_hole_ids'])==set().union(*(set(v) for v in MANUAL.values()))
    assert manifest['hole_count']==4 and manifest['zero_drill_pad_ids']==['pad:J1:3']
    assert manifest['source_pcb_sha256']==pcb_digest(raw) and manifest['profile_sha256']==digest(canonical(manifest['profile']))
    assert complete['source_pcb_sha256']==manifest['source_pcb_sha256'] and complete['profile_sha256']==manifest['profile_sha256']
    assert {r['filename'] for r in complete['files']}=={'PTH.xnc','NPTH.xnc','manifest.json'}
    for row in complete['files']:
        data=(target/row['filename']).read_bytes();assert row['sha256']==digest(data) and row['bytes']==len(data)
    code,out,err=invoke(['excellon_split_verify',str(source),'--excellon-profile',str(decl),'--excellon-package',str(target)])
    assert code==0 and not err and json.loads(out)['status']=='verified_declared_split_cad_package_only'
    assert all(manifest[key] is False for key in ('manufacturing_qualified','machine_program_qualified','actual_hardware_verified'))
    assert P.MANIFEST['permissions']==dict(automatic_execution=False,network=False,filesystem=False,hardware=False)
    assert (raw,profile)==original and source.read_bytes()==source_bytes and decl.read_bytes()==decl_bytes


def test_missing_explicit_hole_pth_or_npth_declarations_never_write_package(tmp_path):
    raw,profile=fixture();missing_hole=deepcopy(profile);missing_hole['assignments'].pop()
    missing_pth=deepcopy(profile);next(r for r in missing_pth['assignments'] if r['plating']=='PTH').pop('plating')
    missing_npth=deepcopy(profile);next(r for r in missing_npth['assignments'] if r['plating']=='NPTH').pop('plating')
    source=tmp_path/'source.json';source.write_bytes(canonical(raw));before=source.read_bytes()
    for i,declared in enumerate((None,missing_hole,missing_pth,missing_npth)):
        result=P.execute('excellon_split_prepare',raw,profile=declared);assert result['status']=='UNAVAILABLE' and result['files_generated']==[]
        target=tmp_path/('no'+str(i));args=['excellon_split_export',str(source),'--output',str(target)]
        if declared is not None:
            path=tmp_path/('invalid'+str(i)+'.json');path.write_bytes(canonical(declared));args+=['--excellon-profile',str(path)]
        code,out,err=invoke(args)
        assert code==2 and not out and json.loads(err)['status']=='UNAVAILABLE' and not target.exists()
    assert not list(tmp_path.glob('.*.partial-*')) and source.read_bytes()==before


def test_stale_source_and_modified_group_or_manifest_are_not_accepted(tmp_path):
    raw,profile=fixture();target=tmp_path/'p';assert X.write_split_xnc_package_new(raw,profile,target)['published']
    changed=deepcopy(raw);changed['components'][0]['x_mm']+=1
    assert X.verify_split_xnc_package(changed,profile,target)['reasons'][0]['code']=='PROFILE_SOURCE_MISMATCH'
    for filename in ('PTH.xnc','manifest.json'):
        path=target/filename;before=path.read_bytes()
        if filename.endswith('.xnc'):path.write_bytes(before.replace(b'X10.000Y14.000',b'X10.001Y14.000'))
        else:
            bad=json.loads(before);bad['manufacturing_qualified']=True;path.write_bytes(canonical(bad)+b'\n')
        result=X.verify_split_xnc_package(raw,profile,target)
        assert result['status']=='UNAVAILABLE' and result['reasons'][0]['code']=='PACKAGE_CONTENT_MISMATCH'
        path.write_bytes(before)
    assert X.verify_split_xnc_package(raw,profile,target)['status']=='verified_declared_split_cad_package_only'


def test_uniform_module_and_host_compatibility_and_missing_drill_rule_guards_are_preserved(tmp_path):
    raw,profile=fixture();uniform={k:deepcopy(v) for k,v in profile.items() if k not in ('assignments','dialect')}
    uniform.update(dialect=U.DIALECT,declared_drill_span=['F.Cu','B.Cu'],plating='Plated',hole_tools={r['source_id']:r['tool'] for r in profile['assignments']})
    result=P.execute('excellon_prepare',raw,profile=uniform)
    assert result['status']=='prepared_declared_cad_data'
    tools,hits=parse_independent(result['xnc_text']);assert tools==TOOLS and hits=={**MANUAL['PTH.xnc'],**MANUAL['NPTH.xnc']}
    project=dict(format='prompt-cad-project',version=2,design=Design(name='421 current host',parts=[],pcb=PCBProject.model_validate(raw)).model_dump(mode='json'))
    whole=tmp_path/'project.json';whole.write_bytes(canonical(project));before=whole.read_bytes()
    code,out,err=invoke(['compatibility',str(whole)])
    assert code==0 and not err and json.loads(out)['document_kind']=='project' and json.loads(out)['validated'] is True
    kept=tmp_path/'existing.json';kept.write_bytes(b'KEEP REPORT')
    code,out,err=invoke(['compatibility',str(whole),'--output',str(kept)])
    assert code==2 and not out and json.loads(err)['status']=='blocked' and kept.read_bytes()==b'KEEP REPORT'
    pcb=tmp_path/'pcb.json';pcb.write_bytes(canonical(raw));absent=tmp_path/'missing-rules.json'
    code,out,err=invoke(['drill_review',str(pcb),'--drill-gap-mm','.2','--output',str(absent)])
    assert code==2 and not out and json.loads(err)['reasons'][0]['code']=='MISSING_DRILL_RULES' and not absent.exists()
    assert whole.read_bytes()==before


def test_new_directory_no_replace_and_empty_destination_publish_race_are_preserved(tmp_path,monkeypatch):
    raw,profile=fixture();empty=tmp_path/'empty';empty.mkdir()
    assert X.write_split_xnc_package_new(raw,profile,empty)['reasons'][0]['code']=='OUTPUT_EXISTS' and list(empty.iterdir())==[]
    owned=tmp_path/'owned';owned.mkdir();marker=owned/'custom.txt';marker.write_bytes(b'KEEP USER DATA')
    assert X.write_split_xnc_package_new(raw,profile,owned)['reasons'][0]['code']=='OUTPUT_EXISTS' and marker.read_bytes()==b'KEEP USER DATA'
    assert not list(tmp_path.glob('.*.partial-*'))
    original_publish=X._publish;target=tmp_path/'race'
    def compete(stage,destination):
        destination.mkdir();return original_publish(stage,destination)
    monkeypatch.setattr(X,'_publish',compete)
    result=X.write_split_xnc_package_new(raw,profile,target)
    assert result['status']=='PARTIAL_WRITE' and result['complete'] is False and result['published'] is False
    assert result['failed_phase']=='publish' and target.is_dir() and list(target.iterdir())==[]
    stage=Path(result['staging_directory']);assert stage.is_dir() and 'COMPLETE.json' in {p.name for p in stage.iterdir()}
    assert {Path(p).name for p in result['files_generated']}=={p.name for p in stage.iterdir()}
    assert X.verify_split_xnc_package(raw,profile,stage)['reasons'][0]['code']=='UNPUBLISHED_STAGE'


class PrefixErrorStream:
    def __init__(self,stream):self.stream=stream
    def __enter__(self):self.stream.__enter__();return self
    def __exit__(self,*args):return self.stream.__exit__(*args)
    def __getattr__(self,name):return getattr(self.stream,name)
    def write(self,data):
        self.stream.write(data[:11]);self.stream.flush();raise OSError('Owned prefix-write failure')


def test_realistic_prefix_write_or_fsync_errors_report_actual_unpublished_stage(tmp_path,monkeypatch):
    raw,profile=fixture();original=deepcopy(raw),deepcopy(profile);original_open=Path.open
    for fault in ('write','fsync'):
        target=tmp_path/('partial-'+fault)
        with monkeypatch.context() as context:
            if fault=='write':
                def inject(path,*args,**kwargs):
                    stream=original_open(path,*args,**kwargs)
                    return PrefixErrorStream(stream) if path.name=='PTH.xnc' and args and args[0]=='xb' else stream
                context.setattr(Path,'open',inject)
            else:
                def fail_sync(fd):raise OSError('Owned fsync failure')
                context.setattr(X.os,'fsync',fail_sync)
            result=X.write_split_xnc_package_new(raw,profile,target)
        assert result['status']=='PARTIAL_WRITE' and result['complete'] is False and result['published'] is False and result['filesystem_modified'] is True
        assert result['failed_phase']=='write:PTH.xnc' and result['fully_written_items']==[] and not target.exists()
        stage=Path(result['staging_directory']);actual={p.name for p in stage.iterdir()}
        assert actual=={'PTH.xnc'} and {Path(p).name for p in result['files_generated']}==actual
        assert (stage/'PTH.xnc').stat().st_size==11 if fault=='write' else (stage/'PTH.xnc').stat().st_size>11
        assert X.verify_split_xnc_package(raw,profile,stage)['reasons'][0]['code']=='UNPUBLISHED_STAGE'
    assert (raw,profile)==original
