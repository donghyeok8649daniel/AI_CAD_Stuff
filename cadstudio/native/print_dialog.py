"""Output-only plate layout, with the export action tied to the checked preview."""
from copy import deepcopy
from PySide6.QtWidgets import QCheckBox,QFormLayout,QFileDialog,QWidget,QVBoxLayout,QToolButton
from ..printing import prepare_print,export_print_stl
from .workflows import PreviewDialog,choice
from .widgets import label,number,button


class PrintDialog(PreviewDialog):
    def __init__(self,parent,raw,selected=()):
        super().__init__(parent,'3D 프린팅 · STL 미리보기','출력할 부품과 방향을 선택하세요. 부품을 분리해 바닥에 배치하며 원본 설계·관절은 변경하지 않습니다.')
        self.source=deepcopy(raw);self.part_boxes={};self.warnings=[];self.bed_actor=None;self.placements={};self.plate_view_initialized=False
        self.apply_button.setText('이 미리보기로 STL 저장')
        def section(title):
            toggle=QToolButton();toggle.setText('▸ '+title);toggle.setCheckable(True);self.controls.addWidget(toggle)
            panel=QWidget();box=QVBoxLayout(panel);box.setContentsMargins(0,0,0,0);panel.hide();self.controls.addWidget(panel)
            def changed(opened):panel.setVisible(opened);toggle.setText(('▾ ' if opened else '▸ ')+title)
            toggle.toggled.connect(changed);return box
        form=QFormLayout();self.controls.addLayout(form)
        self.active_part=choice([(p['id'],p['name']) for p in raw['parts']]);self.active_part.setProperty('cadUserText',True);form.addRow('배치할 부품',self.active_part)
        self.pose_inputs={}
        for key,title in [('x','바닥 중심 X'),('y','바닥 중심 Y'),('rx','부품 X 회전'),('ry','부품 Y 회전'),('rz','부품 Z 회전')]:
            w=number(0,-5000 if len(key)==1 else -360,5000 if len(key)==1 else 360,' mm' if len(key)==1 else ' °');self.pose_inputs[key]=w;form.addRow(title,w);w.valueChanged.connect(self.change_pose)
        self.active_part.currentIndexChanged.connect(self.sync_pose)
        self.drag_enabled=QCheckBox('부품을 드래그해서 바닥에 배치');self.drag_enabled.setChecked(True);self.controls.addWidget(self.drag_enabled)
        self.controls.addWidget(button('상면에서 배치',self.top_plate))
        self.controls.addWidget(button('전체 자동 배치 / 방향 초기화',self.auto_pack))
        picks=section('출력할 부품 선택')
        for part in raw['parts']:
            box=QCheckBox(part['name']);box.setProperty('cadUserText',True);box.setChecked(not selected or part['id'] in selected);box.toggled.connect(self.schedule);picks.addWidget(box);self.part_boxes[part['id']]=box
        settings=section('프린터 / 자동 배치 설정');form=QFormLayout();settings.addLayout(form);self.orientation=[];self.bed=[]
        for axis in 'XYZ':
            w=choice([(0,'0°'),(90,'90°'),(180,'180°'),(270,'270°')]);w.currentIndexChanged.connect(self.auto_pack);form.addRow('출력 '+axis+' 회전',w);self.orientation.append(w)
        for axis,value in zip('XYZ',(220,220,250)):
            w=number(value,1,5000,' mm');w.valueChanged.connect(self.schedule);form.addRow('출력 영역 '+axis,w);self.bed.append(w)
        self.gap=number(5,.1,100,' mm');self.gap.valueChanged.connect(self.auto_pack);form.addRow('부품 간격',self.gap)
        self.quality=choice([(.025,'정밀 · 0.025 mm'),(.05,'표준 · 0.05 mm'),(.1,'가벼움 · 0.1 mm'),(.01,'고정밀 · 0.01 mm')]);form.addRow('STL 메시 오차',self.quality)
        self.controls.addWidget(label('선택한 부품의 바운딩 박스 중심을 X/Y로 지정합니다. 회전 후 바닥 Z=0에 놓습니다. 빈 공간 드래그는 시점 회전입니다.',True))
        from .print_placement import PrintPlacementHandle
        self.placement_handle=PrintPlacementHandle(self)
        self.viewport.footer.setText('부품 드래그: 출력 위치 이동 · 휠: 커서 중심 확대 · 빈 공간 드래그: 회전')
        settings.addWidget(label('단위 mm · 현재 형상을 출력하며 보정을 중복 적용하지 않습니다. 서포트·인필·레이어·G-code는 슬라이서에서 설정하세요.',True))
        self.controls.addStretch();self.schedule()
    def candidate(self):
        return dict(raw=self.source,identifiers=[k for k,v in self.part_boxes.items() if v.isChecked()],rotation=[w.currentData() for w in self.orientation],bed=[w.value() for w in self.bed],gap=self.gap.value(),placements=deepcopy(self.placements))
    def auto_pack(self,*_):
        self.placements={};self.fit_next=True;self.schedule()
    def top_plate(self):
        self.viewport.set_view('top',False);x,y,z=[w.value() for w in self.bed]
        self.viewport.renderer.ResetCamera(-x/2,x/2,-y/2,y/2,0,0)
        self.viewport.renderer.ResetCameraClippingRange();self.viewport.window.Render()
    def sync_pose(self,*_):
        identifier=self.active_part.currentData();pose=self.placements.get(identifier)
        for key,w in self.pose_inputs.items():
            w.blockSignals(True);w.setEnabled(pose is not None);w.setValue((pose or {}).get(key,0));w.blockSignals(False)
        self.viewport.select(identifier if identifier in self.viewport.actors else None)
    def change_pose(self,*_):
        identifier=self.active_part.currentData()
        if identifier not in self.placements:return
        self.placements[identifier]={k:w.value() for k,w in self.pose_inputs.items()};self.schedule()
    def compute(self,payload):
        d,r,warnings=prepare_print(**payload);r['print_warnings']=warnings;return d,r
    def present(self):
        super().present();self.warnings=self.result.get('print_warnings',[])
        self.placements.update(self.result['print_placements']);self.sync_pose()
        from vtkmodules.vtkFiltersSources import vtkCubeSource
        from vtkmodules.vtkRenderingCore import vtkPolyDataMapper,vtkActor
        if self.bed_actor:self.viewport.renderer.RemoveActor(self.bed_actor)
        bed=vtkCubeSource();bed.SetXLength(self.bed[0].value());bed.SetYLength(self.bed[1].value());bed.SetZLength(.4);bed.SetCenter(0,0,-.25)
        mapper=vtkPolyDataMapper();mapper.SetInputConnection(bed.GetOutputPort());actor=vtkActor();actor.SetMapper(mapper);actor.GetProperty().SetColor(.25,.36,.4);actor.GetProperty().SetOpacity(.35);actor.GetProperty().EdgeVisibilityOn();actor.PickableOff();self.bed_actor=actor;self.viewport.renderer.AddActor(actor);self.viewport.window.Render()
        if not self.plate_view_initialized:self.plate_view_initialized=True;self.top_plate()
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
