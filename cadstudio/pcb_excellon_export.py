"""Declared circular CAD-to-CAM XNC subset; not a machine or shop approval.

Syntax reference: Ucamco XNC2021.11 sections2.2,2.3,2.6,3.2-3.9,3.15,4.
Every physical interpretation is a caller declaration, never inferred from PCB.
"""
from copy import deepcopy
from decimal import Decimal,ROUND_HALF_EVEN,localcontext
import hashlib
import json
from pathlib import Path
import re
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator
from .pcb import PCBProject,pcb_digest,copper_layers
from .pcb_drill_review import _holes

DIALECT='ucamco-xnc-2021.11-circular-metric-pth'
DECIMAL_TEXT=re.compile(r'[+-]?[0-9]+(?:\.[0-9]+)?')


def unavailable(code,message,**details):
    return dict(status='UNAVAILABLE',reasons=[dict(code=code,message=message,**details)],
        files_generated=[],automatic_fallback=False,data_modified=False,
        manufacturing_qualified=False,machine_program_qualified=False,actual_hardware_verified=False)


def number(text):
    if not isinstance(text,str) or len(text)>64 or not DECIMAL_TEXT.fullmatch(text):raise ValueError('Use an explicit finite decimal string without exponent notation.')
    value=Decimal(text)
    if not value.is_finite():raise ValueError('Non-finite profile value.')
    return value


class ProfileData(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,allow_inf_nan=False,revalidate_instances='always')


class Origin(ProfileData):
    kind: Literal['pcb-design']
    offset_mm: list[str]=Field(min_length=2,max_length=2)
    rotation_deg: str
    mirror_x: bool
    mirror_y: bool
    @model_validator(mode='after')
    def identity_only(self):
        if any(number(v)!=0 for v in self.offset_mm) or number(self.rotation_deg)!=0 or self.mirror_x or self.mirror_y:raise ValueError('Only unchanged PCB origin/axes are supported; no inferred alignment or machine datum.')
        return self


class CoordinateFormat(ProfileData):
    notation: Literal['explicit-decimal']
    mode: Literal['absolute']
    decimal_places: int=Field(ge=1,le=9)
    rounding: Literal['ROUND_HALF_EVEN']
    maximum_numeric_rounding_error_mm: str
    @model_validator(mode='after')
    def explicit_error_budget(self):
        if number(self.maximum_numeric_rounding_error_mm)<0:raise ValueError('Numeric rounding error budget must be nonnegative; it is not a fabrication tolerance.')
        return self


class Tool(ProfileData):
    number: str
    diameter_mm: str
    function: Literal['ComponentDrill','ViaDrill']
    @model_validator(mode='after')
    def declared_tool(self):
        if not re.fullmatch(r'(?:0[1-9]|[1-9][0-9])',self.number):raise ValueError('XNC tool numbers must be two digits01..99.')
        if number(self.diameter_mm)<=0:raise ValueError('Finished-hole diameter must be positive.')
        return self


class ExportProfile(ProfileData):
    schema_version: Literal[1]
    dialect: Literal['ucamco-xnc-2021.11-circular-metric-pth']
    source_pcb_sha256: str=Field(pattern=r'^[a-f0-9]{64}$')
    units: Literal['mm']
    origin: Origin
    coordinate_format: CoordinateFormat
    diameter_semantics: Literal['model_drill_mm_declared_finished_hole_mm']
    copper_layers: list[str]=Field(min_length=2,max_length=8)
    declared_drill_span: list[str]=Field(min_length=2,max_length=2)
    plating: Literal['Plated']
    profile_basis: str=Field(min_length=1,max_length=1500)
    tools: list[Tool]=Field(min_length=1,max_length=99)
    hole_tools: dict[str,str]=Field(min_length=1,max_length=1024)
    @model_validator(mode='before')
    @classmethod
    def exact_version(cls,value):
        if not isinstance(value,dict) or type(value.get('schema_version')) is not int or value['schema_version']!=1:raise ValueError('Explicit integer profile schema_version1 required.')
        return value
    @model_validator(mode='after')
    def complete_declarations(self):
        if not self.profile_basis.strip():raise ValueError('An explicit interpretation basis is required.')
        if len({t.number for t in self.tools})!=len(self.tools):raise ValueError('Duplicate tool numbers.')
        if self.declared_drill_span!=['F.Cu','B.Cu']:raise ValueError('Only explicitly declared full-board PTH span is supported.')
        return self


def decimal_token(value):
    text=format(value,'f')
    if '.' in text:text=text.rstrip('0').rstrip('.')
    return text if '.' in text else text+'.0'


def quantized(value,fmt):
    with localcontext() as context:
        context.prec=80
        source=Decimal(str(value));quantum=Decimal(1).scaleb(-fmt.decimal_places)
        emitted=source.quantize(quantum,rounding=ROUND_HALF_EVEN)
        error=abs(emitted-source)
        if error>number(fmt.maximum_numeric_rounding_error_mm):raise ValueError('Requested decimal precision exceeds the explicitly allowed numeric rounding error.')
        if emitted==0:emitted=abs(emitted)
        return format(emitted,'.'+str(fmt.decimal_places)+'f'),format(source,'f'),format(error,'f')


def prepare_declared_xnc(project,profile):
    if profile is None:return unavailable('PROFILE_REQUIRED','No export without explicit units, identity origin, coordinate format, finished-diameter interpretation, layer/PTH declarations and source-to-tool assignments.')
    try:
        checked=ExportProfile.model_validate(profile)
        p=PCBProject.model_validate(project)
    except (ValueError,TypeError) as exc:
        details=[dict(path=list(r['loc']),type=r['type']) for r in exc.errors(include_url=False,include_input=False)][:32] if hasattr(exc,'errors') else []
        return unavailable('INVALID_PROFILE_OR_PCB',str(exc).splitlines()[0],validation_errors=details)
    digest=pcb_digest(p)
    if checked.source_pcb_sha256!=digest:return unavailable('PROFILE_SOURCE_MISMATCH','The declared profile belongs to another PCB state; no cached assignments applied.')
    layers=copper_layers(p)
    if checked.copper_layers!=layers:return unavailable('LAYER_ORDER_MISMATCH','Explicit copper order must exactly match the current PCB model.')
    holes,zero=_holes(p)
    if not holes:return unavailable('NO_DECLARED_CIRCULAR_HOLES','No modeled circular holes to export; zero-drill pads are not invented holes.')
    ids={hole['id'] for hole in holes}
    if set(checked.hole_tools)!=ids:return unavailable('HOLE_TOOL_MAP_MISMATCH','Every modeled circular hole, including DNP footprints, needs one explicit assignment; no source hole is dropped.',missing=sorted(ids-set(checked.hole_tools)),unknown=sorted(set(checked.hole_tools)-ids))
    tools={tool.number:tool for tool in checked.tools};hits=[];occupied={}
    for hole in holes:
        if hole['kind']=='via' and hole['expanded_copper_span']!=layers:return unavailable('UNSUPPORTED_VIA_SPAN','Blind/buried/partial copper spans cannot be silently exported as full-board PTH.',hole=hole['id'])
        chosen=checked.hole_tools[hole['id']]
        if chosen not in tools:return unavailable('UNDEFINED_TOOL','A source hole selects an undeclared tool.',hole=hole['id'],tool=chosen)
        tool=tools[chosen]
        expected='ViaDrill' if hole['kind']=='via' else 'ComponentDrill'
        if tool.function!=expected:return unavailable('TOOL_FUNCTION_MISMATCH','Explicit tool function disagrees with the modeled source kind.',hole=hole['id'],tool=chosen)
        if number(tool.diameter_mm)!=Decimal(str(hole['diameter_mm'])):return unavailable('FINISHED_DIAMETER_MISMATCH','Tool C is the declared finished-hole diameter, not an inferred bit/plating compensation.',hole=hole['id'],tool=chosen)
        try:
            x,sx,ex=quantized(hole['center_mm'][0],checked.coordinate_format)
            y,sy,ey=quantized(hole['center_mm'][1],checked.coordinate_format)
        except ValueError as exc:return unavailable('COORDINATE_PRECISION_LOSS',str(exc),hole=hole['id'])
        if (x,y) in occupied:return unavailable('COINCIDENT_OR_COLLAPSED_HITS','Coincident or quantized-collapsed source holes require an explicit modeling decision; no duplicate hit or automatic merge is emitted.',holes=[occupied[(x,y)],hole['id']])
        occupied[(x,y)]=hole['id']
        hits.append(dict(source_id=hole['id'],source_kind=hole['kind'],component_fitted=hole.get('component_fitted'),
            tool=chosen,tool_function=tool.function,finished_diameter_mm=decimal_token(number(tool.diameter_mm)),
            source_xy_mm=[sx,sy],emitted_xy_mm=[x,y],numeric_rounding_error_mm=[ex,ey],
            source_copper_layers=hole['declared_copper_layers'],declared_drill_span=checked.declared_drill_span))
    hits.sort(key=lambda row:(int(row['tool']),Decimal(row['emitted_xy_mm'][0]),Decimal(row['emitted_xy_mm'][1]),row['source_id']))
    lines=['M48','; DECLARED CAD TO CAM DATA - NOT MACHINE QUALIFIED','; SOURCE_PCB_SHA256 '+digest,
        '; #@! TF.FileFunction,Plated,1,'+str(p.layer_count)+',PTH','METRIC']
    for key in sorted(tools,key=int):
        tool=tools[key];lines.extend(['; #@! TA.AperFunction,'+tool.function,'T'+key+'C'+decimal_token(number(tool.diameter_mm))])
    lines.extend(['%','G05']);selected=None
    for row in hits:
        if row['tool']!=selected:lines.append('T'+row['tool']);selected=row['tool']
        lines.append('; SOURCE '+row['source_id']);lines.append('X'+row['emitted_xy_mm'][0]+'Y'+row['emitted_xy_mm'][1]);row['command_line']=len(lines)
    lines.append('M30');text='\n'.join(lines)+'\n';encoded=text.encode('ascii')
    effective=checked.model_dump(mode='json');effective['tools']=sorted(effective['tools'],key=lambda t:int(t['number']))
    return dict(status='prepared_declared_cad_data',dialect=DIALECT,xnc_text=text,
        xnc_sha256=hashlib.sha256(encoded).hexdigest(),xnc_bytes=len(encoded),source_pcb_sha256=digest,
        profile=effective,profile_sha256=hashlib.sha256(json.dumps(effective,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest(),
        traceability=hits,zero_drill_pad_ids=zero,unused_tool_numbers=sorted(set(tools)-{row['tool'] for row in hits}),
        plating=dict(declared='Plated',verified='UNAVAILABLE'),drill_span=dict(declared=checked.declared_drill_span,verified_depth='UNAVAILABLE'),
        actual_stackup='UNAVAILABLE',machine_datum='UNAVAILABLE',shop_capability='UNAVAILABLE',physical_tolerance='UNAVAILABLE',
        machine_bit_diameters_feeds_speeds='UNAVAILABLE',manufacturing_qualified=False,machine_program_qualified=False,actual_hardware_verified=False,
        data_modified=False,files_generated=[],qualification='Syntax and explicit CAD/profile declarations only. C values are nominal finished holes; no physical plating/depth/tool process is inferred.')


def write_declared_xnc_new(project,profile,path):
    result=prepare_declared_xnc(project,profile)
    if result['status']=='UNAVAILABLE':return result
    path=Path(path)
    if path.suffix.lower()!='.xnc':return unavailable('UNSUPPORTED_OUTPUT_EXTENSION','This candidate emits the specified XNC subset only as.xnc; no JSON renamed as.drl/.gbr.')
    if path.exists():return unavailable('OUTPUT_EXISTS','Choose a new output path; existing data is preserved.')
    created=False
    try:
        with path.open('x',encoding='ascii',newline='\n') as stream:
            created=True;stream.write(result['xnc_text'])
    except FileExistsError:return unavailable('OUTPUT_EXISTS','The output appeared before creation and was preserved.')
    except OSError as exc:
        if created:
            try:path.unlink()
            except OSError:pass
        return unavailable('WRITE_FAILED',str(exc))
    result={**result,'status':'written_declared_cad_data','files_generated':[str(path)]}
    return result


class ExcellonExportError(ValueError):
    def __init__(self,report):self.report=report;super().__init__(report['reasons'][0]['message'])


def decode_export_profile(text):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate profile key')
            result[key]=value
        return result
    def constant(value):raise ValueError('Non-finite JSON constant')
    try:return json.loads(text,object_pairs_hook=pairs,parse_constant=constant)
    except (ValueError,TypeError,UnicodeError,RecursionError) as exc:raise ExcellonExportError(unavailable('INVALID_PROFILE_JSON','Finite unique-key profile JSON is required.')) from exc



def verify_declared_xnc_artifact(project,profile,artifact):
    """Canonical regeneration check, not a general importer or machine validator.

    No path is opened: callers supply the actual text and metadata to check.
    The writer status and filesystem paths alone are not evidence of file state.
    """
    expected=prepare_declared_xnc(project,profile)
    if expected['status']=='UNAVAILABLE':return expected
    if not isinstance(artifact,dict) or artifact.get('status') not in ('prepared_declared_cad_data','written_declared_cad_data'):
        return unavailable('INVALID_ARTIFACT','A declared XNC text/traceability artifact is required.')
    actual={key:value for key,value in artifact.items() if key not in ('status','files_generated')}
    expected={key:value for key,value in expected.items() if key not in ('status','files_generated')}
    try:
        matches=json.dumps(actual,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':'))==json.dumps(expected,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    except (ValueError,TypeError,RecursionError):return unavailable('INVALID_ARTIFACT_JSON','Artifact metadata is not finite JSON; no field is adopted.')
    if not matches:return unavailable('EXPORT_CONTENT_MISMATCH','XNC text, tool/coordinate trace, source/profile binding or qualification fields differ from a current declared export.')
    return dict(status='verified_declared_cad_data_only',source_pcb_sha256=expected['source_pcb_sha256'],profile_sha256=expected['profile_sha256'],xnc_sha256=expected['xnc_sha256'],
        filesystem_state_checked=False,shop_capability='UNAVAILABLE',manufacturing_qualified=False,machine_program_qualified=False,actual_hardware_verified=False,
        qualification='Current source/profile and supplied canonical text/metadata match. No filesystem, general dialect, machine or manufacturing acceptance.')
