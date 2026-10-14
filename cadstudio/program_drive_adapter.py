"""Readonly source/net → mean voltage → motor scenario, with exact bindings.

Minimum supported route is RPi GPIO virtual trace → typed Pololu2130 channel A,
explicit nSLEEP HIGH and slow-decay inputs → explicitly declared DC plant.
No board/PWM/parameter defaults, uploaded source execution or Document writes.
"""
from copy import deepcopy
from collections import defaultdict
from hashlib import sha256
import json,math
from pathlib import Path
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator,field_validator
from .models import Design
from .program_attachment import ProgramAttachment
from .program_simulation import simulate_program,ProgramSimulationResult
from . import program_simulation
from .mcu_connections import connection_endpoints,pin_aliases
from .board_pins import board_pinout
from .mean_voltage_motor import voltage_response

PRODUCER_SHA='fc78917683a9eda3e73794829eb50567500eea58f72ea8f71d4b104f84d54cad'
PROFILE='pololu2130_A_slow_decay_explicit_sleep_v1'
UNITS={'resistance_ohm':'ohm','inductance_h':'H','torque_constant_nm_per_a':'N*m/A',
       'back_emf_v_per_rad_s':'V/(rad/s)','inertia_kg_m2':'kg*m^2','viscous_friction_nm_per_rad_s':'N*m/(rad/s)',
       'load_torque_nm':'N*m','supply_voltage_v':'V','source_internal_resistance_ohm':'ohm'}
INITIAL_UNITS={'current_a':'A','omega_rad_s':'rad/s','angle_rad':'rad'}


def fingerprint(value):
    return sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()


class _Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,allow_inf_nan=False)


class Scalar(_Strict):
    value:float
    unit:str=Field(min_length=1,max_length=40)
    @field_validator('value',mode='before')
    @classmethod
    def finite_number(cls,value):
        if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('finite numeric value required; no bool/default')
        return value


class ParameterRecord(_Strict):
    schema_version:Literal[1]
    record_id:str=Field(min_length=1,max_length=80)
    qualification:Literal['declared_synthetic','user_declared_scenario','measured_input_declared']
    evidence_reference:str=Field(min_length=1,max_length=500)
    motor_part_id:str=Field(min_length=1,max_length=40)
    shaft_reference:str=Field(min_length=1,max_length=160)
    motor_type:Literal['dc']
    values:dict[str,Scalar]
    initial_state:dict[str,Scalar]
    encoder_counts_per_rev:Scalar|None=None
    duration_s:float=Field(gt=0,le=5)
    integration_step_s:float=Field(gt=0,le=.005)
    sample_interval_s:float=Field(gt=0,le=.05)
    assumptions:Literal['ideal_stiff_source_and_wire_driver_voltage_no_losses_slow_decay_average']
    @field_validator('schema_version',mode='before')
    @classmethod
    def real_schema(cls,v):
        if type(v) is not int:raise ValueError('integer schema required')
        return v
    @field_validator('duration_s','integration_step_s','sample_interval_s',mode='before')
    @classmethod
    def finite_time(cls,v):return Scalar.finite_number(v)
    @model_validator(mode='after')
    def physical_units(self):
        if set(self.values)!=set(UNITS) or set(self.initial_state)!=set(INITIAL_UNITS):raise ValueError('missing or extra required constants/initial state')
        for name,unit in {**UNITS,**INITIAL_UNITS}.items():
            row=self.values[name] if name in UNITS else self.initial_state[name]
            if row.unit!=unit:raise ValueError('unconverted units: '+name)
        positive=set(UNITS)-{'viscous_friction_nm_per_rad_s','load_torque_nm','source_internal_resistance_ohm'}
        if any(self.values[k].value<=0 for k in positive):raise ValueError('positive R/L/Kt/Ke/J/supply required')
        if any(self.values[k].value<0 for k in set(UNITS)-positive):raise ValueError('nonnegative b/load/source resistance required')
        if self.encoder_counts_per_rev is not None:
            n=self.encoder_counts_per_rev
            if n.unit!='decoded_count/rev' or n.value<=0 or n.value>1e6 or n.value!=int(n.value):raise ValueError('declared integer decoded encoder counts required')
        return self


class DriveContract(_Strict):
    schema_version:Literal[1]
    driver_profile:Literal['pololu2130_A_slow_decay_explicit_sleep_v1']
    time_basis:Literal['declared_virtual_seconds']
    duty_unit:Literal['fraction_0_to_1']
    source_profile:Literal['raspberry_python']
    source_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    workspace_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    parameter_record_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    producer_source_sha256:Literal['fc78917683a9eda3e73794829eb50567500eea58f72ea8f71d4b104f84d54cad']
    board_component_id:str=Field(min_length=1,max_length=40)
    board_catalog_id:str=Field(min_length=1,max_length=100)
    source_component_id:str=Field(min_length=1,max_length=40)
    driver_component_id:str=Field(min_length=1,max_length=40)
    motor_component_id:str=Field(min_length=1,max_length=40)
    motor_part_id:str=Field(min_length=1,max_length=40)
    motor_catalog_id:str=Field(max_length=100)
    driver_scenario_enabled:bool
    driver_model_basis:Literal['explicit_virtual_truth_table_not_DC_analysis']
    command_pins:dict[str,str]
    @field_validator('schema_version',mode='before')
    @classmethod
    def real_schema(cls,v):
        if type(v) is not int:raise ValueError('integer schema required')
        return v
    @model_validator(mode='after')
    def unique_pins(self):
        if set(self.command_pins)!= {'AIN1','AIN2','nSLEEP'} or len(set(self.command_pins.values()))!=3:raise ValueError('three distinct explicit command pins required')
        if len({self.board_component_id,self.source_component_id,self.driver_component_id,self.motor_component_id})!=4:raise ValueError('drive role identity collision')
        return self


class TraceEnvelope(_Strict):
    schema_version:Literal[1]
    producer:Literal['cadstudio.program_simulation.simulate_program']
    producer_source_sha256:Literal['fc78917683a9eda3e73794829eb50567500eea58f72ea8f71d4b104f84d54cad']
    source_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    workspace_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    time_basis:Literal['declared_virtual_seconds']
    duty_unit:Literal['fraction_0_to_1']
    result:dict
    result_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
    @field_validator('schema_version',mode='before')
    @classmethod
    def real_schema(cls,v):
        if type(v) is not int:raise ValueError('integer schema required')
        return v


class AdapterProblem(ValueError):
    pass


def require(value,reason):
    if not value:raise AdapterProblem(reason)


def routes(design,contract,parameters,explicit_fields):
    """Exact typed control/supply/output graph. Manual pads are not rails."""
    workspace=design.electrical;require(workspace is not None,'missing_circuit')
    lookup={c.id:c for c in workspace.components};parts={p.id for p in design.parts}
    ids={'board':contract.board_component_id,'source':contract.source_component_id,'driver':contract.driver_component_id,'motor':contract.motor_component_id}
    chosen={}
    for role,cid in ids.items():
        item=lookup.get(cid);require(item is not None,'missing_'+role)
        require(item.part_registration and item.part_id in parts,'unregistered_'+role)
        require(item.closed and (contract.driver_scenario_enabled if role=='driver' else item.analysis_enabled),'disabled_'+role)
        require({'analysis_enabled','closed'}<=explicit_fields.get(item.id,set()),'undeclared_enable_'+role)
        chosen[role]=item
    board,source,driver,motor=(chosen[k] for k in ids)
    require(board.kind=='mcu' and board.catalog_id==contract.board_catalog_id and board.pinout_catalog_id==board.catalog_id,'board_pinout_mismatch')
    require(source.kind=='battery' and driver.kind=='load' and motor.kind=='motor','wrong_drive_roles')
    require(driver.catalog_id=='pololu_2130' and driver.product_pinout_catalog_id=='pololu_2130','unsupported_or_untyped_driver')
    require(driver.analysis_enabled is False,'carrier_reference_DC_status_must_be_preserved')
    require(motor.part_id==contract.motor_part_id==parameters.motor_part_id,'motor_part_mismatch')
    require(motor.catalog_id==contract.motor_catalog_id,'motor_catalog_mismatch')
    require(motor.catalog_id in ('','pololu_4755'),'unsupported_exact_motor_DC_profile')
    require({'voltage_v','internal_resistance_ohm'}<=explicit_fields.get(source.id,set()),'undeclared_source_voltage_or_resistance')
    v=parameters.values
    require(source.voltage_v==v['supply_voltage_v'].value and source.internal_resistance_ohm==v['source_internal_resistance_ohm'].value,'source_parameter_mismatch')
    require(2.7<=source.voltage_v<=10.8,'driver_supply_outside_supported_range')
    require(source.internal_resistance_ohm==0.,'nonstiff_source_not_supported_by_this_profile')
    graph=defaultdict(set)
    for component in workspace.components:
        if component.kind in ('wire','switch') and component.closed:
            require(component.analysis_enabled and {'analysis_enabled','closed'}<=explicit_fields.get(component.id,set()),'disabled_or_undeclared_conductor')
            graph[component.a].add(component.b);graph[component.b].add(component.a)
    def reach(node):
        if node is None:return set()
        seen={node};pending=[node]
        while pending:
            for other in graph[pending.pop()]:
                if other not in seen:seen.add(other);pending.append(other)
        return seen
    def joined(a,b):return a is not None and b is not None and b in reach(a)
    require(not joined(source.a,source.b),'source_rails_shorted')
    require(all(key in driver.terminal_pins for key in ('VIN','GND','AIN1','AIN2','nSLEEP','AOUT1','AOUT2')),'missing_typed_driver_terminal')
    require(joined(source.a,driver.terminal_pins['VIN']) and joined(source.b,driver.terminal_pins['GND']),'driver_power_disconnected')
    require(joined(source.a,board.a) and joined(source.b,board.b),'board_supply_disconnected')
    require(board.supply_pinout_catalog_id==board.catalog_id and board.board_supply_pins,'missing_physical_board_supply')
    pinout=board_pinout(board.catalog_id);require(pinout is not None and pinout.logic_voltage_v==3.3,'unsupported_board_logic_profile')
    physical={p.key:p for p in pinout.pins}
    supplies=[(physical[k],node) for k,node in board.board_supply_pins.items()]
    require(any(p.kind=='power' and '5 V rail' in p.functions and joined(node,source.a) for p,node in supplies) and any(p.kind=='ground' and joined(node,source.b) for p,node in supplies),'physical_5V_board_supply_route_missing')
    require(source.voltage_v==5.,'RPi_5V_supply_model_requires_explicit_separate_supply_outside_this_profile')
    require(joined(driver.terminal_pins['AOUT1'],motor.a) and joined(driver.terminal_pins['AOUT2'],motor.b),'motor_output_disconnected')
    require(not joined(motor.a,motor.b) and not any(joined(output,rail) for output in (motor.a,motor.b) for rail in (source.a,source.b)),'motor_short_or_driver_bypass')
    endpoints=connection_endpoints(workspace);commands={}
    for terminal,pin in contract.command_pins.items():
        require(pin in physical and physical[pin].kind=='signal','unknown_command_pin')
        aliases=pin_aliases(board,pin);nodes={board.signal_pins[key] for key in aliases if key in board.signal_pins}
        require(len(nodes)==1,'missing_or_ambiguous_command_pin_net');node=next(iter(nodes))
        require(joined(node,driver.terminal_pins[terminal]),'driver_command_disconnected:'+terminal)
        require(not joined(node,source.a) and not joined(node,source.b),'command_shorted_to_power')
        receivers={ep.component_id+'/'+ep.terminal for ep in endpoints if ep.component_id not in (board.id,) and lookup[ep.component_id].kind not in ('wire','switch') and ep.node in reach(node)}
        require(receivers=={driver.id+'/port:'+terminal},'command_net_fanout_or_wrong_driver:'+terminal)
        commands[pin]={'terminal':terminal,'node':node,'targets':sorted(receivers)}
    require(len({driver.terminal_pins[k] for k in contract.command_pins})==3,'driver_control_inputs_shorted')
    for other in workspace.components:
        if other.kind=='battery' and other.closed and other.id!=source.id:
            require(not(joined(other.a,source.a) or joined(other.a,source.b)),'additional_source_on_modeled_rail')
    return commands


def voltage_intervals(trace,commands,parameters):
    """Only fully declared slow-decay channel-A snapshots; no initial LOW."""
    require(trace.status=='ready','program_trace_not_ready')
    allowed={'physical_behavior'}
    require(all(issue.code in allowed for issue in trace.issues),'program_trace_has_pending_or_incomplete_behavior')
    require(trace.duration_s==parameters.duration_s,'trace_duration_mismatch')
    require(trace.events and len(trace.events)<=2000,'missing_or_excessive_trace_events')
    last=-1.;groups={}
    for event in trace.events:
        require(event.pin in commands,'unmapped_program_output_pin')
        require(event.time_s>=last and math.isfinite(event.time_s) and 0<=event.time_s<=parameters.duration_s,'invalid_virtual_event_time')
        require(type(event.duty) in (float,int) and math.isfinite(event.duty) and 0<=event.duty<=1,'invalid_PWM_duty')
        command=commands[event.pin]
        require(event.node==command['node'] and sorted(event.targets)==command['targets'],'trace_pin_route_mismatch')
        require(event.logic_voltage_v==3.3,'trace_logic_voltage_mismatch')
        if 0<event.duty<1:require(event.frequency_hz is not None and math.isfinite(event.frequency_hz) and event.frequency_hz>0,'PWM_frequency_undeclared')
        groups.setdefault(event.time_s,[]).append(event);last=event.time_s
    require(0. in groups,'missing_explicit_initial_commands')
    times=sorted(set(groups)|{parameters.duration_s});states={};segments=[]
    for t,end in zip(times,times[1:]):
        for event in groups.get(t,[]):states[commands[event.pin]['terminal']]=event.duty
        require(set(states)=={'AIN1','AIN2','nSLEEP'},'uninitialized_driver_control_state')
        require(states['nSLEEP']==1,'sleep_or_floating_driver_not_supported')
        a,b=states['AIN1'],states['AIN2']
        require(a==1 or b==1,'coast_fast_decay_or_dual_PWM_not_supported')
        # TI table2: held HIGH plus PWM yields slow decay; the duty to motor
        # voltage is inverted if PWM is on the opposite input. No clamping.
        duty=a-b
        segments.append({'start_s':t,'end_s':end,'voltage_v':duty*parameters.values['supply_voltage_v'].value})
    return segments


def review_program_drive(raw,attachment=None,contract=None,parameter_record=None,*,trace_envelope=None,cancel_event=None):
    """Missing/bad data returns null actual/scenario values with exact reasons."""
    out={'ok':False,'status':'input_missing','scope':'readonly declared virtual mean-motor scenario',
         'actual_rpm':None,'actual_current_a':None,'actual_encoder_counts':None,'scenario':None,
         'physical_clock_verified':False,'actual_motion_qualified':False,'allow_hardware_motion':False,
         'findings':[],'input_counts':{},'code_executed':False,'Document_writes':0}
    def finding(code,message):out['findings'].append({'code':code,'message':message})
    try:
        if isinstance(raw,Design):
            explicit_fields={item.id:set(item.model_fields_set) for item in raw.electrical.components} if raw.electrical else {}
            data=raw.model_dump(mode='json')
        else:
            data=raw
            explicit_fields={item['id']:set(item) for item in (data.get('electrical') or {}).get('components',[])}
        design=Design.model_validate(deepcopy(data))
        workspace=design.electrical
        if workspace:
            devices=[c for c in workspace.components if c.kind not in ('wire','switch')]
            out['input_counts']={'registered_devices':sum(bool(c.part_registration) for c in devices),'wires':sum(c.kind=='wire' for c in workspace.components),'disabled_devices':sum(not c.analysis_enabled for c in devices),'program_attachments':len(workspace.programs)}
            if any(not c.analysis_enabled for c in devices):finding('analysis_disabled_devices','회로 참조 등록과 계산 가능한 구동 경로는 다릅니다. 선택한 장치의 전원·핀·상수를 먼저 확인해야 합니다.')
        if attachment is None:finding('missing_program','지원 소스와 대상 보드의 정확한 연결이 필요합니다.')
        if contract is None:finding('missing_drive_binding','보드·드라이버·모터·전원·핀·가상 시간·SHA 연결 계약이 필요합니다.')
        if parameter_record is None:finding('missing_motor_constants','R,L,Kt,Ke,J,b,부하·공급전압·초기상태의 값/단위/출처가 필요합니다. Kv/형상/질량으로 대신 채우지 않습니다.')
        if attachment is None or contract is None or parameter_record is None:return out
        parameters=ParameterRecord.model_validate(parameter_record);spec=DriveContract.model_validate(contract)
        program=ProgramAttachment.model_validate(attachment)
        require(program.language=='raspberry_python' and program.language==spec.source_profile,'unsupported_code_profile')
        require(workspace is not None,'missing_circuit')
        require(program.sha256==spec.source_sha256,'stale_source_hash')
        require(fingerprint(workspace.model_dump(mode='json'))==spec.workspace_sha256,'stale_workspace_hash')
        require(fingerprint(parameter_record)==spec.parameter_record_sha256,'stale_parameter_record_hash')
        require(program.board_component_id==spec.board_component_id,'source_board_binding_mismatch')
        from .program_drive_provenance import assert_trace_producer
        producer_binding=assert_trace_producer(program_simulation,simulate_program)
        commands=routes(design,spec,parameters,explicit_fields)
        trace=simulate_program(workspace,program,duration_s=parameters.duration_s,cancel_event=cancel_event)
        if trace.status=='cancelled':
            out['status']='cancelled';finding('cancelled','가상 코드 추적이 취소됐습니다. 설계·회로·코드는 변경하지 않았습니다.');return out
        require(trace.status=='ready','program_trace_not_ready: '+ '; '.join(issue.code+': '+issue.message for issue in trace.issues))
        require(trace.board_component_id==spec.board_component_id and trace.attachment_sha256==spec.source_sha256,'trace_source_binding_mismatch')
        serialized=trace.model_dump(mode='json')
        envelope={'schema_version':1,'producer':'cadstudio.program_simulation.simulate_program','producer_source_sha256':PRODUCER_SHA,
                  'source_sha256':program.sha256,'workspace_sha256':spec.workspace_sha256,'time_basis':spec.time_basis,'duty_unit':spec.duty_unit,
                  'result':serialized,'result_sha256':fingerprint(serialized)}
        if trace_envelope is not None:
            supplied=TraceEnvelope.model_validate(trace_envelope).model_dump(mode='json')
            require(supplied==envelope,'stale_or_modified_trace_envelope')
            ProgramSimulationResult.model_validate(supplied['result'])
        intervals=voltage_intervals(trace,commands,parameters)
        scenario=voltage_response(parameters,intervals,cancel_event=cancel_event)
        out.update(ok=True,status='scenario_ready',scenario=scenario,voltage_intervals=intervals,trace_envelope=envelope,producer_binding=producer_binding,
                   parameter_record_sha256=spec.parameter_record_sha256,driver_profile=spec.driver_profile,parameter_qualification=parameters.qualification,
                   warnings=['가상 명령 시간과 선언된 평균 DC 모델입니다. 실제 MCU/OS/ISR·엔코더 입력·RPM 측정·FOC/상전환·PWM 스위칭·전선/드라이버 손실·전류 보호·과열은 검증하지 않습니다.',
                             '기존 PI/RPM 수동 시뮬레이터와 분리된 외부 전압 입력 경로입니다. 코드로 엔코더 피드백을 재실행하지 않습니다.'])
    except (ValueError,TypeError,KeyError,AttributeError,ArithmeticError,OSError) as exc:
        out['status']='blocked';out['scenario']=None;finding('adapter_rejected',str(exc)[:1200])
    return out


def drive_review_view_model(result,language='ko'):
    """Plain data view; no Qt/renderer, no fabricated unknown curves."""
    english=language=='en'
    return {'title':'Code → mean motor RPM review' if english else '코드 → 평균 모터 RPM 연결 검토',
            'status':result['status'],'can_run_declared_scenario':bool(result['ok']),
            'actual_rpm':None,'actual_current_a':None,'physical_time':'Unknown' if english else '미확인',
            'scenario_label':'Declared virtual DC scenario' if english else '선언된 가상 DC 시나리오',
            'scenario_points':[] if result['scenario'] is None else deepcopy(result['scenario']['points']),
            'missing_or_blocking_reasons':[] if result['ok'] else deepcopy(result['findings']),
            'physical_unverified_reasons':deepcopy(result['findings']) if result['ok'] else [],'hardware_motion_allowed':False,
            'next_required':['exact board/source/driver/output/motor SHA binding','typed closed supply/control/output routes','SI motor constants and initial state with declared provenance'],
            'native_UI_created':False}
