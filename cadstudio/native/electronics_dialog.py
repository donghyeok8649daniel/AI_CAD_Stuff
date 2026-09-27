from copy import deepcopy
from uuid import uuid4
from PySide6.QtWidgets import QFormLayout,QCheckBox
from .workflows import PreviewDialog,choice
from .widgets import number,label,button
from ..electronics_mount import MountSpec,add_electronics_mount
from ..kernel import KERNEL_LOCK,preview


class ElectronicsMountDialog(PreviewDialog):
    def __init__(self,parent,raw,part_id,face):
        super().__init__(parent,'전장부품 장착 자리','배터리·MCU·액추에이터의 실측 치수로 자리와 체결/전선 구멍을 만듭니다. 입력 치수는 선택 면 좌표입니다.')
        self.base=deepcopy(raw);self.part_id=part_id;self.face=deepcopy(face);self.prefix='mount-'+uuid4().hex[:8];self.created=[]
        self.source_record=None;self.controls.addWidget(button('제품 URL에서 스펙 가져오기…',self.import_specs))
        self.source_summary=label('',True);self.controls.addWidget(self.source_summary)
        self.shape=choice([('rectangle','사각 자리'),('circle','원형 자리')]);self.controls.addWidget(self.shape);self.checks={};self.inputs={};form=QFormLayout();form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows);self.controls.addLayout(form)
        defaults=MountSpec().model_dump()
        if raw.get('print_profile') and raw['print_profile'].get('enabled',True):defaults['clearance']=raw['print_profile']['hole_expansion']
        for key,title in [('pocket','부품 자리 파기'),('bolts','4개 체결 구멍'),('wire','전선 통과 구멍')]:
            w=QCheckBox(title);w.setChecked(defaults[key]);self.checks[key]=w;self.controls.addWidget(w);w.toggled.connect(self.schedule)
        for key,title in [('width','부품 폭 / 지름'),('length','부품 길이'),('depth','자리 깊이'),('clearance','자리 전체 여유'),('x','중심 X'),('y','중심 Y'),('spacing_x','체결 구멍 간격 X'),('spacing_y','체결 구멍 간격 Y'),('bolt_diameter','체결 구멍 지름'),('wire_diameter','전선 구멍 지름'),('wire_x','전선 위치 X'),('wire_y','전선 위치 Y')]:
            f=MountSpec.model_fields[key];lo=next(m.ge for m in f.metadata if hasattr(m,'ge'));hi=next(m.le for m in f.metadata if hasattr(m,'le'));w=number(defaults[key],lo,hi,' mm',decimals=3);w.setMinimumWidth(125);self.inputs[key]=w;form.addRow(title,w);w.valueChanged.connect(self.schedule)
        self.controls.addWidget(label('자리 전체 여유 0.2 mm는 양쪽 0.1 mm입니다. 원형 자리는 폭을 지름으로 사용합니다. 체결/전선 구멍은 관통하며 프린터 보정에 연결됩니다.\n실제 제품의 치수·구멍 간격은 직접 입력하세요. 커넥터 돌출, 배선 굽힘, 발열·배터리 팽창 공간은 별도 확인해야 합니다. 체결 강도나 전기적 안전 인증 기능은 아닙니다.',True));self.controls.addStretch();self.shape.currentIndexChanged.connect(self.schedule);self.schedule()
    def candidate(self):
        return dict(raw=self.base,part_id=self.part_id,face_index=self.face['index'],spec=dict(shape=self.shape.currentData(),**{k:w.value() for k,w in self.inputs.items()},**{k:w.isChecked() for k,w in self.checks.items()}),prefix=self.prefix)
    def import_specs(self):
        from .component_specs_dialog import ComponentSpecsDialog
        dialog=ComponentSpecsDialog(self)
        if not dialog.exec():return
        if dialog.mode=='ai':
            self.parent().use_component_source(dialog.record);self.reject();return
        self.source_record=dialog.record;values=dialog.record['selected_dimensions_mm']
        self.inputs['width'].setValue(values[0]);self.inputs['length'].setValue(values[1]);self.checks['bolts'].setChecked(False)
        self.source_summary.setText(dialog.record['title']+'\n'+dialog.record['url']+'\n가져온 1번 치수 → 폭, 2번 → 길이. 치수 순서를 확인하세요. 제품 높이를 자리 깊이로 자동 적용하지 않습니다.')
        self.schedule()
    @staticmethod
    def compute(payload):
        with KERNEL_LOCK:
            d,_=add_electronics_mount(**payload);return d,preview(d)
