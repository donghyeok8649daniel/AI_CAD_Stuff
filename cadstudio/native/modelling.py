"""Native editors for sketch-driven sweeps, lofts and edge finishing."""
from copy import deepcopy
import numpy as np
from scipy.spatial.transform import Rotation
from PySide6.QtCore import Signal,Qt
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QCheckBox,QTabWidget,QTableWidget,QTableWidgetItem,QListWidget,QListWidgetItem)
from .widgets import number,label,button
from .workflows import PreviewDialog,choice
from .viewport import CADViewport
from .geometry import uid
from ..models import (Design,Part,Extrusion,ModelFrame,ModelSection,SweepGeometry,LoftGeometry,SweepPath,circle_profile)
from ..advanced_geometry import section_from_saved,edge_records
from ..kernel import local_shape,preview,KERNEL_LOCK
from ..constraints import transform_matrix,anchors


class SectionEditor(QWidget):
    changed=Signal()
    def __init__(self,design,section):
        super().__init__();self.design=design;self.initial=section.model_copy(deep=True)
        v=QVBoxLayout(self);v.setContentsMargins(0,0,0,0);form=QFormLayout();v.addLayout(form)
        self.source=choice([('#circle','원형 단면'),('#rectangle','사각 단면'),('#embedded','기존 단면'),*[(s.id,'스케치 · '+s.name) for s in design.sketches]])
        form.addRow('단면',self.source)
        g=section.sketch;circle=next((e for e in g.entities if e.kind=='circle'),None)
        self.radius=number(circle.radius if circle else 10,.01,1000,' mm');form.addRow('반지름',self.radius)
        self.width=number(30,.01,2000,' mm');self.height=number(20,.01,2000,' mm');form.addRow('폭',self.width);form.addRow('높이',self.height)
        frame=section.frame;rotation=np.column_stack((frame.x_direction,np.cross(frame.normal,frame.x_direction),frame.normal));angles=Rotation.from_matrix(rotation).as_euler('xyz',degrees=True)
        self.position=[number(value,-5000,5000,' mm') for value in frame.origin]
        self.angles=[number(value,-360,360,' °') for value in angles]
        for title,w in zip(('위치 X','위치 Y','위치 Z'),self.position):form.addRow(title,w)
        for title,w in zip(('회전 X','회전 Y','회전 Z'),self.angles):form.addRow(title,w)
        self.source.setCurrentIndex(self.source.findData(section.sketch_id or ('#circle' if circle and len(g.entities)==1 else '#embedded')))
        self.source.currentIndexChanged.connect(self.source_changed)
        for w in [self.radius,self.width,self.height,*self.position,*self.angles]:w.valueChanged.connect(self.changed)
        self.form=form;self.update_fields()
        v.addWidget(label('저장한 스케치의 치수가 바뀌면 단면도 갱신됩니다. 위치·회전은 이 피처의 배치 값입니다.',True))
    def update_fields(self):
        for w in (self.radius,self.width,self.height):
            shown=(w is self.radius and self.source.currentData()=='#circle') or (w is not self.radius and self.source.currentData()=='#rectangle')
            w.setVisible(shown);self.form.labelForField(w).setVisible(shown)
    def source_changed(self):
        saved=next((s for s in self.design.sketches if s.id==self.source.currentData()),None)
        if saved:
            section=section_from_saved(self.design,saved);self.initial=section
            frame=section.frame;matrix=np.column_stack((frame.x_direction,np.cross(frame.normal,frame.x_direction),frame.normal));angles=Rotation.from_matrix(matrix).as_euler('xyz',degrees=True)
            for w,value in zip([*self.position,*self.angles],[*frame.origin,*angles]):w.blockSignals(True);w.setValue(value);w.blockSignals(False)
        self.update_fields();self.changed.emit()
    def value(self):
        selected=self.source.currentData();saved=next((s for s in self.design.sketches if s.id==selected),None)
        if saved:g=saved.geometry.model_copy(deep=True)
        elif selected=='#circle':g=circle_profile(self.radius.value())
        elif selected=='#rectangle':
            a,b=self.width.value()/2,self.height.value()/2;g=Extrusion(points=[dict(x=x,y=y) for x,y in [(-a,-b),(a,-b),(a,b),(-a,b)]])
        else:g=self.initial.sketch.model_copy(deep=True)
        rotation=Rotation.from_euler('xyz',[w.value() for w in self.angles],degrees=True).as_matrix()
        return ModelSection(sketch=g,sketch_id=saved.id if saved else '',frame=ModelFrame(origin=[w.value() for w in self.position],normal=rotation[:,2].tolist(),x_direction=rotation[:,0].tolist()))


class ModellingDialog(PreviewDialog):
    def __init__(self,parent,design=None,kind='sweep',surface=False,part_id=None):
        self.kind=kind
        super().__init__(parent,('스윕' if kind=='sweep' else '로프트')+' · 형상 설계','단면과 경로를 선택하고 실제 CAD 형상을 확인하세요. 입력·참조 스케치·설정은 작업 기록에 남습니다.')
        self.base=Design.model_validate(design) if design else Design()
        self.original=next((p for p in self.base.parts if p.id==part_id),None)
        g=self.original.geometry if self.original else (SweepGeometry(solid=not surface) if kind=='sweep' else LoftGeometry(solid=not surface))
        self.identifier=part_id or 'part-'+uid();self.name=QLineEdit(self.original.name if self.original else ('곡면 ' if surface else '')+('스윕' if kind=='sweep' else '로프트'));self.controls.addWidget(self.name)
        self.solid=QCheckBox('두께가 있는 솔리드로 생성');self.solid.setChecked(g.solid);self.controls.addWidget(self.solid)
        if kind=='sweep':
            self.profile=SectionEditor(self.base,g.profile);self.controls.addWidget(self.profile);self.profile.changed.connect(self.schedule)
            self.path_source=choice([('#points','XYZ 점으로 경로 작성'),*[(s.id,'경로 · '+s.name) for s in self.base.sketches]])
            self.path_source.setCurrentIndex(max(0,self.path_source.findData(g.path.sketch_id or '#points')));self.controls.addWidget(self.path_source)
            self.points=QTableWidget(len(g.path.points),3);self.points.setHorizontalHeaderLabels(['X mm','Y mm','Z mm']);self.points.horizontalHeader().setStretchLastSection(True);self.points.setColumnWidth(0,75);self.points.setColumnWidth(1,75);self.points.setMinimumHeight(150)
            for row,p in enumerate(g.path.points):
                for column,value in enumerate(p):self.points.setItem(row,column,QTableWidgetItem(f'{value:g}'))
            self.controls.addWidget(self.points);row=QHBoxLayout();row.addWidget(button('+ 경로 점',self.add_point));row.addWidget(button('점 삭제',self.remove_point));self.controls.addLayout(row)
            self.smooth=QCheckBox('경로 점을 부드러운 곡선으로 연결');self.smooth.setChecked(g.path.smooth);self.controls.addWidget(self.smooth)
            self.align=QCheckBox('단면을 경로 시작과 접선에 맞춤');self.align.setChecked(g.align_profile);self.controls.addWidget(self.align)
            self.frenet=QCheckBox('Frenet 프레임으로 단면 회전');self.frenet.setChecked(g.frenet);self.controls.addWidget(self.frenet)
            self.path_source.currentIndexChanged.connect(self.path_changed);self.points.itemChanged.connect(self.schedule)
            for w in (self.smooth,self.align,self.frenet):w.toggled.connect(self.schedule)
            self.path_changed()
        else:
            self.sections=QTabWidget();self.controls.addWidget(self.sections)
            for section in g.sections:self.add_section(section)
            row=QHBoxLayout();row.addWidget(button('+ 단면',lambda:self.add_section()));row.addWidget(button('단면 삭제',self.remove_section));self.controls.addLayout(row)
            self.ruled=QCheckBox('단면 사이를 직선으로 연결');self.ruled.setChecked(g.ruled);self.controls.addWidget(self.ruled);self.ruled.toggled.connect(self.schedule)
            self.controls.addWidget(label('탭 순서대로 단면을 연결합니다. 곡면 모드에서는 열린 스케치도 사용할 수 있습니다.',True))
        self.controls.addStretch();self.solid.toggled.connect(self.schedule);self.name.textChanged.connect(self.schedule);self.schedule()
    def path_changed(self):
        manual=self.path_source.currentData()=='#points';self.points.setEnabled(manual);self.smooth.setEnabled(manual);self.schedule()
    def add_point(self):
        if self.points.rowCount()>=64:return
        row=self.points.rowCount();self.points.insertRow(row)
        for col in range(3):self.points.setItem(row,col,QTableWidgetItem(str(0 if col<2 else row*30)))
        self.schedule()
    def remove_point(self):
        if self.points.rowCount()>2:self.points.removeRow(max(0,self.points.currentRow()));self.schedule()
    def add_section(self,section=None):
        if self.sections.count()>=8:return
        if section is None:
            section=self.sections.widget(self.sections.count()-1).value();section.frame.origin[2]+=30
        editor=SectionEditor(self.base,section);editor.changed.connect(self.schedule);self.sections.addTab(editor,str(self.sections.count()+1));self.sections.setCurrentWidget(editor);self.schedule()
    def remove_section(self):
        if self.sections.count()<=2:return
        index=self.sections.currentIndex();page=self.sections.widget(index);self.sections.removeTab(index);page.deleteLater()
        for i in range(self.sections.count()):self.sections.setTabText(i,str(i+1))
        self.schedule()
    def candidate(self):
        if self.kind=='sweep':
            saved=next((s for s in self.base.sketches if s.id==self.path_source.currentData()),None)
            if saved:
                section=section_from_saved(self.base,saved);path=SweepPath(sketch=section.sketch,frame=section.frame,sketch_id=saved.id)
            else:
                try:points=[[float(self.points.item(row,column).text()) for column in range(3)] for row in range(self.points.rowCount())]
                except (ValueError,AttributeError):raise ValueError('경로의 XYZ 칸에 숫자를 입력하세요.') from None
                path=SweepPath(points=points,smooth=self.smooth.isChecked())
            geometry=SweepGeometry(profile=self.profile.value(),path=path,solid=self.solid.isChecked(),align_profile=self.align.isChecked(),frenet=self.frenet.isChecked())
        else:
            geometry=LoftGeometry(sections=[self.sections.widget(i).value() for i in range(self.sections.count())],solid=self.solid.isChecked(),ruled=self.ruled.isChecked())
        raw=self.base.model_dump();part=next((p for p in raw['parts'] if p['id']==self.identifier),None)
        if part is None:
            part=Part(id=self.identifier,name=self.name.text().strip() or self.kind,geometry=geometry).model_dump();raw['parts'].append(part)
        else:part['geometry']=geometry.model_dump();part['name']=self.name.text().strip() or self.kind
        return raw


class EdgeFinishDialog(PreviewDialog):
    def __init__(self,parent,design,part_id,feature_id=None):
        super().__init__(parent,'3D 필렛 / 모따기','선택 탭에서 모서리를 클릭하거나 목록에서 고르세요. 결과 탭에서 미리 보고 적용합니다.')
        self.base=deepcopy(design);self.part_id=part_id;part=next(p for p in self.base['parts'] if p['id']==part_id)
        existing=next((f for f in part['features'] if f['id']==feature_id),None);self.index=next((i for i,f in enumerate(part['features']) if f['id']==feature_id),len(part['features']));self.feature_id=feature_id or 'edge-'+uid()
        before=deepcopy(self.base);p=next(p for p in before['parts'] if p['id']==part_id);p['features']=p['features'][:self.index]
        design=Design.model_validate(before)
        with KERNEL_LOCK:
            shape=local_shape(design,next(p for p in design.parts if p.id==part_id));self.refs=edge_records(shape);original=preview(design)
        splitter=self.viewport.parent();self.tabs=QTabWidget();splitter.replaceWidget(0,self.tabs);self.selector=CADViewport();self.tabs.addTab(self.selector,'모서리 선택');self.tabs.addTab(self.viewport,'결과 미리보기');self.selector.load(original)
        transformed=[];p=next(p for p in design.parts if p.id==part_id);rotation=transform_matrix(p.transform);position=np.array([p.transform.x,p.transform.y,p.transform.z])
        for ref in self.refs:
            row=deepcopy(ref);row['points']=[(rotation@point+position).tolist() for point in np.array(ref['points'])];transformed.append(row)
        self.selector.set_edge_candidates(transformed)
        form=QFormLayout();self.kind=choice([('fillet','3D 필렛'),('chamfer','모따기')]);self.size=number(existing['size'] if existing else 2,.01,2000,' mm');form.addRow('종류',self.kind);form.addRow('반경 / 거리',self.size);self.controls.addLayout(form)
        if existing:self.kind.setCurrentIndex(self.kind.findData(existing['kind']))
        self.edges=QListWidget();self.edges.setMinimumHeight(280);self.controls.addWidget(self.edges)
        from ..topology import resolve_edge
        selected={resolve_edge(shape,r)[0] if r.get('relative_center') else r['index'] for r in existing['edges']} if existing else set()
        for ref in self.refs:
            item=QListWidgetItem(f"{ref['index']+1} · {ref['curve']} · {ref['length']:.2f} mm");item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(Qt.CheckState.Checked if ref['index'] in selected else Qt.CheckState.Unchecked);self.edges.addItem(item)
        self.selector.edge_selected.connect(self.toggle_edge);self.edges.itemChanged.connect(self.selection_changed);self.kind.currentIndexChanged.connect(self.schedule);self.size.valueChanged.connect(self.schedule);self.controls.addStretch();self.selection_changed()
    def toggle_edge(self,index):
        item=self.edges.item(index);item.setCheckState(Qt.CheckState.Unchecked if item.checkState()==Qt.CheckState.Checked else Qt.CheckState.Checked)
    def selection_changed(self,*args):
        selected={i for i in range(self.edges.count()) if self.edges.item(i).checkState()==Qt.CheckState.Checked};self.selector.highlight_edges(selected);self.schedule()
    def candidate(self):
        refs=[{k:v for k,v in self.refs[i].items() if k!='points'} for i in range(self.edges.count()) if self.edges.item(i).checkState()==Qt.CheckState.Checked]
        if not refs:raise ValueError('처리할 모서리를 하나 이상 선택하세요.')
        raw=deepcopy(self.base);p=next(p for p in raw['parts'] if p['id']==self.part_id);feature=dict(id=self.feature_id,name='3D 필렛' if self.kind.currentData()=='fillet' else '모따기',kind=self.kind.currentData(),size=self.size.value(),edges=refs,support_edge_count=len(self.refs),support_feature=p['features'][self.index-1]['id'] if self.index else 'base')
        if self.index<len(p['features']):p['features'][self.index]=feature
        else:p['features'].append(feature)
        return raw
    def done(self,result):
        self.selector.shutdown();super().done(result)


class ClosureDialog(PreviewDialog):
    def __init__(self,parent,design,identifier=None):
        super().__init__(parent,'폐루프 조립','두 기준점을 연결하고 자동으로 풀 수동 관절을 고르세요. 다른 관절은 구동 값으로 유지합니다.')
        self.base=deepcopy(design);self.identifier=identifier or 'loop-'+uid();existing=next((c for c in self.base.get('loops',[]) if c['id']==identifier),None)
        parts=[(p['id'],p['name']) for p in design['parts']];form=QFormLayout();self.controls.addLayout(form)
        self.parent_part=choice(parts);self.child_part=choice(parts);self.parent_anchor=choice([]);self.child_anchor=choice([])
        form.addRow('기준 부품',self.parent_part);form.addRow('기준점',self.parent_anchor);form.addRow('연결 부품',self.child_part);form.addRow('연결점',self.child_anchor)
        self.planar=QCheckBox('XY 평면의 회전 핀 · 축 높이 차이는 허용');self.planar.setChecked(existing['planar'] if existing else True);self.controls.addWidget(self.planar)
        self.offset=[number(v,-5000,5000,' mm') for v in (existing['offset'] if existing else [0,0,0])]
        for name,w in zip(('오프셋 X','오프셋 Y','오프셋 Z'),self.offset):form.addRow(name,w);w.valueChanged.connect(self.schedule)
        self.controls.addWidget(label('수동 관절 · 자동 계산할 관절만 선택'));self.passive=QListWidget();self.controls.addWidget(self.passive)
        for mate in design['mates']:
            if mate['kind'] not in ('revolute','slider'):continue
            item=QListWidgetItem(f"{mate['id']} · {mate['parent']} → {mate['child']}");item.setData(Qt.ItemDataRole.UserRole,mate['id']);item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(Qt.CheckState.Checked if existing and mate['id'] in existing['passive_joints'] else Qt.CheckState.Unchecked);self.passive.addItem(item)
        if existing:
            self.parent_part.setCurrentIndex(self.parent_part.findData(existing['parent']));self.child_part.setCurrentIndex(self.child_part.findData(existing['child']))
        elif len(parts)>1:self.child_part.setCurrentIndex(1)
        self.refresh_anchors()
        if existing:
            self.parent_anchor.setCurrentIndex(self.parent_anchor.findData(existing['parent_anchor']));self.child_anchor.setCurrentIndex(self.child_anchor.findData(existing['child_anchor']))
        for w in (self.parent_part,self.child_part):w.currentIndexChanged.connect(self.refresh_anchors)
        for w in (self.parent_anchor,self.child_anchor):w.currentIndexChanged.connect(self.schedule)
        self.passive.itemChanged.connect(self.schedule);self.planar.toggled.connect(self.schedule);self.controls.addWidget(label('평면 모드는 XY 위치 2개를, 공간 점 연결은 XYZ 위치 3개를 맞춥니다. 구속을 만족할 수 없는 자세는 적용하지 않습니다.',True));self.controls.addStretch();self.schedule()
    def refresh_anchors(self):
        for part_box,anchor_box in ((self.parent_part,self.parent_anchor),(self.child_part,self.child_anchor)):
            part=next(p for p in self.base['parts'] if p['id']==part_box.currentData());old=anchor_box.currentData();anchor_box.blockSignals(True);anchor_box.clear()
            for name in anchors(Part.model_validate(part).geometry):anchor_box.addItem(name,name)
            anchor_box.setCurrentIndex(max(0,anchor_box.findData(old)));anchor_box.blockSignals(False)
        self.schedule()
    def candidate(self):
        selected=[self.passive.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.passive.count()) if self.passive.item(i).checkState()==Qt.CheckState.Checked]
        if not selected:raise ValueError('자동 계산할 수동 관절을 선택하세요.')
        raw=deepcopy(self.base);loop=dict(id=self.identifier,parent=self.parent_part.currentData(),child=self.child_part.currentData(),parent_anchor=self.parent_anchor.currentData(),child_anchor=self.child_anchor.currentData(),passive_joints=selected,planar=self.planar.isChecked(),offset=[w.value() for w in self.offset])
        raw['loops']=[c for c in raw.get('loops',[]) if c['id']!=self.identifier]+[loop];return raw
    def present(self):
        super().present();stats=self.result['stats']['assembly_constraints'];self.status.setText(f"폐루프 닫힘 오차 {stats['closure_error_mm']:.3g} mm · 자유도 {stats['dof']} · 자세 적용 가능")
