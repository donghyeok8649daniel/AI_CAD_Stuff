"""Dimensioned, asynchronous physical joint preview."""
from copy import deepcopy
from uuid import uuid4
from PySide6.QtWidgets import QFormLayout
from ..joint_hardware import RevoluteHardware, add_revolute_hardware
from ..kernel import KERNEL_LOCK, preview
from .workflows import PreviewDialog, choice
from .widgets import label, number


class JointHardwareDialog(PreviewDialog):
    def __init__(self,parent,raw=None,selected_joint=None):
        super().__init__(parent,'실제 회전 관절 구조','하우징·부시 2개·축·장착/출력 플랜지·칼라를 CAD 부품으로 생성합니다. 단위 mm.')
        self.base=deepcopy(raw);self.prefix='joint-'+uuid4().hex[:8]+'-';self.part_ids=[]
        items=[('', '새 회전 관절 조립 만들기')]+[(m['id'],'기존 관절에 장착 · '+m['id']) for m in (raw or {}).get('mates',[]) if m['kind']=='revolute']
        self.target=choice(items);self.controls.addWidget(self.target)
        self.target.setCurrentIndex(max(0,self.target.findData(selected_joint or '')))
        self.inputs={};form=QFormLayout();self.controls.addLayout(form)
        labels={'shaft_diameter':'축 지름','clearance':'부시 내경 − 축 지름','length':'하우징 길이','bushing_wall':'부시 두께','housing_wall':'하우징 벽 두께','flange_thickness':'플랜지 두께','bolt_diameter':'장착 구멍 지름','axial_gap':'축 방향 여유'}
        defaults=RevoluteHardware().model_dump()
        profile=(raw or {}).get('print_profile')
        if profile and profile.get('enabled',True):
            if profile['gap']>=.02:defaults['axial_gap']=profile['gap']
            self.controls.addWidget(label('이 프로젝트의 프린터 보정을 새 부품의 외경 / 구멍에 연결합니다. 실제 미리보기 치수를 확인하세요.',True))
        for key,title in labels.items():
            field=RevoluteHardware.model_fields[key];bounds=field.metadata
            lo=next(m.ge for m in bounds if hasattr(m,'ge'));hi=next(m.le for m in bounds if hasattr(m,'le'))
            widget=number(defaults[key],lo,hi,' mm');self.inputs[key]=widget;form.addRow(title,widget);widget.valueChanged.connect(self.schedule)
        self.positions=[]
        for axis in 'XYZ':
            widget=number(0,-2000,2000,' mm');self.positions.append(widget);form.addRow('새 조립 '+axis,widget);widget.valueChanged.connect(self.schedule)
        self.controls.addWidget(label('기존 관절 선택 시 같은 회전 축에 구조를 장착하고 기존 운동을 따릅니다. 원래 부품의 구멍·장착부는 자동 가공하지 않으므로 간섭을 확인하세요.\n칼라와 축/출력 플랜지는 강체 연결입니다. 체결 나사·키·베어링 등급과 하중 정격은 포함하지 않은 편집 가능한 설계 초안입니다.',True));self.controls.addStretch()
        self.target.currentIndexChanged.connect(self.target_changed);self.target_changed()

    def target_changed(self):
        for widget in self.positions:widget.setEnabled(not self.target.currentData())
        self.fit_next=True;self.schedule()

    def candidate(self):
        return dict(raw=self.base,dimensions={k:w.value() for k,w in self.inputs.items()},mate_id=self.target.currentData() or None,
                    origin=[w.value() for w in self.positions],prefix=self.prefix)

    @staticmethod
    def compute(payload):
        with KERNEL_LOCK:
            design,_=add_revolute_hardware(**payload);return design,preview(design)

    def present(self):
        super().present();self.part_ids=[p.id for p in self.checked.parts if p.id.startswith(self.prefix)]
        self.viewport.select_many(self.part_ids)
        collisions=self.result['stats']['collisions']
        if collisions:self.status.setText(self.status.text()+' · 기존 부품과 겹치는 부분을 수정한 뒤 제작하세요.')
