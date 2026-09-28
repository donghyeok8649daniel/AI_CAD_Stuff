"""Output-only plate layout, with the export action tied to the checked preview."""
from copy import deepcopy
from PySide6.QtWidgets import QCheckBox,QFormLayout,QFileDialog,QMessageBox
from ..printing import prepare_print,export_print_stl
from .workflows import PreviewDialog,choice
from .widgets import label,number


class PrintDialog(PreviewDialog):
    def __init__(self,parent,raw,selected=()):
        super().__init__(parent,'3D 프린팅 · STL 미리보기','출력할 부품과 방향을 선택하세요. 부품을 분리해 바닥에 배치하며 원본 설계·관절은 변경하지 않습니다.')
        self.source=deepcopy(raw);self.part_boxes={};self.warnings=[];self.bed_actor=None
        self.apply_button.setText('이 미리보기로 STL 저장')
        for part in raw['parts']:
            box=QCheckBox(part['name']);box.setProperty('cadUserText',True);box.setChecked(not selected or part['id'] in selected);box.toggled.connect(self.schedule);self.controls.addWidget(box);self.part_boxes[part['id']]=box
        form=QFormLayout();self.controls.addLayout(form);self.orientation=[];self.bed=[]
        for axis in 'XYZ':
            w=choice([(0,'0°'),(90,'90°'),(180,'180°'),(270,'270°')]);w.currentIndexChanged.connect(self.schedule);form.addRow('출력 '+axis+' 회전',w);self.orientation.append(w)
        for axis,value in zip('XYZ',(220,220,250)):
            w=number(value,1,5000,' mm');w.valueChanged.connect(self.schedule);form.addRow('출력 영역 '+axis,w);self.bed.append(w)
        self.gap=number(5,.1,100,' mm');self.gap.valueChanged.connect(self.schedule);form.addRow('부품 간격',self.gap)
        self.quality=choice([(.025,'정밀 · 0.025 mm'),(.05,'표준 · 0.05 mm'),(.1,'가벼움 · 0.1 mm'),(.01,'고정밀 · 0.01 mm')]);form.addRow('STL 메시 오차',self.quality)
        self.controls.addWidget(label('단위 mm · 프린터 전체 여유가 적용된 현재 형상을 출력합니다. 보정을 중복 적용하지 않습니다.\n서포트·인필·레이어·G-code는 STL을 연 슬라이서에서 설정하세요. 자동 강도/최소 벽두께 인증은 하지 않습니다.',True));self.controls.addStretch();self.schedule()
    def candidate(self):
        return dict(raw=self.source,identifiers=[k for k,v in self.part_boxes.items() if v.isChecked()],rotation=[w.currentData() for w in self.orientation],bed=[w.value() for w in self.bed],gap=self.gap.value())
    def compute(self,payload):
        d,r,warnings=prepare_print(**payload);r['print_warnings']=warnings;return d,r
    def present(self):
        super().present();self.warnings=self.result.get('print_warnings',[])
        from vtkmodules.vtkFiltersSources import vtkCubeSource
        from vtkmodules.vtkRenderingCore import vtkPolyDataMapper,vtkActor
        if self.bed_actor:self.viewport.renderer.RemoveActor(self.bed_actor)
        bed=vtkCubeSource();bed.SetXLength(self.bed[0].value());bed.SetYLength(self.bed[1].value());bed.SetZLength(.4);bed.SetCenter(0,0,-.25)
        mapper=vtkPolyDataMapper();mapper.SetInputConnection(bed.GetOutputPort());actor=vtkActor();actor.SetMapper(mapper);actor.GetProperty().SetColor(.25,.36,.4);actor.GetProperty().SetOpacity(.35);actor.GetProperty().EdgeVisibilityOn();actor.PickableOff();self.bed_actor=actor;self.viewport.renderer.AddActor(actor);self.viewport.window.Render()
        if self.warnings:
            self.status.setText('\n'.join(self.warnings));self.status.setStyleSheet('color:#ffab91;');self.apply_button.setEnabled(False)
        else:self.status.setText(self.status.text()+' · 바닥 Z=0 · 출력 영역 안에 배치됨')
    def accept(self):
        if not self.checked or self.running or not self.apply_button.isEnabled() or self.warnings:return
        path,_=QFileDialog.getSaveFileName(self,'STL 저장','print.stl','STL (*.stl)')
        if not path:return
        if not path.lower().endswith('.stl'):path+='.stl'
        # Export is asynchronous too; closing this dialog does not destroy the
        # worker's immutable shape snapshot or change the original document.
        from .widgets import Worker
        from PySide6.QtCore import QThreadPool
        d=self.checked.model_copy(deep=True);quality=self.quality.currentData();self.running=True;self.controls.parentWidget().setEnabled(False);self.apply_button.setEnabled(False);self.status.setText('STL 메시 생성 중…')
        self.worker=Worker(lambda:export_print_stl(d,path,tolerance=quality))
        def done(target):
            self.running=False
            if not self.alive:return
            self.controls.parentWidget().setEnabled(True);self.status.setText('STL 저장 완료 · '+str(target));self.apply_button.setEnabled(self.checked is not None and not self.warnings)
            if self.checked is None:self.timer.start()
        def failed(message):
            self.running=False
            if self.alive:self.controls.parentWidget().setEnabled(True);self.failed(message)
        self.worker.signals.done.connect(done);self.worker.signals.failed.connect(failed);QThreadPool.globalInstance().start(self.worker)
