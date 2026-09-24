"""Direct 3D extrusion of saved profiles and existing extrusion features."""
from copy import deepcopy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget,QListWidgetItem,QAbstractItemView,QFormLayout,QCheckBox
from .workflows import PreviewDialog,choice
from .parameters import ExpressionField
from .widgets import label
from .geometry import uid,to_entities
from .saved_sketches import preview_sketches
from .interaction import ExtrusionHandle
from ..parameters import parameter_values,set_binding,binding_for
from ..models import Design,Part,SavedSketch
from ..kernel import KERNEL_LOCK
from ..associativity import edit_source
from ..sketch_frames import extrusion_transform


def extrusion_candidate(base,g,context,operation,part_id,feature_id):
    raw=deepcopy(base);g=deepcopy(g)
    if context.get('edit_base'):
        p=next(p for p in raw['parts'] if p['id']==context['part_id']);p['geometry']=g
        edit_source(raw,p.get('profile_sketch_id'),g)
        # The expression field owns this depth now, including a manual override.
        set_binding(raw,['parts',p['id'],'geometry','thickness'],'')
    elif context.get('feature_id'):
        p=next(p for p in raw['parts'] if p['id']==context['part_id']);f=next(f for f in p['features'] if f['id']==context['feature_id']);f['sketch']=g;f['operation']=operation
        edit_source(raw,f.get('sketch_id'),g)
    elif context.get('face'):
        p=next(p for p in raw['parts'] if p['id']==context['part_id']);face=context['face']
        p['features'].append(dict(id=feature_id,name='스케치 절삭' if operation=='cut' else '스케치 돌출',face=face['index'],support_face_count=face['face_count'],support_feature=context['support_feature'],origin=face['origin'],normal=face['normal'],x_direction=face['x_direction'],operation=operation,sketch=g))
        if context.get('sketch_id'):p['features'][-1]['sketch_id']=context['sketch_id']
        if face.get('reference'):p['features'][-1]['reference']=face['reference']
    else:
        transform=extrusion_transform(context)
        raw['parts'].append(Part(id=part_id,name='스케치 돌출 '+str(len(raw['parts'])+1),geometry=g,transform=transform).model_dump())
        if context.get('sketch_id'):raw['parts'][-1]['profile_sketch_id']=context['sketch_id']
    return raw


class ExtrudeDialog(PreviewDialog):
    def __init__(self,parent,design,g,context,profile=None):
        super().__init__(parent,'3D 돌출 / 절삭 · E','노란 화살표를 잡아 늘리거나 줄이세요. 깊이에 숫자 또는 변수 식을 입력할 수 있습니다. 여러 영역은 Ctrl 클릭으로 선택합니다.')
        self.base=deepcopy(design);self.g=to_entities(g);self.context=deepcopy(context);self.part_id=context.get('part_id') or 'part-'+uid();self.feature_id=context.get('feature_id') or 'feature-'+uid();self.region_data=None;self.handle=None
        self.selected_profiles=[profile] if profile is not None else g.get('profiles',[]) or [0]
        self.regions=QListWidget();self.regions.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);self.regions.setMaximumHeight(180);self.controls.addWidget(label('돌출할 스케치 영역'));self.controls.addWidget(self.regions)
        self.face_based=bool(context.get('face') or context.get('feature_id'))
        self.operation=choice([('add','바깥쪽으로 더하기'),('cut','안쪽으로 파내기')] if self.face_based else [('add','새 부품 · 정방향'),('reverse','새 부품 · 반대 방향')]);self.operation.setCurrentIndex(1 if context.get('operation')=='cut' or not self.face_based and g.get('direction',1)<0 else 0)
        root_expr=binding_for(design,['parts',self.part_id,'geometry','thickness']) if context.get('edit_base') else ''
        self.depth=ExpressionField(g['thickness'],.01,2000,variables=parameter_values(design.get('parameters',{})),expression=root_expr or g.get('thickness_expression',''));self.depth.setObjectName('extrudeDepth');form=QFormLayout();form.addRow('작업 / 방향',self.operation);form.addRow('깊이',self.depth);self.controls.addLayout(form);self.controls.addWidget(label('드래그는 숫자 치수로 전환합니다. 변수 연결을 유지하려면 식을 입력하세요.\n\n적용 전 실제 솔리드와 참조 면을 검사합니다. 잘못된 절삭은 적용하지 않습니다.',True));self.controls.addStretch()
        self.regions.itemSelectionChanged.connect(self.regions_changed);self.depth.valueChanged.connect(self.changed);self.operation.currentIndexChanged.connect(self.changed);self.viewport.profile_selected.connect(self.pick_profile);self.viewport.filter.setCurrentIndex(self.viewport.filter.findData('sketch'));self.schedule();self.resize(1150,780)
        self.extent=choice([('distance','한 방향'),('symmetric','대칭 · 입력 깊이가 전체 길이'),('two','양방향 · 별도 깊이')]+([('through','전체 관통 · 두께 변경 추적'),('face','평행한 면까지')] if self.face_based else []));self.extent.setCurrentIndex(self.extent.findData('symmetric' if g.get('symmetric') else 'two' if g.get('reverse_depth') else 'distance'))
        existing=next((f for p in design['parts'] for f in p['features'] if f['id']==context.get('feature_id')),None)
        self.end_face=existing.get('end_face') if existing else None
        if existing and existing.get('through_all'):self.extent.setCurrentIndex(self.extent.findData('through'))
        elif self.end_face:self.extent.setCurrentIndex(self.extent.findData('face'))
        self.back=ExpressionField(g.get('reverse_depth',0),0,2000,variables=parameter_values(design.get('parameters',{})));self.taper=ExpressionField(g.get('taper',0),-60,60,' °',variables=parameter_values(design.get('parameters',{})))
        self.thin=ExpressionField(g.get('thin_wall',0),0,2000,variables=parameter_values(design.get('parameters',{})));self.thin.valueChanged.connect(self.changed)
        form.addRow('범위',self.extent);form.addRow('반대쪽 깊이',self.back);form.addRow('테이퍼',self.taper);form.addRow('얇은 벽 · 0 = 채우기',self.thin)
        self.target_label=label('면까지: 3D에서 같은 부품의 목표 평면을 클릭하세요.',True);self.controls.insertWidget(self.controls.count()-1,self.target_label);self.viewport.face_selected.connect(self.end_picked)
        prefix=['parts',self.part_id,'features',self.feature_id,'sketch'] if self.face_based else ['parts',self.part_id,'geometry']
        for key,w in [('reverse_depth',self.back),('taper',self.taper),('thin_wall',self.thin)]:
            formula=binding_for(design,[*prefix,key])
            if formula:w.setExpression(formula)
        self.hole_style=choice([('plain','일반 절삭'),('counterbore','원통 자리파기'),('countersink','접시머리 구멍')]);self.hole_style.setCurrentIndex(self.hole_style.findData((existing or {}).get('hole_finish','plain')));self.hole_head=[]
        if self.face_based:
            form.addRow('원형 구멍 마감',self.hole_style);self.hole_style.currentIndexChanged.connect(self.changed)
            for key,title,default,minimum,maximum,suffix in [('head_diameter','머리 지름',10,.01,2000,' mm'),('head_depth','자리파기 깊이',3,.01,2000,' mm'),('head_angle','접시 각도',90,10,170,' °')]:
                w=ExpressionField((existing or {}).get(key,default),minimum,maximum,suffix,variables=parameter_values(design.get('parameters',{})));form.addRow(title,w);self.hole_head.append((key,w));w.valueChanged.connect(self.changed)
                expr=binding_for(design,['parts',self.part_id,'features',self.feature_id,key])
                if expr:w.setExpression(expr)
        self.extent.currentIndexChanged.connect(self.extent_changed);self.back.valueChanged.connect(self.changed);self.taper.valueChanged.connect(self.changed);self.extent_changed()
    def extent_changed(self,*args):
        extent=self.extent.currentData();self.back.setEnabled(extent=='two');self.depth.setEnabled(extent not in ('through','face'));self.target_label.setVisible(extent=='face');self.viewport.filter.setCurrentIndex(self.viewport.filter.findData('face' if extent=='face' else 'sketch'))
        if extent=='through':self.operation.setCurrentIndex(self.operation.findData('cut'))
        self.changed()
    def end_picked(self,identifier,face):
        if self.extent.currentData()!='face' or identifier!=self.part_id or not face or not face.get('planar'):return
        self.end_face=face.get('reference');self.target_label.setText('목표 면 '+str(face['index']+1));self.schedule()
    def sign(self):return -1 if self.operation.currentData() in ('cut','reverse') else 1
    def changed(self,*args):
        try:
            if self.handle:self.handle.update(self.depth.value()*self.sign())
        except ValueError:pass
        self.schedule()
    def dragged(self,signed):
        self.depth.blockSignals(True);self.operation.blockSignals(True)
        self.depth.setValue(abs(signed));self.operation.setCurrentIndex(0 if signed>=0 else 1)
        self.depth.blockSignals(False);self.operation.blockSignals(False);self.schedule()
    def regions_changed(self):
        self.selected_profiles=[i.data(Qt.ItemDataRole.UserRole) for i in self.regions.selectedItems()];self.schedule()
    def pick_profile(self,sid,index):
        if sid!='extrude-source':return
        self.regions.setCurrentRow(index);self.regions_changed()
    def candidate(self):
        if not self.selected_profiles:raise ValueError('돌출할 닫힌 영역을 하나 이상 선택하세요.')
        g=deepcopy(self.g);g['thickness']=self.depth.value();g['profiles']=self.selected_profiles;g['direction']=1 if self.face_based else self.sign()
        if self.depth.formula():g['thickness_expression']=self.depth.formula()
        else:g.pop('thickness_expression',None)
        g['symmetric']=self.extent.currentData()=='symmetric';g['reverse_depth']=self.back.value() if self.extent.currentData()=='two' else 0;g['taper']=self.taper.value();g['thin_wall']=self.thin.value()
        raw=extrusion_candidate(self.base,g,self.context,self.operation.currentData(),self.part_id,self.feature_id)
        if self.face_based:
            f=next(f for p in raw['parts'] for f in p['features'] if f['id']==self.feature_id);f['through_all']=self.extent.currentData()=='through';f.pop('end_face',None);f['hole_finish']=self.hole_style.currentData()
            for key,w in self.hole_head:
                f[key]=w.value();set_binding(raw,['parts',self.part_id,'features',self.feature_id,key],w.formula() if self.hole_style.currentData()!='plain' else '')
            if self.extent.currentData()=='face':
                if not self.end_face:raise ValueError('같은 부품의 평행한 목표 면을 선택하세요.')
                f['end_face']=deepcopy(self.end_face)
        prefix=['parts',self.part_id,'features',self.feature_id,'sketch'] if self.face_based else ['parts',self.part_id,'geometry']
        target=next(p for p in raw['parts'] if p['id']==self.part_id)
        geometry=next(f['sketch'] for f in target['features'] if f['id']==self.feature_id) if self.face_based else target['geometry']
        for key,w in [('reverse_depth',self.back),('taper',self.taper),('thin_wall',self.thin)]:
            geometry.setdefault(key,0);set_binding(raw,[*prefix,key],w.formula() if key!='reverse_depth' or self.extent.currentData()=='two' else '')
        return raw
    def compute(self,raw):
        with KERNEL_LOCK:
            d,result=super().compute(raw);part=next(p for p in d.parts if p.id==self.part_id)
            g=next(f.sketch for f in part.features if f.id==self.feature_id) if self.face_based else part.geometry
            ctx={k:deepcopy(v) for k,v in self.context.items() if k in ('plane','work_plane','title','part_id','support_feature','face','operation')}
            if not self.face_based and not self.context.get('edit_base'):ctx.pop('part_id',None)
            source=SavedSketch(id='extrude-source',name='돌출 원본',geometry=g,context=ctx)
            records=preview_sketches(d.model_copy(update={'sketches':[source]}));result['sketches']=records
            return d,result
    def present(self):
        super().present();source=self.result['sketches'][0];self.region_data=source
        self.regions.blockSignals(True);self.regions.clear()
        for region in source['regions']:
            item=QListWidgetItem(f"영역 {region['index']+1} · {region['area']:.2f} mm²");item.setData(Qt.ItemDataRole.UserRole,region['index']);self.regions.addItem(item);item.setSelected(region['index'] in self.selected_profiles)
        self.regions.blockSignals(False)
        selected=[r for r in source['regions'] if r['index'] in self.selected_profiles]
        drag=self.handle.drag if self.handle else None
        if self.handle:self.handle.close()
        if selected:
            self.handle=ExtrusionHandle(self.viewport,selected[0]['center'],source['normal'],[row for r in selected for row in r['outline']],self.dragged);self.handle.update(self.depth.value()*self.sign());self.handle.drag=drag
    def done(self,result):
        if self.handle:self.handle.close();self.handle=None
        super().done(result)
