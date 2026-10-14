"""Explicit readonly source/contract → virtual mean RPM dialog. No CAD render."""
from PySide6.QtCore import QTimer,Qt,Slot
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QComboBox,QLineEdit,QFileDialog,QLabel,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView
from .program_drive_controller import ProgramDriveController,unknown_result
from .program_drive_runner import ProgramDriveRunner
from .widgets import button


class ProgramDriveDialog(QDialog):
    def __init__(self,document_provider,parent=None,language='ko'):
        super().__init__(parent);self.english=language=='en';self.controller=ProgramDriveController(document_provider,language=language)
        self._closing=False;self._worker_busy=False;self._worker=None
        self.runner=ProgramDriveRunner();self.runner.finished.connect(self.worker_finished);self.runner.failed.connect(self.worker_failed)
        self.deadline_timer=QTimer(self);self.deadline_timer.setSingleShot(True);self.deadline_timer.setInterval(30000);self.deadline_timer.timeout.connect(self.expire)
        self.setObjectName('programDriveReviewDialog');self.setWindowTitle(self.word('코드 → 모터 RPM 검토','Code → motor RPM review'));self.resize(1040,780)
        self.setMinimumSize(820,640);root=QVBoxLayout(self)
        root.addWidget(self.text(self.word('읽기 전용 · 선택한 저장 코드와 exact 입력 계약을 검토하고 실행 버튼을 눌렀을 때만 계산합니다.',
            'Read only · review saved code and exact input contracts; calculate only by pressing Run.')))
        root.addWidget(self.text(self.word('최소 지원: RPi GPIO 가상 명령 → Pololu2130 DRV8833 A채널·nSLEEP HIGH·slow-decay → 선언된 DC 평균 모델. BLDC/ESC/FOC·전체 펌웨어/OS·스위칭·발열은 포함하지 않습니다.',
            'Minimum: virtual RPi GPIO → Pololu2130 DRV8833 A-channel, nSLEEP HIGH, slow decay → declared averaged DC model. BLDC/ESC/FOC, complete firmware/OS, switching and thermal behavior are excluded.')))
        self.actual=self.text(self.word('실제 RPM: 미확인 · 실제 전류: 미확인 · 실제 clock: 미확인','Actual RPM: Unknown · actual current: Unknown · physical clock: Unknown'))
        self.actual.setObjectName('programDriveActualUnknown');root.addWidget(self.actual)
        form=QFormLayout();root.addLayout(form);self.board=QComboBox();self.board.setObjectName('programDriveBoard');self.program=QComboBox();self.program.setObjectName('programDriveSavedProgram')
        form.addRow(self.word('등록된 보드','Registered board'),self.board);form.addRow(self.word('현재 설계에 저장된 코드','Code saved in current design'),self.program)
        self.paths={};self.browse_buttons={}
        for kind,ko,en in [('contract','구동 연결 계약 JSON','Drive binding contract JSON'),('parameters','모터 입력·출처 JSON','Motor inputs / provenance JSON')]:
            row=QHBoxLayout();path=QLineEdit();path.setReadOnly(True);path.setObjectName('programDrive_'+kind+'_path');self.paths[kind]=path;row.addWidget(path,1)
            browse=button(self.word('파일 선택…','Choose file…'),lambda k=kind:self.choose_file(k));browse.setObjectName('programDrive_'+kind+'_browse');self.browse_buttons[kind]=browse;row.addWidget(browse);form.addRow(self.word(ko,en),row)
        self.inputs=self.text('');self.inputs.setObjectName('programDriveInputSummary');root.addWidget(self.inputs)
        root.addWidget(button(self.word('모터 방정식 · 상태 행렬','Motor equations / state matrices'),self.show_motor_matrix))
        controls=QHBoxLayout();self.run_button=button(self.word('선언 시나리오 실행','Run declared scenario'),self.start,True);self.run_button.setObjectName('programDriveRun')
        self.cancel_button=button(self.word('계산 취소','Cancel calculation'),self.cancel);self.cancel_button.setObjectName('programDriveCancel');controls.addWidget(self.run_button);controls.addWidget(self.cancel_button);controls.addStretch();root.addLayout(controls)
        self.status=self.text('');self.status.setObjectName('programDriveStatus');self.status.setMaximumHeight(170);root.addWidget(self.status)
        root.addWidget(self.text(self.word('아래 숫자는 선언된 가상 시나리오입니다. 실제 RPM/전류나 엔코더 측정값이 아니며, 코드로 엔코더 피드백을 재실행하지 않습니다.',
            'Values below are a declared virtual scenario, not measured RPM/current/encoder data. Encoder feedback is not rerun through the code.')))
        self.table=QTableWidget(0,5);self.table.setObjectName('programDriveScenarioTable');self.table.setHorizontalHeaderLabels([self.word('가상 시각(s)','Virtual time(s)'),self.word('선언 RPM','Scenario RPM'),self.word('선언 전류(A)','Scenario current(A)'),self.word('평균 전압(V)','Mean voltage(V)'),self.word('가상 decoded count','Virtual decoded count')])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);root.addWidget(self.table,1)
        root.addWidget(self.text(self.word('기존 PI/엔코더 수동 모델과 다른 외부 평균 전압 입력 경로입니다. 참조 등록·analysis-disabled를 실제 동작으로 승격하지 않습니다. 회로/코드/부품/이력/BOM을 저장하거나 수정하지 않습니다.',
            'Separate external mean-voltage input path from the existing manual PI/encoder model. Reference/analysis-disabled registration is not physical readiness. Circuit, code, parts, history and BOM are not saved or modified.')))
        end=QHBoxLayout();end.addStretch();end.addWidget(button(self.word('닫기','Close'),self.reject));root.addLayout(end)
        self.board.addItem(self.word('보드 선택','Choose board'),None)
        for item in self.controller.boards():self.board.addItem(item['name']+' ['+item['id']+']'+(' · '+self.word('계산 제외','analysis disabled') if not item.get('analysis_enabled',True) else ''),item['id'])
        self.program.addItem(self.word('저장 코드 선택','Choose saved code'),None)
        self.board.currentIndexChanged.connect(self.board_changed);self.program.currentIndexChanged.connect(self.program_changed)
        self.render_state()
    def word(self,ko,en):return en if self.english else ko
    def show_motor_matrix(self):
        from .motor_matrix_dialog import MotorMatrixDialog
        try:dialog=MotorMatrixDialog(self.controller.parameters,self,language='en' if self.english else 'ko')
        except ValueError as exc:self.status.setText(str(exc));return
        try:dialog.exec()
        finally:dialog.deleteLater()
    def text(self,value):
        label=QLabel(value);label.setWordWrap(True);label.setTextFormat(Qt.TextFormat.PlainText);label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);return label
    def board_changed(self,*args):
        self.controller.set_board(self.board.currentData());self.program.blockSignals(True);self.program.clear();self.program.addItem(self.word('저장 코드 선택','Choose saved code'),None)
        for saved in self.controller.programs():self.program.addItem(saved['name']+' · '+saved['sha256'][:12],(saved['sha256'],saved['name'],saved.get('board_component_id','')))
        self.program.blockSignals(False);self.render_state()
    def program_changed(self,*args):self.controller.set_program(self.program.currentData());self.render_state()
    def choose_file(self,kind):
        path,_=QFileDialog.getOpenFileName(self,self.word('검토할 입력 JSON 선택','Choose input JSON to review'),'','JSON (*.json)')
        if path:self.load_file(kind,path)
    def load_file(self,kind,path):
        self.paths[kind].setText(str(path));valid=self.controller.load_file(kind,path);self.render_state();return valid
    def start(self):
        if self._closing or self._worker_busy:return
        ticket=self.controller.begin();self.render_state()
        if ticket is None:return
        self._worker_busy=True
        if not self.runner.start(ticket):self._worker_busy=False;self.controller.cancel();self.render_state();return
        self.deadline_timer.start();self.render_state()
    @Slot(object,object)
    def worker_finished(self,ticket,result):
        self._worker_busy=False
        self.deadline_timer.stop()
        if self._closing:return
        self.controller.complete(ticket,result);self._worker=None;self.render_state()
    @Slot(object,str)
    def worker_failed(self,ticket,message):
        self._worker_busy=False
        self.deadline_timer.stop()
        if self._closing:return
        self.controller.failed(ticket,message);self._worker=None;self.render_state()
    def cancel(self):self.controller.cancel();self.render_state()
    def expire(self):
        if self._closing or not self._worker_busy:return
        ticket=self.controller.active
        if ticket:ticket.cancel.timed_out=True;ticket.cancel.set()
        self.controller.cancel();self.controller.result=unknown_result('cancelled','deadline',self.word('계산 시간 한도에 도달했습니다. 결과를 표시하지 않습니다.','Calculation budget reached. No result is displayed.'),self.controller.counts());self.render_state()
    def render_state(self):
        if self._closing:return
        view=self.controller.view();counts=self.controller.counts()
        bindings=[]
        for kind in ('contract','parameters'):
            bound=getattr(self.controller,kind)
            if bound:bindings.append(kind+': '+bound.raw_sha256[:16]+' · '+str(bound.bytes)+' B')
        self.inputs.setText(self.word(f"등록기기 {counts['registered_devices']} · 전선 {counts['wires']} · 계산 제외 {counts['disabled_devices']} · 저장 코드 {counts['program_attachments']}",
            f"Registered devices {counts['registered_devices']} · wires {counts['wires']} · analysis disabled {counts['disabled_devices']} · saved programs {counts['program_attachments']}")+'\n'+'\n'.join(bindings))
        messages=[f['message'] for f in view['missing_or_blocking_reasons']]+[f['message'] for f in view['physical_unverified_reasons']]
        if view['can_run_declared_scenario']:messages.insert(0,self.word('선언 시나리오 결과 · 실제 값은 계속 미확인입니다.','Declared scenario result · physical values remain unknown.'))
        self.status.setText(view['status']+'\n'+'\n'.join(messages))
        self.status.setToolTip(self.status.text())
        points=view['scenario_points'];self.table.setRowCount(len(points))
        for index,point in enumerate(points):
            values=[point['virtual_time_s'],point['scenario_rpm'],point['scenario_current_a'],point['mean_voltage_v'],point['scenario_encoder_counts']]
            for column,value in enumerate(values):
                rendered=self.word('미입력','Unspecified') if value is None else str(value) if column==4 else f'{value:.7g}'
                self.table.setItem(index,column,QTableWidgetItem(rendered))
        self.run_button.setEnabled(self.controller.ready_inputs() and not self._worker_busy);self.cancel_button.setEnabled(self._worker_busy)
    def done(self,result):
        if not self._closing:self._closing=True;self.deadline_timer.stop();self.controller.close();self.runner.close()
        super().done(result)
