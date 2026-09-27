"""Project print profile with explicit dimension selection and real CAD preview."""
import json
from copy import deepcopy
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout,QLineEdit,QCheckBox,QHBoxLayout,QTableWidget,QTableWidgetItem,QHeaderView,QFileDialog
from .workflows import PreviewDialog
from .widgets import label,button,number
from ..models import Design,PrintProfile
from ..print_profile import print_targets,apply_print_profile


class PrintProfileDialog(PreviewDialog):
    def __init__(self,parent,raw=None,selected_ids=()):
        super().__init__(parent,'3D 프린터 · 전체 여유 / 공차','프로젝트 전체의 연결된 치수를 함께 갱신합니다. 적용 전 실제 형상과 변경 치수를 확인하세요. 단위 mm.')
        self.resize(1250,850);self.base=deepcopy(raw or Design().model_dump());self.rows=print_targets(self.base)
        p=PrintProfile.model_validate(self.base.get('print_profile') or {})
        self.enabled=QCheckBox('프린터 보정 사용');self.enabled.setChecked(p.enabled);self.controls.addWidget(self.enabled)
        form=QFormLayout();self.controls.addLayout(form);self.name=QLineEdit(p.name);self.material=QLineEdit(p.material)
        form.addRow('프린터 / 프로필',self.name);form.addRow('재료',self.material);self.inputs={}
        for key,title in [('hole_expansion','구멍 지름 확대 +'),('shaft_reduction','축 외경 축소 −'),('gap','새 관절 축방향 여유'),('uncertainty','검토용 지름 허용편차 ±')]:
            w=number(getattr(p,key),0,5,' mm');w.setDecimals(3);w.setSingleStep(.05);self.inputs[key]=w;form.addRow(title,w);w.valueChanged.connect(self.schedule)
        row=QHBoxLayout();row.addWidget(button('PLA 시작값 · 0.2',lambda:self.defaults(.2)));row.addWidget(button('모든 값 0',lambda:self.defaults(0)));self.controls.addLayout(row)
        self.controls.addWidget(label('지름 +0.2는 한쪽 반경 +0.1입니다. 축 Ø10 / 구멍 Ø10에 기본값을 적용하면 구멍 Ø10.2가 됩니다. ±허용편차는 형상을 바꾸지 않는 검토값입니다. 시험 출력으로 보정하세요.',True))
        self.table=QTableWidget(len(self.rows),4);self.table.setHorizontalHeaderLabels(['적용 / 대상','종류','현재 Ø','적용 후 Ø']);self.table.setMinimumHeight(130);self.table.setMaximumHeight(230);self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        for col in (1,2,3):self.table.setColumnWidth(col,70)
        # Keep the target table above the preview so long names and dimensions
        # remain usable without squeezing the small settings column.
        self.layout().insertWidget(2,self.table)
        if not self.rows:
            self.table.hide();self.layout().insertWidget(2,label('현재 연결 가능한 원형 치수가 없습니다. 프로필을 저장한 뒤 부품이나 구멍을 추가하세요.',True))
        for index,r in enumerate(self.rows):
            item=QTableWidgetItem(r['label']);item.setFlags((item.flags()|Qt.ItemFlag.ItemIsUserCheckable)&~Qt.ItemFlag.ItemIsEditable);item.setCheckState(Qt.CheckState.Checked if r['linked'] else Qt.CheckState.Unchecked);item.setToolTip('/'.join(map(str,r['path'])));self.table.setItem(index,0,item)
            for col,value in [(1,'축' if r['role']=='shaft' else '구멍'),(2,f"{r['value']:.3f}"),(3,'—')]:
                cell=QTableWidgetItem(value);cell.setFlags(cell.flags()&~Qt.ItemFlag.ItemIsEditable);self.table.setItem(index,col,cell)
        row=QHBoxLayout()
        for title,fn in [('전체 연결',lambda:self.check_rows(True)),('연결 해제',lambda:self.check_rows(False)),('선택 부품만',lambda:self.check_rows(True,set(selected_ids)))]:row.addWidget(button(title,fn))
        self.controls.addLayout(row)
        self.controls.addWidget(label('목록에서 체크한 치수만 보정합니다. 체크 해제는 원래 치수/식 복원, 보정 사용 해제는 연결 유지입니다. 일반 부품·원형 구멍을 지원합니다. 나사·가져온 메시·연결 스케치·구속 스케치는 원본 도구에서 편집하세요.\n새 관절의 축방향 여유는 생성 시 기본값입니다. 기존 관절 위치는 바꾸지 않습니다. 프린터 전체 오차를 자동 측정하거나 표준 공차 등급을 인증하지 않습니다.',True))
        row=QHBoxLayout();row.addWidget(button('프로필 저장',self.save_profile));row.addWidget(button('프로필 불러오기',self.load_profile));self.controls.addLayout(row);self.controls.addStretch()
        self.table.itemChanged.connect(self.schedule);self.enabled.toggled.connect(self.schedule);self.name.textChanged.connect(self.schedule);self.material.textChanged.connect(self.schedule);self.schedule()

    def profile(self):
        return PrintProfile(name=self.name.text().strip(),material=self.material.text().strip(),enabled=self.enabled.isChecked(),**{k:w.value() for k,w in self.inputs.items()})

    def defaults(self,value):
        for key,w in self.inputs.items():w.setValue(value if key in ('hole_expansion','gap') else 0)
        self.enabled.setChecked(True);self.schedule()

    def check_rows(self,checked,ids=None):
        self.table.blockSignals(True)
        try:
            for i,r in enumerate(self.rows):self.table.item(i,0).setCheckState(Qt.CheckState.Checked if checked and (ids is None or r['part'] in ids) else Qt.CheckState.Unchecked)
        finally:self.table.blockSignals(False)
        self.schedule()

    def candidate(self):
        selected=[r['path'] for i,r in enumerate(self.rows) if self.table.item(i,0).checkState()==Qt.CheckState.Checked]
        return apply_print_profile(self.base,self.profile(),selected).model_dump()

    def present(self):
        super().present();result={tuple(r['path']):r for r in print_targets(self.checked)};self.table.blockSignals(True)
        try:
            for i,row in enumerate(self.rows):self.table.item(i,3).setText(f"{result[tuple(row['path'])]['value']:.3f}")
        finally:self.table.blockSignals(False)

    def save_profile(self):
        try:p=self.profile()
        except ValueError as exc:self.failed(str(exc));return
        path,_=QFileDialog.getSaveFileName(self,'프린터 프로필 저장','printer-profile.json','JSON (*.json)')
        if path:
            try:Path(path).write_text(json.dumps(p.model_dump(),ensure_ascii=False,indent=2),encoding='utf-8')
            except OSError as exc:self.failed(str(exc))

    def load_profile(self):
        path,_=QFileDialog.getOpenFileName(self,'프린터 프로필 불러오기','','JSON (*.json)')
        if not path:return
        try:
            if Path(path).stat().st_size>16000:raise ValueError('프로필 파일이 너무 큽니다.')
            p=PrintProfile.model_validate_json(Path(path).read_text(encoding='utf-8-sig'))
            self.name.setText(p.name);self.material.setText(p.material);self.enabled.setChecked(p.enabled)
            for key,w in self.inputs.items():w.setValue(getattr(p,key))
            self.schedule()
        except (ValueError,OSError) as exc:self.failed(str(exc))
