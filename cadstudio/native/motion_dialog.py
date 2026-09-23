from copy import deepcopy
from PySide6.QtWidgets import QFormLayout,QCheckBox,QHBoxLayout,QListWidget
from .workflows import PreviewDialog,choice
from .widgets import label,number,button,clear_layout
from .geometry import uid
from ..assembly_motion import JOINT_AXES,JOINT_TITLES


class MotionDialog(PreviewDialog):
    def __init__(self,parent,design):
        super().__init__(parent,'관절 한계 / 모션 연결','관절별 이동 범위를 정하거나 두 관절을 비율로 연결합니다. 연결 결과와 한계를 검사한 뒤 적용합니다.')
        self.raw=deepcopy(design);self.joints={m['id']:m for m in self.raw['mates']};items=[(m['id'],JOINT_TITLES[m['kind']]+' · '+m['id']) for m in self.raw['mates'] if JOINT_AXES[m['kind']]]
        self.joint=choice(items);self.controls.addWidget(label('운동 한계를 설정할 관절'));self.controls.addWidget(self.joint);self.limit_form=QFormLayout();self.controls.addLayout(self.limit_form);self.limit_fields={};self.limit_id=None
        self.controls.addWidget(label('모션 연결 · 결과 = 구동값 × 비율 + 오프셋'))
        form=QFormLayout();self.driver=choice(items);self.driven=choice(items);self.driven.setCurrentIndex(min(1,len(items)-1));self.driver_axis=choice([]);self.driven_axis=choice([])
        for title,w in [('구동 관절',self.driver),('구동 축',self.driver_axis),('따라갈 관절',self.driven),('따라갈 축',self.driven_axis)]:form.addRow(title,w)
        self.ratio=number(1,-10000,10000,'');self.offset=number(0,-5000,5000,'');form.addRow('비율',self.ratio);form.addRow('오프셋 · 결과 축 단위',self.offset);self.controls.addLayout(form);self.controls.addWidget(button('모션 연결 추가',self.add_link));self.links=QListWidget();self.links.setMaximumHeight(130);self.controls.addWidget(self.links);self.controls.addWidget(button('선택한 연결 삭제',self.remove_link));self.controls.addStretch()
        self.driver.currentIndexChanged.connect(self.axes);self.driven.currentIndexChanged.connect(self.axes);self.joint.currentIndexChanged.connect(self.change_joint);self.axes();self.change_joint();self.refresh_links();self.schedule()
    def save_limits(self):
        if self.limit_id:self.joints[self.limit_id]['limits']={k:[lo.value(),hi.value()] for k,(check,lo,hi) in self.limit_fields.items() if check.isChecked()}
    def change_joint(self,*args):
        self.save_limits();self.limit_id=self.joint.currentData();self.limit_fields={}
        while self.limit_form.rowCount():self.limit_form.removeRow(0)
        if self.limit_id is None:return
        mate=self.joints[self.limit_id]
        for key in JOINT_AXES[mate['kind']]:
            bounds=mate.get('limits',{}).get(key,[-180,180] if key.startswith('r') else [-100,100]);limit=360 if key.startswith('r') else 5000;row=QHBoxLayout();enabled=QCheckBox(key.upper());enabled.setChecked(key in mate.get('limits',{}));row.addWidget(enabled);lo=number(bounds[0],-limit,limit,' °' if key.startswith('r') else ' mm');hi=number(bounds[1],-limit,limit,' °' if key.startswith('r') else ' mm');row.addWidget(lo);row.addWidget(hi);self.limit_form.addRow(row);self.limit_fields[key]=(enabled,lo,hi);enabled.toggled.connect(self.schedule);lo.valueChanged.connect(self.schedule);hi.valueChanged.connect(self.schedule)
        self.schedule()
    def axes(self,*args):
        for source,target in [(self.driver,self.driver_axis),(self.driven,self.driven_axis)]:
            previous=target.currentData();target.clear();mate=self.joints.get(source.currentData())
            if mate:
                for axis in JOINT_AXES[mate['kind']]:target.addItem(axis.upper()+(' · °' if axis.startswith('r') else ' · mm'),axis)
                target.setCurrentIndex(max(0,target.findData(previous)))
    def add_link(self):
        if not self.driver.currentData() or not self.driven.currentData():return
        self.raw.setdefault('motion_links',[]).append(dict(id='motion-'+uid(),driver=self.driver.currentData(),driver_axis=self.driver_axis.currentData(),driven=self.driven.currentData(),driven_axis=self.driven_axis.currentData(),ratio=self.ratio.value(),offset=self.offset.value()));self.refresh_links();self.schedule()
    def refresh_links(self):
        self.links.clear()
        for link in self.raw.get('motion_links',[]):self.links.addItem(f"{link['driver']}.{link['driver_axis']} → {link['driven']}.{link['driven_axis']} ×{link['ratio']:g} +{link['offset']:g}")
    def remove_link(self):
        index=self.links.currentRow()
        if index>=0:self.raw['motion_links'].pop(index);self.refresh_links();self.schedule()
    def candidate(self):self.save_limits();return deepcopy(self.raw)
