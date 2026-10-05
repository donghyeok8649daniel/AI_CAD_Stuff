"""Electrical feature tools shared by every AI provider, with no code execution."""
from ..electrical_catalog import CATALOG as ELECTRICAL_CATALOG


TOOLS = ('electrical_register', 'electrical_connect', 'electrical_unregister')
GUIDANCE = '''electrical_register: target is an EXISTING CAD part ID (or one created earlier in this plan). Register that body as an electrical feature, never duplicate its geometry. args={catalog_id?:exact_catalog_ID,kind?:"battery"|"wire"|"switch"|"resistor"|"capacitor"|"inductor"|"load"|"motor"|"actuator"|"mcu",name?,analysis_enabled?:false,apply_default_color?:false,a?,b?,signal_pins?:[{pin,node}],terminal_pins?:[{pin,node}],...explicit operating values}. Capacitors use capacitance_f in FARADS, optional capacitor_polarized and rated_voltage_v, with A positive/B negative for polarized devices; DC treats them as open, without charging/leakage/ESR simulation. Coils use inductance_h in HENRIES and winding_resistance_ohm; enabled DC requires both positive and solves only settled winding resistance, not ideal shorts/transients/saturation/flyback. Actuators use explicit rated_voltage_v/rated_current_a and optional startup_current_a for a separate resistance-equivalent estimate, not actual force/motion/driver behavior. Resistors use resistance_ohm. Convert user microfarads/millihenries to SI units; never fabricate missing capacitance, inductance, resistance or operating ratings. Use the exact model requested by the user from available_electrical_models; do not substitute a family or clone. Catalog source and a verified physical pin/terminal diagram are attached when available. No known diagram means manual/unverified, not a fabricated schematic. Unknown voltage/current is allowed for registration with analysis_enabled=false; it is excluded from DC calculations. Registration alone does not prove the CAD shape matches a physical product's dimensions. Preserve existing colors unless apply_default_color=true is requested, then yellow #FFD400. Preserve geometry, grouping, joints and prior circuit connections. Changing an existing model must explicitly use allow_drop_connections=true only when the user approved clearing its previous pin assignments.
electrical_connect: target is the source registered CAD part ID (MCU or verified electronic product). args={pin:exact_GPIO_key,target_part_id:registered_target_CAD_ID,target_terminal:"pin:GPIO_key"|"port:signal_terminal_key"|"a"|"b"}. Use physical pin labels and keys from registered_electrical_features / available_electrical_models; pin numbers are not BCM GPIO numbers. Register each actual CAD part before wiring it. On a non-MCU product pin is its exact named terminal key, not an invented header position; typed power/ground terminal connections are passive labels and never automatically become a DC power branch. A declared sensor/driver signal port is not its power A/B terminal. This creates a passive signal net; no firmware or complete voltage compatibility claim. Power/reference/reset pins are not ordinary GPIO. Use power_path with measured/verified operating inputs for supply calculations; never wire GPIO to a battery or motor power terminal as a normal signal.
electrical_unregister: target is an existing registered CAD part ID, args={}. Remove its electrical registration only when explicitly requested. The CAD body remains; other devices and net labels are preserved, and their now-unconnected endpoints remain visible.'''
GUIDANCE += '\nSaved measurement_reference and force_acquisition_review are offline reference data. Keep unknown force/frequency/calibration as unknown. Do not infer usable bandwidth from ADC sample rate, manufacture a serial calibration, or claim hardware, firmware or closed-loop qualification. Check actual supply terminals separately from GPIO and retain catalog worst-case ranges when editing a known measurement product.'


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
    else: raise ValueError('지원하지 않는 전장 등록 도구입니다.')
    from ..mcu_connections import topology_warnings
    warnings=topology_warnings(updated.electrical) if updated.electrical else ()
    if warnings:detail+='\n'+'\n'.join(warnings[:6])
    raw.clear();raw.update(updated.model_dump())
    return {'detail':detail,'electrical_warnings':list(warnings)}
