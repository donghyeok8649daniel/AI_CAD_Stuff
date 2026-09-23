"""Saved native engineering studies. Results regenerate from current CAD."""
from copy import deepcopy
import csv
import numpy as np
from PySide6.QtCore import Qt,QTimer,QThreadPool,QPointF,QByteArray
from PySide6.QtGui import QColor,QPainter,QPen,QPainterPath
from PySide6.QtWidgets import QDialog,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QSplitter,QScrollArea,QSlider,QCheckBox,QFileDialog
from PySide6.QtSvgWidgets import QSvgWidget
from .widgets import Worker,label,button,number
from .workflows import choice
from .viewport import CADViewport,polydata
from .geometry import uid
from ..models import Design
from ..kernel import KERNEL_LOCK,preview
from ..dynamics import RobotSettings,chains,cad_robot,simulate
from ..tensile import TensileSettings,analyze
from ..drawings import DrawingSettings,sheet,svg,export_sheet


class CurvePlot(QWidget):
    def __init__(self):super().__init__();self.data=None;self.setMinimumHeight(150);self.setMaximumHeight(230)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.fillRect(self.rect(),QColor('#12212c'))
        if self.data:
            x,ys,unit=self.data;ys=np.array(ys);low,high=float(ys.min()),float(ys.max());span=max(high-low,1e-6);left,top,w,h=66,22,self.width()-85,self.height()-47
            p.setPen(QColor('#9ab4c4'));p.drawText(8,17,unit);p.drawText(6,35,f'{high:.3g}');p.drawText(6,top+h,f'{low:.3g}');p.drawText(left,top+h+20,'0');p.drawText(left+w-55,top+h+20,f'{x[-1]:.2f} s')
            for i,color in enumerate(('#62d8bf','#eebc72')):
                path=QPainterPath()
                for j,(t,row) in enumerate(zip(x,ys)):
                    point=QPointF(left+w*t/x[-1],top+h*(high-row[i])/span)
                    if j:path.lineTo(point)
                    else:path.moveTo(point)
                p.setPen(QPen(QColor(color),2));p.drawPath(path)
        p.end()


class StudyDialog(QDialog):
    kind=''
    def __init__(self,parent,design,title,identifier=None):
        super().__init__(parent);self.setWindowTitle(title);self.resize(1180,820);self.setMinimumSize(820,590);self.base=Design.model_validate(design);self.identifier=identifier or 'study-'+uid();self.existing=next((s for s in self.base.studies if s.id==identifier),None);self.running=False;self.alive=True;self.checked=None;self.output=None;self.revision=0
        root=QVBoxLayout(self);root.addWidget(label(title));self.split=QSplitter();root.addWidget(self.split,1);self.visual=QWidget();self.visual_layout=QVBoxLayout(self.visual);self.visual_layout.setContentsMargins(0,0,0,0);self.split.addWidget(self.visual);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setMinimumWidth(280);scroll.setMaximumWidth(360);widget=QWidget();self.controls=QVBoxLayout(widget);scroll.setWidget(widget);self.split.addWidget(scroll)
        self.form=QFormLayout();self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows);self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow);self.controls.addLayout(self.form);self.status=label('조건을 정한 뒤 계산을 누르세요.');root.addWidget(self.status);buttons=QHBoxLayout();self.calculate_button=button('계산 / 갱신',self.calculate,True);buttons.addWidget(self.calculate_button);self.save_button=button('조건을 작업 기록에 저장',self.accept);self.save_button.setEnabled(False);buttons.addWidget(self.save_button);buttons.addStretch();buttons.addWidget(button('닫기',self.reject));root.addLayout(buttons)
    def dirty(self,*args):
        self.revision+=1;self.checked=None;self.save_button.setEnabled(False);self.status.setText('입력이 변경되었습니다. 다시 계산하세요.')
    def calculate(self):
        if self.running:return
        try:settings=self.settings()
        except Exception as exc:self.failed(str(exc));return
        self.checked=None;self.save_button.setEnabled(False);self.running=True;self.calculate_button.setEnabled(False);revision=self.revision;self.status.setText('계산 중…');worker=Worker(lambda:self.compute(settings));self.worker=worker
        def done(result):
            self.running=False
            if not self.alive:return
            self.calculate_button.setEnabled(True)
            if revision!=self.revision:self.status.setText('계산 중 입력이 바뀌었습니다. 다시 계산하세요.');return
            self.output=result;self.checked=settings;self.save_button.setEnabled(True)
            try:self.present()
            except Exception as exc:self.failed(str(exc))
        def failed(message):
            self.running=False
            if self.alive:self.calculate_button.setEnabled(True);self.failed(message)
        worker.signals.done.connect(done);worker.signals.failed.connect(failed);QThreadPool.globalInstance().start(worker)
    def failed(self,message):self.checked=None;self.save_button.setEnabled(False);self.status.setText(message[:700])
    def accept(self):
        if self.checked is None:return
        raw=self.base.model_dump();record=dict(id=self.identifier,kind=self.kind,name=self.windowTitle(),settings=self.checked.model_dump());raw['studies']=[s for s in raw['studies'] if s['id']!=self.identifier]+[record];self.candidate=raw;super().accept()
    def done(self,result):self.alive=False;super().done(result)
    def bind(self,w):
        signal=getattr(w,'valueChanged',None) or getattr(w,'currentIndexChanged',None) or getattr(w,'toggled',None) or getattr(w,'textChanged',None)
        signal.connect(self.dirty)


class RobotStudy(StudyDialog):
    kind='robot'
    def __init__(self,parent,design,identifier=None):
        super().__init__(parent,design,'로봇 · 도달 / 토크 / 운동 해석',identifier);s=RobotSettings.model_validate(self.existing.settings if self.existing else {})
        self.viewport=CADViewport();self.visual_layout.addWidget(self.viewport,1);self.plot=CurvePlot();self.visual_layout.addWidget(self.plot);self.slider=QSlider(Qt.Orientation.Horizontal);self.slider.setRange(0,200);self.visual_layout.addWidget(self.slider)
        self.chain=choice([(a.id,f'{a.id} → {b.id}') for a,b in chains(self.base)]);self.form.addRow('관절 체인',self.chain)
        if s.shoulder:self.chain.setCurrentIndex(self.chain.findData(s.shoulder))
        self.mode=choice([('inverse','목표 자세 → 필요한 토크'),('forward','일정 토크 → 운동')]);self.mode.setCurrentIndex(self.mode.findData(s.mode));self.form.addRow('해석',self.mode);self.inputs={}
        for key,title,value,lo,hi,suffix in [('density','이동 부품 공통 밀도',s.density,1,30000,' kg/m³'),('payload','끝단 하중 질량',s.payload,0,1000,' kg'),('duration','동작 시간',s.duration,.02,20,' s'),('damping','관절 점성 감쇠',s.damping,0,100,' N·m·s/rad')]:
            w=number(value,lo,hi,suffix);self.form.addRow(title,w);self.inputs[key]=w;self.bind(w)
        self.gravity=QCheckBox('수직 운동 평면 · 중력 -Y');self.gravity.setChecked(s.gravity);self.controls.addWidget(self.gravity)
        self.controls.addWidget(label('해제: 수평 XY 운동, 중력에 의한 회전 토크 0',True));self.target=[];self.torque=[];self.velocity=[]
        for i in range(2):
            for values,key,lo,hi,suffix,title in [(self.target,'target',-360,360,' °','목표 각도'),(self.torque,'torque',-100,100,' N·m','입력 토크'),(self.velocity,'velocity',-720,720,' °/s','초기 속도')]:
                w=number(getattr(s,key)[i],lo,hi,suffix);values.append(w);self.form.addRow(f'관절 {i+1} {title}',w);self.bind(w)
        self.tx=number(100,-3000,3000,' mm');self.ty=number(50,-3000,3000,' mm');self.elbow=choice([(1,'팔꿈치 +'),(-1,'팔꿈치 −')]);self.form.addRow('목표점 X · 어깨 기준',self.tx);self.form.addRow('목표점 Y',self.ty);self.form.addRow('IK 분기',self.elbow);self.controls.addWidget(button('목표점으로 목표 각도 계산',self.inverse_kinematics))
        self.plot_metric=choice([('torque','관절 토크 N·m'),('angles','각도 °'),('velocity','각속도 °/s')]);self.controls.addWidget(self.plot_metric);self.plot_metric.currentIndexChanged.connect(self.update_plot);self.controls.addWidget(button('결과 CSV 저장',self.export_csv));self.apply_pose=QCheckBox('저장할 때 현재 시간의 자세도 설계에 적용');self.controls.addWidget(self.apply_pose)
        self.controls.addWidget(label('강체 2회전 관절 모델입니다. 고정된 부착 부품의 질량도 포함합니다. 충돌 반력·기어 마찰·모터 제어·관절 제한은 계산하지 않습니다.',True));self.controls.addStretch()
        for w in (self.chain,self.mode,self.gravity):self.bind(w)
        self.mode.currentIndexChanged.connect(self.update_mode);self.slider.valueChanged.connect(self.pose);self.update_mode()
        with KERNEL_LOCK:self.viewport.load(preview(self.base))
    def update_mode(self):
        inverse=self.mode.currentData()=='inverse'
        for w in self.target:self.form.setRowVisible(w,inverse)
        for w in self.torque+self.velocity:self.form.setRowVisible(w,not inverse)
    def settings(self):return RobotSettings(shoulder=self.chain.currentData() or '',mode=self.mode.currentData(),gravity=self.gravity.isChecked(),target=[w.value() for w in self.target],torque=[w.value() for w in self.torque],velocity=[w.value() for w in self.velocity],**{k:w.value() for k,w in self.inputs.items()})
    def inverse_kinematics(self):
        try:
            with KERNEL_LOCK:robot,_,_=cad_robot(self.base,self.settings())
            q=np.degrees(robot.ik(np.array([self.tx.value(),self.ty.value()])/1000,self.elbow.currentData()))
            for w,v in zip(self.target,q):w.setValue(v)
            self.mode.setCurrentIndex(0);self.status.setText('목표 각도를 계산했습니다. 계산 / 갱신으로 궤적과 토크를 확인하세요.')
        except Exception as exc:self.failed(str(exc))
    def compute(self,settings):
        with KERNEL_LOCK:robot,pair,included=cad_robot(self.base,settings)
        result=simulate(robot,np.radians([m.rz for m in pair]),settings);result['joints']=[m.id for m in pair];result['included']=included;return result
    def present(self):self.update_plot();self.pose();self.status.setText(f"최대 토크 {self.output['peak_torque'][0]:.4f} / {self.output['peak_torque'][1]:.4f} N·m · 이동 질량 {sum(self.output['masses']):.4f} kg · 도달 반경 {self.output['reach_mm'][0]:.2f}~{self.output['reach_mm'][1]:.2f} mm · 포함: "+', '.join(self.output['included']))
    def update_plot(self):
        if self.output:self.plot.data=(self.output['time'],self.output[self.plot_metric.currentData()],self.plot_metric.currentText());self.plot.update()
    def pose_design(self):
        raw=self.base.model_dump();angles=self.output['angles'][self.slider.value()]
        for mate in raw['mates']:
            if mate['id'] in self.output['joints']:mate['rz']=(angles[self.output['joints'].index(mate['id'])]+180)%360-180
        return Design.model_validate(raw)
    def pose(self):
        if not self.output:return
        from ..constraints import transform_matrix
        from vtkmodules.vtkCommonMath import vtkMatrix4x4
        d=self.pose_design();old={p.id:p for p in self.base.parts}
        for p in d.parts:
            before=old[p.id].transform;after=p.transform;rotation=transform_matrix(after)@transform_matrix(before).T;translation=np.array([after.x,after.y,after.z])-rotation@np.array([before.x,before.y,before.z]);matrix=vtkMatrix4x4()
            for i in range(3):
                for j in range(3):matrix.SetElement(i,j,rotation[i,j])
                matrix.SetElement(i,3,translation[i])
            for actor in self.viewport.actors.get(p.id,[]):actor.SetUserMatrix(matrix)
        self.viewport.window.Render();self.viewport.footer.setText(f"시간 {self.output['time'][self.slider.value()]:.3f} s · 슬라이더로 운동 궤적 확인")
    def export_csv(self):
        if self.checked is None:return
        path,_=QFileDialog.getSaveFileName(self,'운동 결과 CSV','robot-motion.csv','CSV (*.csv)')
        if path:
            try:
                with open(path,'w',newline='',encoding='utf-8-sig') as f:
                    writer=csv.writer(f);writer.writerow(['time_s','q1_deg','q2_deg','v1_deg_s','v2_deg_s','a1_deg_s2','a2_deg_s2','tau1_Nm','tau2_Nm','tip_x_mm','tip_y_mm','energy_J'])
                    for i,t in enumerate(self.output['time']):writer.writerow([t,*self.output['angles'][i],*self.output['velocity'][i],*self.output['acceleration'][i],*self.output['torque'][i],*self.output['tip'][i],self.output['energy'][i]])
            except OSError as exc:self.status.setText(str(exc))
    def accept(self):
        if self.checked is not None and self.apply_pose.isChecked():self.base=self.pose_design()
        super().accept()
    def done(self,result):self.viewport.shutdown();super().done(result)


class TensileStudy(StudyDialog):
    kind='tensile'
    def __init__(self,parent,design,identifier=None,part_id=None):
        super().__init__(parent,design,'시편 · 인장 응력 / 변형 해석',identifier);parts=[(p.id,p.name) for p in self.base.parts if p.geometry.kind in ('round_specimen','flat_specimen')]
        s=TensileSettings.model_validate(self.existing.settings if self.existing else {'part_id':part_id or (parts[0][0] if parts else '')});self.part=choice(parts);self.part.setCurrentIndex(max(0,self.part.findData(s.part_id)));self.form.addRow('시편',self.part);self.inputs={}
        for key,title,value,lo,hi,suffix in [('young_gpa','탄성계수 E',s.young_gpa,.01,2000,' GPa'),('poisson','푸아송비 ν',s.poisson,0,.45,''),('yield_mpa','비교할 항복 강도',s.yield_mpa,.01,100000,' MPa'),('force_n','축방향 인장력',s.force_n,0,1e7,' N')]:
            w=number(value,lo,hi,suffix);self.form.addRow(title,w);self.inputs[key]=w;self.bind(w)
        self.refinement=choice([(1,'보통'),(2,'세밀'),(3,'매우 세밀')]);self.refinement.setCurrentIndex(s.refinement-1);self.form.addRow('메시',self.refinement);self.deform=number(1,0,10000,' ×');self.form.addRow('변형 표시 배율',self.deform);self.deform.valueChanged.connect(self.render);self.viewport=CADViewport();self.visual_layout.addWidget(self.viewport,1);self.metrics=label('');self.controls.addWidget(self.metrics);self.controls.addWidget(button('절점 변위 / 요소 응력 CSV',self.export_csv));self.controls.addWidget(label('한쪽 그립 완전 고정, 반대쪽 균일 인장. 기본값은 예시 재료입니다. 실제 재료값을 입력하세요. 3D 선형 탄성 TET4 해석이며 항복·파단·좌굴은 계산하지 않습니다. 고정단 최대응력은 메시의 영향을 받습니다.',True));self.controls.addStretch()
        for w in (self.part,self.refinement):self.bind(w)
    def settings(self):return TensileSettings(part_id=self.part.currentData() or '',refinement=self.refinement.currentData(),**{k:w.value() for k,w in self.inputs.items()})
    def compute(self,settings):return analyze(self.base,settings)
    def present(self):
        r=self.output;self.metrics.setText(f"절점 {len(r['nodes']):,} · 요소 {len(r['tets']):,}\n변위 최대 {r['max_displacement_mm']:.6g} mm\n등가응력 최대 {r['max_stress_mpa']:.4g} MPa\n평행부 평균 σx {r['gauge_axial_stress_mpa']:.4g} MPa\n공칭 F/A {r['nominal_stress_mpa']:.4g} MPa\n고정단 반력 {r['reaction'][0]:.4g} N")
        self.status.setText('항복 강도를 초과했습니다. 선형 탄성 가정의 적용 범위를 벗어납니다.' if r['yield_exceeded'] else '선형 탄성 해석 완료 · 다른 메시 단계와 비교해 수렴을 확인하세요.');self.render()
    def render(self):
        if not self.output:return
        from vtkmodules.vtkRenderingCore import vtkPolyDataMapper,vtkActor
        from vtkmodules.vtkRenderingAnnotation import vtkScalarBarActor
        from vtkmodules.vtkCommonCore import vtkLookupTable
        from vtkmodules.util.numpy_support import numpy_to_vtk
        r=self.output;tets=r['tets'];faces=np.concatenate([tets[:,idx] for idx in [(0,1,2),(0,1,3),(0,2,3),(1,2,3)]]);owners=np.tile(np.arange(len(tets)),4);_,first,counts=np.unique(np.sort(faces,axis=1),axis=0,return_index=True,return_counts=True);indices=first[counts==1];nodes=r['nodes']+r['displacement']*self.deform.value();mesh=polydata(nodes,faces[indices]);mesh.GetCellData().SetScalars(numpy_to_vtk(r['von_mises'][owners[indices]],deep=True))
        table=vtkLookupTable();table.SetHueRange(.66,0);table.SetTableRange(0,max(r['max_stress_mpa'],1e-9));table.Build();mapper=vtkPolyDataMapper();mapper.SetInputData(mesh);mapper.SetLookupTable(table);mapper.SetScalarRange(0,max(r['max_stress_mpa'],1e-9));actor=vtkActor();actor.SetMapper(mapper);actor.GetProperty().SetAmbient(.35);bar=vtkScalarBarActor();bar.SetLookupTable(table);bar.SetTitle('von Mises / MPa');bar.SetNumberOfLabels(5);bar.SetWidth(.13);bar.SetHeight(.6)
        self.viewport.renderer.RemoveAllViewProps();self.viewport.renderer.AddActor(actor);self.viewport.renderer.AddActor2D(bar);self.viewport.renderer.ResetCamera();self.viewport.window.Render();self.viewport.caption.setText('인장 응력 · 변형 표시 '+f'{self.deform.value():g}배');self.viewport.footer.setText('회전 / 확대 가능 · 색상은 요소별 등가응력 MPa · 형상은 메시 근사')
    def export_csv(self):
        if self.checked is None:return
        path,_=QFileDialog.getSaveFileName(self,'해석 CSV','specimen-results.csv','CSV (*.csv)')
        if not path:return
        try:
            with open(path,'w',newline='',encoding='utf-8-sig') as f:
                w=csv.writer(f);w.writerow(['NODE','x_mm','y_mm','z_mm','ux_mm','uy_mm','uz_mm'])
                for i,(p,u) in enumerate(zip(self.output['nodes'],self.output['displacement'])):w.writerow([i,*p,*u])
                w.writerow(['ELEMENT','sx_MPa','sy_MPa','sz_MPa','txy_MPa','tyz_MPa','txz_MPa','von_mises_MPa'])
                for i,(s,vm) in enumerate(zip(self.output['stress'],self.output['von_mises'])):w.writerow([i,*s,vm])
        except OSError as exc:self.status.setText(str(exc))
    def done(self,result):self.viewport.shutdown();super().done(result)


class DrawingDialog(StudyDialog):
    kind='drawing'
    def __init__(self,parent,design,identifier=None,part_id=None):
        from PySide6.QtWidgets import QLineEdit
        super().__init__(parent,design,'도면 · 정투상 / 치수 / 내보내기',identifier);s=DrawingSettings.model_validate(self.existing.settings if self.existing else {'part_id':part_id or '', 'title':self.base.name});self.part=choice([('','전체 조립'),*[(p.id,p.name) for p in self.base.parts]]);self.part.setCurrentIndex(max(0,self.part.findData(s.part_id)));self.page=choice([('A4','A4 가로'),('A3','A3 가로')]);self.page.setCurrentIndex(self.page.findData(s.page));self.scale=number(s.scale,0,100,' : 1',decimals=4);self.title=QLineEdit(s.title);self.number=QLineEdit(s.number);self.rev=QLineEdit(s.revision);self.hidden=QCheckBox('숨은선');self.hidden.setChecked(s.hidden);self.dimensions=QCheckBox('외형 치수');self.dimensions.setChecked(s.dimensions)
        for title,w in [('대상',self.part),('용지',self.page),('축척 · 0 = 자동',self.scale),('도면명',self.title),('도면 번호',self.number),('개정',self.rev)]:self.form.addRow(title,w);self.bind(w)
        for w in (self.hidden,self.dimensions):self.controls.addWidget(w);self.bind(w)
        self.svg_widget=QSvgWidget();self.visual_layout.addWidget(self.svg_widget,1)
        for fmt in ('svg','dxf','pdf'):self.controls.addWidget(button(fmt.upper()+' 내보내기',lambda _,f=fmt:self.export(f)))
        self.controls.addWidget(label('제3각법 상면·정면·우측면과 외형 치수입니다. 형상 변경 후 갱신하면 도면이 다시 생성됩니다. 선은 CAD 숨은선 계산 결과를 폴리라인으로 근사합니다.',True));self.controls.addStretch()
    def settings(self):return DrawingSettings(part_id=self.part.currentData(),title=self.title.text(),number=self.number.text(),revision=self.rev.text(),page=self.page.currentData(),scale=self.scale.value(),hidden=self.hidden.isChecked(),dimensions=self.dimensions.isChecked())
    def compute(self,settings):
        with KERNEL_LOCK:return sheet(self.base,settings)
    def present(self):self.svg_widget.load(QByteArray(svg(self.output).encode()));self.svg_widget.renderer().setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio);self.status.setText(f"도면 갱신 완료 · mm · 축척 {self.output['scale']:.4g}:1")
    def export(self,fmt):
        if self.checked is None:self.status.setText('먼저 계산 / 갱신을 누르세요.');return
        path,_=QFileDialog.getSaveFileName(self,'도면 저장','drawing.'+fmt,f'{fmt.upper()} (*.{fmt})')
        if path:
            try:export_sheet(self.output,path);self.status.setText('도면 저장: '+path)
            except Exception as exc:self.status.setText(str(exc))
