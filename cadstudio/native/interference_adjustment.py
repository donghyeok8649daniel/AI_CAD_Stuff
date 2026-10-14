"""Preview-gated interference correction. No automatic assembly unlock."""
from copy import deepcopy
from PySide6.QtWidgets import QHBoxLayout,QFormLayout,QSpinBox
from ..catalog import FIELDS
from ..parameters import binding_for
from ..interference_adjustment import selected_overlap,require_selected_clear,separation_suggestion
from ..interference import VOLUME_EPS
from .placement_dialog import PlacementDialog
from .workflows import PreviewDialog
from .widgets import label,button,number


class SelectedPairGate:
    def present_interference(self):
        super().present_interference()
        if self.checked is None or self.result is None:return
        volume=selected_overlap(self.result['stats']['collisions'],self.adjust_pair)
        if volume>VOLUME_EPS:
            self.apply_button.setEnabled(False)
            self.status.setText(self.status.text()+f'\n선택 간섭 {volume:.6g} mm³가 남아 있습니다 · 조정을 계속하세요.')
        else:self.status.setText(self.status.text()+'\n선택한 부품 사이 체적 간섭 해소 · 다른 간섭은 위 검사 결과를 확인하세요.')
    def accept(self):
        if self.result is None:return
        try:require_selected_clear(self.result['stats']['collisions'],self.adjust_pair)
        except ValueError:return
        super().accept()


class InterferenceMoveDialog(SelectedPairGate,PlacementDialog):
    def __init__(self,parent,design,identifier,pair,bounds):
        self.adjust_pair=list(pair);self.moving=identifier;self.bounds=deepcopy(bounds)
        if identifier not in pair:raise ValueError('조정할 부품이 선택 간섭에 없습니다.')
        self.target=next(i for i in pair if i!=identifier)
        super().__init__(parent,design,[identifier]);self.setWindowTitle('간섭 이동 / 회전 조정')
        self.clearance=number(.2,0,100,' mm')
        form=QFormLayout();form.addRow('분리 제안 여유',self.clearance);self.controls.insertLayout(0,form)
        self.controls.insertWidget(1,label('경계 기준 분리 제안 · 기존 배치에서 계산하며 회전값을 0으로 초기화합니다. 미리보기 전에는 간섭 해소·실제 맞춤 공차가 검증되지 않습니다.',True))
        for offset,axis in enumerate('xyz'):
            row=QHBoxLayout()
            for direction in (-1,1):
                btn=button(axis.upper()+('−' if direction<0 else '+')+' 분리 제안',lambda a=axis,d=direction:self.suggest(a,d))
                btn.setObjectName('separate_'+axis+('_minus' if direction<0 else '_plus'));row.addWidget(btn)
            self.controls.insertLayout(2+offset,row)
    def suggest(self,axis,direction):
        try:
            proposal=separation_suggestion(self.base,self.bounds,self.moving,self.target,axis,direction,self.clearance.value(),connected=self.connected.isChecked())
        except ValueError as exc:self.failed(str(exc));return
        for key,value in zip('xyz',proposal['translation']):self.fields[key].setValue(value)
        for key in ('rx','ry','rz'):self.fields[key].setValue(0.)
        self.schedule()


class InterferenceDimensionDialog(SelectedPairGate,PreviewDialog):
    def __init__(self,parent,design,identifier,pair):
        self.base=deepcopy(design);self.part_id=identifier;self.adjust_pair=list(pair)
        part=next((p for p in self.base['parts'] if p['id']==identifier),None)
        if part is None or identifier not in pair:raise ValueError('조정할 부품을 찾을 수 없습니다.')
        if part.get('source_part_id'):raise ValueError('연결된 부품은 원본 부품의 치수를 조정해야 합니다. 원본 편집을 사용하세요.')
        fields={k:v for k,v in part['geometry'].items() if k in FIELDS and type(v) in (int,float)}
        if not fields:raise ValueError('이 형상에는 직접 수정할 기본 치수가 없습니다. 원본 스케치·피처 편집에서 수정한 뒤 다시 검사하세요.')
        super().__init__(parent,'간섭 치수 조정','입력한 기본 치수만 변경합니다. 원래 요청 치수와 조립 여유를 확인하세요. 전체 형상·구속·새 간섭을 미리보기로 검사합니다.')
        self.inputs={};self.original=fields;self.edited=set();form=QFormLayout();self.controls.addLayout(form)
        for key,value in fields.items():
            if type(value) is int:
                widget=QSpinBox();widget.setRange(min(0,value),max(2000,value));widget.setValue(value)
            else:widget=number(value,min(0,value),max(2000,value),' '+FIELDS[key][1],decimals=6)
            widget.setObjectName('interference_dimension_'+key)
            bound=binding_for(self.base,['parts',identifier,'geometry',key])
            if bound:widget.setEnabled(False);widget.setToolTip('변수로 구속된 치수입니다. 변수 편집에서 변경하세요: '+bound)
            form.addRow(FIELDS[key][0],widget);self.inputs[key]=widget
            widget.valueChanged.connect(lambda *args,k=key:self.edited.add(k));widget.valueChanged.connect(self.schedule)
        self.controls.addWidget(label('변수 연결·연결 원본·피처는 자동 해제하지 않습니다. 재료·공차·하중 정격과 전체 구동 범위는 별도 확인해야 합니다.',True));self.controls.addStretch();self.schedule()
    def changed_dimensions(self):
        return {key:widget.value() for key,widget in self.inputs.items() if key in self.edited and widget.isEnabled() and widget.value()!=self.original[key]}
    def candidate(self):
        raw=deepcopy(self.base);part=next(p for p in raw['parts'] if p['id']==self.part_id)
        part['geometry'].update(self.changed_dimensions());return raw
    def present(self):
        super().present()
        if not self.changed_dimensions():self.apply_button.setEnabled(False);self.status.setText(self.status.text()+'\n변경된 치수가 없습니다.')
