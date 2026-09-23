"""Direct native length measurements and a face-based hole workflow."""
from copy import deepcopy
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QListWidget,QCheckBox
from .widgets import label,button,number
from .workflows import PreviewDialog,choice
from .viewport import CADViewport
from .geometry import uid
from ..models import Design,Extrusion
from ..kernel import build,preview,KERNEL_LOCK,local_shape,face_frame
from ..constraints import transform_matrix
from ..advanced_geometry import edge_records


def interference_data(design):
    with KERNEL_LOCK:
        d=Design.model_validate(design);result=preview(d);shapes=dict(zip((p.id for p in d.parts),build(d)));overlaps=[]
        for pair in result['stats']['collisions']:
            shape=shapes[pair['a']].intersect(shapes[pair['b']]);vertices,triangles=shape.tessellate(.08)
            overlaps.append(dict(pair,vertices=[v.toTuple() for v in vertices],triangles=triangles))
        return result,overlaps


class InterferenceDialog(QDialog):
    def __init__(self,parent,result,overlaps):
        super().__init__(parent);self.setWindowTitle('부품 간섭 검사');self.resize(1050,740);self.overlaps=overlaps;root=QVBoxLayout(self)
        root.addWidget(label(f'체적 간섭 {len(overlaps)}곳 · 항목을 선택하면 겹친 영역이 빨갛게 나타납니다. 단순 접촉과 쉘 곡면은 체적 간섭에 포함하지 않습니다.',True));row=QHBoxLayout();root.addLayout(row,1);self.viewport=CADViewport();row.addWidget(self.viewport,1);self.list=QListWidget();self.list.setMaximumWidth(330);row.addWidget(self.list);self.viewport.load(result)
        names={m['id']:m['name'] for m in result['meshes']};self.highlights=[]
        from vtkmodules.vtkRenderingCore import vtkActor,vtkPolyDataMapper
        from .viewport import polydata
        for actors in self.viewport.actors.values():
            for actor in actors:actor.GetProperty().SetOpacity(.18)
        for pair in overlaps:
            self.list.addItem(f"{names[pair['a']]} ↔ {names[pair['b']]}\n{pair['volume']:.4f} mm³")
            mapper=vtkPolyDataMapper();mapper.SetInputData(polydata(pair['vertices'],pair['triangles']));actor=vtkActor();actor.SetMapper(mapper);actor.GetProperty().SetColor(1,.22,.18);actor.PickableOff();self.viewport.renderer.AddActor(actor);self.highlights.append(actor)
        self.list.currentRowChanged.connect(self.highlight);root.addWidget(button('닫기',self.accept));self.setMinimumSize(820,560);self.viewport.setMinimumSize(400,280);self.list.setMinimumWidth(200);self.resize(1050,740)
        if overlaps:self.list.setCurrentRow(0)
    def highlight(self,index):
        for i,actor in enumerate(self.highlights):actor.SetVisibility(i==index)
        self.viewport.window.Render()
    def done(self,result):self.viewport.shutdown();super().done(result)


class MeasurementDialog(QDialog):
    def __init__(self,parent,design):
        super().__init__(parent);self.setWindowTitle('길이 측정 · mm');self.resize(1040,740);v=QVBoxLayout(self);v.addWidget(label('꼭짓점 2개를 클릭하면 거리, 모서리를 클릭하면 곡선을 따른 길이를 표시합니다.'))
        self.mode=choice([('vertices','두 꼭짓점 사이 거리'),('edges','모서리 길이')]);v.addWidget(self.mode);row=QHBoxLayout();v.addLayout(row,1);self.viewport=CADViewport();row.addWidget(self.viewport,1);self.list=QListWidget();self.list.setMaximumWidth(275);row.addWidget(self.list)
        self.output=label('측정 대상을 선택하세요.');self.output.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);self.output.setStyleSheet('padding:12px;font-size:14px;color:#a8efdb;');v.addWidget(self.output);v.addWidget(button('닫기',self.accept));self.picks=[];self.vertices=[];self.edges=[]
        d=Design.model_validate(design)
        with KERNEL_LOCK:
            shapes=build(d);self.viewport.load(preview(d))
            for p,shape in zip(d.parts,shapes):
                for vertex in shape.Vertices():self.vertices.append(dict(name=p.name,point=list(vertex.Center().toTuple())))
                for ref in edge_records(shape):self.edges.append(dict(ref,name=p.name))
        self.viewport.edge_selected.connect(self.pick);self.list.currentRowChanged.connect(self.pick);self.mode.currentIndexChanged.connect(self.rebuild);self.rebuild();self.setMinimumSize(820,560);self.viewport.setMinimumSize(400,280);self.list.setMinimumWidth(200);self.resize(1040,740)
    def rebuild(self):
        self.picks=[];self.list.blockSignals(True);self.list.clear();vertices=self.mode.currentData()=='vertices';records=self.vertices if vertices else self.edges
        for i,r in enumerate(records):self.list.addItem(f"{i+1} · {r['name']}"+(f" · {r['length']:.3f} mm" if not vertices else ''))
        self.list.blockSignals(False);self.viewport.set_edge_candidates([dict(index=i,points=[r['point']] if vertices else r['points']) for i,r in enumerate(records)]);self.output.setText('꼭짓점 두 개를 선택하세요.' if vertices else '모서리를 선택하세요.')
    def pick(self,index):
        if index<0:return
        if self.mode.currentData()=='edges':
            r=self.edges[index];self.viewport.highlight_edges({index});self.output.setText(f"모서리 길이 {r['length']:.6f} mm · {r['curve']} · {r['name']}\nCAD 곡선을 따른 길이입니다.");return
        if len(self.picks)==2:self.picks=[]
        self.picks.append(index);self.viewport.highlight_edges(set(self.picks));a=np.array(self.vertices[self.picks[0]]['point'])
        if len(self.picks)==1:self.output.setText('첫 점: '+', '.join(f'{n:.4f}' for n in a)+' mm · 두 번째 점을 선택하세요.');return
        b=np.array(self.vertices[index]['point']);delta=b-a
        self.output.setText(f"거리 {np.linalg.norm(delta):.6f} mm\nΔX {delta[0]:.6f} mm  ·  ΔY {delta[1]:.6f} mm  ·  ΔZ {delta[2]:.6f} mm")
    def done(self,result):self.viewport.shutdown();super().done(result)


class HoleDialog(PreviewDialog):
    def __init__(self,parent,design,part_id,face):
        super().__init__(parent,'구멍 뚫기','선택 면의 중심을 원점으로 위치를 지정하세요. 미리보기의 같은 평면을 클릭해 중심을 옮길 수 있습니다.')
        self.base=deepcopy(design);self.part_id=part_id;self.face=deepcopy(face);self.feature_id='hole-'+uid();self.x=number(0,-1000,1000,' mm');self.y=number(0,-1000,1000,' mm');self.diameter=number(6,.02,2000,' mm');self.depth=number(10,.01,2000,' mm');self.through=QCheckBox('전체 관통');form=QFormLayout();self.controls.addLayout(form)
        for title,w in [('중심 X',self.x),('중심 Y',self.y),('직경',self.diameter),('깊이',self.depth)]:form.addRow(title,w);w.valueChanged.connect(self.schedule)
        self.style=choice([('plain','직선 구멍'),('counterbore','원통 자리파기 · Counterbore'),('countersink','접시머리 · Countersink')]);self.head_diameter=number(10,.02,2000,' mm');self.head_depth=number(3,.01,2000,' mm');self.head_angle=number(90,10,170,' °');form.addRow('구멍 유형',self.style)
        for title,w in [('머리 지름',self.head_diameter),('자리파기 깊이',self.head_depth),('접시머리 각도',self.head_angle)]:form.addRow(title,w);w.valueChanged.connect(self.schedule)
        def head_fields():
            for w,shown in [(self.head_diameter,self.style.currentData()!='plain'),(self.head_depth,self.style.currentData()=='counterbore'),(self.head_angle,self.style.currentData()=='countersink')]:w.setVisible(shown);form.labelForField(w).setVisible(shown)
            self.schedule()
        self.style.currentIndexChanged.connect(head_fields);head_fields()
        self.controls.addWidget(self.through);self.through.toggled.connect(lambda checked:self.depth.setEnabled(not checked));self.through.toggled.connect(self.schedule);self.controls.addWidget(label('원형 절삭 스케치와 참조 면, 지름, 깊이를 피처 기록으로 저장합니다. 이후 트리에서 구멍 피처를 더블클릭해 편집할 수 있습니다.',True));self.controls.addStretch()
        d=Design.model_validate(self.base);part=next(p for p in d.parts if p.id==part_id);self.rotation=transform_matrix(part.transform);self.position=np.array([part.transform.x,part.transform.y,part.transform.z]);self.normal=np.array(face['normal']);self.origin=np.array(face['origin']);self.u=np.array(face['x_direction']);self.v=np.cross(self.normal,self.u)
        with KERNEL_LOCK:
            shape=local_shape(d,part);box=shape.BoundingBox();self.through_depth=(box.xlen**2+box.ylen**2+box.zlen**2)**.5+.1
        self.viewport.point_selected.connect(self.center_clicked);self.schedule()
    def center_clicked(self,identifier,point):
        if identifier!=self.part_id:return
        relative=self.rotation.T@(np.array(point)-self.position)-self.origin
        if abs(relative@self.normal)>.05:return
        self.x.setValue(float(relative@self.u));self.y.setValue(float(relative@self.v))
    def candidate(self):
        raw=deepcopy(self.base);part=next(p for p in raw['parts'] if p['id']==self.part_id);face=self.face
        depth=self.through_depth if self.through.isChecked() else self.depth.value()
        if depth>2000:raise ValueError('현재 구멍 도구의 관통 깊이는 2000 mm 이하입니다.')
        g=Extrusion(sketch_mode='entities',entities=[dict(id='hole-circle',kind='circle',center={'x':self.x.value(),'y':self.y.value()},radius=self.diameter.value()/2)],thickness=depth)
        part['features'].append(dict(id=self.feature_id,name=f"구멍 Ø{self.diameter.value():g} · "+('관통' if self.through.isChecked() else f'{depth:g} mm'),face=face['index'],support_face_count=face['face_count'],support_feature=part['features'][-1]['id'] if part['features'] else 'base',origin=face['origin'],normal=face['normal'],x_direction=face['x_direction'],operation='cut',sketch=g.model_dump()))
        if face.get('reference'):part['features'][-1]['reference']=face['reference']
        if self.through.isChecked():part['features'][-1]['through_all']=True
        if self.style.currentData()!='plain':part['features'][-1].update(hole_finish=self.style.currentData(),head_diameter=self.head_diameter.value(),head_depth=self.head_depth.value(),head_angle=self.head_angle.value())
        return raw
