"""Explicit per-hole PTH/NPTH XNC packages. Declared CAD data only.

XNC2021.11 section4.1 requires separate plated/non-plated files.
Windows-only new-directory publication; no overwrite or rollback deletion.
"""
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import uuid
from typing import Literal
from pydantic import Field,model_validator
from .pcb import PCBProject,pcb_digest,copper_layers
from .pcb_drill_review import _holes
from .pcb_excellon_export import (ProfileData,Origin,CoordinateFormat,Tool,
    number,decimal_token,quantized,unavailable,decode_export_profile)

DIALECT='ucamco-xnc-2021.11-split-circular-metric'
GROUPS=('PTH','NPTH')
FLAGS=dict(manufacturing_qualified=False,machine_program_qualified=False,actual_hardware_verified=False)


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':')).encode('utf-8')


def sha(data):return hashlib.sha256(data).hexdigest()


class HoleAssignment(ProfileData):
    source_id: str=Field(min_length=1,max_length=150)
    plating: Literal['PTH','NPTH']
    tool: str=Field(pattern=r'^(?:0[1-9]|[1-9][0-9])$')
    declared_drill_span: list[str]=Field(min_length=2,max_length=2)
    @model_validator(mode='after')
    def full_span(self):
        if self.declared_drill_span!=['F.Cu','B.Cu']:raise ValueError('Only explicitly declared full-board circular holes are supported.')
        return self


class SplitProfile(ProfileData):
    schema_version: Literal[1]
    dialect: Literal['ucamco-xnc-2021.11-split-circular-metric']
    source_pcb_sha256: str=Field(pattern=r'^[a-f0-9]{64}$')
    units: Literal['mm']
    origin: Origin
    coordinate_format: CoordinateFormat
    diameter_semantics: Literal['model_drill_mm_declared_finished_hole_mm']
    copper_layers: list[str]=Field(min_length=2,max_length=8)
    profile_basis: str=Field(min_length=1,max_length=1500)
    tools: list[Tool]=Field(min_length=1,max_length=99)
    assignments: list[HoleAssignment]=Field(min_length=1,max_length=1024)
    @model_validator(mode='before')
    @classmethod
    def integer_version(cls,value):
        if not isinstance(value,dict) or type(value.get('schema_version')) is not int or value['schema_version']!=1:raise ValueError('Explicit integer schema_version1 required.')
        return value
    @model_validator(mode='after')
    def declarations(self):
        if not self.profile_basis.strip():raise ValueError('An explicit interpretation basis is required.')
        if len({t.number for t in self.tools})!=len(self.tools):raise ValueError('Duplicate tool numbers.')
        return self


def prepare_split_xnc(project,profile):
    if profile is None:return unavailable('PROFILE_REQUIRED','Every source hole needs an explicit source-bound plating, tool and full-board span declaration.')
    try:
        checked=SplitProfile.model_validate(profile);p=PCBProject.model_validate(project)
    except (ValueError,TypeError) as exc:
        details=[dict(path=list(r['loc']),type=r['type']) for r in exc.errors(include_url=False,include_input=False)][:32] if hasattr(exc,'errors') else []
        return unavailable('INVALID_SPLIT_PROFILE_OR_PCB',str(exc).splitlines()[0],validation_errors=details)
    digest=pcb_digest(p)
    if checked.source_pcb_sha256!=digest:return unavailable('PROFILE_SOURCE_MISMATCH','The full PCB source state differs from this profile.')
    layers=copper_layers(p)
    if checked.copper_layers!=layers:return unavailable('LAYER_ORDER_MISMATCH','Declared copper order must exactly match the current model.')
    holes,zero=_holes(p)
    if not holes:return unavailable('NO_DECLARED_CIRCULAR_HOLES','Zero-drill pads are not invented holes.')
    mapping={}
    for item in checked.assignments:
        if item.source_id in mapping:return unavailable('DUPLICATE_HOLE_ASSIGNMENT','Exactly one plating/tool/span declaration is required for each source hole.',source_id=item.source_id)
        mapping[item.source_id]=item
    ids={h['id'] for h in holes}
    if set(mapping)!=ids:return unavailable('HOLE_ASSIGNMENT_SET_MISMATCH','All and only source holes, including DNP footprints, require explicit assignments.',missing=sorted(ids-set(mapping)),unknown=sorted(set(mapping)-ids))
    tools={t.number:t for t in checked.tools};hits=[];occupied={}
    for hole in holes:
        item=mapping[hole['id']]
        if hole['kind']=='via' and hole['expanded_copper_span']!=layers:return unavailable('UNSUPPORTED_VIA_SPAN','Partial source spans are not converted into full-board holes.',source_id=hole['id'])
        tool=tools.get(item.tool)
        if tool is None:return unavailable('UNDEFINED_TOOL','A source hole selects an undeclared tool.',source_id=hole['id'],tool=item.tool)
        expected='ViaDrill' if hole['kind']=='via' else 'ComponentDrill'
        if tool.function!=expected:return unavailable('TOOL_FUNCTION_MISMATCH','Tool function must match the modeled source kind; plating is separately declared.',source_id=hole['id'])
        if number(tool.diameter_mm)!=Decimal(str(hole['diameter_mm'])):return unavailable('FINISHED_DIAMETER_MISMATCH','C is declared finished-hole diameter; bit or plating compensation is not inferred.',source_id=hole['id'])
        try:
            x,sx,ex=quantized(hole['center_mm'][0],checked.coordinate_format)
            y,sy,ey=quantized(hole['center_mm'][1],checked.coordinate_format)
        except ValueError as exc:return unavailable('COORDINATE_PRECISION_LOSS',str(exc),source_id=hole['id'])
        if (x,y) in occupied:return unavailable('COINCIDENT_OR_COLLAPSED_HITS','Duplicate or quantized-collapsed holes across either group require a source modeling decision.',source_ids=[occupied[(x,y)],hole['id']])
        occupied[(x,y)]=hole['id']
        hits.append(dict(source_id=hole['id'],source_kind=hole['kind'],component_fitted=hole.get('component_fitted'),
            declared_plating=item.plating,filename=item.plating+'.xnc',tool=item.tool,tool_function=tool.function,
            finished_diameter_mm=decimal_token(number(tool.diameter_mm)),source_xy_mm=[sx,sy],emitted_xy_mm=[x,y],
            numeric_rounding_error_mm=[ex,ey],source_copper_layers=hole['declared_copper_layers'],declared_drill_span=item.declared_drill_span))
    hits.sort(key=lambda r:(GROUPS.index(r['declared_plating']),int(r['tool']),Decimal(r['emitted_xy_mm'][0]),Decimal(r['emitted_xy_mm'][1]),r['source_id']))
    texts={};files=[]
    for group in GROUPS:
        rows=[r for r in hits if r['declared_plating']==group]
        if not rows:
            files.append(dict(plating=group,status='NOT_PRESENT',source_ids=[]));continue
        classification='Plated' if group=='PTH' else 'NonPlated'
        lines=['M48','; DECLARED CAD TO CAM DATA - NOT MACHINE QUALIFIED','; SOURCE_PCB_SHA256 '+digest,
            '; #@! TF.FileFunction,'+classification+',1,'+str(p.layer_count)+','+group,'METRIC']
        for key in sorted(tools,key=int):
            t=tools[key];lines.extend(['; #@! TA.AperFunction,'+t.function,'T'+key+'C'+decimal_token(number(t.diameter_mm))])
        lines.extend(['%','G05']);selected=None
        for row in rows:
            if row['tool']!=selected:lines.append('T'+row['tool']);selected=row['tool']
            lines.extend(['; SOURCE '+row['source_id'],'X'+row['emitted_xy_mm'][0]+'Y'+row['emitted_xy_mm'][1]])
            row['command_line']=len(lines)
        lines.append('M30');text='\n'.join(lines)+'\n';encoded=text.encode('ascii');filename=group+'.xnc';texts[filename]=text
        files.append(dict(plating=group,status='PREPARED',filename=filename,sha256=sha(encoded),bytes=len(encoded),source_ids=sorted(r['source_id'] for r in rows),hit_count=len(rows),unused_tool_numbers=sorted(set(tools)-{r['tool'] for r in rows},key=int)))
    effective=checked.model_dump(mode='json');effective['tools']=sorted(effective['tools'],key=lambda t:int(t['number']));effective['assignments']=sorted(effective['assignments'],key=lambda r:r['source_id'])
    manifest=dict(schema_version=1,format='pcb-declared-split-xnc-package-v1',dialect=DIALECT,source_pcb_sha256=digest,
        profile=effective,profile_sha256=sha(canonical(effective)),files=files,traceability=hits,all_source_hole_ids=sorted(ids),
        zero_drill_pad_ids=sorted(zero),hole_count=len(holes),plating_evidence='CALLER_DECLARATION_ONLY',
        physical_plating='UNAVAILABLE',actual_stackup='UNAVAILABLE',physical_drill_depth='UNAVAILABLE',
        machine_datum='UNAVAILABLE',shop_capability='UNAVAILABLE',physical_tolerance='UNAVAILABLE',
        machine_bit_diameters_feeds_speeds='UNAVAILABLE',source_data_modified=False,**FLAGS)
    return dict(status='prepared_declared_split_cad_data',manifest=manifest,xnc_files=texts,files_generated=[],**FLAGS)


def _payloads(prepared):
    return {**{name:text.encode('ascii') for name,text in prepared['xnc_files'].items()},'manifest.json':canonical(prepared['manifest'])+b'\n'}


def _commit(prepared,destination_name,payloads):
    return dict(schema_version=1,state='COMPLETE_DECLARED_CAD_PACKAGE',published_directory_name=destination_name,
        source_pcb_sha256=prepared['manifest']['source_pcb_sha256'],profile_sha256=prepared['manifest']['profile_sha256'],
        files=[dict(filename=name,sha256=sha(data),bytes=len(data)) for name,data in payloads.items()],**FLAGS)


def _write_exclusive(path,data):
    with path.open('xb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())


def _publish(stage,destination):
    # Windows os.rename always raises FileExistsError if dst exists. No replace fallback.
    os.rename(stage,destination)


def _link(path):
    return path.is_symlink() or getattr(path,'is_junction',lambda:False)()


def _destination(path):
    value=Path(path)
    if not value.name or value.name.startswith('.') or '.partial-' in value.name or value.name.rstrip(' .')!=value.name:raise ValueError('Use a new, non-hidden package directory with an explicit name.')
    parent=value.absolute().parent.resolve(strict=True)
    if not parent.is_dir():raise ValueError('Package parent must already exist.')
    return parent/value.name


def write_split_xnc_package_new(project,profile,path):
    prepared=prepare_split_xnc(project,profile)
    if prepared['status']=='UNAVAILABLE':return prepared
    if os.name!='nt':return unavailable('UNSUPPORTED_PUBLICATION_PLATFORM','No portable no-replace directory publication is claimed; this writer requires Windows.')
    try:destination=_destination(path)
    except (OSError,ValueError,TypeError) as exc:return unavailable('INVALID_PACKAGE_PATH',str(exc))
    if destination.exists() or _link(destination):return unavailable('OUTPUT_EXISTS','Existing destination data is preserved.')
    payloads=_payloads(prepared);payloads['COMPLETE.json']=canonical(_commit(prepared,destination.name,payloads))+b'\n'
    stage=destination.parent/('.'+destination.name+'.partial-'+uuid.uuid4().hex)
    created=False;written=[];phase='create_stage'
    try:
        stage.mkdir();created=True
        for name,data in payloads.items():
            phase='write:'+name;_write_exclusive(stage/name,data);written.append(name)
        phase='publish';_publish(stage,destination)
    except OSError as exc:
        if not created:return unavailable('STAGING_CREATE_FAILED',str(exc))
        return dict(status='PARTIAL_WRITE',complete=False,published=False,source_data_modified=False,
            filesystem_modified=True,failed_phase=phase,error_type=type(exc).__name__,error=str(exc),
            destination=str(destination),staging_directory=str(stage),fully_written_items=written,
            files_generated=[str(stage/name) for name in payloads if (stage/name).exists()],
            recovery='Retained unpublished staging data for inspection; choose a new package destination for a fresh attempt. No automatic deletion or resume.',**FLAGS)
    return dict(status='written_declared_split_cad_package',complete=True,published=True,source_data_modified=False,
        filesystem_modified=True,destination=str(destination),files_generated=[str(destination/name) for name in payloads],
        source_pcb_sha256=prepared['manifest']['source_pcb_sha256'],profile_sha256=prepared['manifest']['profile_sha256'],**FLAGS)


def verify_split_xnc_package(project,profile,path):
    """Read a completed local snapshot; not a general XNC/CAM validator."""
    prepared=prepare_split_xnc(project,profile)
    if prepared['status']=='UNAVAILABLE':return prepared
    directory=Path(path)
    if directory.name.startswith('.') or '.partial-' in directory.name:return unavailable('UNPUBLISHED_STAGE','Staging data is never accepted as a completed package.')
    try:
        if _link(directory) or not directory.is_dir():return unavailable('INVALID_PACKAGE_DIRECTORY','A real completed package directory is required.')
        payloads=_payloads(prepared);payloads['COMPLETE.json']=canonical(_commit(prepared,directory.name,payloads))+b'\n'
        if {entry.name for entry in directory.iterdir()}!=set(payloads):return unavailable('PACKAGE_FILE_SET_MISMATCH','Expected group files, manifest and completion marker must match exactly.')
        for name,expected in payloads.items():
            target=directory/name
            if _link(target) or not target.is_file():return unavailable('INVALID_PACKAGE_ENTRY','Package entries must be regular files.',filename=name)
            with target.open('rb') as stream:actual=stream.read(len(expected)+1)
            if actual!=expected:return unavailable('PACKAGE_CONTENT_MISMATCH','Source/profile-bound canonical package bytes differ.',filename=name)
    except OSError as exc:return unavailable('PACKAGE_READ_FAILED',str(exc))
    return dict(status='verified_declared_split_cad_package_only',filesystem_state_checked=True,
        directory=str(directory),source_pcb_sha256=prepared['manifest']['source_pcb_sha256'],profile_sha256=prepared['manifest']['profile_sha256'],
        files_verified=list(payloads),concurrent_mutation_protection=False,**FLAGS,
        qualification='Canonical current-source/profile package snapshot only. No machine, shop, physical or general CAM acceptance.')
