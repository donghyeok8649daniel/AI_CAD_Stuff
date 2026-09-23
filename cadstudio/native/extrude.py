"""Direct 3D extrusion of saved profiles and existing extrusion features."""
from copy import deepcopy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget,QListWidgetItem,QAbstractItemView,QFormLayout
from .workflows import PreviewDialog,choice
from .parameters import ExpressionField
from .widgets import label
from .geometry import uid,to_entities
from .saved_sketches import preview_sketches
from .interaction import ExtrusionHandle
from ..parameters import parameter_values,set_binding,binding_for
from ..models import Design,Part,SavedSketch
from ..kernel import KERNEL_LOCK


def extrusion_candidate(base,g,context,operation,part_id,feature_id):
    raw=deepcopy(base);g=deepcopy(g)
    if context.get('edit_base'):
        p=next(p for p in raw['parts'] if p['id']==context['part_id']);p['geometry']=g
        # The expression field owns this depth now, including a manual override.
        set_binding(raw,['parts',p['id'],'geometry','thickness'],'')
    elif context.get('feature_id'):
        p=next(p for p in raw['parts'] if p['id']==context['part_id']);f=next(f for f in p['features'] if f['id']==context['feature_id']);f['sketch']=g;f['operation']=operation
    elif context.get('face'):
        p=next(p for p in raw['parts'] if p['id']==context['part_id']);face=context['face']
        p['features'].append(dict(id=feature_id,name='스케치 절삭' if operation=='cut' else '스케치 돌출',face=face['index'],support_face_count=face['face_count'],support_feature=context['support_feature'],origin=face['origin'],normal=face['normal'],x_direction=face['x_direction'],operation=operation,sketch=g))
    else:
        plane=context.get('plane','XY');transform={'rx':90} if plane=='XZ' else {'rx':90,'rz':90} if plane=='YZ' else {}
        raw['parts'].append(Part(id=part_id,name='스케치 돌출 '+str(len(raw['parts'])+1),geometry=g,transform=transform).model_dump())
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
        return extrusion_candidate(self.base,g,self.context,self.operation.currentData(),self.part_id,self.feature_id)
    def compute(self,raw):
        with KERNEL_LOCK:
            d,result=super().compute(raw);part=next(p for p in d.parts if p.id==self.part_id)
            g=next(f.sketch for f in part.features if f.id==self.feature_id) if self.face_based else part.geometry
            ctx={k:deepcopy(v) for k,v in self.context.items() if k in ('plane','title','part_id','support_feature','face','operation')}
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
