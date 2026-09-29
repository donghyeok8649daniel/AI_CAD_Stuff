"""Explicit cylinder selection and checked preview for repairing eccentric joints."""
from copy import deepcopy
from PySide6.QtWidgets import QFormLayout,QCheckBox
from ..joint_alignment import options,align
from ..kernel import preview,KERNEL_LOCK
from .workflows import PreviewDialog,choice
from .widgets import label,number


class JointAlignmentDialog(PreviewDialog):
    def __init__(self,parent,raw,selected=None):
        super().__init__(parent,'관절 축 · 구멍 동심 정렬','실제 구멍과 축의 원통 면을 선택하세요. 미리보기와 간섭 검사 후 적용합니다.')
        self.base=deepcopy(raw);self.alignment=None
        self.mate=choice([(m['id'],m['id']) for m in raw.get('mates',[]) if m['kind'] in ('revolute','cylindrical','slider')])
        self.mate.setCurrentIndex(max(0,self.mate.findData(selected)))
        self.parent_face=choice([]);self.child_face=choice([])
        self.keep_pose=QCheckBox('현재 축 방향 위치 / 회전 각도 유지');self.keep_pose.setChecked(True)
        self.gap=number(0,-5000,5000,' mm');self.angle=number(0,-360,360,' °');self.flip=QCheckBox('축 방향 뒤집기')
        form=QFormLayout();form.addRow('관절',self.mate);form.addRow('기준 부품 · 구멍 / 원통',self.parent_face);form.addRow('이동 부품 · 축 / 원통',self.child_face);form.addRow(self.keep_pose);form.addRow('축 방향 간격',self.gap);form.addRow('축 주위 각도',self.angle);form.addRow(self.flip);self.controls.addLayout(form)
        self.detail=label('',True);self.controls.addWidget(self.detail)
        self.controls.addWidget(label('선택한 두 원통의 중심선에 관절을 다시 연결합니다. 부품 치수는 바뀌지 않습니다. 연결된 하위 부품은 함께 이동하므로 칼라·체결부도 확인하세요. 잘린 원통, 폐루프 수동 관절, 모션 연결의 종속 관절은 먼저 해당 구성을 편집해야 합니다.',True));self.controls.addStretch()
        self.mate.currentIndexChanged.connect(self.refresh_faces)
        for box in (self.parent_face,self.child_face):box.currentIndexChanged.connect(self.schedule)
        for widget in (self.gap,self.angle):widget.valueChanged.connect(self.schedule)
        self.keep_pose.toggled.connect(self.pose_changed);self.flip.toggled.connect(self.schedule)
        self.pose_changed();self.refresh_faces()

    def pose_changed(self):
        for widget in (self.gap,self.angle):widget.setEnabled(not self.keep_pose.isChecked())
        self.schedule()

    def refresh_faces(self):
        # Enumeration shares the preview worker; no kernel work on the UI thread.
        self.faces_for=None
        for box in (self.parent_face,self.child_face):box.blockSignals(True);box.clear();box.blockSignals(False)
        self.fit_next=True;self.schedule()

    def candidate(self):
        if self.faces_for==self.mate.currentData() and (self.parent_face.currentData() is None or self.child_face.currentData() is None):raise ValueError('기준 부품과 이동 부품의 원통 면을 각각 선택하세요.')
        return dict(raw=self.base,mate_id=self.mate.currentData(),parent_face=self.parent_face.currentData(),child_face=self.child_face.currentData(),gap=None if self.keep_pose.isChecked() else self.gap.value(),angle=None if self.keep_pose.isChecked() else self.angle.value(),flipped=self.flip.isChecked())

    @staticmethod
    def compute(payload):
        from ..models import Design
        with KERNEL_LOCK:
            if payload['parent_face'] is None or payload['child_face'] is None:
                rows=options(payload['raw'],payload['mate_id']);d=Design.model_validate(payload['raw']);r=preview(d);r['alignment_options']=rows;return d,r
            d,info=align(**payload);r=preview(d);r['alignment_info']=info;return d,r

    def present(self):
        super().present()
        if 'alignment_options' in self.result:
            rows=self.result['alignment_options'];self.apply_button.setEnabled(False)
            for box,items in zip((self.parent_face,self.child_face),rows):
                box.blockSignals(True);box.clear();box.addItem('원통 면 선택…',None)
                for r in items:
                    f=r['frame'];center=', '.join(f'{v:.3f}' for v in f['origin'])
                    box.addItem(f"{'구멍' if r['internal'] else '축'} Ø{r['diameter']:g} · 면 {r['index']} · ({center})",r['index'])
                box.blockSignals(False)
            self.detail.setText('양쪽 원통 면을 선택하면 편심 거리와 정렬 결과를 표시합니다.' if all(rows) else '완전한 원통 면이 없는 부품입니다. 실제 축 / 구멍 형상을 먼저 만드세요.')
            self.faces_for=self.mate.currentData()
        else:
            info=self.result['alignment_info'];self.alignment=info
            self.detail.setText(f"정렬 전 편심 {info['offset_mm']:.4f} mm · 축 각도 차 {info['tilt_deg']:.3f}°\n정렬 후 두 중심선 일치 · 간격 {info['gap_mm']:.3f} mm · 각도 {info['angle_deg']:.3f}°")
