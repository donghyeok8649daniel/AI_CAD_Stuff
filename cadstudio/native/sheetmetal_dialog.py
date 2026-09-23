from copy import deepcopy
from PySide6.QtWidgets import QFormLayout,QCheckBox,QFileDialog
from .workflows import PreviewDialog
from .widgets import number,label,button
from .geometry import uid
from ..models import Part,SheetMetalGeometry
from ..sheetmetal import bend_allowance,flat_length,export_flat


class SheetMetalDialog(PreviewDialog):
    def __init__(self,parent,design,part_id=None):
        super().__init__(parent,'판금 · 단일 절곡 / 전개','직선부의 접선 길이, 안쪽 절곡 반경, 두께와 K 계수로 굽힌 판과 전개도를 만듭니다.')
        self.raw=deepcopy(design);self.part_id=part_id or 'part-'+uid();part=next((p for p in design['parts'] if p['id']==part_id),None);g=SheetMetalGeometry.model_validate(part['geometry']) if part else SheetMetalGeometry();self.fields={};form=QFormLayout();self.controls.addLayout(form)
        for key,title,low,high,suffix in [('length','바닥 직선 길이',.01,2000,' mm'),('width','판 폭',.01,2000,' mm'),('flange_length','플랜지 직선 길이',.01,2000,' mm'),('thickness','판 두께',.01,2000,' mm'),('bend_radius','안쪽 절곡 반경',.01,2000,' mm'),('bend_angle','굽힘 각도',1,175,' °'),('k_factor','K 계수',.001,.5,'')]:
            w=number(getattr(g,key),low,high,suffix);self.fields[key]=w;form.addRow(title,w);w.valueChanged.connect(self.schedule)
        self.flat=QCheckBox('전개 상태로 보기 / 모델 저장');self.flat.setChecked(g.flat);self.controls.addWidget(self.flat);self.flat.toggled.connect(self.schedule);self.summary=label('');self.controls.addWidget(self.summary);self.controls.addWidget(button('전개 DXF · 절단선 / 절곡 경계',self.export));self.controls.addWidget(label('단일 절곡 판을 지원합니다. 다중 플랜지·코너 릴리프와 피처 절삭의 전개는 아직 지원하지 않습니다. K 계수는 소재와 가공 조건에 맞게 입력하세요.',True));self.controls.addStretch();self.schedule()
    def candidate(self):
        raw=deepcopy(self.raw);g=SheetMetalGeometry(**{k:w.value() for k,w in self.fields.items()},flat=self.flat.isChecked());p=next((p for p in raw['parts'] if p['id']==self.part_id),None)
        if p:p['geometry']=g.model_dump()
        else:raw['parts'].append(Part(id=self.part_id,name='판금 · 단일 절곡',geometry=g).model_dump())
        return raw
    def present(self):
        super().present();g=next(p.geometry for p in self.checked.parts if p.id==self.part_id);self.summary.setText(f'절곡 여유 {bend_allowance(g):.4f} mm\n전개 길이 {flat_length(g):.4f} mm × 폭 {g.width:g} mm')
    def export(self):
        if self.checked is None:self.status.setText('유효한 형상을 먼저 계산하세요.');return
        part=next(p for p in self.checked.parts if p.id==self.part_id)
        if part.features:self.status.setText('추가 피처를 포함한 판금 전개는 아직 지원하지 않습니다.');return
        path,_=QFileDialog.getSaveFileName(self,'전개 DXF 저장','sheet-flat.dxf','DXF (*.dxf)')
        if path:
            try:export_flat(part.geometry,path);self.status.setText('전개도 저장: '+path)
            except Exception as exc:self.status.setText(str(exc))
