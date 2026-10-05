"""Native, editable force-acquisition references with explicit unknown values."""
from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox,QDialog,QDialogButtonBox,QFormLayout,
    QHBoxLayout,QLabel,QLineEdit,QListWidget,QListWidgetItem,QMessageBox,
    QPushButton,QScrollArea,QTabWidget,QTextEdit,QVBoxLayout,QWidget)

from ..electrical import ElectricalWorkspace
from ..force_acquisition import assess_force_chain,calibrate_force
from ..measurement_catalog import catalog_measurement
from ..measurement_specs import (AdcMeasurement,EnvironmentalMeasurement,
    ForceCalibration,ForceChainSpec,LoadCellMeasurement)
from ..mcu_connections import connection_endpoints


ROLE_NAMES={'load_cell':'로드셀','adc':'ADC 수집','humidity_temperature':'온습도'}
FIELDS={
 'load_cell':(
    ('rated_capacity_n','정격 용량','N'),('sensitivity_mv_per_v','정격 감도','mV/V'),
    ('sensitivity_nominal_mv_per_v','제품 공칭 감도 (교정값 아님)','mV/V'),('sensitivity_min_mv_per_v','제품 비조정 감도 최소','mV/V'),('sensitivity_max_mv_per_v','제품 비조정 감도 최대','mV/V'),
    ('excitation_voltage_v','선택 여자 전압','V'),('excitation_min_v','여자 최소','V'),
    ('excitation_max_v','여자 최대','V'),('bridge_resistance_ohm','브리지 저항','Ω'),
    ('bridge_resistance_min_ohm','제품 브리지 저항 하한','Ω'),
    ('output_common_mode_v','실측/명시 공통모드','V'),('dynamic_bandwidth_hz','장착 경로 동적 대역폭','Hz'),
    ('fatigue_cycles','제조사 피로 사이클 정격','cycles'),('fatigue_load_n','제조사 반복 하중 정격','N')),
 'adc':(
    ('resolution_bits','분해능','bit'),('gain','선택 PGA gain','V/V'),('sample_rate_sps','선택 데이터 출력률','SPS'),
    ('max_sample_rate_sps','제품 최대 출력률','SPS'),('usable_bandwidth_hz','수집 경로 사용 대역폭','Hz'),
    ('settling_time_ms','필터 설정 후 정착 시간','ms'),('reference_voltage_v','기준 전압','V'),
    ('input_full_scale_mv','차동 입력 ±풀스케일','mV'),('analog_supply_voltage_v','선택 AVDD','V'),
    ('digital_supply_voltage_v','선택 DVDD','V'),('analog_supply_min_v','AVDD 최소','V'),
    ('analog_supply_max_v','AVDD 최대','V'),('digital_supply_min_v','DVDD 최소','V'),
    ('digital_supply_max_v','DVDD 최대','V'),('input_common_mode_min_v','각 입력 최소','V'),
    ('input_common_mode_max_v','각 입력 최대','V'),('simultaneous_channels','동시 채널','channels'),
    ('clock_frequency_hz','CLKIN 클록','Hz'),('oversampling_ratio','선택 OSR','ratio')),
 # Excitation monitoring is a different channel than the bridge gain.
 'humidity_temperature':(
    ('supply_min_v','전원 최소','V'),('supply_max_v','전원 최대','V'),
    ('temperature_min_c','온도 최소','°C'),('temperature_max_c','온도 최대','°C'),
    ('humidity_min_rh','습도 최소','%RH'),('humidity_max_rh','습도 최대','%RH'),
    ('i2c_address','I²C 주소 (0x44 가능)','address'),('response_time_s','응답 시간','s')),
}
CHOICES={
 'load_cell':{'bridge_type':('unknown','full_bridge'),'load_direction':('unknown','tension','compression','tension_compression'),'fatigue_rated':(None,False,True)},
 'adc':{'interface':('unknown','spi','i2c','clock_data'),'reference_mode':('unknown','internal','external_ratiometric','external_fixed'),
    'bandwidth_basis':('unknown','datasheet_filter','measured_system'),'power_mode':('unknown','high_resolution','low_power','very_low_power'),'turbo_mode':(None,False,True)},
 'humidity_temperature':{'interface':('unknown','i2c','spi','analog')},
}
INTEGER_FIELDS={'resolution_bits','simultaneous_channels','oversampling_ratio','fatigue_cycles','i2c_address'}


def _parse_mapping(text):
    values={}
    for line in text.splitlines():
        line=line.strip()
        if not line:continue
        key,sep,value=line.partition('=')
        if not sep or not key.strip() or not value.strip() or key.strip() in values:raise ValueError('각 행은 역할=실제단자 형식이며 역할은 중복하지 않습니다.')
        values[key.strip()]=value.strip()
    return values


class MeasurementComponentDialog(QDialog):
    def __init__(self,parent,component,workspace,role=None):
        super().__init__(parent);self.setWindowTitle(component.name+' · 계측 사양');self.resize(660,800)
        self.component=component;self.role=role or (component.measurement.role if component.measurement else 'load_cell')
        profile=component.measurement or catalog_measurement(component.catalog_id)
        if profile is None or profile.role!=self.role:profile={'load_cell':LoadCellMeasurement,'adc':AdcMeasurement,'humidity_temperature':EnvironmentalMeasurement}[self.role]()
        self.original=profile.model_dump();self.measurement=None;self.fields={};self.choices={}
        layout=QVBoxLayout(self);notice=QLabel(ROLE_NAMES[self.role]+' · 빈 칸은 미확인입니다. 제품 자료와 선택 설정을 구분해 입력하세요.');notice.setWordWrap(True);layout.addWidget(notice)
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();form=QFormLayout(body)
        for key,label,unit in FIELDS[self.role]:
            edit=QLineEdit('' if self.original.get(key) is None else str(self.original[key]));edit.setObjectName('measurement_'+key);edit.setPlaceholderText('미확인');form.addRow(f'{label} ({unit})',edit);self.fields[key]=edit
        if self.role=='adc':
            for key,label in (('excitation_sense_divider_ratio','여자 감시 실제 분압 비 (출력/여자)'),('excitation_sense_gain','여자 감시 별도 채널 gain')):
                edit=QLineEdit('' if self.original.get(key) is None else str(self.original[key]));self.fields[key]=edit;form.addRow(label,edit)
        for key,options in CHOICES[self.role].items():
            combo=QComboBox()
            for option in options:
                label='미확인' if option is None else ('Turbo OFF' if option is False else 'Turbo ON') if key=='turbo_mode' else '제조사 피로 정격 없음' if option is False else '제조사 피로 정격 있음' if option is True else option
                combo.addItem(label,option)
            combo.setCurrentIndex(max(0,combo.findData(self.original.get(key))));combo.setObjectName('measurement_'+key);form.addRow(key,combo);self.choices[key]=combo
        self.source_url=QLineEdit(self.original.get('source_url',''));form.addRow('사양 출처 HTTPS',self.source_url)
        self.notes=QTextEdit();self.notes.setPlainText(self.original.get('notes',''));self.notes.setMaximumHeight(90);form.addRow('출처·설정 메모',self.notes)
        self.terminals=QTextEdit();self.terminals.setPlainText('\n'.join(f'{key}={value}' for key,value in self.original.get('terminal_roles',{}).items()));self.terminals.setObjectName('measurementTerminalRoles');self.terminals.setMaximumHeight(140)
        self.terminals.setPlaceholderText('excitation_positive=port:EXC_POS\nsignal_positive=port:SIG_POS');form.addRow('역할 = 실제 단자',self.terminals)
        available=[item.terminal for item in connection_endpoints(workspace) if item.component_id==component.id]
        hint=QLabel('등록 단자: '+', '.join(available));hint.setWordWrap(True);hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);form.addRow(hint)
        self.calibration=self.original.get('calibration')
        if self.role=='load_cell':
            self.calibration_points=QTextEdit();self.calibration_points.setMaximumHeight(100);self.calibration_points.setPlaceholderText('실측 ADC count, 하중 N\n1000, 0\n21000, 100')
            self.calibration_points.setObjectName('forceCalibrationPoints');form.addRow('실측 교정점 (count,N)',self.calibration_points)
            self.calibration_status=QLabel('교정 상태: '+self.calibration['status']);form.addRow(self.calibration_status)
            calibrate=QPushButton('실측점으로 N/count 교정');calibrate.clicked.connect(self.calibrate);form.addRow(calibrate)
            reset=QPushButton('교정 미확인으로 되돌리기');reset.clicked.connect(self.clear_calibration);form.addRow(reset)
        scroll.setWidget(body);layout.addWidget(scroll,1)
        self.error=QLabel();self.error.setWordWrap(True);layout.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def calibrate(self):
        try:
            points=[]
            for line in self.calibration_points.toPlainText().splitlines():
                if line.strip():points.append(tuple(float(value.strip()) for value in line.split(',')))
            self.calibration=calibrate_force(points).model_dump();self.calibration_status.setText(f"사용자 실측 교정 · {self.calibration['scale_n_per_count']:.8g} N/count · 인증 미검증");self.error.clear()
        except (ValueError,TypeError) as exc:self.error.setText(str(exc))

    def clear_calibration(self):
        self.calibration=ForceCalibration().model_dump();self.calibration_status.setText('교정 상태: uncalibrated')

    def candidate(self):
        data=deepcopy(self.original)
        for key,edit in self.fields.items():
            text=edit.text().strip()
            data[key]=None if not text else int(text,0) if key=='i2c_address' else int(text) if key in INTEGER_FIELDS else float(text)
        data.update({key:combo.currentData() for key,combo in self.choices.items()})
        data.update(source_url=self.source_url.text().strip(),notes=self.notes.toPlainText(),terminal_roles=_parse_mapping(self.terminals.toPlainText()))
        if self.role=='load_cell':data['calibration']=self.calibration
        if data!=self.original:
            # Edited specifications are user assertions; an old reference URL
            # must not label modified operating values manufacturer-verified.
            data['provenance']='user_entered'
        return {'load_cell':LoadCellMeasurement,'adc':AdcMeasurement,'humidity_temperature':EnvironmentalMeasurement}[self.role].model_validate(data)

    def accept(self):
        try:self.measurement=self.candidate()
        except (ValueError,TypeError) as exc:self.error.setText(str(exc)[:1800]);return
        super().accept()


class ForceAcquisitionDialog(QDialog):
    def __init__(self,parent,raw_design):
        super().__init__(parent);self.setWindowTitle('힘 계측 · 로드셀 / ADC / 온습도');self.resize(1000,800)
        raw=raw_design.model_dump() if hasattr(raw_design,'model_dump') else deepcopy(raw_design)
        self.workspace=ElectricalWorkspace.model_validate(raw.get('electrical') or {}).model_copy(deep=True)
        self.accepted_workspace=None;self.result=None
        chain=self.workspace.force_chain or ForceChainSpec();layout=QVBoxLayout(self)
        notice=QLabel('로드셀 여자·차동 신호·ADC 실제 단자·수집 보드 핀을 회로도에서 연결하세요. 빈 사양은 미확인으로 유지하며 실물이나 펌웨어를 실행하지 않습니다.');notice.setWordWrap(True);layout.addWidget(notice)
        tabs=QTabWidget();setup=QWidget();form=QFormLayout(setup);self.selectors={}
        for field,title,kind,role in (('source_id','로드셀 여자 전원','battery',None),('load_cell_id','로드셀','load','load_cell'),('adc_id','ADC 수집','load','adc'),('controller_id','수집 MCU / MPU','mcu',None)):
            row=QHBoxLayout();combo=QComboBox();combo.setObjectName('force_'+field);combo.addItem('선택 / 미확인','')
            for component in self.workspace.components:
                if component.kind==kind:combo.addItem(component.name+' · '+component.id,component.id)
            combo.setCurrentIndex(max(0,combo.findData(getattr(chain,field))));self.selectors[field]=combo;row.addWidget(combo,1)
            if role:
                edit=QPushButton('계측 사양…');edit.clicked.connect(lambda checked=False,f=field,r=role:self.edit_spec(f,r));row.addWidget(edit)
            form.addRow(title,row)
        self.frequency=QLineEdit('' if chain.target_frequency_hz is None else str(chain.target_frequency_hz));self.frequency.setObjectName('forceTargetFrequency');form.addRow('목표 반복 주파수 (Hz)',self.frequency)
        self.external_clock=QComboBox();self.external_clock.addItem('선택 / 미확인','')
        for component in self.workspace.components:
            if component.kind=='load':self.external_clock.addItem(component.name+' · '+component.id,component.id)
        self.external_clock.setCurrentIndex(max(0,self.external_clock.findData(chain.external_clock_id)));form.addRow('ADC 별도 CLKIN 발진 부품',self.external_clock)
        self.external_clock_terminal=QLineEdit(chain.external_clock_terminal);self.external_clock_terminal.setPlaceholderText('port:CLKOUT');form.addRow('발진 부품의 실제 출력 단자',self.external_clock_terminal)
        self.force=QLineEdit('' if chain.target_peak_force_n is None else str(chain.target_peak_force_n));self.force.setObjectName('forceTargetLoad');form.addRow('목표 최대 하중 (N)',self.force)
        self.samples=QLineEdit(str(chain.samples_per_cycle_required));form.addRow('주기당 샘플 검토 기준 (규격값 아님)',self.samples)
        self.purpose=QComboBox();self.purpose.addItem('계측 기록 검토','acquisition_only');self.purpose.addItem('힘 폐루프 검토 · 실물 검증 필수','force_feedback');self.purpose.setCurrentIndex(max(0,self.purpose.findData(chain.purpose)));form.addRow('목적',self.purpose)
        self.host_terminals=QTextEdit();self.host_terminals.setPlainText('\n'.join(f'{key}={value}' for key,value in chain.controller_terminals.items()));self.host_terminals.setObjectName('forceHostTerminalRoles');self.host_terminals.setMaximumHeight(135);self.host_terminals.setPlaceholderText('clock=pin:PA5\ndata_out=pin:PA6\nground=supply:GND_CN5_7');form.addRow('ADC 역할 = 수집 보드 실제 핀',self.host_terminals)
        self.host_hint=QLabel();self.host_hint.setWordWrap(True);self.host_hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);form.addRow(self.host_hint);self.selectors['controller_id'].currentIndexChanged.connect(self.refresh_host_hint);self.refresh_host_hint()
        self.environment=QListWidget();self.environment.setObjectName('forceEnvironmentComponents')
        for component in self.workspace.components:
            if component.kind=='load':
                item=QListWidgetItem(component.name+' · '+component.id);item.setData(Qt.ItemDataRole.UserRole,component.id);item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(Qt.CheckState.Checked if component.id in chain.environment_ids else Qt.CheckState.Unchecked);self.environment.addItem(item)
        form.addRow('환경 기록 센서 (선택)',self.environment)
        envbutton=QPushButton('선택 센서 온습도 사양…');envbutton.clicked.connect(self.edit_environment);form.addRow(envbutton)
        self.setup_scroll=QScrollArea();self.setup_scroll.setWidgetResizable(True);self.setup_scroll.setObjectName('forceSetupScroll');self.setup_scroll.setWidget(setup)
        tabs.addTab(self.setup_scroll,'계측 경로 / 사양');self.report=QTextEdit();self.report.setReadOnly(True);self.report.setObjectName('forceChainReport');tabs.addTab(self.report,'검토 결과');layout.addWidget(tabs,1);self.tabs=tabs
        row=QHBoxLayout();self.check_button=QPushButton('배선·용량·대역폭 검토');self.check_button.setObjectName('forceAssessButton');self.check_button.clicked.connect(self.check);row.addWidget(self.check_button)
        self.save_button=QPushButton('설계에 계측 설정 저장');self.save_button.setObjectName('forceSaveButton');self.save_button.clicked.connect(self.accept);row.addWidget(self.save_button)
        close=QPushButton('취소');close.clicked.connect(self.reject);row.addWidget(close);layout.addLayout(row)

    def refresh_host_hint(self):
        identifier=self.selectors['controller_id'].currentData();endpoints=[item.terminal for item in connection_endpoints(self.workspace) if item.component_id==identifier]
        self.host_hint.setText('선택 보드 실제 단자: '+', '.join(endpoints))

    def edit_spec(self,field,role):
        identifier=self.selectors[field].currentData();self._edit(identifier,role)

    def edit_environment(self):
        item=self.environment.currentItem()
        if item:self._edit(item.data(Qt.ItemDataRole.UserRole),'humidity_temperature')

    def _edit(self,identifier,role):
        component=next((item for item in self.workspace.components if item.id==identifier),None)
        if component is None:self.report.setPlainText('먼저 등록 부품을 선택하세요.');self.tabs.setCurrentIndex(1);return
        dialog=MeasurementComponentDialog(self,component,self.workspace,role)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            component.measurement=dialog.measurement
            self.workspace=ElectricalWorkspace.model_validate(self.workspace.model_dump())

    def candidate(self):
        def optional(edit):return float(edit.text().strip()) if edit.text().strip() else None
        spec=ForceChainSpec(**{key:combo.currentData() for key,combo in self.selectors.items()},
            target_frequency_hz=optional(self.frequency),target_peak_force_n=optional(self.force),
            samples_per_cycle_required=float(self.samples.text()),purpose=self.purpose.currentData(),
            external_clock_id=self.external_clock.currentData(),external_clock_terminal=self.external_clock_terminal.text().strip(),
            controller_terminals=_parse_mapping(self.host_terminals.toPlainText()),
            environment_ids=[self.environment.item(index).data(Qt.ItemDataRole.UserRole) for index in range(self.environment.count()) if self.environment.item(index).checkState()==Qt.CheckState.Checked])
        workspace=self.workspace.model_copy(deep=True);workspace.force_chain=spec
        return ElectricalWorkspace.model_validate(workspace.model_dump())

    def check(self):
        try:self.result=assess_force_chain(self.candidate());self.report.setPlainText(self.result.report_text())
        except (ValueError,TypeError) as exc:self.report.setPlainText('설정 입력 확인: '+str(exc)[:2200]);self.result=None
        self.tabs.setCurrentIndex(1)

    def accept(self):
        try:self.accepted_workspace=self.candidate();self.result=assess_force_chain(self.accepted_workspace)
        except (ValueError,TypeError) as exc:self.report.setPlainText('설정 입력 확인: '+str(exc)[:2200]);self.tabs.setCurrentIndex(1);return
        super().accept()
