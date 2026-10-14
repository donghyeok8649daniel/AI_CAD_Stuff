"""Native view for an embedded G474 ELF, backed by a headless child process."""
import json
from copy import deepcopy
from pathlib import Path
import threading

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout

from ..electrical import ElectricalWorkspace
from ..firmware_emulation import attach_elf
from ..program_drive_adapter import fingerprint
from .firmware_emulation_runner import FirmwareEmulationRunner,FirmwareRunTicket
from .widgets import button


class FirmwareEmulationDialog(QDialog):
    def __init__(self,workspace,parent=None,language='ko',selected_component_id='',design=None,document_provider=None):
        super().__init__(parent)
        self.en=language=='en'; self.workspace=ElectricalWorkspace.model_validate(workspace.model_dump() if hasattr(workspace,'model_dump') else workspace).model_copy(deep=True)
        self.design=deepcopy(design);self.document_provider=document_provider
        self.document_digest=None if document_provider is None else fingerprint(document_provider())
        self.images=list(self.workspace.firmware_images);self.result=None;self._running=False;self._cancel=threading.Event();self._ticket=None;self._revision=0;self._alive=True;self._published_context=None
        self.runner=FirmwareEmulationRunner();self.runner.finished.connect(self.execution_finished);self.runner.failed.connect(self.execution_failed)
        self.setWindowTitle(self.word('G474 전체 펌웨어 실행','G474 full firmware execution'));self.resize(880,580)
        layout=QVBoxLayout(self)
        note=QLabel(self.word('컴파일된 ELF를 ARM Cortex-M4F에서 실행합니다. 가상 클록 16 MHz · 실제 보드 연결 없음.',
            'Run compiled ELF on ARM Cortex-M4F. Virtual 16 MHz clock · no physical board connection.'));note.setWordWrap(True);layout.addWidget(note)
        row=QHBoxLayout();self.boards=QComboBox();self.boards.setObjectName('g474FirmwareBoard')
        for c in self.workspace.components:
            if c.kind=='mcu' and c.catalog_id=='st_nucleo_g474re' and c.pinout_catalog_id==c.catalog_id:self.boards.addItem(c.name,c.id)
        index=self.boards.findData(selected_component_id)
        if index>=0:self.boards.setCurrentIndex(index)
        row.addWidget(self.boards,1)
        self.scenarios=QComboBox();self.scenarios.addItem(self.word('기본 부팅','Boot'),'boot');self.scenarios.addItem(self.word('DRDY 입력 / EXTI','DRDY / EXTI'),'drdy');self.scenarios.addItem(self.word('TIM2 오버플로','TIM2 overflow'),'timer_rollover');row.addWidget(self.scenarios)
        for ko,en,value in [('가상 모터 왕복','Virtual motor cycle','motor_drive'),('가상 정지 입력','Virtual stop','motor_stop'),('가상 인터록','Virtual guard','motor_guard'),('가상 상한 입력','Virtual upper limit','motor_limit')]:self.scenarios.addItem(self.word(ko,en),value)
        if any(i.virtual_drive for i in self.images):self.scenarios.setCurrentIndex(self.scenarios.findData('motor_drive'))
        self.upload=button(self.word('ELF 연결…','Attach ELF…'),self.attach);row.addWidget(self.upload)
        self.run_button=button(self.word('가상 실행','Run virtually'),self.run_image);row.addWidget(self.run_button)
        self.stop=button(self.word('중지','Stop'),self.cancel);row.addWidget(self.stop)
        self.export=button(self.word('결과 내보내기…','Export result…'),self.export_result);row.addWidget(self.export)
        self.replay=button(self.word('3D 동작 재생…','Replay in 3D…'),self.replay_motion);row.addWidget(self.replay)
        layout.addLayout(row)
        self.status=QLabel(self.word('보드와 ELF를 선택하세요.','Select a board and ELF.'));self.status.setWordWrap(True);layout.addWidget(self.status)
        self.report=QPlainTextEdit();self.report.setReadOnly(True);self.report.setObjectName('g474FirmwareResult');layout.addWidget(self.report,1)
        scope=QLabel(self.word('펌웨어의 초기화·함수·인터럽트를 실행합니다. 지원 범위를 벗어난 주변장치는 오류로 보고합니다. '
            'ADC 시작·모터 허용은 펌웨어의 원래 조건을 따릅니다. 가상 실행은 실물 타이밍·전장·모터 검증이 아닙니다.',
            'Execute firmware startup, functions and interrupts. Unsupported peripherals are reported as errors. '
            'ADC start and drive enable follow original firmware conditions. Virtual execution does not validate physical timing, wiring or motors.'));scope.setWordWrap(True);layout.addWidget(scope)
        footer=QHBoxLayout();footer.addStretch();self.apply=button(self.word('ELF 첨부 적용','Apply ELF attachment'),self.accept);footer.addWidget(self.apply)
        footer.addWidget(button(self.word('취소 / 닫기','Cancel / close'),self.reject));layout.addLayout(footer);self._busy(False)
        self.boards.currentIndexChanged.connect(self.configuration_changed);self.scenarios.currentIndexChanged.connect(self.configuration_changed)
    def word(self,ko,en):return en if self.en else ko
    def current_unchanged(self):
        try:return self.document_provider is None or fingerprint(self.document_provider())==self.document_digest
        except (TypeError,ValueError,AttributeError):return False
    def configuration_digest(self):
        return fingerprint(dict(board=self.boards.currentData(),scenario=self.scenarios.currentData(),workspace=self.workspace.model_dump(mode='json'),images=[i.model_dump(mode='json') for i in self.images],design=self.design))
    def configuration_changed(self,*args):
        if not self._alive:return
        self._revision+=1;self.cancel();self.result=None;self._published_context=None;self.report.clear()
        if not self.runner.busy:self._busy(False)
    def discard_stale(self):
        self.result=None;self._published_context=None;self.report.clear();self.status.setText(self.word('설계·배선·ELF·시나리오가 바뀌어 이전 결과를 버렸습니다. 다시 열어 실행하세요.','Design, wiring, ELF or scenario changed; the old result was discarded. Reopen and run again.'));self._busy(False)
    def _busy(self,value):
        self._running=value;self.boards.setEnabled(not value);self.scenarios.setEnabled(not value);self.upload.setEnabled(not value);self.run_button.setEnabled(not value and bool(self.images));self.stop.setEnabled(value);self.apply.setEnabled(not value);self.export.setEnabled(not value and self.result is not None);self.replay.setEnabled(not value and self.result is not None and self.result.get('status')=='executed' and bool(self.result.get('virtual_motion_trace')))
    def attach(self):
        board=self.boards.currentData()
        if not board:self.status.setText(self.word('등록된 G474 보드가 없습니다.','No registered G474 board.'));return
        path,_=QFileDialog.getOpenFileName(self,self.word('G474 ELF 선택','Select G474 ELF'),'','ARM ELF (*.elf)')
        if not path:return
        try:
            image=attach_elf(path,self.workspace,board)
            self.images=[i for i in self.images if i.board_component_id!=board]+[image]
            self.configuration_changed()
            self.status.setText(self.word('ELF를 연결했습니다. 실행은 별도로 시작하세요.','ELF attached. Start execution separately.'));self._busy(False)
        except Exception as exc:self.status.setText(str(exc))
    def run_image(self):
        if self.runner.busy or not self._alive:return
        if not self.current_unchanged():self.discard_stale();return
        images=[i for i in self.images if i.board_component_id==self.boards.currentData()]
        if len(images)!=1:self.status.setText(self.word('선택 보드의 ELF 하나를 연결하세요.','Attach one ELF for the selected board.'));return
        self._revision+=1;self._cancel=threading.Event();self.result=None;self._published_context=None;self.report.clear()
        ticket=FirmwareRunTicket(self._revision,self.workspace.model_dump(mode='json'),images[0].model_copy(deep=True),deepcopy(self.design),self.scenarios.currentData(),self._cancel,self.configuration_digest())
        self._ticket=ticket
        if not self.runner.start(ticket):self._ticket=None;return
        self._busy(True);self.status.setText(self.word('ARM 가상 실행 중…','ARM virtual execution…'))
    @Slot(object,object)
    def execution_finished(self,ticket,result):
        if not self._alive:return
        if self._ticket is not ticket or ticket.revision!=self._revision:
            if not self.runner.busy:self._busy(False)
            return
        self._ticket=None
        if ticket.cancel.is_set():self.result=None;self.report.clear();self.status.setText(self.word('실행을 취소했습니다. 결과를 적용하지 않았습니다.','Execution cancelled; no result was applied.'));self._busy(False);return
        if not self.current_unchanged() or ticket.context_digest!=self.configuration_digest():self.discard_stale();return
        valid=isinstance(result,dict) and result.get('status') in ('blocked','fault','cancelled','timeout','executed') and result.get('physical_IO') is False and result.get('allow_motion') is False and result.get('qualification',0)==0
        if valid and result['status']=='executed':valid=result.get('image_sha256')==ticket.image.sha256 and result.get('board_component_id')==ticket.image.board_component_id and result.get('scenario')==ticket.scenario
        if not valid:result=dict(status='fault',errors=['Invalid virtual worker identity or physical-permission payload.'],physical_IO=False,allow_motion=False)
        self.result=deepcopy(result);self._published_context=ticket.context_digest;self.report.setPlainText(json.dumps(result,ensure_ascii=False,indent=2));self.status.setText(self.word('실행 결과: ','Execution result: ')+result['status']);self._busy(False)
    @Slot(object,str)
    def execution_failed(self,ticket,message):
        self.execution_finished(ticket,dict(status='fault',errors=[message],physical_IO=False,allow_motion=False))
    def cancel(self):self._cancel.set()
    def accept(self):
        if self.runner.busy:return
        if not self.current_unchanged():self.discard_stale();return
        super().accept()
    def reject(self):
        if self._running:self.cancel();self.status.setText(self.word('중지 중입니다. 종료 후 닫으세요.','Stopping. Close after completion.'));return
        super().reject()
    def closeEvent(self,event):
        if self._running:self.cancel();event.ignore()
        else:super().closeEvent(event)
    def export_result(self):
        if self.result is None:return
        if not self.current_unchanged() or self._published_context!=self.configuration_digest():self.discard_stale();return
        path,_=QFileDialog.getSaveFileName(self,self.word('실행 결과 저장','Save execution result'),'g474-result.json','JSON (*.json)')
        if path:Path(path).write_text(json.dumps(self.result,ensure_ascii=False,indent=2),encoding='utf-8')
    def replay_motion(self):
        if self.result is None:return
        if not self.current_unchanged() or self._published_context!=self.configuration_digest():self.discard_stale();return
        from .firmware_motion_dialog import FirmwareMotionDialog
        node=self.parent()
        while node is not None and not hasattr(node,'document'):node=node.parent()
        if node is None or not node.result:self.status.setText(self.word('먼저 이 설계를 CAD 3D 화면에 불러오세요.','Load this design in the CAD viewport first.'));return
        selected=[i for i in self.images if i.sha256==self.result.get('image_sha256')]
        try:
            if len(selected)!=1:raise ValueError('ELF execution identity is ambiguous.')
            dialog=FirmwareMotionDialog(self.design,selected[0],self.result,node.result,self,language='en' if self.en else 'ko',document_provider=self.document_provider)
            try:dialog.exec()
            finally:dialog.deleteLater()
        except Exception as exc:self.status.setText(str(exc))
    def done(self,value):
        self._alive=False;self.cancel();self.runner.close();super().done(value)
