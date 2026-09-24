"""Native offset/angled sketch plane preview, with explicit dependency edits."""
from copy import deepcopy
from PySide6.QtWidgets import QFormLayout,QCheckBox
from ..models import Design,WorkPlane
from ..kernel import KERNEL_LOCK,preview
from ..work_planes import edit_sketch_plane,plane_preview_sketch
from ..sketch_frames import work_plane_frame
from .widgets import number,label
from .workflows import PreviewDialog,choice


class WorkPlaneDialog(PreviewDialog):
    def __init__(self,parent,raw=None,plane=None,sketch_id=None):
        title='스케치 작업 평면 편집' if sketch_id else '작업 평면에서 스케치'
        super().__init__(parent,title,'기준 평면의 법선 방향 오프셋과 기울기를 지정하세요. 격자 간격은 10 mm이며 미리보기 전용입니다.')
        self.base=deepcopy(raw) if raw else Design().model_dump();self.sketch_id=sketch_id
        self.original=WorkPlane.model_validate(plane or {});self.fields={};self.changed=set()
        self.plane=choice([(v,v+' 기준 평면') for v in ('XY','XZ','YZ')]);self.plane.setCurrentIndex(self.plane.findData(self.original.plane));self.controls.addWidget(self.plane)
        self.offset=number(self.original.offset,-5000,5000,' mm');form=QFormLayout();form.addRow('법선 오프셋',self.offset);self.controls.addLayout(form)
        self.controls.addWidget(label('회전 · 기준 평면의 X → Y → Z 축 순서',True));angles=QFormLayout();self.controls.addLayout(angles)
        self.controls.addWidget(label('원점 추가 이동 · 세계 좌표',True));origin=QFormLayout();self.controls.addLayout(origin)
        for key in ('rx','ry','rz','x','y','z'):
            angular=key.startswith('r');field=number(getattr(self.original.placement,key),-360 if angular else -5000,360 if angular else 5000,' °' if angular else ' mm')
            self.fields[key]=field;(angles if angular else origin).addRow(key.upper(),field)
            field.valueChanged.connect(lambda *args,k=key:self.change(k))
        self.grounded=QCheckBox('고정 부품도 함께 이동 · 고정 상태 유지');self.grounded.setVisible(bool(sketch_id));self.controls.addWidget(self.grounded)
        if sketch_id:self.controls.addWidget(label('연결된 기본 돌출도 함께 이동합니다. 선택 밖 조립 구속·몸체 연산 또는 위치 변수와 충돌하면 적용하지 않습니다. 회전·스윕·로프트의 단면 배치는 해당 도구에서 편집하세요.',True))
        self.controls.addStretch();self.plane.currentIndexChanged.connect(self.schedule);self.offset.valueChanged.connect(lambda:self.change('offset'));self.grounded.toggled.connect(self.schedule)
        self.apply_button.setText('작업 평면 적용' if sketch_id else '이 평면에서 스케치');self.schedule()

    def change(self,key):self.changed.add(key);self.schedule()

    def schedule(self,*args):
        self.fit_next=True;super().schedule(*args)

    def candidate(self):
        raw=self.original.model_dump();raw['plane']=self.plane.currentData()
        if 'offset' in self.changed:raw['offset']=self.offset.value()
        for key in self.changed-{'offset'}:raw['placement'][key]=self.fields[key].value()
        return dict(plane=raw,raw=self.base,sketch_id=self.sketch_id,allow_grounded=self.grounded.isChecked())

    @staticmethod
    def compute(payload):
        with KERNEL_LOCK:
            plane=WorkPlane.model_validate(payload['plane']);work_plane_frame(plane)
            raw=edit_sketch_plane(payload['raw'],payload['sketch_id'],plane,allow_grounded=payload['allow_grounded']) if payload['sketch_id'] else payload['raw']
            design=Design.model_validate(raw);display=design.model_copy(deep=True)
            display.sketches.append(plane_preview_sketch(plane))
            return (plane,design),preview(display)

    def present(self):
        plane,_=self.checked;origin,x,y=work_plane_frame(plane)
        self.status.setStyleSheet('color:#8dd7c0;');self.status.setText('평면 원점 (mm): '+', '.join(f'{v:g}' for v in origin)+' · 미리보기 확인 후 적용하세요.')
