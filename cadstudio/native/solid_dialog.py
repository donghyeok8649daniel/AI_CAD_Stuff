"""Native tools for feature modelling and linked sketch revolutions."""
from copy import deepcopy
from PySide6.QtCore import Qt,QThreadPool
from PySide6.QtWidgets import QFormLayout,QTabWidget,QListWidget,QListWidgetItem,QAbstractItemView,QCheckBox
from .workflows import PreviewDialog,choice
from .widgets import label,number,Worker
from .parameters import ExpressionField
from .geometry import uid
from .viewport import CADViewport
from ..models import Design,Part,RevolveGeometry,SolidFeature
from ..parameters import parameter_values,remove_bindings,set_binding,binding_for

OPERATIONS={'shell':'셸 · 속 비우기','draft':'구배','boolean':'몸체 합치기 / 빼기 / 교집합','split':'몸체 분할','mirror':'몸체 대칭','linear_pattern':'몸체 직사각형 패턴','circular_pattern':'몸체 원형 패턴'}


class SolidDialog(PreviewDialog):
    def __init__(self,parent,design,part_id,operation='shell',feature_id=None,face=None,insert_index=None):
        super().__init__(parent,'솔리드 도구','작업 선택 → 기준 면 / 치수 지정 → 미리보기 → 적용. 부품의 로컬 좌표를 사용합니다.')
        self.base=deepcopy(design);self.part_id=part_id;self.ready=False;self.refs={};self.initial_face=face
        part=next(p for p in self.base['parts'] if p['id']==part_id)
        self.existing=next((f for f in part['features'] if f['id']==feature_id),None);self.index=part['features'].index(self.existing) if self.existing else len(part['features']);self.feature_id=feature_id or 'solid-'+uid()
        if insert_index is not None and not self.existing:self.index=insert_index
        initial=SolidFeature.model_validate(self.existing) if self.existing else SolidFeature(id=self.feature_id,operation=operation,angle=3 if operation=='draft' else 360)
        split=self.viewport.parent();self.tabs=QTabWidget();split.replaceWidget(0,self.tabs);self.selector=CADViewport();self.selector.set_selection_mode('face');self.tabs.addTab(self.selector,'기준 형상 / 면 선택');self.tabs.addTab(self.viewport,'결과 미리보기');self.selector.face_selected.connect(self.pick_face)
        self.operation=choice(OPERATIONS.items());self.operation.setCurrentIndex(self.operation.findData(initial.operation));self.controls.addWidget(self.operation)
        self.faces=QListWidget();self.faces.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection);self.faces.setMaximumHeight(155);self.controls.addWidget(label('셸: 열어 둘 면 / 구배: 기울일 면'));self.controls.addWidget(self.faces)
        self.form=QFormLayout();self.controls.addLayout(self.form);self.rows={};self.fields={};variables=parameter_values(design.get('parameters',{}))
        def row(key,title,w):self.rows[key]=w;self.form.addRow(title,w);return w
        self.size=row('size','벽 두께',ExpressionField(abs(initial.size),.01,2000,variables=variables))
        self.angle=row('angle','각도',ExpressionField(initial.angle,-360,360,' °',variables=variables))
        for key,w in [('size',self.size),('angle',self.angle)]:
            expr=binding_for(design,['parts',part_id,'features',self.feature_id,key])
            if expr:w.setExpression(expr)
        self.tool=row('tool','도구 부품',choice([(p['id'],p['name']) for p in self.base['parts'] if p['id']!=part_id]));self.tool.setCurrentIndex(max(0,self.tool.findData(initial.tool_part_id)))
        self.boolean=row('boolean','몸체 연산',choice([('union','합치기'),('cut','빼기'),('intersect','교집합')]));self.boolean.setCurrentIndex(self.boolean.findData(initial.boolean_mode))
        self.origin=[];self.direction=[];self.spacing=[]
        for key,title,values,lo,hi,suffix in [('origin','기준점',initial.origin,-5000,5000,' mm'),('direction','방향',initial.direction,-1,1,''),('spacing','간격',initial.spacing,-5000,5000,' mm')]:
            group=getattr(self,key)
            for axis,v in zip('XYZ',values):group.append(row(key+axis,title+' '+axis,number(v,lo,hi,suffix)))
        self.count=row('count','개수 / X',number(initial.count,2,64,' 개',0));self.count_y=row('count_y','Y 개수',number(initial.count_y,1,64,' 개',0))
        self.side=row('side','분할 결과',choice([('all','양쪽 유지'),('positive','기준 방향 쪽'),('negative','기준 방향 반대쪽')]));self.side.setCurrentIndex(self.side.findData(initial.keep_side))
        self.keep=QCheckBox('대칭 전 원본 몸체 유지');self.keep.setChecked(initial.keep_original);self.controls.addWidget(self.keep)
        self.controls.addWidget(label('몸체 연산의 도구 부품은 참조로 유지됩니다. 브라우저에서 숨길 수 있습니다. 패턴은 같은 부품 안의 여러 몸체입니다.',True));self.controls.addStretch()
        self.operation.currentIndexChanged.connect(self.changed);self.faces.itemSelectionChanged.connect(self.changed);self.keep.toggled.connect(self.changed)
        for w in self.rows.values():
            (w.currentIndexChanged if hasattr(w,'currentIndexChanged') else w.valueChanged).connect(self.changed)
        before=deepcopy(self.base);p=next(p for p in before['parts'] if p['id']==part_id);remove_bindings(before,*[['parts',part_id,'features',f['id']] for f in p['features'][self.index:]]);p['features']=p['features'][:self.index]
        def prepare():
            from ..kernel import local_shape
            from ..topology import resolve_face
            checked,result=self.compute(before);selected=set();unresolved=False
            if self.existing and self.existing['faces']:
                shape=local_shape(checked,next(p for p in checked.parts if p.id==self.part_id))
                for ref in self.existing['faces']:
                    try:selected.add(resolve_face(shape,ref)[0])
                    except ValueError:unresolved=True
                if unresolved:selected.clear()
            elif self.initial_face:selected.add(self.initial_face['index'])
            return checked,result,selected,unresolved
        self.running=True;self.worker=Worker(prepare);self.worker.signals.done.connect(self.loaded);self.worker.signals.failed.connect(self.load_failed);QThreadPool.globalInstance().start(self.worker);self.update_fields()

    def loaded(self,result):
        self.running=False
        if not self.alive:return
        _,r,selected,unresolved=result;self.selector.load(r);mesh=next(m for m in r['meshes'] if m['id']==self.part_id)
        self.faces.blockSignals(True)
        for f in mesh['faces']:
            self.refs[f['index']]=f['reference'];item=QListWidgetItem(f"면 {f['index']+1} · {f['reference']['surface']}");item.setData(Qt.ItemDataRole.UserRole,f['index']);self.faces.addItem(item);item.setSelected(f['index'] in selected)
        self.faces.blockSignals(False);self.ready=True;self.changed()
        if unresolved:self.status.setText('기준 형상이 바뀌었습니다. 적용할 면을 다시 선택하세요.')

    def load_failed(self,message):
        self.running=False
        if self.alive:self.failed(message)

    def pick_face(self,part_id,face):
        if not face or part_id!=self.part_id or not self.ready:return
        for i in range(self.faces.count()):
            item=self.faces.item(i)
            if item.data(Qt.ItemDataRole.UserRole)==face['index']:item.setSelected(not item.isSelected());self.faces.scrollToItem(item);break

    def update_fields(self):
        op=self.operation.currentData();self.faces.setVisible(op in ('shell','draft'));self.keep.setVisible(op=='mirror')
        visible={'shell':{'size'},'draft':{'angle','origin','direction'},'boolean':{'tool','boolean'},'split':{'origin','direction','side'},'mirror':{'origin','direction'},'linear_pattern':{'count','count_y','spacing'},'circular_pattern':{'count','angle','origin','direction'}}[op]
        for key,w in self.rows.items():
            show=key.rstrip('XYZ') in visible;w.setVisible(show);self.form.labelForField(w).setVisible(show)

    def changed(self,*args):
        self.update_fields()
        if self.ready:self.schedule()

    def candidate(self):
        if not self.ready:raise ValueError('기준 형상 준비 중입니다.')
        raw=deepcopy(self.base);part=next(p for p in raw['parts'] if p['id']==self.part_id);operation=self.operation.currentData()
        f=SolidFeature(id=self.feature_id,name=OPERATIONS[operation],operation=operation,faces=[self.refs[i.data(Qt.ItemDataRole.UserRole)] for i in self.faces.selectedItems()],size=self.size.value(),angle=self.angle.value(),origin=[w.value() for w in self.origin],direction=[w.value() for w in self.direction],spacing=[w.value() for w in self.spacing],count=int(self.count.value()),count_y=int(self.count_y.value()),tool_part_id=self.tool.currentData() or '',boolean_mode=self.boolean.currentData(),keep_side=self.side.currentData(),keep_original=self.keep.isChecked(),support_feature=part['features'][self.index-1]['id'] if self.index else 'base')
        if self.existing:
            f.suppressed=self.existing.get('suppressed',False)
            part['features'][self.index]=f.model_dump()
        else:part['features'].insert(self.index,f.model_dump())
        previous='base'
        for feature in part['features']:feature['support_feature']=previous;previous=feature['id']
        for key,w in [('size',self.size),('angle',self.angle)]:set_binding(raw,['parts',self.part_id,'features',self.feature_id,key],w.formula())
        return raw

    def done(self,result):
        self.selector.shutdown();super().done(result)


class RevolveDialog(PreviewDialog):
    def __init__(self,parent,design,part_id=None):
        from .modelling import SectionEditor
        from ..models import ModelSection,Extrusion
        super().__init__(parent,'회전 · Revolve','단면 스케치와 회전축을 선택하세요. 저장 스케치와 연결하여 치수 변경을 반영합니다.')
        self.base=Design.model_validate(design);self.part_id=part_id or 'part-'+uid();p=next((p for p in self.base.parts if p.id==part_id),None)
        g=p.geometry if p else RevolveGeometry(profile=ModelSection(sketch=Extrusion(points=[dict(x=x,y=y) for x,y in [(5,0),(15,0),(15,20),(5,20)]])))
        self.profile=SectionEditor(self.base,g.profile);self.controls.addWidget(self.profile);self.profile.changed.connect(self.schedule);form=QFormLayout();self.controls.addLayout(form)
        self.angle=number(g.angle,.01,360,' °');form.addRow('회전 각도',self.angle);self.angle.valueChanged.connect(self.schedule);self.origin=[];self.direction=[]
        for group,title,values,lo,hi,suffix in [(self.origin,'축 원점',g.axis_start,-5000,5000,' mm'),(self.direction,'축 방향',g.axis_direction,-1,1,'')]:
            for axis,value in zip('XYZ',values):
                w=number(value,lo,hi,suffix);form.addRow(title+' '+axis,w);group.append(w);w.valueChanged.connect(self.schedule)
        self.controls.addStretch();self.schedule()

    def candidate(self):
        raw=self.base.model_dump();g=RevolveGeometry(profile=self.profile.value(),angle=self.angle.value(),axis_start=[w.value() for w in self.origin],axis_direction=[w.value() for w in self.direction]);p=next((p for p in raw['parts'] if p['id']==self.part_id),None)
        if p:p['geometry']=g.model_dump()
        else:raw['parts'].append(Part(id=self.part_id,name='회전 부품',geometry=g).model_dump())
        return raw
