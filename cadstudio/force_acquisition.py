"""Offline force-acquisition chain checks, never firmware or hardware simulation.

The calculations distinguish digitisation rate, measured system bandwidth,
static capacity, fatigue qualification and a declared force calibration.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Literal

from pydantic import Field

from .electrical import ElectricalWorkspace, ElectricalModel
from .measurement_specs import (AdcMeasurement, EnvironmentalMeasurement,
    ForceCalibration, ForceChainSpec, LoadCellMeasurement)
from .mcu_connections import connection_endpoints
from .measurement_catalog import catalog_measurement


class ForceChainFinding(ElectricalModel):
    code: str
    severity: Literal['blocked','pending','warning','info']
    message: str
    component_id: str = ''


class ForceChainAssessment(ElectricalModel):
    status: Literal['blocked','pending','review_ready']
    findings: list[ForceChainFinding] = Field(default_factory=list)
    metrics: dict[str,float] = Field(default_factory=dict)
    # This is invariant, including a complete offline reference check.
    hardware_verified: Literal[False] = False
    firmware_executed: Literal[False] = False

    def report_text(self):
        state={'blocked':'설정·배선 오류 있음','pending':'확인할 사양·배선 있음','review_ready':'참고 검토 완료 · 실물 검증 전'}[self.status]
        lines=[state,'실물·펌웨어·폐루프 제어를 실행하거나 인증한 결과가 아닙니다.']
        lines.extend(f'{key}: {value:.8g}' for key,value in self.metrics.items())
        labels={'blocked':'오류','pending':'미확인','warning':'주의','info':'참고'}
        lines.extend(f'[{labels[item.severity]}] {item.message}' for item in self.findings)
        return '\n'.join(lines)


def _workspace(raw):
    if isinstance(raw,ElectricalWorkspace):return ElectricalWorkspace.model_validate(raw.model_dump())
    if hasattr(raw,'electrical'):return ElectricalWorkspace.model_validate(raw.electrical.model_dump()) if raw.electrical else ElectricalWorkspace()
    if isinstance(raw,dict):return ElectricalWorkspace.model_validate(raw.get('electrical') or {} if 'electrical' in raw else raw)
    raise TypeError('Use a CAD Design or ElectricalWorkspace.')


def assess_force_chain(raw, spec: ForceChainSpec | dict | None = None) -> ForceChainAssessment:
    workspace=_workspace(raw)
    selected=spec or workspace.force_chain
    chain=ForceChainSpec.model_validate(selected.model_dump() if isinstance(selected,ForceChainSpec) else selected) if selected is not None else ForceChainSpec()
    found=[];metrics={};components={item.id:item for item in workspace.components}
    def add(code,severity,message,component_id=''):
        found.append(ForceChainFinding(code=code,severity=severity,message=message,component_id=component_id))
    def pick(identifier,role):
        item=components.get(identifier)
        if item is None:add(role+'_missing','pending',f'{role}: 회로에 등록된 실제 부품을 선택하세요.',identifier)
        return item
    source=pick(chain.source_id,'excitation_source');load=pick(chain.load_cell_id,'load_cell')
    adc=pick(chain.adc_id,'adc');controller=pick(chain.controller_id,'controller')
    if source and source.kind!='battery':add('source_kind','blocked','여기서 선택한 여자 전원은 전압이 지정된 배터리/전원 항목이어야 합니다.',source.id)
    if source and (not source.closed or not source.analysis_enabled):add('source_disabled','blocked','선택한 여자 전원이 OFF이거나 계산에서 제외되어 있습니다.',source.id)
    if controller and controller.kind!='mcu':add('controller_kind','blocked','수집 MCU/MPU 보드를 선택하세요. 전원·ADC·모터를 제어기로 지정할 수 없습니다.',controller.id)
    if len({value for value in (chain.source_id,chain.load_cell_id,chain.adc_id,chain.controller_id) if value})<sum(bool(value) for value in (chain.source_id,chain.load_cell_id,chain.adc_id,chain.controller_id)):
        add('roles_overlap','blocked','여자 전원·로드셀·ADC·제어기는 별도 등록 부품으로 지정하세요.')
    lc=load.measurement if load and isinstance(load.measurement,LoadCellMeasurement) else None
    am=adc.measurement if adc and isinstance(adc.measurement,AdcMeasurement) else None
    documented_lc=catalog_measurement(load.catalog_id) if lc else None
    if load and lc is None:add('load_cell_spec_missing','pending','선택 부품에 로드셀 용량·감도·여자·단자 사양을 등록하세요.',load.id)
    if adc and am is None:add('adc_spec_missing','pending','선택 부품에 실제 ADC 모델과 선택한 설정을 등록하세요.',adc.id)
    for component,reference in ((load,lc),(adc,am)):
        official=catalog_measurement(component.catalog_id) if component and reference else None
        if official:
            if official.role!=reference.role:add('catalog_measurement_role_mismatch','blocked','등록된 실제 제품 기능과 계측 역할이 다릅니다.',component.id)
            for role,terminal in official.terminal_roles.items():
                if role in reference.terminal_roles and reference.terminal_roles[role]!=terminal:
                    add('catalog_terminal_role_mismatch','blocked',f'{component.name}: 선택 제품의 {role} 기능 단자를 다른 단자로 바꿀 수 없습니다. 다른 실제 보드는 별도 수동 모델로 등록하세요.',component.id)
    # Only explicit conducting wire/switch branches bridge net names. Loads,
    # ADCs, board DC A/B and signal terminals never become logical shortcuts.
    graph=defaultdict(set)
    for item in workspace.components:
        if item.kind in ('wire','switch') and item.closed and item.analysis_enabled:
            graph[item.a].add(item.b);graph[item.b].add(item.a)
    def reachable(start,end):
        if start is None or end is None:return False
        todo=[start];seen=set()
        while todo:
            key=todo.pop()
            if key==end:return True
            if key not in seen:seen.add(key);todo.extend(graph[key]-seen)
        return False
    endpoints=connection_endpoints(workspace)
    endpointmap={(item.component_id,item.terminal):item.node for item in endpoints}
    def node(component,terminal,code):
        if component is None:return None
        if not terminal or (component.id,terminal) not in endpointmap:
            add(code+'_terminal_missing','pending',f'{component.name}: 실제 단자와 기능 역할의 매핑을 지정하세요 ({code}).',component.id);return None
        value=endpointmap[(component.id,terminal)]
        if value is None:add(code+'_wire_missing','pending',f'{component.name}: {terminal} 단자가 연결되지 않았습니다.',component.id)
        return value
    def role_node(component,reference,role):return node(component,reference.terminal_roles.get(role,'') if reference else '',role)
    def join(left,right,code,label):
        if left is not None and right is not None and not reachable(left,right):add(code,'blocked',label)
    def rail_voltage(positive,negative,code):
        if positive is None or negative is None:return None
        if reachable(positive,negative):add(code+'_short','blocked','전원 +/− 단자가 같은 도통망에 연결되었습니다.');return 0.
        values=[]
        for battery in workspace.components:
            if battery.kind=='battery' and battery.closed and battery.analysis_enabled:
                if reachable(positive,battery.a) and reachable(negative,battery.b):values.append(battery.voltage_v)
                if reachable(positive,battery.b) and reachable(negative,battery.a):values.append(-battery.voltage_v)
        if not values:add(code+'_supply_missing','pending','물리 전원 단자에 실제 공급 전압을 가진 전원 경로를 연결하세요.');return None
        if max(values)-min(values)>1e-8:add(code+'_source_conflict','blocked','한 전원망에 다른 전압의 이상 전원이 병렬 연결되어 있습니다.');return None
        return values[0]
    if lc:
        if isinstance(documented_lc,LoadCellMeasurement):
            for field in ('sensitivity_nominal_mv_per_v','sensitivity_min_mv_per_v','sensitivity_max_mv_per_v'):
                canonical=getattr(documented_lc,field);saved=getattr(lc,field)
                if canonical is not None and (saved is None or not math.isclose(saved,canonical,rel_tol=1e-8,abs_tol=1e-8)):
                    add('catalog_sensitivity_reference_mismatch','pending' if saved is None else 'blocked',
                        f'선택한 실제 로드셀 SKU의 제조사 {field} 참고값과 저장 값이 다릅니다. 제조사 상한으로 입력 여유를 검사하며 일련번호 실측 감도와 N/count 교정은 별도로 보존합니다.',load.id)
            actual=lc.sensitivity_mv_per_v;minimum=documented_lc.sensitivity_min_mv_per_v;maximum=documented_lc.sensitivity_max_mv_per_v
            if actual is not None and (minimum is not None and actual<minimum or maximum is not None and actual>maximum):
                add('serial_sensitivity_outside_reference','pending','입력한 일련번호 실측 감도가 선택 SKU의 비조정 범위 밖입니다. 제품/단위/교정 자료를 확인하세요. 실측 교정값을 삭제하거나 제조사 값으로 바꾸지 않습니다.',load.id)
        positive=role_node(load,lc,'excitation_positive');negative=role_node(load,lc,'excitation_negative')
        if source:
            join(source.a,positive,'excitation_open','로드셀 여자 +가 선택 전원에 연결되지 않았습니다.')
            join(source.b,negative,'excitation_return_open','로드셀 여자 −가 선택 전원 리턴에 연결되지 않았습니다.')
        actual_excitation=rail_voltage(positive,negative,'excitation')
        if actual_excitation is not None:
            metrics['connected_excitation_v']=actual_excitation
            if lc.excitation_voltage_v is not None and not math.isclose(actual_excitation,lc.excitation_voltage_v,rel_tol=.001,abs_tol=.001):add('excitation_setting_mismatch','blocked','로드셀 여자 설정과 연결된 전원의 전압이 다릅니다.',load.id)
        elif lc.excitation_voltage_v is not None:metrics['declared_excitation_v']=lc.excitation_voltage_v
        excitation=actual_excitation if actual_excitation is not None else lc.excitation_voltage_v
        for value in ('rated_capacity_n','sensitivity_mv_per_v','excitation_voltage_v'):
            if getattr(lc,value) is None:add('load_cell_'+value+'_missing','pending',f'로드셀 {value}를 실제 제품 자료 또는 측정값으로 입력하세요.',load.id)
        if lc.excitation_min_v is None or lc.excitation_max_v is None:add('excitation_range_unknown','pending','로드셀 여자 전압 허용 범위를 확인하세요.',load.id)
        if excitation is not None and (excitation<=0 or lc.excitation_min_v is not None and excitation<lc.excitation_min_v or lc.excitation_max_v is not None and excitation>lc.excitation_max_v):add('excitation_out_of_range','blocked','연결 여자 전압이 로드셀 허용 범위를 벗어납니다.',load.id)
        if chain.target_peak_force_n is None:add('target_force_missing','pending','목표 최대 하중(N)을 정해야 로드셀 용량을 비교할 수 있습니다.')
        elif lc.rated_capacity_n is not None:
            metrics['capacity_utilization']=chain.target_peak_force_n/lc.rated_capacity_n
            if chain.target_peak_force_n>lc.rated_capacity_n:add('capacity_exceeded','blocked','목표 하중이 로드셀 정격 용량을 초과합니다.',load.id)
        if load.catalog_id=='hbk_u10m_25kn_passive' and lc.rated_capacity_n!=25000:add('catalog_capacity_mismatch','blocked','선택한 U10M 25 kN 제품과 입력 용량이 다릅니다. 다른 실제 제품은 별도 모델로 등록하세요.',load.id)
        if lc.load_direction!='tension_compression':add('load_direction_unverified','pending','인장·압축 반복 용도에 대한 로드셀 방향 사양을 확인하세요.',load.id)
        if lc.fatigue_rated is not True or lc.fatigue_cycles is None or lc.fatigue_load_n is None:add('fatigue_qualification_unknown','pending','정적 용량으로 반복 피로 정격을 추정하지 않습니다. 반복 하중·사이클 정격을 확인하세요.',load.id)
        if lc.fatigue_load_n is not None and chain.target_peak_force_n is not None and chain.target_peak_force_n>lc.fatigue_load_n:add('fatigue_load_exceeded','blocked','목표 반복 하중이 입력된 로드셀 피로 하중 정격을 초과합니다.',load.id)
        if lc.calibration.status=='uncalibrated':add('force_uncalibrated','pending','로드셀·여자·ADC 설정 조합으로 실제 하중 교정이 필요합니다.',load.id)
        else:add('calibration_declared','warning','교정 계수는 사용자가 선언한 자료입니다. 인증서나 실물 교정을 앱이 검증하지 않습니다.',load.id)
    else:excitation=None
    if am:
        sigp=role_node(adc,am,'signal_positive');sign=role_node(adc,am,'signal_negative')
        if sigp is not None and sign is not None and reachable(sigp,sign):add('signal_short','blocked','ADC 차동 입력 +/−가 같은 도통망에 연결되어 있습니다.',adc.id)
        if lc:
            join(role_node(load,lc,'signal_positive'),sigp,'signal_positive_open','로드셀 출력 +와 ADC 입력 +의 결선이 없습니다.')
            join(role_node(load,lc,'signal_negative'),sign,'signal_negative_open','로드셀 출력 −와 ADC 입력 −의 결선이 없습니다.')
        ap=role_node(adc,am,'analog_positive');an=role_node(adc,am,'analog_negative')
        dp=role_node(adc,am,'digital_positive');dn=role_node(adc,am,'digital_negative')
        av=rail_voltage(ap,an,'adc_analog');dv=rail_voltage(dp,dn,'adc_digital')
        for voltage,label,minimum,maximum,declared in ((av,'analog',am.analog_supply_min_v,am.analog_supply_max_v,am.analog_supply_voltage_v),(dv,'digital',am.digital_supply_min_v,am.digital_supply_max_v,am.digital_supply_voltage_v)):
            if voltage is not None:
                metrics['connected_'+label+'_supply_v']=voltage
                if minimum is not None and voltage<minimum or maximum is not None and voltage>maximum:add('adc_'+label+'_supply_range','blocked','ADC '+label+' 전원 허용 범위를 벗어납니다.',adc.id)
                if declared is not None and not math.isclose(voltage,declared,rel_tol=.001,abs_tol=.001):add('adc_'+label+'_supply_mismatch','blocked','ADC '+label+' 전원 설정과 물리 결선 전압이 다릅니다.',adc.id)
            if minimum is None or maximum is None:add('adc_'+label+'_supply_unknown','pending','ADC '+label+' 전원 허용 범위를 확인하세요.',adc.id)
            documented={'ti_ads131m04':(2.7,3.6),'ti_ads1232':(2.7,5.3),'avia_hx711':(2.6,5.5)}.get(adc.catalog_id)
            if voltage is not None and documented and not documented[0]<=voltage<=documented[1]:add('adc_'+label+'_datasheet_supply','blocked','입력한 사용자 범위와 관계없이 해당 ADC 자료의 기본 전원 허용 범위를 벗어납니다.',adc.id)
        if lc:join(role_node(load,lc,'excitation_negative'),an,'analog_reference_open','로드셀 여자 리턴과 ADC 아날로그 기준 사이의 참조 경로를 확인하세요. 절연 경로는 수동 검토가 필요합니다.')
        gain=am.gain;fullscale=am.input_full_scale_mv;lo=am.input_common_mode_min_v;hi=am.input_common_mode_max_v
        if gain is None:add('adc_gain_missing','pending','선택한 PGA gain을 입력하세요.',adc.id)
        reference=am.reference_voltage_v
        if adc.catalog_id=='ti_ads131m04':
            if gain is not None and gain not in (1,2,4,8,16,32,64,128):add('adc_gain_unsupported','blocked','ADS131M04 PGA는 1/2/4/8/16/32/64/128 중 하나입니다.',adc.id)
            if gain:fullscale=1200/gain
            if av is not None and gain is not None:lo=-1.3;hi=av-(1.8 if gain>=8 else 0)
            if am.reference_mode!='internal':add('adc_reference_mode','blocked','이 ADS131M04 참고 모델은 내부 1.2 V 기준만 확인되었습니다.',adc.id)
            if reference is not None and not math.isclose(reference,1.2,rel_tol=.001):add('adc_reference_mismatch','blocked','ADS131M04 내부 기준값 설정을 확인하세요.',adc.id)
            if am.clock_frequency_hz is None or am.oversampling_ratio is None or am.power_mode=='unknown':add('adc_clock_settings_missing','pending','ADS131M04 CLKIN·OSR·power mode를 지정해야 출력률이 결정됩니다.',adc.id)
            else:
                maximum_clock={'high_resolution':8.4e6,'low_power':4.15e6,'very_low_power':2.08e6}[am.power_mode]
                if not 3e5<=am.clock_frequency_hz<=maximum_clock or am.oversampling_ratio not in (64,128,256,512,1024,2048,4096,8192,16384):add('adc_clock_settings_range','blocked','ADS131M04 선택 power mode의 권장 CLKIN 범위 또는 지원 OSR을 확인하세요.',adc.id)
                if am.oversampling_ratio==64:
                    if am.turbo_mode is False:add('adc_turbo_mode_mismatch','blocked','ADS131M04 OSR 64는 CLOCK.TBM(Turbo Mode)=1이 필요합니다.',adc.id)
                    elif am.turbo_mode is None:add('adc_turbo_mode_unknown','pending','OSR 64를 선택하려면 CLOCK.TBM(Turbo Mode)=1 설정을 확인하세요.',adc.id)
                elif am.turbo_mode is True:add('adc_turbo_mode_mismatch','blocked','Turbo Mode=1은 OSR 64입니다. 선택한 일반 OSR과 다릅니다.',adc.id)
                expected_rate=am.clock_frequency_hz/(2*am.oversampling_ratio);metrics['clock_derived_sample_rate_sps']=expected_rate
                if am.sample_rate_sps is not None and not math.isclose(am.sample_rate_sps,expected_rate,rel_tol=.001):add('adc_clock_rate_mismatch','blocked','ADC 입력한 출력률이 CLKIN/(2·OSR)와 다릅니다.',adc.id)
            external=node(adc,'port:CLKIN','external_clock')
            oscillator=components.get(chain.external_clock_id)
            if oscillator is None or oscillator.id in (chain.controller_id,chain.adc_id,chain.load_cell_id,chain.source_id):add('adc_external_clock_missing','pending','CLKIN에는 SPI clock와 별도의 실제 클록 공급 부품·출력 단자를 지정하세요.',adc.id)
            else:
                clock_node=node(oscillator,chain.external_clock_terminal,'oscillator_output')
                join(external,clock_node,'adc_external_clock_open','별도 클록 공급 출력과 ADC CLKIN의 실제 결선이 없습니다.')
                add('oscillator_reference_only','pending','클록 부품의 실제 3.3 V 레벨·허용 오차·듀티·배선 타이밍을 검토하세요. 선언한 주파수만으로 발진 동작을 증명하지 않습니다.',oscillator.id)
            if lc and excitation is not None:
                ratio=am.excitation_sense_divider_ratio;sensegain=am.excitation_sense_gain
                if ratio is None or sensegain is None:add('excitation_monitor_unknown','pending','내부 기준 ADC에서는 여자 변동을 측정할 실제 분압·채널 gain·버퍼/교정 경로가 미확인입니다.',adc.id)
                else:
                    metrics['declared_excitation_sense_v']=excitation*ratio
                    if sensegain not in (1,2,4,8,16,32,64,128):add('excitation_sense_gain_unsupported','blocked','여자 감시 ADC 채널 gain 설정을 확인하세요.',adc.id)
                    elif excitation*ratio>=1.2/sensegain:add('excitation_sense_clipping','blocked','여자 감시 분압 출력이 별도 채널의 ±1.2 V/gain 입력 범위를 넘거나 도달합니다.',adc.id)
                    for role in ('excitation_sense_positive','excitation_sense_negative'):role_node(adc,am,role)
                    add('excitation_monitor_calibration','pending','분압 실제 비·버퍼·입력 공통모드·배선·동기 취득 교정은 아직 검증되지 않았습니다.',adc.id)
        elif adc.catalog_id=='ti_ads1232':
            if gain is not None and gain not in (1,2,64,128):add('adc_gain_unsupported','blocked','ADS1232 지원 gain은 1/2/64/128입니다.',adc.id)
            if gain and reference:fullscale=500*reference/gain
            if av is not None and gain is not None and gain>=64:lo=1.5;hi=av-1.5
            if am.sample_rate_sps is not None and am.sample_rate_sps not in (10,80):add('adc_rate_unsupported','blocked','ADS1232 출력 설정은 10 또는 80 SPS입니다.',adc.id)
        elif adc.catalog_id=='avia_hx711':
            if gain is not None and gain not in (64,128):add('adc_gain_unsupported','blocked','이 HX711 채널 A의 gain은 64/128입니다. B 채널 gain 32를 A에 적용하지 않습니다.',adc.id)
            if gain and av is not None:fullscale=500*av/gain;lo=1.2;hi=av-1.3
            if am.sample_rate_sps is not None and am.sample_rate_sps not in (10,80):add('adc_rate_unsupported','blocked','HX711 내부 클록 기준 설정은 10 또는 80 SPS입니다.',adc.id)
            if chain.purpose=='force_feedback':add('hx711_force_control','pending','HX711의 저속 데이터 출력만으로 고주파 힘 폐루프 제어를 승인하지 않습니다.',adc.id)
        if am.reference_mode=='unknown':add('adc_reference_unknown','pending','ADC 기준 전압과 라티오메트릭/고정 기준 구성을 확인하세요.',adc.id)
        if am.reference_mode.startswith('external'):
            rp=role_node(adc,am,'reference_positive');rn=role_node(adc,am,'reference_negative')
            rv=rail_voltage(rp,rn,'adc_reference')
            if rv is not None and reference is not None and not math.isclose(rv,reference,rel_tol=.001,abs_tol=.001):add('reference_voltage_mismatch','blocked','외부 ADC 기준 전압 설정과 실제 결선이 다릅니다.',adc.id)
            if am.reference_mode=='external_ratiometric' and lc:
                join(rp,role_node(load,lc,'excitation_positive'),'ratiometric_positive','라티오메트릭 기준 +가 여자 +와 연결되지 않았습니다.')
                join(rn,role_node(load,lc,'excitation_negative'),'ratiometric_negative','라티오메트릭 기준 −가 여자 −와 연결되지 않았습니다.')
        sensitivity_values=(lc.sensitivity_mv_per_v,lc.sensitivity_max_mv_per_v,
            documented_lc.sensitivity_max_mv_per_v if isinstance(documented_lc,LoadCellMeasurement) else None) if lc else ()
        sensitivity=max(value for value in sensitivity_values if value is not None) if any(value is not None for value in sensitivity_values) else None
        if lc and sensitivity is not None and excitation is not None:
            rated_signal=sensitivity*excitation;metrics['rated_bridge_output_mv']=rated_signal
            if isinstance(documented_lc,LoadCellMeasurement) and documented_lc.sensitivity_max_mv_per_v is not None:
                add('sensitivity_worst_case','info','입력 여유는 선택 SKU의 제조사 비조정 감도 상한을 포함해 검토합니다. 저장한 범위 변경으로 이를 낮추지 않습니다. N/count 변환에는 실제 일련번호 교정이 필요합니다.',load.id)
            elif lc.sensitivity_max_mv_per_v is not None:
                add('sensitivity_worst_case','info','수동 로드셀 입력 여유는 사용자가 선언한 감도 상한을 포함합니다. 제조사 자료나 실측 교정을 검증한 값은 아닙니다.',load.id)
            requested_signal=rated_signal*chain.target_peak_force_n/lc.rated_capacity_n if chain.target_peak_force_n is not None and lc.rated_capacity_n else rated_signal
            metrics['requested_bridge_output_mv']=requested_signal
            if fullscale is None:add('adc_fullscale_unknown','pending','ADC 차동 입력 풀스케일과 gain/ref 설정을 확인하세요.',adc.id)
            else:
                metrics['adc_differential_full_scale_mv']=fullscale;metrics['adc_headroom_ratio']=requested_signal/fullscale
                if requested_signal>=fullscale:add('adc_input_clipping','blocked','목표 하중의 브리지 차동 출력이 ADC 입력 범위를 넘거나 도달합니다.',adc.id)
            cm=lc.output_common_mode_v
            if cm is None and lc.bridge_type=='full_bridge':cm=excitation/2;add('balanced_bridge_cm_estimate','warning','브리지 공통모드는 균형 브리지 여자/2 추정입니다. 실물·증폭기·오프셋을 별도 확인하세요.',load.id)
            if cm is None or lo is None or hi is None:add('input_common_mode_unknown','pending','ADC 각 입력의 허용 공통모드와 실제 브리지 오프셋을 확인하세요.',adc.id)
            else:
                low_input=cm-abs(requested_signal)/2000;high_input=cm+abs(requested_signal)/2000
                metrics.update(input_min_estimate_v=low_input,input_max_estimate_v=high_input,adc_input_allowed_min_v=lo,adc_input_allowed_max_v=hi)
                if low_input<lo or high_input>hi:add('adc_common_mode_violation','blocked',f'ADC 각 입력 {low_input:.4g}–{high_input:.4g} V가 gain 조건의 허용 {lo:.4g}–{hi:.4g} V 밖입니다.',adc.id)
        fs=am.sample_rate_sps;frequency=chain.target_frequency_hz
        if fs is None:add('sample_rate_missing','pending','ADC 실제 선택 출력률(SPS)을 입력하세요. 최대 SPS는 선택 출력률이 아닙니다.',adc.id)
        elif am.max_sample_rate_sps is not None and fs>am.max_sample_rate_sps:
            if adc.catalog_id=='ti_ads131m04':add('sample_rate_above_nominal','warning','ADS131M04 자료의 64 kSPS는 공칭 8.192 MHz 조건입니다. 실제 CLKIN·power mode·OSR 범위와 출력률 계산을 함께 확인하세요.',adc.id)
            else:add('sample_rate_exceeded','blocked','선택 출력률이 ADC 자료의 최대값을 초과합니다.',adc.id)
        if frequency is None:add('test_frequency_missing','pending','목표 반복 주파수(Hz)를 입력하세요.')
        if fs is not None and frequency is not None:
            metrics['samples_per_cycle']=fs/frequency
            if fs<=2*frequency:add('sampling_aliasing','blocked','출력률이 목표 주파수의 2배 이하입니다. 파형 복원 여유가 없습니다.',adc.id)
            elif fs/frequency<chain.samples_per_cycle_required:add('sampling_quality_criterion','pending','주기당 샘플이 사용자가 설정한 검토 기준에 미달합니다. 이 기준은 규격 인증값이 아닙니다.',adc.id)
        if am.usable_bandwidth_hz is None or am.bandwidth_basis=='unknown':add('system_bandwidth_unknown','pending','출력 SPS를 대역폭으로 간주하지 않습니다. 필터 또는 측정한 시스템 대역폭을 입력하세요.',adc.id)
        elif frequency is not None and frequency>=am.usable_bandwidth_hz:add('acquisition_bandwidth_exceeded','blocked','목표 주파수가 입력한 수집 경로의 사용 대역폭 이상입니다.',adc.id)
        if am.bandwidth_basis=='datasheet_filter':add('filter_not_system_bandwidth','pending','ADC 필터 대역폭은 증폭기·센서·배선·제어기의 전체 사용 대역폭 검증을 대신하지 않습니다.',adc.id)
        if lc and frequency is not None:
            if lc.dynamic_bandwidth_hz is None:add('load_cell_bandwidth_unknown','pending','로드셀의 실제 장착 조건에 대한 동적 대역폭이 미확인입니다.',load.id)
            elif frequency>=lc.dynamic_bandwidth_hz:add('load_cell_bandwidth_exceeded','blocked','목표 주파수가 입력한 로드셀 동적 대역폭 이상입니다.',load.id)
        if controller:
            from .board_pins import board_pinout
            pinout=board_pinout(controller.supply_pinout_catalog_id or controller.catalog_id)
            if pinout and pinout.logic_voltage_v is not None and dv is not None and dv>pinout.logic_voltage_v+.1:
                add('host_digital_level_mismatch','blocked','ADC DVDD가 수집 보드 신호 전압보다 높습니다. 실제 레벨 변환 경로를 별도 모델로 검토해야 하며 직결로 승인하지 않습니다.',controller.id)
            signals=('clock','data_out','data_in','chip_select','data_ready') if am.interface=='spi' else ('clock','data_out') if am.interface=='clock_data' else ('clock','data') if am.interface=='i2c' else ()
            if not signals:add('adc_interface_unknown','pending','ADC의 디지털 수집 인터페이스를 확인하세요.',adc.id)
            host_nodes=[]
            for role in signals:
                terminal=chain.controller_terminals.get(role,'')
                endpoint=next((item for item in endpoints if item.component_id==controller.id and item.terminal==terminal),None)
                if endpoint and (not terminal.startswith('pin:') or endpoint.pin_kind!='signal'):
                    add('host_signal_not_gpio','blocked','ADC 디지털 신호는 수집 보드의 실제 신호 핀에 연결하세요. 전원 A/B·물리 전원 단자는 GPIO가 아닙니다.',controller.id)
                adcn=role_node(adc,am,role);hostn=node(controller,terminal,'host_'+role)
                if hostn is not None:host_nodes.append(hostn)
                join(adcn,hostn,'host_'+role+'_open',f'ADC {role}와 선택한 MCU/MPU 핀의 실제 결선이 없습니다.')
            if any(reachable(first,second) for index,first in enumerate(host_nodes) for second in host_nodes[index+1:]):add('digital_signals_short','blocked','서로 다른 ADC 인터페이스 신호가 같은 도통망에 연결되었습니다.',adc.id)
            ground_terminal=chain.controller_terminals.get('ground','')
            ground_endpoint=next((item for item in endpoints if item.component_id==controller.id and item.terminal==ground_terminal),None)
            if ground_endpoint and (not ground_terminal.startswith('supply:') or ground_endpoint.pin_kind!='ground'):
                add('host_ground_not_physical','blocked','수집 보드의 실제 GND 단자를 지정하세요. DC 부하 B와 물리 GND를 자동으로 같다고 간주하지 않습니다.',controller.id)
            hostground=node(controller,ground_terminal,'host_ground');join(dn,hostground,'host_reference_open','ADC 디지털 리턴과 MCU/MPU의 실제 기준 리턴 경로를 확인하세요.')
            add('digital_protocol_unverified','pending','결선과 전압 참고 검토입니다. GPIO 방향·풀업·SPI/I²C·DRDY·실시간 수집 코드는 실행하지 않았습니다.',controller.id)
        add('wire_loss_unverified','warning','여자·ADC 전원 전압은 연결된 이상 전원의 지정값입니다. 실제 배선 손실·레귤레이터·노이즈·입력 보호는 별도 검토하세요.',adc.id)
    for identifier in chain.environment_ids:
        sensor=pick(identifier,'environment')
        em=sensor.measurement if sensor and isinstance(sensor.measurement,EnvironmentalMeasurement) else None
        if not em:
            if sensor:add('environment_spec_missing','pending','온습도 센서의 실제 모델·물리 핀·전압 사양을 등록하세요.',identifier)
            continue
        official=catalog_measurement(sensor.catalog_id)
        if official and official.role!=em.role:add('catalog_measurement_role_mismatch','blocked','등록된 실제 제품을 온습도 센서로 바꿔 평가할 수 없습니다.',identifier)
        if official:
            for role,terminal in official.terminal_roles.items():
                if role in em.terminal_roles and em.terminal_roles[role]!=terminal:add('catalog_terminal_role_mismatch','blocked','해당 센서 제품의 기능 핀을 전원 또는 다른 핀으로 바꿔 평가할 수 없습니다.',identifier)
        voltage=rail_voltage(role_node(sensor,em,'power_positive'),role_node(sensor,em,'power_negative'),'environment_'+identifier)
        if voltage is not None and (em.supply_min_v is not None and voltage<em.supply_min_v or em.supply_max_v is not None and voltage>em.supply_max_v):add('environment_supply_range','blocked','온습도 센서에 허용 범위를 벗어난 전압이 연결되어 있습니다.',identifier)
        documented={'sensirion_sht45_ad1b':(1.08,3.6),'sensirion_sht31_dis_b':(2.15,5.5)}.get(sensor.catalog_id)
        if voltage is not None and documented and not documented[0]<=voltage<=documented[1]:add('environment_datasheet_supply','blocked','해당 실제 센서의 제조사 전원 범위를 벗어납니다. 사용자 범위 편집으로 이를 승인하지 않습니다.',identifier)
        if em.interface=='i2c' and em.i2c_address is None:add('environment_address_unknown','pending','실제 ADDR 설정 또는 제품별 I²C 주소를 확인하세요.',identifier)
        for role in ('clock','data'):
            signal=role_node(sensor,em,role)
            if signal is not None and not any(endpoint.component_id!=identifier and endpoint.terminal.startswith('pin:') and reachable(signal,endpoint.node) for endpoint in endpoints if endpoint.node):add('environment_'+role+'_host_missing','pending','온습도 센서 '+role+'의 수집 보드 핀 연결을 확인하세요.',identifier)
        add('environment_not_force_compensation','warning','온습도 값은 환경 기록용입니다. 검증된 재료/센서 모델 없이 힘·피로 보정값을 만들지 않습니다.',identifier)
    if chain.purpose=='force_feedback':add('force_control_unverified','pending','힘 폐루프에는 실제 수집 지연·제어 주기·센서 대역폭·구동 플랜트·펌웨어 검증이 추가로 필요합니다.')
    status='blocked' if any(item.severity=='blocked' for item in found) else 'pending' if any(item.severity=='pending' for item in found) else 'review_ready'
    return ForceChainAssessment(status=status,findings=found,metrics=metrics)


def calibrate_force(points, *, notes='') -> ForceCalibration:
    """Least-squares affine count-to-newton calibration from user measurements."""
    pairs=list(points)
    if not 2<=len(pairs)<=10000:raise ValueError('Supply 2–10000 measured (ADC count, force N) pairs.')
    checked=[]
    for counts,force_n in pairs:
        if isinstance(counts,bool) or isinstance(force_n,bool) or not math.isfinite(float(counts)) or not math.isfinite(float(force_n)):raise ValueError('Calibration values must be finite counts and newtons.')
        if abs(float(counts))>2**53 or abs(float(force_n))>1e9:raise ValueError('Calibration points exceed supported ADC count precision or 1e9 N force bound.')
        checked.append((float(counts),float(force_n)))
    xc=sum(x for x,y in checked)/len(checked);yc=sum(y for x,y in checked)/len(checked)
    denominator=sum((x-xc)**2 for x,y in checked)
    if denominator<=0:raise ValueError('ADC counts must vary between calibration points.')
    scale=sum((x-xc)*(y-yc) for x,y in checked)/denominator
    if not math.isfinite(scale) or scale==0:raise ValueError('Measured force must establish a nonzero N/count slope.')
    offset=xc-yc/scale
    residual=math.sqrt(sum((y-(x-offset)*scale)**2 for x,y in checked)/len(checked))
    return ForceCalibration(status='user_calibrated',zero_offset_counts=offset,scale_n_per_count=scale,
        point_count=len(checked),rms_residual_n=residual,notes=notes)


def force_from_counts(counts, calibration: ForceCalibration | dict) -> float:
    calibration=ForceCalibration.model_validate(calibration) if isinstance(calibration,dict) else calibration
    if calibration.status=='uncalibrated' or calibration.scale_n_per_count is None or calibration.zero_offset_counts is None:raise ValueError('Measured calibration is required before converting ADC counts to N.')
    if isinstance(counts,bool) or not math.isfinite(float(counts)):raise ValueError('ADC counts must be finite.')
    value=(float(counts)-calibration.zero_offset_counts)*calibration.scale_n_per_count
    if not math.isfinite(value):raise ValueError('Force conversion overflowed.')
    return value
