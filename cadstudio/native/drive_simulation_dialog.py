"""Local motor/controller/encoder study with bounded background computation.

The selected CAD components and user-entered SI motor constants define a
reduced model. This dialog never changes CAD parts, saved wiring or firmware.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import threading

from PySide6.QtCore import QObject, QPointF, QRect, QRectF, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QScrollArea, QSpinBox, QSplitter,
    QVBoxLayout, QWidget)

from ..models import Design
from ..drive_simulation import DriveSimulationSpec, simulate_drive, synthetic_drive_demo
from .widgets import button, label, number


class _SimulationSignals(QObject):
    finished = Signal(int, object)
    failed = Signal(int, str)


class _SimulationWorker(QRunnable):
    def __init__(self, generation, design, spec, cancel_event):
        super().__init__()
        self.generation, self.design, self.spec = generation, design, spec
        self.cancel_event = cancel_event
        self.signals = _SimulationSignals()

    @Slot()
    def run(self):
        try:
            result = simulate_drive(self.design, self.spec, cancel_event=self.cancel_event)
            self.signals.finished.emit(self.generation, result)
        except Exception as exc:
            self.signals.failed.emit(self.generation, str(exc)[:1800])


class DriveTracePlot(QLabel):
    """Bounded image traces painted offscreen, shown by Qt's standard QLabel.

    No Python QWidget paint override holds a painter on Qt's backing store.
    The fixed-size image also bounds allocations during window resizing.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('driveSimulationTracePlot')
        self.setMinimumSize(340, 230)
        self.setScaledContents(True)
        self.traces = []
        self.unit = 'rpm'
        self.duration = 0.0
        self.empty_text = ''
        self.paint_error = ''
        self.render_width = 1024
        self.render_height = 580

    def set_traces(self, points, metric, target_rpm, english=False):
        word=lambda ko,en:en if english else ko
        definitions = {
            'speed': [('speed_rpm',word('모터 rpm','Motor rpm'),'#63D5BD'),
                      ('encoder_speed_rpm',word('엔코더 rpm','Encoder rpm'),'#E6B972')],
            'current': [('current_a',word('전류 A','Current A'),'#63D5BD')],
            'voltage': [('bus_voltage_v',word('버스 전압 V','Bus voltage V'),'#63D5BD')],
            'error': [('error_rpm',word('속도 오차 rpm','Speed error rpm'),'#E6B972')],
            'duty': [('duty_cycle',word('듀티 비율','Duty ratio'),'#63D5BD')],
        }
        self.unit = {'speed':'rpm', 'current':'A', 'voltage':'V', 'error':'rpm', 'duty':'ratio'}[metric]
        rows = list(points)
        stride = max(1, math.ceil(len(rows) / 1600))
        selected = rows[::stride]
        if rows and selected[-1] is not rows[-1]:
            selected.append(rows[-1])
        self.traces = []
        for field, title, color in definitions[metric]:
            samples = [(float(point.time_s), float(getattr(point, field))) for point in selected]
            if any(not math.isfinite(t) or not math.isfinite(value) for t, value in samples):
                raise ValueError('Non-finite simulation trace.')
            self.traces.append((title, color, samples))
        self.duration = float(rows[-1].time_s) if rows else 0
        if metric == 'speed' and rows:
            self.traces.append((word('목표 rpm','Target rpm'),'#8BA4BC',[(0,target_rpm),(self.duration,target_rpm)]))
        self.render_plot()

    def render_plot(self):
        image = QImage(self.render_width,self.render_height,QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor('#12212C'))
        painter = QPainter(image)
        self.paint_error = ''
        try:
            self._paint(painter)
        except Exception as exc:
            # Keep the temporary image's painter bounded even if a numeric
            # label fails. No active painter escapes into Qt widget events.
            self.paint_error = str(exc)[:300]
            painter.fillRect(image.rect(), QColor('#12212C'))
            painter.setPen(QColor('#E6B972'))
            painter.drawText(16, 28, 'Plot could not be drawn.')
        finally:
            painter.end()
        self.setPixmap(QPixmap.fromImage(image))

    def _paint(self, painter):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect=QRect(0,0,self.render_width,self.render_height)
        painter.fillRect(rect, QColor('#12212C'))
        painter.setPen(QColor('#A6BECE'))
        area = QRectF(68,48,self.render_width-90,self.render_height-85)
        values = [value for _, _, rows in self.traces for _, value in rows]
        if not values:
            painter.drawText(rect.adjusted(22,22,-22,-22),Qt.AlignmentFlag.AlignCenter,
                             self.empty_text)
            return
        low, high = min(values), max(values)
        span = max(high - low, max(abs(low), abs(high), 1) * .04)
        low -= span * .05
        high += span * .05
        span = high - low
        for index in range(5):
            y = area.top() + area.height() * index / 4
            painter.setPen(QPen(QColor('#2C4252'), 1))
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            painter.setPen(QColor('#A6BECE'))
            painter.drawText(QRectF(2, y - 10, 59, 20), Qt.AlignmentFlag.AlignRight,
                             f'{high - span * index / 4:.4g}')
        painter.drawText(QRectF(10, 20, 54, 20), Qt.AlignmentFlag.AlignLeft, self.unit)
        painter.drawText(QRectF(area.left(), area.bottom() + 10, 70, 20), Qt.AlignmentFlag.AlignLeft, '0 s')
        painter.drawText(QRectF(area.right() - 88, area.bottom() + 10, 88, 20),
                         Qt.AlignmentFlag.AlignRight, f'{self.duration:.4g} s')
        legend_x = area.left()
        for title, color, rows in self.traces:
            painter.setPen(QPen(QColor(color), 2))
            painter.drawLine(QPointF(legend_x, 25), QPointF(legend_x + 16, 25))
            painter.setPen(QColor(color))
            painter.drawText(QRectF(legend_x + 22, 14, 130, 23), Qt.AlignmentFlag.AlignLeft, title)
            legend_x += 150
            path = QPainterPath()
            for index, (time_s, value) in enumerate(rows):
                point = QPointF(area.left() + area.width() * time_s / max(self.duration, 1e-12),
                                area.bottom() - area.height() * (value - low) / span)
                if index:
                    path.lineTo(point)
                else:
                    path.moveTo(point)
            painter.setPen(QPen(QColor(color), 1.8))
            painter.drawPath(path)


class DriveSimulationDialog(QDialog):
    """An explicit local study; imported real product names never supply guesses."""
    def __init__(self, parent, design):
        super().__init__(parent)
        language = getattr(QApplication.instance(), 'cad_language', None)
        self.english = getattr(language, 'language', 'ko') == 'en'
        self.design = Design.model_validate(design).model_copy(deep=True)
        self.virtual_demo = False
        self.result = None
        self.checked_spec = None
        self.checked_design = None
        self.running = False
        self._closing = False
        self._generation = 0
        self._input_revision = 0
        self._run_revision = None
        self._result_revision = None
        self._cancel = threading.Event()
        self.worker = None
        self.setWindowTitle(self.word('구동 시뮬레이션 · 모터 / 엔코더 / 제어기',
                                     'Drive simulation · motor / encoder / controller'))
        self.setObjectName('driveSimulationDialog')
        self.resize(1120, 850)
        root = QVBoxLayout(self)
        root.addWidget(label(self.word(
            '실제 등록 부품·배선과 입력한 모터 상수로 속도 제어를 계산합니다. 조건은 이 창에서만 사용되며 CAD는 바뀌지 않습니다.',
            'Calculate speed control using registered parts, wiring and entered motor constants. These local settings do not modify CAD.')))
        self.mode_status = label(self.word('실제 설계 선택 · 측정값/데이터시트 상수를 입력하세요.',
                                           'Current CAD study · enter measured or datasheet constants.'), True)
        root.addWidget(self.mode_status)
        split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(split, 1)
        visual = QWidget()
        visual_layout = QVBoxLayout(visual)
        visual_layout.setContentsMargins(0, 0, 0, 0)
        self.metric_combo = QComboBox()
        for value, ko, en in [('speed','회전 속도 / 엔코더 / 목표','Speed / encoder / target'),
                              ('current','모터 전류','Motor current'), ('voltage','전원 전압 강하','Supply voltage drop'),
                              ('error','속도 오차','Speed error'), ('duty','드라이버 듀티','Driver duty')]:
            self.metric_combo.addItem(self.word(ko,en),value)
        visual_layout.addWidget(self.metric_combo)
        self.plot = DriveTracePlot()
        self.plot.empty_text = self.word('조건을 입력하고 실행하세요.', 'Enter conditions and run the simulation.')
        self.plot.render_plot()
        visual_layout.addWidget(self.plot, 1)
        self.summary = label(self.word('아직 계산 결과가 없습니다.', 'No simulation result yet.'))
        self.summary.setObjectName('driveSimulationSummary')
        visual_layout.addWidget(self.summary)
        self.messages = label('', True)
        self.messages.setTextFormat(Qt.TextFormat.PlainText)
        self.messages.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        visual_layout.addWidget(self.messages)
        visual_layout.addWidget(label(self.word(
            '속도 PI 제어 + 양자화 엔코더 + 회전 모터 축약 모델입니다. BLDC 평균 모델은 FOC·상별 PWM·STM32 펌웨어 실행·실기 검증을 대신하지 않습니다.',
            'Speed PI control, a quantized encoder and a reduced rotational motor model. Averaged BLDC does not execute FOC, phase PWM or STM32 firmware, and is not hardware validation.'), True))
        split.addWidget(visual)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(350)
        scroll.setMaximumWidth(470)
        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        self.controls_widget = controls
        self.selectors = {}
        self.inputs = {}
        selection = self._group(controls_layout, '등록된 CAD 전장 부품', 'Registered CAD electrical parts')
        for key, ko, en in [('source_id','배터리 / 전원','Battery / source'),
                            ('motor_id','회전 모터','Rotational motor'),
                            ('controller_id','MCU / ESC / 드라이버','MCU / ESC / driver'),
                            ('driver_id','별도 ESC / 드라이버 (선택)','Separate ESC / driver (optional)'),
                            ('encoder_id','엔코더 / 위치 센서','Encoder / position sensor')]:
            combo = QComboBox()
            combo.setObjectName('driveSimulation_' + key)
            selection.addRow(self.word(ko,en), combo)
            self.selectors[key] = combo
        self.motor_type = self._choice(selection, '모터 모델', 'Motor model',
            [('dc','브러시 DC','Brushed DC'),('bldc_average','BLDC 평균 모델','Averaged BLDC')])
        self.controller_type = self._choice(selection, '드라이버 종류', 'Driver type',
            [('dc_driver','DC 양방향 드라이버','Bidirectional DC driver'),
             ('three_phase_esc','3상 ESC','Three-phase ESC')])
        self.encoder_interface = self._choice(selection, '엔코더 인터페이스', 'Encoder interface',
            [('quadrature','A/B 증분형','A/B quadrature'),('sampled_angle','샘플링 각도 센서','Sampled angle sensor')])
        supply = self._group(controls_layout,'전원 · 이번 계산의 설정','Supply · this local calculation')
        self.supply_voltage = number(0,0,1000,' V',6)
        self.supply_resistance = number(0,0,10000,' Ω',6)
        supply.addRow(self.word('개방 전압','Open-circuit voltage'),self.supply_voltage)
        supply.addRow(self.word('전원 내부 저항','Source internal resistance'),self.supply_resistance)
        motor = self._group(controls_layout,'실제 모터 / 부하 상수','Measured motor / load constants')
        rows = [
            ('resistance_ohm','권선 저항 R','Winding resistance R',0,0,10000,' Ω',7,1),
            ('inductance_h','권선 인덕턴스 L','Winding inductance L',0,0,1000000,' mH',7,.001),
            ('torque_constant_nm_per_a','토크 상수 kt','Torque constant kt',0,0,10000,' N·m/A',8,1),
            ('back_emf_v_per_rad_s','역기전력 상수 ke','Back-EMF constant ke',0,0,10000,' V/(rad/s)',8,1),
            ('inertia_kg_m2','전체 회전 관성 J','Total rotor/load inertia J',0,0,10000,' kg·m²',10,1),
            ('viscous_friction_nm_per_rad_s','점성 마찰 b','Viscous friction b',0,0,10000,' N·m/(rad/s)',9,1),
            ('load_torque_nm','부하 토크','Load torque',0,0,100000,' N·m',6,1),
        ]
        self.scales = {}
        for key,ko,en,value,lo,hi,suffix,decimals,scale in rows:
            field = number(value,lo,hi,suffix,decimals)
            field.setObjectName('driveSimulation_' + key)
            motor.addRow(self.word(ko,en),field)
            self.inputs[key] = field
            self.scales[key] = scale
        controller = self._group(controls_layout,'속도 제어 / 보호 설정','Speed control / protection settings')
        for key,ko,en,value,lo,hi,suffix,decimals,scale in [
            ('target_rpm','목표 회전 속도','Target speed',0,0,200000,' rpm',3,1),
            ('duration_s','계산 시간','Duration',5,.001,120,' s',4,1),
            ('current_limit_a','전류 제한','Current limit',0,0,10000,' A',5,1),
            ('overspeed_rpm','과속 차단 값','Overspeed cutoff',0,0,1000000,' rpm',3,1),
            ('voltage_limit_fraction','유효 모터 전압 / 버스 전압','Effective motor voltage / bus voltage',0,0,1,'',6,1),
            ('proportional_gain_v_per_rad_s','PI 비례 게인 Kp','PI proportional gain Kp',0,0,10000,' V/(rad/s)',8,1),
            ('integral_gain_v_per_rad','PI 적분 게인 Ki','PI integral gain Ki',0,0,10000,' V/rad',8,1),
            ('dt_s','제어 샘플 간격','Control sample interval',5,.1,20,' ms',3,.001),
        ]:
            field=number(value,lo,hi,suffix,decimals)
            field.setObjectName('driveSimulation_' + key)
            controller.addRow(self.word(ko,en),field)
            self.inputs[key]=field
            self.scales[key]=scale
        self.encoder_ticks=QSpinBox()
        self.encoder_ticks.setRange(0,1000000)
        self.encoder_ticks.setObjectName('driveSimulation_encoderTicks')
        controller.addRow(self.word('엔코더 유효 카운트 / 회전','Effective encoder counts / revolution'),self.encoder_ticks)
        self.encoder_polarity=self._choice(controller,'엔코더 방향','Encoder polarity',
            [(1,'정방향 +1','Normal +1'),(-1,'역방향 −1','Reversed −1')])
        self.enabled=QCheckBox(self.word('드라이버 활성화','Driver enabled'))
        self.enabled.setChecked(True)
        controller.addRow(self.enabled)
        self.encoder_connected=QCheckBox(self.word('엔코더 정상 연결 (해제: 단선 시험)','Encoder connected (clear to inject disconnect)'))
        self.encoder_connected.setChecked(True)
        controller.addRow(self.encoder_connected)
        controls_layout.addWidget(label(self.word(
            '상수는 자동 추정하지 않습니다. 엔코더 카운트는 PPR이 아니라 실제 카운터의 유효 counts/rev를 입력하세요.',
            'Constants are not guessed. Enter effective counter counts/rev, not unconverted encoder PPR.'), True))
        controls_layout.addStretch()
        scroll.setWidget(controls)
        split.addWidget(scroll)
        split.setSizes([680,400])
        self.status=label('')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setObjectName('driveSimulationStatus')
        root.addWidget(self.status)
        actions=QHBoxLayout()
        self.demo_button=button(self.word('가상 예제 불러오기','Load virtual demo'),self.load_virtual_demo)
        actions.addWidget(self.demo_button)
        self.run_button=button(self.word('시뮬레이션 실행','Run simulation'),self.start_simulation,True)
        actions.addWidget(self.run_button)
        self.cancel_button=button(self.word('계산 취소','Cancel calculation'),self.cancel_simulation)
        self.cancel_button.setEnabled(False)
        actions.addWidget(self.cancel_button)
        self.csv_button=button(self.word('결과 CSV','Result CSV'),self.export_csv)
        self.csv_button.setEnabled(False)
        actions.addWidget(self.csv_button)
        self.report_button=button(self.word('설정 / 결과 JSON','Settings / result JSON'),self.export_report)
        self.report_button.setEnabled(False)
        actions.addWidget(self.report_button)
        actions.addStretch()
        actions.addWidget(button(self.word('닫기','Close'),self.reject))
        root.addLayout(actions)
        self.metric_combo.currentIndexChanged.connect(self.update_plot)
        self.selectors['source_id'].currentIndexChanged.connect(self._source_selected)
        for combo in [*self.selectors.values(),self.motor_type,self.controller_type,
                      self.encoder_interface,self.encoder_polarity]:
            combo.currentIndexChanged.connect(self._inputs_changed)
        for field in [*self.inputs.values(),self.supply_voltage,self.supply_resistance,self.encoder_ticks]:
            field.valueChanged.connect(self._inputs_changed)
        self.enabled.toggled.connect(self._inputs_changed)
        self.encoder_connected.toggled.connect(self._inputs_changed)
        self._populate_components()

    def word(self,ko,en):
        return en if self.english else ko

    def _group(self,layout,ko,en):
        group=QGroupBox(self.word(ko,en))
        form=QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        layout.addWidget(group)
        return form

    def _choice(self,form,ko,en,choices):
        combo=QComboBox()
        for value,title_ko,title_en in choices:
            combo.addItem(self.word(title_ko,title_en),value)
        form.addRow(self.word(ko,en),combo)
        return combo

    def _populate_components(self):
        components=self.design.electrical.components if self.design.electrical else []
        part_ids={part.id for part in self.design.parts}
        for key,combo in self.selectors.items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(self.word('제어기에 드라이버 포함','Controller includes the driver') if key=='driver_id' else
                          self.word('등록 부품 선택…','Select a registered part…'),'')
            for component in components:
                kinds={'source_id':{'battery'},'motor_id':{'motor'},
                       'controller_id':{'mcu','load'},'driver_id':{'mcu','load'},
                       'encoder_id':{'mcu','load','motor'}}[key]
                if (component.kind not in kinds or not component.part_registration
                        or component.part_id not in part_ids):
                    continue
                name=f'{component.name} · {component.catalog_id or component.id}'
                combo.addItem(name,component.id)
            combo.blockSignals(False)
        self._source_selected()

    def _source_selected(self,*args):
        identifier=self.selectors['source_id'].currentData()
        components=self.design.electrical.components if self.design.electrical else []
        source=next((component for component in components if component.id==identifier),None)
        self.supply_voltage.setValue(source.voltage_v if source else 0)
        self.supply_resistance.setValue(source.internal_resistance_ohm if source else 0)

    def _inputs_changed(self,*args):
        self._input_revision+=1
        if self.result is not None:
            self.csv_button.setEnabled(False)
            self.report_button.setEnabled(False)
            self.status.setText(self.word('조건이 바뀌었습니다. 표시된 궤적은 이전 조건의 결과입니다. 다시 실행하세요.',
                                          'Inputs changed. The displayed trace belongs to the previous conditions. Run again.'))

    def load_virtual_demo(self):
        if self.running:
            return
        design,spec=synthetic_drive_demo()
        self.design=Design.model_validate(design).model_copy(deep=True)
        self.virtual_demo=True
        self.result=None
        self.checked_spec=None
        self.checked_design=None
        self._result_revision=None
        self.csv_button.setEnabled(False)
        self.report_button.setEnabled(False)
        self._populate_components()
        self.set_spec(spec)
        self.mode_status.setText(self.word(
            '가상 예제 · 실제 제품 정격/배선/검증값이 아닙니다. 원래 CAD는 변경되지 않습니다.',
            'Virtual demo · these are synthetic constants and wiring, not real product validation. Original CAD is unchanged.'))
        self.summary.setText(self.word('가상 예제 조건을 불러왔습니다. 실행을 누르세요.',
                                       'Virtual demo loaded. Press Run.'))
        self.messages.setText('')
        self.plot.traces=[]
        self.plot.render_plot()

    def set_spec(self,spec):
        spec=DriveSimulationSpec.model_validate(spec)
        for key,combo in self.selectors.items():
            index=combo.findData(getattr(spec,key))
            if index>=0:
                combo.setCurrentIndex(index)
        for key,field in self.inputs.items():
            field.setValue(getattr(spec,key)/self.scales[key])
        for key in ('motor_type','controller_type','encoder_interface','encoder_polarity'):
            combo=getattr(self,key)
            index=combo.findData(getattr(spec,key))
            if index>=0:
                combo.setCurrentIndex(index)
        self.encoder_ticks.setValue(spec.encoder_ticks_per_rev)
        self.enabled.setChecked(spec.enabled)
        self.encoder_connected.setChecked(spec.encoder_connected)

    def settings(self):
        values={key:field.value()*self.scales[key] for key,field in self.inputs.items()}
        values.update({key:combo.currentData() or '' for key,combo in self.selectors.items()})
        values.update(motor_type=self.motor_type.currentData(),controller_type=self.controller_type.currentData(),
            encoder_interface=self.encoder_interface.currentData(),encoder_ticks_per_rev=self.encoder_ticks.value(),
            encoder_polarity=self.encoder_polarity.currentData(),enabled=self.enabled.isChecked(),
            encoder_connected=self.encoder_connected.isChecked())
        return DriveSimulationSpec.model_validate(values)

    def simulation_design(self):
        raw=self.design.model_dump()
        source_id=self.selectors['source_id'].currentData()
        if raw.get('electrical'):
            for component in raw['electrical']['components']:
                if component['id']==source_id:
                    component['voltage_v']=self.supply_voltage.value()
                    component['internal_resistance_ohm']=self.supply_resistance.value()
        return Design.model_validate(raw)

    def _set_busy(self,busy):
        self.running=busy
        self.controls_widget.setEnabled(not busy)
        self.run_button.setEnabled(not busy)
        self.demo_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        valid=self.result is not None and self._result_revision==self._input_revision
        self.csv_button.setEnabled(not busy and valid and bool(self.result.points))
        self.report_button.setEnabled(not busy and valid)

    def start_simulation(self):
        if self.running or self._closing:
            return
        try:
            spec=self.settings()
            design=self.simulation_design()
        except Exception as exc:
            self.status.setText(self.word('조건 확인: ','Check inputs: ')+str(exc)[:1400])
            return
        self._generation+=1
        self._cancel=threading.Event()
        self.checked_spec=spec
        self.checked_design=design
        self._run_revision=self._input_revision
        self._set_busy(True)
        self.status.setText(self.word('계산 중… 창은 계속 사용할 수 있습니다.','Calculating… the UI remains responsive.'))
        worker=_SimulationWorker(self._generation,design,spec,self._cancel)
        self.worker=worker
        worker.signals.finished.connect(self._finished,Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(self._failed,Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(worker)

    def cancel_simulation(self):
        if self.running:
            self._cancel.set()
            self.cancel_button.setEnabled(False)
            self.status.setText(self.word('취소 중…','Cancelling…'))

    @Slot(int,object)
    def _finished(self,generation,result):
        if self._closing or generation!=self._generation:
            return
        self.result=result
        self._result_revision=self._run_revision
        self._set_busy(False)
        self.present_result()

    @Slot(int,str)
    def _failed(self,generation,message):
        if self._closing or generation!=self._generation:
            return
        self._set_busy(False)
        self.status.setText(self.word('계산을 완료하지 못했습니다: ','Calculation could not complete: ')+message)

    def present_result(self):
        result=self.result
        if result is None:
            return
        summary=result.summary
        value=lambda key: summary.get(key) if isinstance(summary,dict) else getattr(summary,key,None)
        lines=[]
        for key,ko,en,unit in [('final_speed_rpm','최종 속도','Final speed','rpm'),
                             ('final_error_rpm','최종 오차','Final error','rpm'),
                             ('peak_current_a','최대 전류','Peak current','A'),
                             ('min_bus_voltage_v','최저 전압','Minimum bus voltage','V')]:
            number_value=value(key)
            if number_value is not None:
                lines.append(f'{self.word(ko,en)} {float(number_value):.5g} {unit}')
        self.summary.setText(' · '.join(lines) or self.word('유효 궤적이 없습니다.','No valid trajectory.'))
        messages=[*result.faults,*result.warnings]
        self.messages.setText('\n'.join(str(message) for message in messages)[:3000])
        prefix=self.word('가상 예제','Virtual demo') if self.virtual_demo else self.word('입력 조건의 축약 모델','Reduced model under entered conditions')
        states={'blocked':('결선 / 조건 확인 필요','Wiring / inputs blocked'),
                'disabled':('구동 비활성','Driver disabled'),'cancelled':('계산 취소','Cancelled'),
                'converged':('입력 조건에서 목표 속도 수렴','Target speed converged under inputs'),
                'not_converged':('입력 조건에서 목표 속도 미수렴','Target speed not converged under inputs'),
                'fault':('보호 조건 / 오류로 정지','Stopped by protection / fault')}
        state=self.word(*states[result.status])
        self.status.setText(f'{prefix} · {state} · '+self.word(
            '실제 하드웨어·펌웨어 검증 결과가 아닙니다.','This is not a hardware or firmware validation result.'))
        self.update_plot()

    def update_plot(self,*args):
        if self.result is not None and self.checked_spec is not None:
            self.plot.set_traces(self.result.points,self.metric_combo.currentData(),self.checked_spec.target_rpm,self.english)

    def write_csv(self,path):
        if (self.result is None or self.checked_spec is None or not self.result.points
                or self.running or self._result_revision!=self._input_revision):
            raise ValueError(self.word('먼저 궤적을 계산하세요.','Calculate a trajectory first.'))
        path=Path(path)
        fields=('time_s','speed_rpm','encoder_speed_rpm','current_a','bus_voltage_v',
                'angle_rad','error_rpm','duty_cycle')
        with path.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream)
            writer.writerow([*fields,'target_rpm','virtual_demo','model_status'])
            for point in self.result.points:
                writer.writerow([*(getattr(point,key) for key in fields),self.checked_spec.target_rpm,
                                 int(self.virtual_demo),self.result.status])
        return path

    def export_csv(self,path=None):
        if isinstance(path,bool):
            path=None
        if path is None:
            path,_=QFileDialog.getSaveFileName(self,self.word('구동 궤적 CSV','Drive trajectory CSV'),
                                             'drive-simulation.csv','CSV (*.csv)')
        if not path:
            return None
        try:
            result=self.write_csv(path)
            self.status.setText(self.word('CSV 저장: ','CSV saved: ')+str(result))
            return result
        except Exception as exc:
            self.status.setText(str(exc)[:1400])
            return None

    def export_report(self,path=None):
        if (self.result is None or self.checked_spec is None or self.checked_design is None
                or self.running or self._result_revision!=self._input_revision):
            return None
        if isinstance(path,bool):
            path=None
        if path is None:
            path,_=QFileDialog.getSaveFileName(self,self.word('구동 조건 / 결과 JSON','Drive conditions / result JSON'),
                                             'drive-simulation.json','JSON (*.json)')
        if not path:
            return None
        identifiers={getattr(self.checked_spec,key) for key in self.selectors}
        source_components=self.checked_design.electrical.components if self.checked_design.electrical else []
        report=dict(schema_version=1,virtual_demo=self.virtual_demo,
            model_scope='Reduced rotational motor, quantized encoder and speed PI controller; no firmware/FOC or hardware validation.',
            conditions=self.checked_spec.model_dump(),
            components=[component.model_dump() for component in source_components if component.id in identifiers],
            result=self.result.model_dump())
        try:
            destination=Path(path)
            destination.write_text(json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
            self.status.setText(self.word('JSON 저장: ','JSON saved: ')+str(destination))
            return destination
        except Exception as exc:
            self.status.setText(str(exc)[:1400])
            return None

    def done(self,result):
        self._closing=True
        self._cancel.set()
        super().done(result)

    def closeEvent(self,event):
        self._closing=True
        self._cancel.set()
        super().closeEvent(event)
