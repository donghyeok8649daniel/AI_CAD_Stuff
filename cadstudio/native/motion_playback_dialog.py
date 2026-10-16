"""Checked-sample CAD animation; no document, power or firmware execution."""
from copy import deepcopy
from dataclasses import dataclass
import threading,time
from PySide6.QtCore import QRunnable,Slot,QTimer,Qt,Signal
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QSplitter,QWidget,QScrollArea,QCheckBox,QComboBox,QPlainTextEdit
from vtkmodules.vtkCommonMath import vtkMatrix4x4
from ..motion_playback import compile_joint_playback,playback_frame_index
from ..assembly_motion import motion_controls
from ..automatic_interference import design_digest
from ..models import Design
from ..motion_initial_view import bound_initial_motion_preview
from .program_drive_runner import ProgramDriveRunner,_Signals
from .viewport import CADViewport
from .widgets import number,label,button


_PHASES={'kernel_wait':'다른 형상 작업 종료 대기','starting':'검사 준비','base_validation':'현재 설계 검증',
         'base_build':'현재 솔리드 구성','endpoint_validation':'종료 자세 검증','endpoint_build':'종료 솔리드 구성',
         'baseline_collisions':'현재 자세 전체 간섭 검사','baseline_bounds':'기준 경계 구성',
         'sample_validation':'표본 자세 검증','sample_shapes':'표본 솔리드 구성','sample_invariants':'구속·형상 일치 확인',
         'sample_collisions':'표본 간섭 검사','frame_matrices':'재생 자세 구성','checked_preview':'검사한 자세 메시 준비','complete':'검사 완료'}


def _progress_text(report):
    stage=_PHASES.get(report.get('stage'),report.get('stage','검사'))
    sample=f" · 자세 {report['sample']}/{report['samples']}" if report.get('sample') and report.get('samples') else ''
    work=f"전체 {report.get('active_seconds',0):.1f}초 · 분할 작업 {report.get('slice_active_seconds',0):.1f}/{report.get('active_budget_seconds',0):g}초" if report.get('budget_scope')=='completed_work_slices' else f"실제 검사 {report.get('active_seconds',0):.1f}/{report.get('active_budget_seconds',0):g}초"
    return f"{stage}{sample}\n형상 엔진 대기 {report.get('queue_seconds',0):.1f}초 · {work} · 취소 가능"


@dataclass
class _Ticket:
    revision:int
    raw:dict
    targets:list
    cancel:threading.Event
    metrics:dict|None=None


class _MotionSignals(_Signals):
    progress=Signal(object,object)


class _MotionWorker(QRunnable):
    def __init__(self,ticket,parent):
        super().__init__();self.setAutoDelete(False);self.ticket=ticket;self.signals=_MotionSignals(parent)
    @Slot()
    def run(self):
        def check():
            if self.ticket.cancel.is_set():raise ValueError('회전 검사 취소 · 설계는 유지됩니다.')
        def progress(report):
            self.ticket.metrics=report;self.signals.progress.emit(self.ticket,report)
        try:self.signals.finished.emit(self.ticket,compile_joint_playback(self.ticket.raw,self.ticket.targets,check=check,progress=progress,segmented=True))
        except Exception as exc:
            self.ticket.metrics=getattr(exc,'report',self.ticket.metrics)
            message=str(exc)
            if self.ticket.metrics:message+='\n'+_progress_text(self.ticket.metrics).replace(' · 취소 가능','')
            self.signals.failed.emit(self.ticket,message[:1800])


class _MotionRunner(ProgramDriveRunner):
    progress=Signal(object,object)
    def start(self,ticket):
        if self.busy or self.closing:return False
        worker=_MotionWorker(ticket,self);self.worker=worker;self.busy=True
        worker.signals.finished.connect(self.collect_finished);worker.signals.failed.connect(self.collect_failed)
        worker.signals.progress.connect(self.collect_progress)
        self.pool.start(worker);return True
    @Slot(object,object)
    def collect_progress(self,ticket,report):
        if not self.closing and self.worker is not None and self.worker.ticket is ticket:self.progress.emit(ticket,report)


class MotionPlaybackDialog(QDialog):
    def __init__(self,parent,raw,document_provider=None,*,initial_snapshot=None,revision_provider=None):
        super().__init__(parent);self.input_digest=design_digest(raw);self.base=Design.model_validate(deepcopy(raw)).model_dump();self.base_digest=design_digest(self.base)
        self.document_provider=document_provider;self.revision=0;self.compiled=None;self.alive=True;self.ticket=None;self.previous_ids=set();self.inspection_metrics=None
        self.revision_provider=revision_provider;self.revision_captured=True
        try:self.document_revision=deepcopy(revision_provider()) if revision_provider is not None else None
        except Exception:self.document_revision=None;self.revision_captured=False
        self.initial_snapshot=initial_snapshot;self.initial_view_state='missing'
        self.setObjectName('motionPlaybackDialog');self.setWindowTitle('3D 관절 회전 재생 · 보기 전용');self.resize(1100,760);self.setMinimumSize(820,560)
        root=QVBoxLayout(self);root.addWidget(label('관절과 종속 부품을 실제 표본 자세로 검사한 뒤 재생합니다. 원본 위치·구속·이력은 바꾸지 않습니다.',True))
        self.initial_note=label('현재 자세 보기 · 구동 검사는 아직 완료되지 않았습니다.',True);self.initial_note.setObjectName('motionPlaybackInitialViewStatus');root.addWidget(self.initial_note)
        split=QSplitter();root.addWidget(split,1);self.viewport=CADViewport();split.addWidget(self.viewport)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setMinimumWidth(290);scroll.setMaximumWidth(370);pane=QWidget();self.controls=QVBoxLayout(pane);scroll.setWidget(pane);split.addWidget(scroll)
        self.rows={};names={p['id']:p['name'] for p in self.base['parts']}
        for mate in self.base['mates']:
            if mate['kind'] not in ('revolute','cylindrical'):continue
            control=motion_controls(self.base,mate['id']).get('rz')
            if not control or 'driven_by' in control:continue
            lo,hi=control['limits'];checked=QCheckBox(mate['id']+' · '+names[mate['child']]);self.controls.addWidget(checked)
            field=number(control['value'],lo,hi,' °',decimals=4);form=QFormLayout();form.addRow('종료 관절각',field);self.controls.addLayout(form)
            row=QHBoxLayout();self.controls.addLayout(row)
            for text,delta in [('CW −360°',-360),('CCW +360°',360)]:
                row.addWidget(button(text,lambda _checked=False,k=mate['id'],d=delta:self.one_turn(k,d)))
            checked.toggled.connect(self.invalidate);field.valueChanged.connect(self.invalidate)
            self.rows[mate['id']]=(checked,field,control['value'])
        self.controls.addWidget(label('CW/CCW는 해당 관절의 로컬 +Z 기준 수학적 방향입니다. 실제 ESC·프로펠러 방향은 따로 확인합니다.',True))
        self.compile_button=button('선택 범위의 형상·간섭 검사',self.compile,True);self.compile_button.setObjectName('motionPlaybackCompile');self.controls.addWidget(self.compile_button)
        self.cancel_button=button('검사 취소',self.cancel);self.controls.addWidget(self.cancel_button)
        self.rpm=number(0,0,30000,' rpm',decimals=3);self.rpm.setObjectName('motionPlaybackDisplayRPM');form=QFormLayout();form.addRow('가장 큰 선택각도 기준 표시 RPM',self.rpm);self.controls.addLayout(form)
        self.controls.addWidget(label('선택 각도 범위가 짧은 관절은 비례해 느리게 움직입니다. 실제 모터/감속비 RPM으로 환산하지 않습니다.',True))
        self.mode=QComboBox();self.mode.addItem('1회','once');self.mode.addItem('1바퀴 반복 · 끝 자세가 같을 때','loop');self.mode.addItem('검사한 범위 왕복','bounce');self.mode.setCurrentIndex(2);self.controls.addWidget(self.mode)
        self.play_button=button('재생',self.play,True);self.play_button.setObjectName('motionPlaybackPlay');self.controls.addWidget(self.play_button)
        self.controls.addWidget(button('중지 · 원래 자세',self.stop));self.controls.addStretch()
        self.controls.addWidget(label('입력 RPM은 표시 시나리오이며 실제 모터 RPM·전기구동·힘/열/비행 검증이 아닙니다. 최대 2도 표본 검사이며 표본 사이 연속 충돌·공차는 미검증입니다.',True))
        self.status=label('회전 관절과 종료 각도를 고른 뒤 검사하세요. 아직 계산·재생하지 않았습니다.',True);root.addWidget(self.status);root.addWidget(button('닫기',self.reject))
        self.metrics_button=button('검사 시간·단계 기록…',self.show_inspection_metrics);self.controls.insertWidget(self.controls.count()-1,self.metrics_button)
        self.runner=_MotionRunner();self.runner.finished.connect(self.ready);self.runner.failed.connect(self.failed);self.runner.progress.connect(self.progress)
        self.timer=QTimer(self);self.timer.setInterval(33);self.timer.timeout.connect(self.tick)
        self.rpm.valueChanged.connect(self.speed_changed);self.mode.currentIndexChanged.connect(self.speed_changed);self.update_buttons()
        self.show_initial_view()

    def current_unchanged(self):
        try:
            if not self.revision_captured:return False
            if self.revision_provider is not None and self.revision_provider()!=self.document_revision:return False
            if self.document_provider is None:return True
            current=self.document_provider()
            return current is not None and design_digest(current)==self.input_digest
        except Exception:return False
    def clear_initial_view(self,state='stale'):
        had_view=self.initial_view_state=='current' or state=='display_error' or bool(getattr(self.viewport,'actors',{}))
        self.initial_view_state=state
        if had_view:self.viewport.load(None)
        self.initial_note.setText('현재 프로젝트/리비전 형상이 바뀌었거나 표시할 수 없습니다. 새 설계에서 다시 여세요. 구동 미검사.')
    def show_initial_view(self):
        if not self.current_unchanged():self.clear_initial_view();return
        data,state=bound_initial_motion_preview(self.initial_snapshot,self.base,self.input_digest,self.document_revision)
        self.initial_view_state=state
        if data is None:
            self.initial_note.setText('현재 프로젝트의 유효한 형상 미리보기가 없습니다. 주 화면에서 형상을 준비하고 다시 여세요. 구동 미검사.')
            return
        try:self.viewport.load(data);self.viewport.orbit_mode=True
        except Exception:
            self.clear_initial_view('display_error')
            self.status.setText('현재 형상을 표시하지 못했습니다. 구동 검사는 아직 완료되지 않았습니다.')
            return
        self.initial_note.setText('현재 프로젝트/리비전 형상 · 보기 전용 · 구동 검사 전')
    def one_turn(self,mid,delta):
        checked,field,start=self.rows[mid];value=start+delta
        if not field.minimum()<=value<=field.maximum():self.status.setText('기존 관절 한계 안의 범위를 직접 입력하세요. 한계를 자동으로 풀지 않습니다.');return
        checked.setChecked(True);field.setValue(value)
    def invalidate(self,*args):
        self.revision+=1;self.cancel();self.stop();self.compiled=None
        if self.initial_view_state=='current':self.initial_note.setText('현재 프로젝트/리비전 형상 · 보기 전용 · 구동 검사 전')
        if hasattr(self,'play_button'):self.update_buttons()
    def cancel(self):
        if self.ticket:self.ticket.cancel.set();self.ticket=None
    def compile(self):
        if self.runner.busy:return
        self.invalidate()
        if not self.current_unchanged():self.clear_initial_view();self.status.setText('원본 설계가 바뀌었습니다. 새 설계에서 다시 열어 검사하세요.');return
        targets=[dict(mate_id=mid,end_degrees=field.value()) for mid,(checked,field,start) in self.rows.items() if checked.isChecked()]
        self.ticket=_Ticket(self.revision,deepcopy(self.base),targets,threading.Event())
        self.inspection_metrics=None
        self.runner.start(self.ticket);self.status.setText('형상 엔진 대기 / 현재 자세·구동 표본 검사 준비 중… 취소 가능');self.update_buttons()
    @Slot(object,object)
    def progress(self,ticket,report):
        if not self.alive or self.ticket is not ticket or ticket.revision!=self.revision:return
        self.inspection_metrics=report;self.status.setText(_progress_text(report));self.metrics_button.setEnabled(True)
    def show_inspection_metrics(self):
        if not self.inspection_metrics:return
        import json
        dialog=QDialog(self);dialog.setWindowTitle('회전 검사 시간·단계 기록');dialog.resize(700,520)
        layout=QVBoxLayout(dialog);layout.addWidget(label('대기는 실제 검사와 분리되며, 동일 입력의 완료된 작업부터 자동으로 나누어 계속 검사합니다. 모든 표본이 끝나기 전에는 재생을 허용하지 않습니다. 진행 중인 네이티브 형상 계산은 끝날 때까지 기다릴 수 있습니다.',True))
        text=QPlainTextEdit();text.setReadOnly(True);text.setPlainText(json.dumps(self.inspection_metrics,ensure_ascii=False,indent=2));layout.addWidget(text,1)
        layout.addWidget(button('닫기',dialog.accept));dialog.exec()
    @Slot(object,object)
    def ready(self,ticket,result):
        if not self.alive:return
        if self.ticket is not ticket or ticket.revision!=self.revision:self.update_buttons();return
        self.ticket=None
        if not self.current_unchanged():self.failed(ticket,'원본 설계가 바뀌어 검사 결과를 버렸습니다.');return
        try:self.viewport.load(result['preview']);self.viewport.orbit_mode=True
        except Exception:
            self.compiled=None;self.clear_initial_view('display_error');self.show_initial_view()
            self.failed(ticket,'검사 결과 형상을 표시하지 못했습니다. 재생하지 않습니다.');return
        self.compiled=result;self.inspection_metrics=result.get('inspection_metrics')
        self.initial_view_state='current'
        self.initial_note.setText('전체 표본·마지막 미리보기 검사 완료 · 검사한 시작 자세 표시 · 실제 구동 미확인')
        self.status.setText(f"{result['samples']}개 자세 · 최대 {result['step_degrees']:.3g}° 간격 · 표본 체적 간섭 없음\n실제 RPM 미확인 · 표시용 속도를 입력하고 재생하세요.");self.update_buttons()
    @Slot(object,str)
    def failed(self,ticket,message):
        if not self.alive:return
        if ticket.revision!=self.revision:self.update_buttons();return
        if ticket.metrics:self.inspection_metrics=ticket.metrics
        self.ticket=None;self.compiled=None;self.status.setText(message);self.update_buttons()
        if not self.current_unchanged():self.clear_initial_view()
        elif self.initial_view_state=='current':self.initial_note.setText('현재 프로젝트/리비전 형상 · 보기 전용 · 구동 검사 미완료')
    def update_buttons(self):
        busy=getattr(self,'runner',None) and self.runner.busy
        self.compile_button.setEnabled(not busy and bool(self.rows));self.cancel_button.setEnabled(bool(busy))
        self.play_button.setEnabled(bool(self.compiled) and self.rpm.value()>0 and not busy)
        self.metrics_button.setEnabled(bool(self.inspection_metrics))
    def speed_changed(self,*args):
        self.stop();self.update_buttons()
    def play(self):
        if not self.compiled or self.rpm.value()<=0:return
        if not self.current_unchanged():self.stop();self.compiled=None;self.clear_initial_view();self.status.setText('설계가 바뀌어 재생 결과를 버렸습니다. 새 설계에서 다시 검사하세요.');self.update_buttons();return
        if self.mode.currentData()=='loop' and not self.compiled['can_loop']:
            self.status.setText('끝 자세가 시작과 다릅니다. 나사-슬라이더 등은 왕복 또는 1회 재생을 선택하세요.');return
        self.started=time.monotonic();self.timer.start();self.tick()
    def tick(self):
        if not self.alive or not self.compiled:return
        if not self.current_unchanged():self.stop();self.compiled=None;self.clear_initial_view();self.status.setText('설계가 바뀌어 재생을 중단했습니다. 다시 검사하세요.');self.update_buttons();return
        distance=max(abs(d['end']-d['start']) for d in self.compiled['drives']);elapsed=time.monotonic()-self.started
        index=playback_frame_index(elapsed,self.rpm.value(),distance,len(self.compiled['frames']),self.mode.currentData())
        frame=self.compiled['frames'][index];now=set(frame['matrices'])
        for pid in self.previous_ids-now:
            for actor in self.viewport.actors.get(pid,()):actor.SetUserMatrix(None)
        for pid,data in frame['matrices'].items():
            matrix=vtkMatrix4x4()
            for r in range(4):
                for c in range(4):matrix.SetElement(r,c,data[r][c])
            for actor in self.viewport.actors.get(pid,()):actor.SetUserMatrix(matrix)
        self.previous_ids=now;self.viewport.render()
        progress=elapsed*self.rpm.value()*6/distance
        direction=-1 if self.mode.currentData()=='bounce' and progress%2>=1 else 1
        if self.mode.currentData()=='once' and progress>=1:direction=0
        speeds=' / '.join(f"{d['mate_id']} {direction*self.rpm.value()*(d['end']-d['start'])/distance:.3g} rpm" for d in self.compiled['drives'])
        self.status.setText(f"보기 전용 · 현재 재생 방향의 표시 관절 {speeds}\n표본 {index+1}/{len(self.compiled['frames'])} · 실제 RPM 미확인")
        if self.mode.currentData()=='once' and index==len(self.compiled['frames'])-1:self.timer.stop()
    def stop(self):
        if hasattr(self,'timer'):self.timer.stop()
        for pid in self.previous_ids:
            for actor in self.viewport.actors.get(pid,()):actor.SetUserMatrix(None)
        self.previous_ids=set()
        if hasattr(self,'status') and self.compiled:
            speeds=' / '.join(f"{d['mate_id']} 0 rpm" for d in self.compiled['drives'])
            self.status.setText(f"정지 · 원래 자세 · 표시 관절 {speeds}\n실제 RPM 미확인 · 설정한 속도로 다시 재생할 수 있습니다.")
        if hasattr(self,'viewport') and not self.viewport.closed:self.viewport.render()
    def done(self,result):
        if self.alive:
            self.alive=False;self.cancel();self.stop();self.runner.close();self.viewport.shutdown()
        super().done(result)
