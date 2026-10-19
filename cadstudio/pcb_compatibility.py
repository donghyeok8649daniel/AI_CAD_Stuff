"""Lossless PCB quote-context IO preflight. No field stripping or down-conversion.

Profile names express exact data capabilities, not inferred installed-app versions.
The light preflight scans only structural PCB/history locations, never user labels.
"""
from copy import deepcopy
import json
import math
from pathlib import Path

FEATURE='pcb.cost.quote-context.v1'
PRICE_GUARD='pcb.cost.saved-price-failclosed.v1'
CONTEXT_FIELDS=('quantity_break_contexts','accepted_ai_quote_contexts')
PROFILES={
    'pcb-v1-pre407':dict(pcb_versions=[1],design_versions=[1],project_versions=[1,2],history_versions=[1],features=[]),
    'pcb-v1-context407':dict(pcb_versions=[1],design_versions=[1],project_versions=[1,2],history_versions=[1],features=[FEATURE,PRICE_GUARD]),
}
CURRENT_PROFILE='pcb-v1-context407'


class PCBCompatibilityError(ValueError):
    def __init__(self,report):
        self.report=deepcopy(report)
        self.code=report['reasons'][0]['code']
        super().__init__(report['reasons'][0]['message'])


def _pointer(parts):
    return '/'+('/'.join(str(part).replace('~','~0').replace('/','~1') for part in parts)) if parts else ''


def _failure(code,message,*,kind=None,target=CURRENT_PROFILE,**details):
    reason=dict(code=code,message=message,**details)
    return dict(status='blocked',compatible=False,document_kind=kind,target_profile=target,
                required_features=[],feature_locations=[],versions=[],reasons=[reason],
                data_modified=False,fields_removed=[],automatic_migration=False,validated=False)


def preflight(payload,target_profile=CURRENT_PROFILE):
    """Inspect capability/version requirements before any schema or state mutation."""
    if not isinstance(target_profile,str) or target_profile not in PROFILES:
        target_profile=target_profile if isinstance(target_profile,str) else repr(target_profile)
        return _failure('UNKNOWN_TARGET_PROFILE','Choose an explicit supported compatibility profile.',target=target_profile,available_profiles=sorted(PROFILES))
    if not isinstance(payload,dict):return _failure('INVALID_DOCUMENT_SHAPE','A PCB or CAD project object is required.',target=target_profile)
    target=PROFILES[target_profile];kind='project' if 'design' in payload or 'format' in payload else 'pcb'
    locations=[];versions=[];reasons=[]
    def version(scope,value,path):
        reported=repr(value) if isinstance(value,float) and not math.isfinite(value) else value
        versions.append(dict(scope=scope,value=reported,path=_pointer(path)))
        if type(value) is not int or value not in target[scope+'_versions']:
            reasons.append(dict(code='UNSUPPORTED_VERSION',scope=scope,value=reported,path=_pointer(path),supported=target[scope+'_versions'],message='This data version is unsupported; preserve the original and use a matching reader.'))
    def contexts(data,path):
        if not isinstance(data,dict):return
        # Presence matters: even an explicit empty unknown field is rejected by
        # a pre407 strict schema. Never silently omit it for an older target.
        for field in CONTEXT_FIELDS:
            if field in data:locations.append(dict(feature=FEATURE,path=_pointer([*path,field])))
        for field in ('accepted_ai_estimates','quantity_breaks'):
            if data.get(field):locations.append(dict(feature=PRICE_GUARD,path=_pointer([*path,field])))
    def budget(data,path):
        if isinstance(data,dict):contexts(data.get('cost_inputs'),[*path,'cost_inputs'])
    def pcb(data,path):
        if not isinstance(data,dict):return
        version('pcb',data.get('schema_version',1),[*path,'schema_version']);budget(data.get('budget'),[*path,'budget'])
    def design(data,path):
        if not isinstance(data,dict):return
        version('design',data.get('schema_version',1),[*path,'schema_version']);pcb(data.get('pcb'),[*path,'pcb'])
    def changed_value(value,change_path,location):
        if change_path==[]:design(value,location)
        elif change_path==['pcb']:pcb(value,location)
        elif change_path==['pcb','budget']:budget(value,location)
        elif change_path==['pcb','budget','cost_inputs']:contexts(value,location)
        elif len(change_path)>=4 and change_path[:3]==['pcb','budget','cost_inputs'] and change_path[3] in CONTEXT_FIELDS:
            locations.append(dict(feature=FEATURE,path=_pointer(location),history_change_path=change_path))
        elif len(change_path)>=4 and change_path[:3]==['pcb','budget','cost_inputs'] and change_path[3] in ('accepted_ai_estimates','quantity_breaks'):
            # Empty whole-field no-ops have no saved price to revive. Deeper
            # leaf edits still require the guard; their parent may be priced.
            if len(change_path)>4 or value:
                locations.append(dict(feature=PRICE_GUARD,path=_pointer(location),history_change_path=change_path))
        elif change_path==['pcb','schema_version'] and value is not None:version('pcb',value,location)
        elif change_path==['schema_version'] and value is not None:version('design',value,location)
    if kind=='pcb':pcb(payload,[])
    else:
        version('project',payload.get('version',2),['version']);design(payload.get('design'),['design'])
        history=payload.get('history')
        if isinstance(history,dict):
            version('history',history.get('version',1),['history','version']);design(history.get('base'),['history','base'])
            entries=history.get('entries',[])
            if isinstance(entries,list):
                for index,entry in enumerate(entries):
                    if not isinstance(entry,dict):continue
                    changes=entry.get('changes',[])
                    if not isinstance(changes,list):continue
                    for row,change in enumerate(changes):
                        if not isinstance(change,dict) or not isinstance(change.get('path'),list):continue
                        for field in ('before','after'):
                            if field in change:changed_value(change[field],change['path'],['history','entries',index,'changes',row,field])
    required=sorted({location['feature'] for location in locations})
    unsupported=sorted(set(required)-set(target['features']))
    for feature in unsupported:
        reasons.append(dict(code='POTENTIAL_STALE_PRICE_REVIVAL' if feature==PRICE_GUARD else 'UNSUPPORTED_FEATURE',feature=feature,paths=[row['path'] for row in locations if row['feature']==feature],message='The target cannot preserve quote bindings or fail-closed saved-price behavior. Keep the original and use a context407-capable reader; no lossy downgrade is provided.',action='USE_CONTEXT407_CAPABLE_READER_OR_KEEP_ORIGINAL'))
    return dict(status='blocked' if reasons else 'preflight_ok',compatible=not reasons,document_kind=kind,target_profile=target_profile,
                required_features=required,feature_locations=locations,versions=versions,reasons=reasons,
                data_modified=False,fields_removed=[],automatic_migration=False,validated=False,
                scope='PCB cost-context and declared data-version preflight; a matching profile is not proof that every historical application supports all other features.')


def validate_payload(payload,target_profile=CURRENT_PROFILE,*,expected_kind=None):
    report=preflight(payload,target_profile)
    if not report['compatible']:raise PCBCompatibilityError(report)
    if expected_kind is not None and report['document_kind']!=expected_kind:
        raise PCBCompatibilityError(_failure('UNEXPECTED_DOCUMENT_KIND','Choose the matching PCB or CAD project input.',kind=report['document_kind'],target=target_profile,expected_kind=expected_kind))
    try:
        if report['document_kind']=='pcb':
            from .pcb import PCBProject
            PCBProject.model_validate(payload)
        else:
            from .models import Project
            Project.model_validate(payload)
    except (ValueError,TypeError,RecursionError) as exc:
        details=[]
        if hasattr(exc,'errors'):
            details=[dict(path=_pointer(row['loc']),type=row['type']) for row in exc.errors(include_url=False,include_input=False)][:32]
        raise PCBCompatibilityError(_failure('SCHEMA_VALIDATION_FAILED','The current schema rejected this input; no fields were removed or data adopted.',kind=report['document_kind'],target=target_profile,validation_errors=details)) from exc
    report['status']='compatible';report['validated']=True
    return report


def decode_compatible(text,target_profile=CURRENT_PROFILE,*,expected_kind=None):
    def pairs(items):
        data={}
        for key,value in items:
            if key in data:raise ValueError('Duplicate JSON key')
            data[key]=value
        return data
    def constant(value):raise ValueError('Non-finite JSON constant')
    def finite_float(value):
        parsed=float(value)
        if not math.isfinite(parsed):raise ValueError('Overflowed JSON number')
        return parsed
    try:payload=json.loads(text,object_pairs_hook=pairs,parse_constant=constant,parse_float=finite_float)
    except (ValueError,TypeError,UnicodeError,RecursionError) as exc:
        raise PCBCompatibilityError(_failure('INVALID_JSON','Strict finite JSON with unique keys is required; the original was not changed.',target=target_profile)) from exc
    report=validate_payload(payload,target_profile,expected_kind=expected_kind)
    return payload,report


def encode_compatible(payload,target_profile=CURRENT_PROFILE,*,expected_kind=None,indent=2):
    # Preserve the supplied tree, not a schema model_dump that might omit fields.
    report=validate_payload(payload,target_profile,expected_kind=expected_kind)
    try:text=json.dumps(payload,ensure_ascii=False,indent=indent,allow_nan=False)
    except (ValueError,TypeError,RecursionError) as exc:
        raise PCBCompatibilityError(_failure('INVALID_JSON','The input cannot be encoded without loss as finite JSON.',kind=report['document_kind'],target=target_profile)) from exc
    return text,report


def write_compatible_export(payload,path,target_profile=CURRENT_PROFILE):
    text,report=encode_compatible(payload,target_profile)
    path=Path(path)
    if path.exists():raise PCBCompatibilityError(_failure('OUTPUT_EXISTS','Export uses a new file; preserve the existing output and choose another path.',kind=report['document_kind'],target=target_profile))
    created=False
    try:
        with path.open('x',encoding='utf-8') as stream:
            created=True;stream.write(text)
    except FileExistsError as exc:
        raise PCBCompatibilityError(_failure('OUTPUT_EXISTS','The export destination appeared before creation; it was preserved.',target=target_profile)) from exc
    except OSError:
        if created:
            try:path.unlink()
            except OSError:pass
        raise
    return report
