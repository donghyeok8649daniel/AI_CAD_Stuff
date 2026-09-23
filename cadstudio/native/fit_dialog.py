"""Saved fit calculation linked to CAD shaft and circular-hole dimensions."""
import csv
from pathlib import Path
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QGroupBox,QFileDialog
from .widgets import label,button,number
from .workflows import choice
from .geometry import uid
from ..models import Design
from ..fits import FitSettings,diameter_choices,calculate_fit


class FitDialog(QDialog):
    def __init__(self,parent,design,identifier=None):
        super().__init__(parent);self.setWindowTitle('축 / 구멍 공차 · 끼워맞춤');self.resize(700,570);self.base=Design.model_validate(design);self.identifier=identifier or 'fit-'+uid();self.inputs={};self.refs={};self.output=None
        old=next((s for s in self.base.studies if s.id==identifier),None);settings=FitSettings.model_validate(old.settings if old else {})
        v=QVBoxLayout(self);v.addWidget(label('상한 / 하한은 기준 지름에 더하는 편차입니다. 단위 mm · 예: 하한 -0.020, 상한 0.000',True));row=QHBoxLayout();v.addLayout(row)
        for side,title in [('shaft','축'),('hole','구멍')]:
            group=QGroupBox(title);form=QFormLayout(group);form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows);row.addWidget(group)
            candidates=diameter_choices(self.base,side);ref=choice([('', '직접 입력')]+[(c['ref'],c['label']) for c in candidates]);self.refs[side]=ref;form.addRow('형상 연결',ref)
            saved=getattr(settings,side+'_ref')
            if saved and ref.findData(saved)<0:ref.addItem('삭제된 참조 · 다시 선택',saved)
            if old:ref.setCurrentIndex(ref.findData(saved))
            elif candidates:ref.setCurrentIndex(1)
            for field,name,lo,hi in [('nominal','기준 지름',.001,2000),('upper','상한 편차',-100,100),('lower','하한 편차',-100,100)]:
                key=side+'_'+field;w=number(getattr(settings,key),lo,hi,' mm');w.setDecimals(4);w.setSingleStep(.001 if field!='nominal' else 1);self.inputs[key]=w;form.addRow(name,w)
        self.result=label('');self.result.setStyleSheet('padding:16px;background:#172d36;color:#a8efdb;font-size:14px;');v.addWidget(self.result)
        v.addWidget(label('3D 형상은 기준 치수를 유지하며 제작 허용 범위를 별도로 저장합니다. 양수 틈새는 여유, 음수는 간섭입니다. 원통도·동축도·온도·변형·끼워넣는 힘은 포함하지 않습니다. ISO 끼워맞춤 등급을 자동 인증하지 않습니다.',True))
        buttons=QHBoxLayout();self.save_button=button('공차를 작업 기록에 저장',self.accept,True);buttons.addWidget(self.save_button);self.csv_button=button('공차표 CSV',self.export_csv);buttons.addWidget(self.csv_button);buttons.addWidget(button('닫기',self.reject));v.addLayout(buttons)
        for w in self.inputs.values():w.valueChanged.connect(self.calculate)
        for w in self.refs.values():w.currentIndexChanged.connect(self.calculate)
        self.calculate()
    def calculate(self,*args):
        try:
            for side,ref in self.refs.items():
                w=self.inputs[side+'_nominal'];w.setEnabled(not ref.currentData());item=next((c for c in diameter_choices(self.base,side) if c['ref']==ref.currentData()),None)
                if item:w.blockSignals(True);w.setValue(item['nominal']);w.blockSignals(False)
            self.settings=FitSettings(**{k:w.value() for k,w in self.inputs.items()},**{side+'_ref':w.currentData() for side,w in self.refs.items()});r=calculate_fit(self.base,self.settings);self.output=r
            self.result.setText(f"{r['kind']}\n축 Ø{r['shaft']['low']:.4f} ~ {r['shaft']['high']:.4f} mm\n구멍 Ø{r['hole']['low']:.4f} ~ {r['hole']['high']:.4f} mm\n지름 기준 틈새 {r['minimum']:+.4f} ~ {r['maximum']:+.4f} mm");self.save_button.setEnabled(True);self.csv_button.setEnabled(True)
        except ValueError as exc:self.output=None;self.result.setText(str(exc));self.save_button.setEnabled(False);self.csv_button.setEnabled(False)
    def accept(self):
        if not self.output:return
        raw=self.base.model_dump();raw['studies']=[s for s in raw['studies'] if s['id']!=self.identifier]+[dict(id=self.identifier,kind='fit',name='축 / 구멍 공차',settings=self.settings.model_dump())];self.candidate=raw;super().accept()
    def export_csv(self):
        if not self.output:return
        path,_=QFileDialog.getSaveFileName(self,'공차표 저장','fit.csv','CSV (*.csv)')
        if not path:return
        with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.writer(f);writer.writerow(['대상','형상','기준 mm','최소 mm','최대 mm'])
            for side,title in [('shaft','축'),('hole','구멍')]:r=self.output[side];writer.writerow([title,r['label'],r['nominal'],r['low'],r['high']])
            writer.writerow(['지름 틈새',self.output['kind'],'',self.output['minimum'],self.output['maximum']])
