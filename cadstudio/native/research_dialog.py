from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLineEdit,QDialogButtonBox,QComboBox
from ..research_package import TestProtocol,manifest
from .widgets import label


class ResearchDialog(QDialog):
    def __init__(self,parent,raw,selected=None):
        super().__init__(parent);self.setWindowTitle('피로시험 조건 / 데이터 양식');self.resize(530,450)
        self.raw=raw;self.protocol=None
        root=QVBoxLayout(self);root.addWidget(label('시편 STEP + 시험 조건 + 실측 CSV 양식',True))
        root.addWidget(label('아직 정하지 않은 하중·속도·왕복거리는 비워두세요. 입력값은 장비 성능이 아닌 시험 계획이며 설계를 변경하지 않습니다.',True))
        form=QFormLayout();root.addLayout(form);self.part=QComboBox()
        for p in raw['parts']:self.part.addItem(p['name'],p['id'])
        candidates=[p for p in raw['parts'] if p['geometry']['kind'] in ('round_specimen','flat_specimen','wafer') or p.get('role')=='specimen']
        self.part.setCurrentIndex(max(0,self.part.findData(selected or (candidates[0]['id'] if candidates else ''))))
        self.material=QComboBox();self.material.addItem('Al · aluminum','aluminum');self.material.addItem('Si wafer · silicon_wafer','silicon_wafer')
        self.method=QComboBox();self.method.addItem('인장·압축 반복','axial_tension_compression');self.method.addItem('미정 · 방식 확인 필요','undecided')
        self.batch=QLineEdit();self.batch.setMaxLength(160)
        form.addRow('시편',self.part);form.addRow('재료',self.material);form.addRow('시험 방식',self.method);form.addRow('재료 배치 / 상태',self.batch)
        self.fields={}
        for key,title in [('max_force_N','목표 최대 하중 · N'),('frequency_Hz','목표 반복 속도 · Hz'),('peak_to_peak_stroke_mm','목표 왕복거리 · peak-to-peak mm')]:
            field=QLineEdit();field.setPlaceholderText('미정 · 비워두기');field.setMaxLength(32);self.fields[key]=field;form.addRow(title,field)
        root.addWidget(label('실측 초·Hz와 연구 모델 시간은 자동 변환하지 않습니다. 크로스헤드 변위를 시편 변형률로 대신하지 않습니다. 웨이퍼의 시험·고정구 검증은 별도로 필요합니다.',True))
        self.error=label('',True);root.addWidget(self.error)
        box=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);box.accepted.connect(self.accept);box.rejected.connect(self.reject);root.addWidget(box)
        self.part.currentIndexChanged.connect(self.part_changed);self.material.currentIndexChanged.connect(self.material_changed);self.part_changed()
    def part_changed(self):
        part=next(p for p in self.raw['parts'] if p['id']==self.part.currentData())
        if part['geometry']['kind']=='wafer':self.material.setCurrentIndex(self.material.findData('silicon_wafer'))
    def material_changed(self):
        if self.material.currentData()=='silicon_wafer':self.method.setCurrentIndex(self.method.findData('undecided'))
    def accept(self):
        try:
            values={key:float(w.text()) if w.text().strip() else None for key,w in self.fields.items()}
            self.protocol=TestProtocol(material_id=self.material.currentData(),method=self.method.currentData(),batch=self.batch.text(),**values)
            manifest(self.raw,self.part.currentData(),self.protocol)
        except ValueError:self.error.setText('입력값을 확인하세요. 치수는 양수이며 미정은 비워둡니다. 웨이퍼의 시험 방식은 미정이어야 합니다.');return
        super().accept()
