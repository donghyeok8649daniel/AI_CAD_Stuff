"""Built-in extension entry point. Data-only commands; no dynamic import paths."""
from copy import deepcopy
import hashlib
import json
from .pcb import PCBProject, bom_report, inspect_layout, pcb_digest
from .pcb_simulation import simulate_pcb, spice_netlist

MANIFEST = dict(id='promptcad.pcb',version='0.2.6',schema_version=1,workspace='pcb',
    entry_point='cadstudio.pcb_plugin:execute',ui_entry_point='cadstudio.native.pcb_workbench:PCBWorkbench',
    commands=['validate','layout','simulate','bom','spice','electrical_preview','compatibility','drill_review','drill_review_verify','excellon_prepare','excellon_split_prepare','excellon_split_declaration_draft'],
    dependencies=['pydantic (existing CAD runtime)','numpy (existing CAD runtime)','PySide6 (existing CAD runtime)'],
    simulation_backend='builtin-linear',external_runtime=None,
    permissions=dict(automatic_execution=False,network=False,filesystem=False,hardware=False),
    ai='Explicit existing ChatGPT/Codex answer transport; advisory only; no API fallback',
    geometry=dict(copper_layers=[2,4,6,8],pads=['circle','rect','oval','roundrect'],drills='circular',
        vias='ordered copper-layer span',zones='declared outlines and explicitly supplied filled polygons are distinct'),
    excellon_candidate=dict(dialect='ucamco-xnc-2021.11-circular-metric-pth',explicit_profile_required=True,machine_program_qualified=False),
    excellon_split_candidate=dict(dialect='ucamco-xnc-2021.11-split-circular-metric',explicit_per_hole_plating_required=True,filesystem_writer='CLI only; Windows new-directory package',machine_program_qualified=False),
    fabrication_review=dict(format='pcb-circular-drill-review-json-v1',units='mm',origin='pcb-design',fabrication_files='UNAVAILABLE',rules='explicit caller values only'),
    limits=['Declared circular PTH XNC is CAD-to-CAM data requiring an explicit profile; Gerber output and machine/manufacturing qualification remain unavailable. Circular-drill JSON is a geometry review only.', 'No dynamic code plugins. No Gerber/KiCad import or fabrication acceptance.',
        'DC/AC ideal R/C/voltage-source models only; unmodeled devices block simulation.'])


def design_digest(raw):
    return hashlib.sha256(json.dumps(raw,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def with_pcb(raw, project, *, expected_digest):
    from .models import Design
    if design_digest(raw) != expected_digest:
        raise ValueError('CAD 문서가 변경되었습니다. 다시 불러오세요. / Stale CAD snapshot.')
    data=deepcopy(raw);data['pcb']=PCBProject.model_validate(project).model_dump(mode='json')
    return Design.model_validate(data)


def electrical_preview(project, workspace=None):
    """Explicit namespaced append. Preserve existing electrical data verbatim.

    Models translate to existing DC types; only nonnegative sources translate.
    Unknown ICs become passive registrations with analysis disabled, never loads.
    Applying twice requires explicit removal of the prior namespaced entries.
    """
    from .electrical import ElectricalWorkspace
    p=PCBProject.model_validate(project)
    raw=deepcopy(workspace or dict(nodes=['GND'],components=[]))
    existing=ElectricalWorkspace.model_validate(raw)
    ids={c.id for c in existing.components};nodes=set(existing.nodes)
    def node(n):return 'GND' if n=='GND' else 'pcb_'+n
    reserved=nodes|{node(n) for n in p.nets}
    def nc(ref,port,occupied):
        prefix='pcb_nc_'+ref+'_'+port;candidate=prefix;index=0
        while candidate in occupied:
            index+=1;candidate=prefix+'_'+str(index)
        return candidate
    added=[]
    for c in p.components:
        if not c.fitted:continue
        identifier='pcb_'+c.ref
        if identifier in ids:raise ValueError('이 PCB는 이미 전장에 등록되었습니다. / PCB component ID conflict: '+identifier)
        m=c.model;pins={pin.number:pin.net for pin in c.pins}
        if m.kind in ('resistor','capacitor','voltage_source'):
            a,b=pins[m.pin_a],pins[m.pin_b]
            if a is None or b is None:raise ValueError(c.ref+': 모델 핀 net이 없습니다. / Missing model nets.')
            a,b=node(a),node(b)
            kind={'resistor':'resistor','capacitor':'capacitor','voltage_source':'battery'}[m.kind]
            row=dict(id=identifier,name=(c.ref+' '+(c.value or m.kind))[:80],kind=kind,a=a,b=b,analysis_enabled=True)
            if m.kind=='resistor':row['resistance_ohm']=m.resistance_ohm
            elif m.kind=='capacitor':row['capacitance_f']=m.capacitance_f
            else:
                if m.dc_voltage_v <= 0:raise ValueError(c.ref+': 기존 전장에는 양의 DC 전압원만 적용됩니다. / CAD electrical requires a positive DC source.')
                row['voltage_v']=m.dc_voltage_v
        else:
            connections={pin.number:node(pin.net) for pin in c.pins if pin.net}
            connected=list(dict.fromkeys(connections.values()));occupied=reserved|nodes|set(connections.values())
            a=connected[0] if connected else nc(c.ref,'a',occupied)
            b=connected[1] if len(connected)>1 else nc(c.ref,'b',occupied|{a})
            row=dict(id=identifier,name=(c.ref+' '+(c.value or 'PCB passive'))[:80],kind='load',a=a,b=b,analysis_enabled=False,terminal_pins=connections)
            nodes.update(connections.values())
        nodes.update([row['a'],row['b']]);added.append(row)
    raw['nodes']=[*existing.nodes,*sorted(nodes-set(existing.nodes))];raw['components']=[*raw.get('components',[]),*added]
    return ElectricalWorkspace.model_validate(raw).model_dump(mode='json')


def execute(command, payload, **options):
    if command not in MANIFEST['commands']:raise ValueError('지원하지 않는 PCB 명령입니다. / Unknown PCB command.')
    if command=='compatibility':
        from .pcb_compatibility import preflight,CURRENT_PROFILE
        return preflight(payload,options.get('target_profile',CURRENT_PROFILE))
    if command=='excellon_split_declaration_draft':
        from .pcb_excellon_declarations import split_declaration_draft
        from .pcb_excellon_export import unavailable
        if options:return unavailable('UNSUPPORTED_REQUEST_OPTION','Declaration drafts consume the current PCB only; no replacement profile or inferred defaults.',options=sorted(options))
        return split_declaration_draft(payload)
    if command=='excellon_split_prepare':
        from .pcb_excellon_split import prepare_split_xnc
        from .pcb_excellon_export import unavailable
        if set(options)-{'profile'}:return unavailable('UNSUPPORTED_REQUEST_OPTION','No unknown split export options are ignored.',options=sorted(set(options)-{'profile'}))
        return prepare_split_xnc(payload,options.get('profile'))
    if command=='excellon_prepare':
        from .pcb_excellon_export import prepare_declared_xnc,unavailable
        if set(options)-{'profile'}:return unavailable('UNSUPPORTED_REQUEST_OPTION','No unknown Excellon export options are ignored.',options=sorted(set(options)-{'profile'}))
        return prepare_declared_xnc(payload,options.get('profile'))
    if command in ('drill_review','drill_review_verify'):
        from .pcb_drill_review import drill_review,verify_drill_review,_unavailable
        allowed={'review_report'} if command=='drill_review_verify' else {'minimum_gap_mm','minimum_edge_mm','units','origin','output_format','max_findings'}
        if set(options)-allowed:return _unavailable('UNSUPPORTED_REQUEST_OPTION','No unrecognized drill-review request options are ignored.',options=sorted(set(options)-allowed))
        return verify_drill_review(payload,options.get('review_report')) if command=='drill_review_verify' else drill_review(payload,**options)
    project=PCBProject.model_validate(payload)
    if command=='validate':return dict(status='valid',pcb_sha256=pcb_digest(project),project=project.model_dump(mode='json'))
    if command=='layout':return inspect_layout(project)
    if command=='simulate':return simulate_pcb(project,**options)
    if command=='bom':return bom_report(project)
    if command=='spice':return spice_netlist(project)
    return electrical_preview(project,options.get('workspace'))
