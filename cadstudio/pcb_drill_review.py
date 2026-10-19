"""Declared circular-drill XY review, never a fabrication generator or approval.

Both comparison rules must be supplied by the caller. No fabrication minima, plating,
drill travel/depth, physical stackup or machine origin is inferred.
"""
import math
import json
from .pcb import PCBProject,pcb_digest,pad_positions,copper_layers,via_layers

FORMAT='pcb-circular-drill-review-json-v1'
ORIGIN='pcb-design'
TOLERANCE_MM=1e-9  # Floating-point comparison tolerance, not a shop capability.


def _unavailable(code,message,**details):
    return dict(status='UNAVAILABLE',reasons=[dict(code=code,message=message,**details)],
                manufacturing_qualified=False,actual_hardware_verified=False,data_modified=False,
                automatic_fallback=False,files_generated=[])


def _rule(value):
    if value is None:return None
    if isinstance(value,bool):raise ValueError('Boolean is not a drill-rule distance.')
    number=float(value)
    if not math.isfinite(number) or number<0:raise ValueError('Drill-rule distances must be finite, nonnegative millimetres.')
    return number


def _holes(p):
    components={c.ref:c for c in p.components};holes=[];zero=[]
    for pad in pad_positions(p):
        identifier='pad:'+pad['ref']+':'+pad['pin']
        if pad['drill_mm']==0:
            zero.append(identifier);continue
        holes.append(dict(id=identifier,kind='pad',ref=pad['ref'],pin=pad['pin'],net=pad['net'],
            center_mm=[pad['x'],pad['y']],diameter_mm=pad['drill_mm'],shape='circle',
            declared_copper_layers=list(pad['layers']),component_fitted=components[pad['ref']].fitted,
            plating='UNAVAILABLE',drill_travel_and_depth='UNAVAILABLE'))
    for via in p.vias:
        holes.append(dict(id='via:'+via.id,kind='via',net=via.net,
            center_mm=[via.x_mm,via.y_mm],diameter_mm=via.drill_mm,shape='circle',
            declared_copper_layers=list(via.layers),expanded_copper_span=via_layers(p,via),
            plating='UNAVAILABLE',drill_travel_and_depth='UNAVAILABLE'))
    return holes,zero


def drill_review(project,*,minimum_gap_mm=None,minimum_edge_mm=None,units='mm',origin=ORIGIN,
                 output_format=FORMAT,max_findings=128):
    if output_format!=FORMAT:return _unavailable('UNSUPPORTED_OUTPUT_FORMAT','Only a declared-geometry JSON review is available; no Gerber, Excellon, drill-machine or fallback file is generated.',requested=output_format if isinstance(output_format,str) else repr(output_format),supported=[FORMAT])
    if units!='mm':return _unavailable('UNSUPPORTED_UNITS','Only unchanged model millimetres are supported; no automatic conversion.',requested=units if isinstance(units,str) else repr(units),supported=['mm'])
    if origin!=ORIGIN:return _unavailable('UNSUPPORTED_ORIGIN','Only the existing PCB design coordinate frame is supported; no machine origin or offset is inferred.',requested=origin if isinstance(origin,str) else repr(origin),supported=[ORIGIN])
    if type(max_findings) is not int or not 1<=max_findings<=4096:return _unavailable('INVALID_FINDING_LIMIT','Choose an explicit report detail limit from1 to4096.')
    missing=[name for name,value in (('minimum_gap_mm',minimum_gap_mm),('minimum_edge_mm',minimum_edge_mm)) if value is None]
    if missing:return _unavailable('MISSING_DRILL_RULES','Both drill gap and rectangle-edge rules must be explicitly supplied in millimetres; missing rules are not zero or a passing check.',missing_rules=missing)
    try:
        gap,edge=_rule(minimum_gap_mm),_rule(minimum_edge_mm)
        p=PCBProject.model_validate(project)
    except (ValueError,TypeError,OverflowError) as exc:return _unavailable('INVALID_PCB_OR_RULE',str(exc))
    holes,zero=_holes(p);findings=[];total=0;pair_count=0;minimum_pair=None;minimum_edge=None
    def finding(code,ids,measured,required):
        nonlocal total
        total+=1
        if len(findings)<max_findings:findings.append(dict(code=code,holes=ids,measured_mm=measured,required_mm=required))
    for index,hole in enumerate(holes):
        x,y=hole['center_mm'];radius=hole['diameter_mm']/2
        edge_gap=min(x-radius,y-radius,p.width_mm-x-radius,p.height_mm-y-radius)
        minimum_edge=edge_gap if minimum_edge is None else min(minimum_edge,edge_gap)
        if edge is not None and edge_gap<edge-TOLERANCE_MM:finding('DRILL_TO_DECLARED_RECTANGLE_GAP',[hole['id']],edge_gap,edge)
        for other in holes[index+1:]:
            ox,oy=other['center_mm'];pair_count+=1
            distance=math.hypot(x-ox,y-oy)-radius-other['diameter_mm']/2
            minimum_pair=distance if minimum_pair is None else min(minimum_pair,distance)
            if gap is not None and distance<gap-TOLERANCE_MM:finding('PROJECTED_DRILL_TO_DRILL_GAP',[hole['id'],other['id']],distance,gap)
    # Finding truncation never changes whether violations exist. The two
    # geometric result statuses below do not constitute manufacturing approval.
    def check(value,applicable):
        return dict(status='UNAVAILABLE' if value is None else 'NOT_APPLICABLE' if not applicable else 'EVALUATED_DECLARED_RULE_ONLY',required_mm=value)
    return dict(schema_version=1,report_kind='pcb-circular-drill-review',status='reviewed',format=FORMAT,
        source_pcb_sha256=pcb_digest(p),source_schema_version=p.schema_version,
        units='mm',origin=dict(kind=ORIGIN,offset_mm=[0.0,0.0],transform='identity',machine_origin='UNAVAILABLE'),
        board=dict(width_mm=p.width_mm,height_mm=p.height_mm,declared_thickness_mm=p.thickness_mm,
            boundary='declared_model_rectangle',physical_outline_and_cutouts='UNAVAILABLE'),
        layer_count=p.layer_count,copper_layers=copper_layers(p),physical_stackup='UNAVAILABLE',
        rules=dict(minimum_gap_mm=gap,minimum_edge_mm=edge,source='explicit caller declarations; no shop/standard defaults',comparison_tolerance_mm=TOLERANCE_MM),
        checks=dict(pair_gap=check(gap,pair_count>0),rectangle_edge=check(edge,len(holes)>0)),
        holes=holes,zero_drill_pad_ids=zero,
        measurements=dict(hole_count=len(holes),pair_comparisons=pair_count,minimum_projected_gap_mm=minimum_pair,minimum_declared_rectangle_gap_mm=minimum_edge),
        findings=findings,findings_total=total,findings_omitted=total-len(findings),findings_complete=total==len(findings),max_findings=max_findings,
        declared_rule_violations_present=total>0,
        manufacturing_qualified=False,actual_hardware_verified=False,data_modified=False,
        fabrication_files='UNAVAILABLE',fabrication_capability='UNAVAILABLE',
        limits=['Circular declared holes in model XY only; all hole projections are compared regardless of unknown depth.',
            'Pad copper layers and via copper spans do not establish plating or drill travel/depth.',
            'Fitted=False components still retain their modeled board holes. Zero-drill pads are listed explicitly.',
            'No slot/oval drill, Gerber/Excellon output, physical stackup, machine origin, material, plating, tool, tolerance, ampacity or fabrication qualification.'])


def verify_drill_review(project,report):
    if not isinstance(report,dict) or report.get('report_kind')!='pcb-circular-drill-review' or type(report.get('schema_version')) is not int or report.get('schema_version')!=1:
        return _unavailable('UNSUPPORTED_REVIEW_SCHEMA','A version1 circular-drill review object is required.')
    try:p=PCBProject.model_validate(project)
    except ValueError as exc:return _unavailable('INVALID_PCB',str(exc))
    if report.get('source_pcb_sha256')!=pcb_digest(p):return _unavailable('SOURCE_MISMATCH','The review is not bound to the current PCB; preserve the source and generate a current review.')
    if report.get('manufacturing_qualified') is not False or report.get('actual_hardware_verified') is not False:
        return _unavailable('UNSUPPORTED_QUALIFICATION_CLAIM','This review cannot assert manufacturing or hardware acceptance.')
    rules=report.get('rules')
    if not isinstance(rules,dict):return _unavailable('INVALID_RULE_RECORD','The explicit rule record is missing.')
    expected=drill_review(p,minimum_gap_mm=rules.get('minimum_gap_mm'),minimum_edge_mm=rules.get('minimum_edge_mm'),
        units=report.get('units'),origin=report.get('origin',{}).get('kind') if isinstance(report.get('origin'),dict) else None,
        output_format=report.get('format'),max_findings=report.get('max_findings'))
    if expected.get('status')=='UNAVAILABLE':return expected
    try:
        # Python dict equality conflates True with1 and can accept wrong JSON
        # metadata types. Compare the exact finite serialized review contract.
        same=json.dumps(report,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':'))==json.dumps(expected,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    except (ValueError,TypeError,RecursionError):return _unavailable('INVALID_REVIEW_JSON','Review data is not finite serializable JSON; no data was adopted.')
    if not same:return _unavailable('REVIEW_CONTENT_MISMATCH','Review coordinates, drills, layers, units/origin, findings, JSON value types or preserved unknowns differ from a current model review; no field is ignored.')
    return dict(status='verified_model_review_only',source_pcb_sha256=pcb_digest(p),
        complete_finding_details=report['findings_complete'],declared_rule_violations_present=report['declared_rule_violations_present'],
        rule_authority='UNAVAILABLE',manufacturing_qualified=False,actual_hardware_verified=False,data_modified=False,
        qualification='Exact supplied-rule model report reproduction only; rule authority, depth, physical fabrication and hardware remain unverified.')


class DrillReviewError(ValueError):
    def __init__(self,report):
        self.report=report
        super().__init__(report['reasons'][0]['message'])


def decode_review_json(text):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate review JSON key')
            result[key]=value
        return result
    def constant(value):raise ValueError('Non-finite review JSON constant')
    def finite(value):
        number=float(value)
        if not math.isfinite(number):raise ValueError('Overflowed review number')
        return number
    try:return json.loads(text,object_pairs_hook=pairs,parse_constant=constant,parse_float=finite)
    except (ValueError,TypeError,UnicodeError,RecursionError) as exc:
        raise DrillReviewError(_unavailable('INVALID_REVIEW_JSON','A finite review JSON object with unique keys is required; no data was adopted.')) from exc
