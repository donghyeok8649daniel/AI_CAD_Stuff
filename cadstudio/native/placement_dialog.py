"""Preview a whole selection with explicit pivot, units and grounded policy."""
from copy import deepcopy

from PySide6.QtWidgets import QCheckBox, QFormLayout

from ..kernel import KERNEL_LOCK, preview
from ..models import Design
from ..placement import placement_selection, move_selection
from .widgets import number, label, button
from .workflows import PreviewDialog, choice


class PlacementDialog(PreviewDialog):
    def __init__(self,parent,raw,identifiers):
        super().__init__(parent,'부품 이동 / 회전','선택한 부품을 함께 배치합니다. 세계 좌표 X/Y/Z, 회전 순서 X → Y → Z. 적용 전 미리보기로 확인하세요.')
        self.base=deepcopy(raw);self.identifiers=list(identifiers);self.moved_ids=[]
        self.members=label('');self.controls.addWidget(self.members)
        self.connected=QCheckBox('연결 부품 포함 · 관절과 몸체 연산 유지');self.connected.setChecked(True);self.controls.addWidget(self.connected)
        self.grounded=QCheckBox('고정 부품도 배치 변경 · 고정 상태 유지');self.controls.addWidget(self.grounded)
        self.fields={};form=QFormLayout();self.controls.addLayout(form)
        for key,title in [('x','X 이동'),('y','Y 이동'),('z','Z 이동'),('rx','X 회전'),('ry','Y 회전'),('rz','Z 회전')]:
            angular=key.startswith('r');field=number(0,-360 if angular else -5000,360 if angular else 5000,' °' if angular else ' mm')
            self.fields[key]=field;form.addRow(title,field);field.valueChanged.connect(self.schedule)
        self.center=choice([('selection','회전 중심 · 선택 부품 원점들의 중심'),('world','회전 중심 · 세계 원점'),('custom','회전 중심 · 직접 입력')]);self.controls.addWidget(self.center)
        pivot_form=QFormLayout();self.controls.addLayout(pivot_form);self.pivot_fields=[]
        for axis in 'XYZ':
            field=number(0,-5000,5000,' mm');field.setEnabled(False);self.pivot_fields.append(field);pivot_form.addRow(axis+' 중심',field);field.valueChanged.connect(self.schedule)
        self.controls.addWidget(button('값 초기화',self.reset_values));self.controls.addStretch()
        self.connected.toggled.connect(self.schedule);self.grounded.toggled.connect(self.schedule);self.center.currentIndexChanged.connect(self.center_changed)
        self.schedule()

    def center_changed(self):
        for field in self.pivot_fields:field.setEnabled(self.center.currentData()=='custom')
        self.schedule()

    def schedule(self,*args):
        self.fit_next=True
        super().schedule(*args)

    def reset_values(self):
        for field in self.fields.values():field.setValue(0)
        for field in self.pivot_fields:field.setValue(0)
        self.center.setCurrentIndex(0);self.schedule()

    def candidate(self):
        ids=placement_selection(self.base,self.identifiers,self.connected.isChecked());self.moved_ids=ids
        parts=[p for p in self.base['parts'] if p['id'] in ids];added=len(ids)-len(self.identifiers)
        self.members.setText(f'{len(ids)}개 부품 이동'+(f' · 연결 부품 {added}개 포함' if added else '')+'\n'+', '.join(p['name'] for p in parts))
        kind=self.center.currentData()
        pivot=[sum(p['transform'][key] for p in parts)/len(parts) for key in ('x','y','z')] if kind=='selection' else [f.value() for f in self.pivot_fields] if kind=='custom' else [0,0,0]
        return dict(raw=self.base,identifiers=self.identifiers,translation=[self.fields[k].value() for k in ('x','y','z')],
                    rotation=[self.fields[k].value() for k in ('rx','ry','rz')],pivot=pivot,
                    connected=self.connected.isChecked(),allow_grounded=self.grounded.isChecked())

    @staticmethod
    def compute(payload):
        with KERNEL_LOCK:
            raw,_=move_selection(**payload);design=Design.model_validate(raw)
            return design,preview(design)

    def present(self):
        super().present();self.viewport.select_many(self.moved_ids)
        if not any(field.value() for field in self.fields.values()):
            self.apply_button.setEnabled(False);self.status.setText('이동 거리 또는 회전 각도를 입력하세요. 단위: mm / °')
