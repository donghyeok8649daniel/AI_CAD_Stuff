"""Cylinder picking and asynchronous, editable helical thread previews."""
from copy import deepcopy
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QFormLayout,QCheckBox,QTabWidget
from .workflows import PreviewDialog,choice
from .widgets import label,Worker
from .parameters import ExpressionField
from .viewport import CADViewport
from .geometry import uid
from ..models import Design,ThreadFeature,CylinderReference
from ..kernel import KERNEL_LOCK,preview
from ..threads import METRIC_PITCHES,DEPTH_FACTOR,suggested_size,thread_title
from ..parameters import parameter_values,binding_for,set_binding,remove_bindings


class ThreadDialog(PreviewDialog):
    def __init__(self,parent,design,part_id,feature_id=None,face_index=None):
        super().__init__(parent,'나사산 · 수나사 / 암나사',
            '원통 면 선택 → 피치·길이 설정 → 결과 확인. 축 바깥은 수나사, 구멍 안쪽은 암나사로 인식합니다.')
        self.base=deepcopy(design);self.part_id=part_id;self.ready=False;self.refs={};self.face_index=face_index
        part=next(p for p in self.base['parts'] if p['id']==part_id)
        self.existing=next((f for f in part['features'] if f['id']==feature_id),None)
        self.index=next((i for i,f in enumerate(part['features']) if f['id']==feature_id),len(part['features']))
        self.feature_id=feature_id or 'thread-'+uid()
        split=self.viewport.parent();self.tabs=QTabWidget();split.replaceWidget(0,self.tabs)
        self.selector=CADViewport();self.selector.set_selection_mode('face')
        self.tabs.addTab(self.selector,'원통 면 선택');self.tabs.addTab(self.viewport,'나사산 미리보기')
        self.selector.face_selected.connect(self.pick_face)
        form=QFormLayout();self.controls.addLayout(form)
        self.faces=choice([]);form.addRow('원통 면',self.faces)
        self.presets=choice([('', '사용자 정의'),*[(f'{d}:{p}',f'M{d:g} × {p:g}') for d,p in METRIC_PITCHES]])
        form.addRow('미터 나사 치수',self.presets)
        values=parameter_values(self.base.get('parameters',{}));self.fields={}
        for key,title,value,lo,hi in [('diameter','호칭 지름',10,.1,2000),('pitch','피치',1.5,.25,12),('length','나사 길이',10,.01,2000),('offset','시작 간격',0,0,2000),('clearance','반경 여유',0,0,1)]:
            w=ExpressionField(value,lo,hi,variables=values);self.fields[key]=w;form.addRow(title,w);w.valueChanged.connect(self.changed)
        self.hand=choice([('right','우나사'),('left','좌나사')]);form.addRow('회전 방향',self.hand)
        self.reverse=QCheckBox('반대쪽 끝에서 시작');self.controls.addWidget(self.reverse)
        self.details=label('',True);self.controls.addWidget(self.details)
        self.controls.addWidget(label('60° 평면 절단 프로파일의 실제 나사 형상입니다. STEP·STL에 포함됩니다.\n\n반경 여유: 수나사는 작게, 암나사는 크게 만듭니다. 규격 공차 등급·가공 인증 값은 아닙니다.\n\n1~32 회전까지 지원합니다. 구멍 입구 모따기는 나사산 전에 적용하세요.',True));self.controls.addStretch()
        self.faces.currentIndexChanged.connect(self.face_changed);self.presets.currentIndexChanged.connect(self.preset_changed)
        self.hand.currentIndexChanged.connect(self.changed);self.reverse.toggled.connect(self.changed)
        before=deepcopy(self.base);p=next(p for p in before['parts'] if p['id']==part_id)
        remove_bindings(before,*[['parts',part_id,'features',f['id']] for f in p['features'][self.index:]])
        p['features']=p['features'][:self.index]
        self.running=True;self.status.setText('기준 원통 면을 찾는 중…');self.worker=Worker(lambda:self.compute(before))
        self.worker.signals.done.connect(self.loaded);self.worker.signals.failed.connect(self.load_failed)
        QThreadPool.globalInstance().start(self.worker)

    def load_failed(self,message):
        self.running=False
        if self.alive:self.failed(message)

    def loaded(self,result):
        self.running=False
        if not self.alive:return
        _,original=result;self.selector.load(original)
        mesh=next(m for m in original['meshes'] if m['id']==self.part_id)
        self.refs={f['index']:CylinderReference.model_validate(f['cylinder']) for f in mesh['faces'] if f.get('cylinder')}
        self.faces.blockSignals(True)
        for idx,ref in self.refs.items():
            self.faces.addItem(f"면 {idx+1} · {'구멍' if ref.internal else '축'} Ø{ref.diameter:g} × {ref.length:g} mm",idx)
        self.faces.blockSignals(False);self.ready=True
        if not self.refs:self.failed('나사를 만들 완전한 원통 면이 없습니다. 원형 축 또는 구멍을 먼저 만드세요.');return
        desired=self.existing['cylinder']['index'] if self.existing else self.face_index
        self.faces.blockSignals(True);self.faces.setCurrentIndex(max(0,self.faces.findData(desired)));self.faces.blockSignals(False)
        self.face_changed()
        if self.existing:
            for key,w in self.fields.items():
                w.setExpression(binding_for(self.base,['parts',self.part_id,'features',self.feature_id,key]) or str(self.existing[key]))
            self.hand.setCurrentIndex(self.hand.findData(self.existing['handedness']));self.reverse.setChecked(self.existing['reverse'])
        self.changed()

    def pick_face(self,part_id,face):
        if not self.ready or part_id!=self.part_id or not face:return
        index=self.faces.findData(face['index'])
        if index<0:self.selector.message.emit('축 바깥 또는 구멍 안쪽의 완전한 원통 면을 선택하세요.');return
        self.faces.setCurrentIndex(index)

    def face_changed(self,*args):
        ref=self.refs.get(self.faces.currentData())
        if not ref:return
        diameter,pitch=suggested_size(ref)
        for key,value in dict(diameter=diameter,pitch=pitch,length=min(ref.length,8*pitch),offset=0,clearance=0).items():self.fields[key].setValue(value)
        self.presets.blockSignals(True);self.presets.setCurrentIndex(0);self.presets.blockSignals(False)
        self.selector.highlight_face(self.part_id,ref.index);self.selector.window.Render();self.changed()

    def preset_changed(self,*args):
        value=self.presets.currentData()
        if value:
            d,p=map(float,value.split(':'));self.fields['diameter'].setValue(d);self.fields['pitch'].setValue(p)
        self.changed()

    def changed(self,*args):
        if not self.ready:return
        ref=self.refs.get(self.faces.currentData())
        if not ref:return
        try:
            d=self.fields['diameter'].value();p=self.fields['pitch'].value();length=self.fields['length'].value()
            self.details.setText(f"{'암나사 · 바탕 구멍' if ref.internal else '수나사 · 축'} Ø{ref.diameter:g} mm\n면 길이 {ref.length:g} mm · {length/p:.2f} 회전\n권장 바탕 구멍 Ø{d-2*DEPTH_FACTOR*p:.3f} mm\n길이·피치 입력에 변수 식도 사용할 수 있습니다.")
        except ValueError:pass
        self.schedule()

    def candidate(self):
        if not self.ready or not self.refs:raise ValueError('원통 면을 선택하세요.')
        ref=self.refs[self.faces.currentData()];raw=deepcopy(self.base);part=next(p for p in raw['parts'] if p['id']==self.part_id)
        feature=ThreadFeature(id=self.feature_id,cylinder=ref,**{k:w.value() for k,w in self.fields.items()},
            handedness=self.hand.currentData(),reverse=self.reverse.isChecked(),support_feature=part['features'][self.index-1]['id'] if self.index else 'base')
        feature.name=thread_title(feature)
        if self.index<len(part['features']):part['features'][self.index]=feature.model_dump()
        else:part['features'].append(feature.model_dump())
        for key,w in self.fields.items():set_binding(raw,['parts',self.part_id,'features',self.feature_id,key],w.formula())
        return raw

    def done(self,result):
        self.selector.shutdown();super().done(result)
