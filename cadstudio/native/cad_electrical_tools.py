"""Electrical feature tools shared by every AI provider, with no code execution."""
from ..electrical_catalog import CATALOG as ELECTRICAL_CATALOG


TOOLS = ('electrical_register', 'electrical_connect', 'electrical_unregister',
         'electrical_bind', 'electrical_unbind', 'electrical_wire_add',
         'electrical_wire_edit', 'electrical_wire_delete')
GUIDANCE = '''electrical_register: target is an EXISTING CAD part ID (or one created earlier in this plan). Register that body as an electrical feature, never duplicate its geometry. args={catalog_id?:exact_catalog_ID,kind?:"battery"|"wire"|"switch"|"resistor"|"capacitor"|"inductor"|"load"|"motor"|"actuator"|"mcu",name?,analysis_enabled?:false,apply_default_color?:false,a?,b?,signal_pins?:[{pin,node}],terminal_pins?:[{pin,node}],...explicit operating values}. Capacitors use capacitance_f in FARADS, optional capacitor_polarized and rated_voltage_v, with A positive/B negative for polarized devices; DC treats them as open, without charging/leakage/ESR simulation. Coils use inductance_h in HENRIES and winding_resistance_ohm; enabled DC requires both positive and solves only settled winding resistance, not ideal shorts/transients/saturation/flyback. Actuators use explicit rated_voltage_v/rated_current_a and optional startup_current_a for a separate resistance-equivalent estimate, not actual force/motion/driver behavior. Resistors use resistance_ohm. Convert user microfarads/millihenries to SI units; never fabricate missing capacitance, inductance, resistance or operating ratings. Use the exact model requested by the user from available_electrical_models; do not substitute a family or clone. Catalog source and a verified physical pin/terminal diagram are attached when available. No known diagram means manual/unverified, not a fabricated schematic. Unknown voltage/current is allowed for registration with analysis_enabled=false; it is excluded from DC calculations. Registration alone does not prove the CAD shape matches a physical product's dimensions. Preserve existing colors unless apply_default_color=true is requested, then yellow #FFD400. Preserve geometry, grouping, joints and prior circuit connections. Changing an existing model must explicitly use allow_drop_connections=true only when the user approved clearing its previous pin assignments.
electrical_connect: target is the source registered CAD part ID (MCU or verified electronic product). args={pin:exact_GPIO_key,target_part_id:registered_target_CAD_ID,target_terminal:"pin:GPIO_key"|"port:signal_terminal_key"|"a"|"b"}. Use physical pin labels and keys from registered_electrical_features / available_electrical_models; pin numbers are not BCM GPIO numbers. Register each actual CAD part before wiring it. On a non-MCU product pin is its exact named terminal key, not an invented header position; typed power/ground terminal connections are passive labels and never automatically become a DC power branch. A declared sensor/driver signal port is not its power A/B terminal. This creates a passive signal net; no firmware or complete voltage compatibility claim. Power/reference/reset pins are not ordinary GPIO. Use power_path with measured/verified operating inputs for supply calculations; never wire GPIO to a battery or motor power terminal as a normal signal.
electrical_unregister: target is an existing registered CAD part ID, args={}. Remove its electrical registration only when explicitly requested. The CAD body remains; other devices and net labels are preserved, and their now-unconnected endpoints remain visible.'''
GUIDANCE += '\nSaved measurement_reference and force_acquisition_review are offline reference data. Keep unknown force/frequency/calibration as unknown. Do not infer usable bandwidth from ADC sample rate, manufacture a serial calibration, or claim hardware, firmware or closed-loop qualification. Check actual supply terminals separately from GPIO and retain catalog worst-case ranges when editing a known measurement product.'
GUIDANCE += '\nSaved electrical_readiness lists registration, documented terminal and passive power-path deficits. Address the requested devices with exact sources and explicit wiring rather than hiding issues by deleting devices, clearing nets, disabling relevant checks or marking pending hardware as approved. An unused GPIO is not a fault. A housing reserved for electronics is not itself a powered device. A custom carrier containing a known IC is not automatically the exact bare IC; preserve its manually defined ports and surrounding circuitry. Do not invent a model, internal regulator connection, load current or firmware behavior to clear a readiness finding.'
GUIDANCE += '''
electrical_bind: target=existing CAD body ID, args={component_id:existing circuit component ID,apply_default_color?:false}. Link the existing item to that body, preserving its component ID, physical pins, ratings, every wire and canvas position. Do not duplicate an existing circuit item by registering it again. Exact legacy pin maps must validate without dropping assignments; family/unknown labels are not exact products. CAD role becomes electrical; custom color is preserved unless requested.
electrical_unbind: target=existing circuit component ID,args={}. Remove only its CAD link, preserving the circuit item and all wires. electrical_unregister instead removes the registration's circuit item; use only for explicit removal.
electrical_wire_add: target=source circuit component ID OR unambiguous registered CAD body ID. args={source_terminal:"pin:GPIO17"|"supply:5V_2"|"port:OUT"|"a"|"b",target_id:target circuit component ID OR registered CAD body ID,target_terminal:exact endpoint,name?,wire_color?:"#RRGGBB",length_mm?,cross_section_mm2?,max_current_a?,analysis_enabled?:false}. Creates an ACTUAL saved wire branch with physical endpoint metadata, visible in the native wiring diagram. Use this for draw/connect/wire requests; electrical_connect only joins net labels and creates no wire branch. Unknown cable length/area are allowed as 0 with analysis_enabled=false; do not invent physical cable dimensions or ampacity. Enable DC only with actual positive length and area. Nodes and wire IDs are generated by CAD; never guess newly generated registration IDs when a registered CAD body ID is available. Use exact documented terminals; custom devices must already declare named ports. No direct GPIO-to-power normal signal wiring; topology warnings remain visible. Supply outputs, bypass/reference and protective earth are distinct and never internally joined.
electrical_wire_edit: target=existing wire ID,args={name?,wire_color?,closed?,length_mm?,cross_section_mm2?,max_current_a?,analysis_enabled?,source_id?,source_terminal?,target_id?,target_terminal?}. Each changed end requires both device ID and terminal. Keeps wire ID, other metadata and unrelated pins. Old disconnected pads/nets remain visible. Set analysis_enabled=false when dimensions remain unknown; never zero or invent unrelated device ratings.
electrical_wire_delete: target=existing wire ID,args={}. Removes only that wire, keeping devices, physical pin labels, other wires and named nets. Do not delete devices to conceal missing wiring.
The electrical_circuit context lists actual circuit IDs (including unlinked devices), terminal kinds, saved wire endpoints and omitted counts. Resolve devices from these records. All these tools produce a private plan preview with normal undoable history; applied wiring is NOT firmware execution, live power or motor-control simulation.'''


def circuit_context(design):
    """Actual circuit IDs and endpoints, including devices not yet linked to CAD."""
    if design.electrical is None:
        return None
    from ..mcu_connections import connection_endpoints
    from collections import defaultdict
    grouped = defaultdict(list)
    for endpoint in connection_endpoints(design.electrical):
        grouped[endpoint.component_id].append(dict(terminal=endpoint.terminal, node=endpoint.node, kind=endpoint.pin_kind))
    devices = [c for c in design.electrical.components if c.kind != 'wire']
    wires = [c for c in design.electrical.components if c.kind == 'wire']
    return dict(nodes=design.electrical.nodes, hardware_verified=False, firmware_executed=False,
        devices=[dict(id=c.id, part_id=c.part_id, registered=c.part_registration, name=c.name,
            kind=c.kind, catalog_id=c.catalog_id, analysis_enabled=c.analysis_enabled,
            rated_voltage_v=c.rated_voltage_v, rated_current_a=c.rated_current_a,
            terminals=grouped[c.id][:96], omitted_terminals=max(0,len(grouped[c.id])-96)) for c in devices[:64]],
        wires=[dict(id=c.id,name=c.name,a=c.a,b=c.b,closed=c.closed,analysis_enabled=c.analysis_enabled,
            wire_color=c.wire_color,length_mm=c.length_mm,cross_section_mm2=c.cross_section_mm2,
            endpoints=[ref.model_dump() for ref in c.wire_endpoints]) for c in wires[:128]],
        omitted=dict(devices=max(0,len(devices)-64),wires=max(0,len(wires)-128)),
        note='Stored passive connections only. Unlisted reserved pins/internal device paths are not inferred.')


def measurement_context(component):
    """Bounded numerical reference; omit arbitrary notes and certificate text."""
    if component.measurement is None:
        return None
    data = component.measurement.model_dump(mode='json', exclude_none=True,
        exclude={'notes', 'calibration'})
    calibration = getattr(component.measurement, 'calibration', None)
    if calibration is not None:
        data['calibration'] = {'status': calibration.status,
            'point_count': calibration.point_count,
            'rms_residual_n': calibration.rms_residual_n}
    return data


def force_review_context(design):
    workspace = design.electrical
    if workspace is None or workspace.force_chain is None:
        return None
    from ..force_acquisition import assess_force_chain
    review = assess_force_chain(workspace)
    priority = {'blocked': 0, 'pending': 1, 'warning': 2, 'info': 3}
    findings = sorted(review.findings, key=lambda item: priority[item.severity])
    return dict(settings=workspace.force_chain.model_dump(exclude_none=True),
        status=review.status, hardware_verified=False, firmware_executed=False,
        findings=[dict(code=item.code, severity=item.severity,
                       component_id=item.component_id) for item in findings[:16]],
        omitted_findings=max(0, len(review.findings)-16))


def readiness_context(design):
    """Bounded structural deficits, with no execution or fabricated approvals."""
    if not design.electrical and not any(p.role=='electrical' for p in design.parts):
        return None
    from ..electrical_readiness import build_electrical_readiness
    report=build_electrical_readiness(design,language='en')
    priority={'blocked':0,'pending':1,'info':2}
    findings=sorted(report.issues,key=lambda item:priority[item.severity])
    unresolved=[p for p in report.parts if p.registration_status!='registered']
    devices=[c for c in report.components if c.kind!='wire']
    return dict(status=report.status,counts=report.counts,
        hardware_execution_supported=False,firmware_execution_supported=False,
        dc_calculation_performed=False,
        missing_registrations=[dict(part_id=p.part_id,status=p.registration_status) for p in unresolved[:24]],
        devices=[dict(component_id=c.component_id,part_id=c.part_id,catalog_id=c.catalog_id,
            model_status=c.model_status,diagram_available=c.diagram_available,power_status=c.power_status,
            assigned_terminals=c.assigned_terminals,isolated_terminals=c.isolated_terminals,
            analysis_enabled=c.analysis_enabled) for c in devices[:24]],
        findings=[dict(code=i.code,severity=i.severity,part_id=i.part_id,
            component_id=i.component_id,terminal=i.terminal) for i in findings[:40]],
        omitted=dict(registrations=max(0,len(unresolved)-24),devices=max(0,len(devices)-24),
            findings=max(0,len(findings)-40)))


def model_context():
    from ..board_pins import board_pinout
    from ..product_diagrams import product_diagram
    from ..electrical_catalog import catalog_functions
    return [dict(id=entry.catalog_id, model=entry.display_name, kind=entry.suggested_kind or 'load',
                 functions=catalog_functions(entry.catalog_id),encoder_interface=entry.encoder_interface,
                 diagram='physical_board_pins' if board_pinout(entry.catalog_id) else
                         'verified_terminals' if product_diagram(entry.catalog_id) else 'unavailable')
            for entry in ELECTRICAL_CATALOG if (not entry.reference_only or product_diagram(entry.catalog_id)) ]


def feature_context(design):
    from ..board_pins import board_pinout
    from ..product_diagrams import product_diagram
    from ..electrical_catalog import catalog_functions,get_catalog_entry
    result=[]
    for component in design.electrical.components if design.electrical else ():
        if not component.part_id: continue
        board=board_pinout(component.catalog_id); product=product_diagram(component.catalog_id)
        entry=get_catalog_entry(component.catalog_id)
        pins=([dict(key=p.key,label=p.label,kind=p.kind,functions=p.functions) for p in board.pins] if board else
              [dict(key=p.key,label=p.label,kind=p.kind,functions=p.functions,signal_level_note=p.signal_level_note_en) for p in product.terminals] if product else [])
        result.append(dict(part_id=component.part_id,component_id=component.id,name=component.name,
                           kind=component.kind,catalog_id=component.catalog_id,
                           functions=catalog_functions(component.catalog_id),
                           encoder_interface=entry.encoder_interface if entry else None,
                           analysis_enabled=component.analysis_enabled,source_url=component.source_url,
                           capacitance_f=component.capacitance_f,inductance_h=component.inductance_h,
                           winding_resistance_ohm=component.winding_resistance_ohm,
                           capacitor_polarized=component.capacitor_polarized,
                           measurement_reference=measurement_context(component),
                           board_supply_pins=component.board_supply_pins,
                           signal_pins=component.signal_pins,terminal_pins=component.terminal_pins,
                           a=component.a,b=component.b,pins=pins))
    return result


def apply_electrical_tool(raw, action):
    from ..electrical_registration import register_part,unregister_part,connect_registered_pin,connect_registered_terminal,registration_for_part
    from copy import deepcopy
    target=action.target; args=deepcopy(action.args)
    def circuit_identifier(reference):
        from ..models import Design
        design=Design.model_validate(raw)
        component=next((c for c in design.electrical.components if c.id==reference),None) if design.electrical else None
        linked=[c for c in design.electrical.components if c.part_id==reference] if design.electrical else []
        if len(linked)>1 or (component and linked and component.id!=linked[0].id):
            raise ValueError('CAD 부품 ID와 회로 부품 ID가 모호합니다. 정확한 회로 부품 ID를 지정하세요.')
        if component:return component.id
        if len(linked)==1:return linked[0].id
        raise ValueError('배선할 기존 회로 부품 또는 등록된 CAD 부품 ID를 선택하세요.')
    if action.tool=='electrical_register':
        for field in ('signal_pins','terminal_pins'):
            rows=args.get(field)
            if isinstance(rows,list):
                mapping={}
                for row in rows:
                    if not isinstance(row,dict) or set(row)!={'pin','node'} or not isinstance(row['pin'],str) or not isinstance(row['node'],str) or row['pin'] in mapping:
                        raise ValueError('핀 매핑은 중복 없이 {pin,node} 항목으로 지정하세요.')
                    mapping[row['pin']]=row['node']
                args[field]=mapping
        updated=register_part(raw,target,args)
        detail='CAD 부품에 전장 모델과 연결 자료를 등록했습니다. 정격 미입력 항목은 회로 계산에서 제외됩니다.'
    elif action.tool=='electrical_connect':
        if set(args)!= {'pin','target_part_id','target_terminal'}:
            raise ValueError('핀 연결에는 pin, target_part_id, target_terminal만 지정하세요.')
        component=registration_for_part(raw,target)
        connector=connect_registered_pin if component and component.kind=='mcu' else connect_registered_terminal
        updated=connector(raw,target,args['pin'],args['target_part_id'],args['target_terminal'])
        detail='등록된 CAD 전장 부품 사이의 신호 핀 연결을 저장했습니다. 실제 코드 동작은 별도 검증이 필요합니다.'
    elif action.tool=='electrical_unregister':
        if args: raise ValueError('전장 등록 해제에는 추가 인자를 지정하지 마세요.')
        updated=unregister_part(raw,target)
        detail='CAD 형상을 유지하고 해당 부품의 전장 등록을 해제했습니다.'
    elif action.tool=='electrical_bind':
        from ..electrical_registration import bind_component_to_part
        if set(args)-{'component_id','apply_default_color'} or 'component_id' not in args:
            raise ValueError('기존 회로 연결에는 component_id와 선택적인 apply_default_color만 지정하세요.')
        updated=bind_component_to_part(raw,args['component_id'],target,apply_default_color=args.get('apply_default_color',False))
        detail='기존 회로 부품 ID와 배선을 유지하며 실제 CAD 본체에 연결했습니다.'
    elif action.tool=='electrical_unbind':
        from ..electrical_registration import unbind_component_from_part
        if args:raise ValueError('CAD 링크 해제에는 추가 인자를 지정하지 마세요.')
        updated=unbind_component_from_part(raw,target)
        detail='회로 부품과 배선을 유지하며 CAD 본체 링크만 해제했습니다.'
    elif action.tool in ('electrical_wire_add','electrical_wire_edit','electrical_wire_delete'):
        from ..models import Design
        from ..circuit_connections import add_schematic_wire,update_schematic_wire,delete_schematic_wire
        from pydantic import BaseModel,ConfigDict,Field
        class WireAdd(BaseModel):
            model_config=ConfigDict(extra='forbid',allow_inf_nan=False,strict=True)
            source_terminal:str
            target_id:str
            target_terminal:str
            name:str=Field(default='AI 배선',min_length=1,max_length=80)
            wire_color:str|None=None
            length_mm:float=Field(default=0,ge=0)
            cross_section_mm2:float=Field(default=0,ge=0)
            max_current_a:float|None=Field(default=None,gt=0)
            analysis_enabled:bool=False
        updated=Design.model_validate(raw)
        if updated.electrical is None:raise ValueError('전장 부품을 먼저 등록하거나 기존 회로 부품을 선택하세요.')
        if action.tool=='electrical_wire_add':
            spec=WireAdd.model_validate(args)
            workspace=add_schematic_wire(updated.electrical,circuit_identifier(target),spec.source_terminal,
                circuit_identifier(spec.target_id),spec.target_terminal,**spec.model_dump(exclude={'source_terminal','target_id','target_terminal'}))
            detail='실제 핀 사이의 전선과 연결 정보를 회로도에 추가했습니다. 미확인 길이·단면적은 DC 계산에서 제외됩니다.'
        elif action.tool=='electrical_wire_edit':
            for field in ('source_id','target_id'):
                if field in args:args[field]=circuit_identifier(args[field])
            workspace=update_schematic_wire(updated.electrical,target,**args)
            detail='선택한 전선 ID를 유지하며 배선 속성·끝점을 수정했습니다.'
        else:
            if args:raise ValueError('전선 삭제에는 추가 인자를 지정하지 마세요.')
            workspace=delete_schematic_wire(updated.electrical,target)
            detail='선택한 전선만 삭제했습니다. 부품과 다른 배선은 유지됩니다.'
        updated.electrical=workspace
    else: raise ValueError('지원하지 않는 전장 등록 도구입니다.')
    from ..mcu_connections import topology_warnings
    warnings=topology_warnings(updated.electrical) if updated.electrical else ()
    if warnings:detail+='\n'+'\n'.join(warnings[:6])
    raw.clear();raw.update(updated.model_dump())
    return {'detail':detail,'electrical_warnings':list(warnings)}
