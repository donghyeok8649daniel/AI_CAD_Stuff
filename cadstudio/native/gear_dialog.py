"""Real spur gear pair, with ordinary editable parts, joints and motion link."""
from copy import deepcopy
from uuid import uuid4
from PySide6.QtWidgets import QFormLayout,QSpinBox
from ..gears import add_gear_pair
from ..kernel import preview
from .workflows import PreviewDialog
from .widgets import label,number


class GearDialog(PreviewDialog):
    def __init__(self,parent,raw):
        super().__init__(parent,'스퍼 기어 구동 설계','실제 인벌류트 치형 · 일체형 축 · 구멍이 있는 지지판을 만들고 두 회전 관절을 잇수비로 연결합니다.')
        self.base=deepcopy(raw);self.prefix='gear-'+uuid4().hex[:8]+'-';form=QFormLayout();self.controls.addLayout(form);self.inputs={}
        for key,title,value,lo,hi,unit in [('module','모듈',2,.5,10,' mm'),('teeth_a','입력 잇수',20,18,80,''),('teeth_b','출력 잇수',40,18,80,''),('thickness','기어 두께',8,1,100,' mm'),('backlash','기어 쌍 백래시',.2,0,2,' mm'),('shaft_diameter','일체형 축 지름',8,2,100,' mm'),('clearance','축 지름 여유',.2,.02,2,' mm')]:
            if key.startswith('teeth'):w=QSpinBox();w.setRange(lo,hi);w.setValue(value)
            else:w=number(value,lo,hi,unit)
            self.inputs[key]=w;form.addRow(title,w);w.valueChanged.connect(self.schedule)
        self.positions=[]
        for axis in 'XYZ':
            w=number(0,-4000,4000,' mm');self.positions.append(w);form.addRow('배치 '+axis,w);w.valueChanged.connect(self.schedule)
        self.metrics=label('',True);self.controls.addWidget(self.metrics)
        self.controls.addWidget(label('압력각 20° · 평기어 18~80T. 백래시는 두 치형에 나눠 적용합니다. 축은 기어와 한 몸이므로 함께 회전합니다. 지지판 위로 삽입하는 구조이며 축 방향 이탈 방지 덮개, 윤활, 베어링·하중 정격은 별도 설계하세요.\n치저는 방사형 완화 형상입니다. 가공용 공구 치저 곡선·강도 인증은 포함하지 않습니다. 프린터 보정은 여기에 입력하는 실제 여유로 확인하세요.',True));self.controls.addStretch();self.schedule()
    def candidate(self):return dict(raw=self.base,prefix=self.prefix,origin=[w.value() for w in self.positions],**{k:w.value() for k,w in self.inputs.items()})
    def compute(self,payload):
        d=add_gear_pair(**payload);return d,preview(d)
    def present(self):
        super().present();a=self.inputs['teeth_a'].value();b=self.inputs['teeth_b'].value();m=self.inputs['module'].value()
        self.metrics.setText(f'축간 거리 {m*(a+b)/2:g} mm\n출력 / 입력 회전비 −{a/b:g}\n적용 후 관절 구동에서 입력 기어를 움직이세요.')
