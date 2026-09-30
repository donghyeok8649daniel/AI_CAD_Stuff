"""Native electrical workbench: explicit component pins and bounded DC checks."""
from copy import deepcopy
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox,QComboBox,QDialog,QDialogButtonBox,QFormLayout,
    QHBoxLayout,QLabel,QLineEdit,QMessageBox,QPlainTextEdit,QScrollArea,
    QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget)

from .widgets import button,label,number


KINDS=[('battery','배터리 / DC 전원'),('wire','전선'),('switch','스위치'),
       ('resistor','저항'),('load','일반 부하'),('motor','모터'),('mcu','MCU 전원 부하')]
KIND_NAMES=dict(KINDS)
FIELDS=[
    ('voltage_v','공급 전압',' V',('battery',)),
    ('internal_resistance_ohm','배터리 내부저항',' Ω',('battery',)),
    ('resistance_ohm','저항값',' Ω',('resistor',)),
    ('rated_voltage_v','정격 전압',' V',('load','motor','mcu')),
    ('rated_current_a','정격 전류',' A',('load','motor','mcu')),
    ('startup_current_a','명시한 기동 전류 · 0은 미입력',' A',('motor',)),
    ('length_mm','전선 길이',' mm',('wire',)),
    ('cross_section_mm2','도체 단면적',' mm²',('wire',)),
    ('resistivity_ohm_mm2_per_m','도체 저항률',' Ω·mm²/m',('wire',)),
    ('contact_resistance_ohm','닫힌 접점 저항',' Ω',('switch',)),
    ('max_current_a','허용 전류 · 0은 미입력',' A',('battery','wire','switch'))]
DEFAULTS={'battery':dict(voltage_v=12,internal_resistance_ohm=.08,max_current_a=2),
          'wire':dict(length_mm=500,cross_section_mm2=.5,resistivity_ohm_mm2_per_m=.01724,max_current_a=2),
          'switch':dict(contact_resistance_ohm=.01,closed=True),
          'resistor':dict(resistance_ohm=100),
          'load':dict(rated_voltage_v=12,rated_current_a=.5),
          'motor':dict(rated_voltage_v=12,rated_current_a=1),
          'mcu':dict(rated_voltage_v=5,rated_current_a=.15)}


class ComponentDialog(QDialog):
    def __init__(self,parent,parts,existing=None):
        super().__init__(parent);self.setWindowTitle('전장 부품 / 배선 편집');self.resize(470,620)
        old=deepcopy(existing or {});layout=QVBoxLayout(self);body=QWidget();form=QFormLayout(body)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(body);layout.addWidget(scroll,1)
        self.name=QLineEdit(old.get('name',''));form.addRow('이름',self.name)
        self.kind=QComboBox()
        for key,title in KINDS:self.kind.addItem(title,key)
        self.kind.setCurrentIndex(max(0,self.kind.findData(old.get('kind','battery'))));form.addRow('종류',self.kind)
        self.a=QLineEdit(old.get('a','VPLUS'));self.b=QLineEdit(old.get('b','GND'))
        form.addRow('첫 번째 단자 / 노드',self.a);form.addRow('두 번째 단자 / 노드',self.b)
        self.part=QComboBox();self.part.addItem('CAD 부품에 연결하지 않음','')
        for item in parts:self.part.addItem(item['name']+' · '+item['id'],item['id'])
        if old.get('part_id') and self.part.findData(old['part_id'])<0:
            self.part.addItem('CAD 부품이 없어짐 · '+old['part_id'],old['part_id'])
        self.part.setCurrentIndex(max(0,self.part.findData(old.get('part_id',''))));form.addRow('CAD 부품',self.part)
        self.inputs={};self.rows={}
        for key,title,suffix,kinds in FIELDS:
            value=old.get(key)
            if value is None:value=0 if key in old else DEFAULTS.get(old.get('kind','battery'),{}).get(key,0)
            field=number(value,0,1000000,suffix,decimals=6);form.addRow(title,field)
            self.inputs[key]=field;self.rows[key]=(form.labelForField(field),field,kinds)
        self.closed=QCheckBox('스위치 닫힘');self.closed.setChecked(old.get('closed',True));form.addRow(self.closed)
        layout.addWidget(label('초기 수치는 가상 예시입니다. 실제 정격·전선 치수로 바꾸세요. 노드 이름은 영문·숫자·_·-만 쓰며 회로 계산은 DC 정상 상태 근사입니다.',True))
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(self.accept);controls.rejected.connect(self.reject);layout.addWidget(controls)
        self.kind.currentIndexChanged.connect(self.refresh_fields);self.refresh_fields()
        self.identifier=old.get('id') or 'electrical-'+uuid4().hex[:10]

    def refresh_fields(self):
        kind=self.kind.currentData()
        for key,(caption,field,kinds) in self.rows.items():
            caption.setVisible(kind in kinds);field.setVisible(kind in kinds)
            if kind in kinds and field.value()==0 and key in DEFAULTS.get(kind,{}):
                field.setValue(DEFAULTS[kind][key])
        self.closed.setVisible(kind=='switch')

    def candidate(self):
        kind=self.kind.currentData()
        values={key:field.value() for key,field in self.inputs.items()
                for _,_,kinds in [self.rows[key]] if kind in kinds}
        for optional in ('max_current_a','startup_current_a'):
            if values.get(optional)==0:values[optional]=None
        return dict(id=self.identifier,name=self.name.text().strip() or KIND_NAMES[kind],kind=kind,
                    a=self.a.text().strip(),b=self.b.text().strip(),part_id=self.part.currentData(),
                    closed=self.closed.isChecked(),**values)

    def accept(self):
        from ..electrical import ElectricalComponent
        try:ElectricalComponent.model_validate(self.candidate())
        except ValueError as exc:QMessageBox.warning(self,'전장 부품 입력 확인',str(exc)[:1000]);return
        super().accept()


class ElectricalDialog(QDialog):
    def __init__(self,parent,design):
        super().__init__(parent);self.setWindowTitle('전장 · 배선 / 전압강하 검사');self.resize(900,730)
        self.parts=(design or {}).get('parts',[]);self.components=deepcopy((design or {}).get('electrical',{} ) or {}).get('components',[])
        layout=QVBoxLayout(self);layout.addWidget(label('배터리·전선·모터·MCU의 두 단자를 노드 이름으로 연결합니다. 실제 제품 정격과 전선 치수를 입력하세요.',True))
        header=QHBoxLayout();self.name=QLineEdit(((design or {}).get('electrical') or {}).get('name','전장 회로'))
        header.addWidget(QLabel('회로 이름'));header.addWidget(self.name,1);layout.addLayout(header)
        self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(['이름','종류','첫 단자','둘째 단자','CAD 부품','주요 입력'])
        self.table.setObjectName('electricalComponents')
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True);layout.addWidget(self.table,1)
        row=QHBoxLayout();row.addWidget(button('부품 / 전선 추가…',self.add,True));row.addWidget(button('선택 편집…',self.edit));row.addWidget(button('선택 제거',self.remove));
        row.addWidget(button('예시 회로 · 가상값',self.demo));layout.addLayout(row)
        layout.addWidget(label('GND는 기준 전위입니다. 이름이 다른 단자는 이어지지 않습니다. 적색 경고는 초과·단선·검증 불가를 뜻합니다.',True))
        self.report=QPlainTextEdit();self.report.setReadOnly(True);self.report.setMinimumHeight(130);layout.addWidget(self.report)
        self.report.setObjectName('electricalReport')
        bottom=QDialogButtonBox();self.check_button=bottom.addButton('회로 다시 계산',QDialogButtonBox.ButtonRole.ActionRole)
        self.apply_button=bottom.addButton('설계에 저장',QDialogButtonBox.ButtonRole.AcceptRole)
        bottom.addButton('닫기',QDialogButtonBox.ButtonRole.RejectRole)
        self.check_button.clicked.connect(self.calculate);self.apply_button.clicked.connect(self.accept)
        bottom.rejected.connect(self.reject);layout.addWidget(bottom)
        self.name.textChanged.connect(self.stale);self.table.doubleClicked.connect(self.edit);self.refresh();self.calculate()

    def stale(self):self.report.setPlainText('입력이 바뀌었습니다. 회로를 다시 계산하세요.')
    def refresh(self):
        names={part['id']:part['name'] for part in self.parts};self.table.setRowCount(len(self.components))
        for row,part in enumerate(self.components):
            notable=next((f'{part[key]:g} {unit}' for key,unit in [('voltage_v','V'),('resistance_ohm','Ω'),('rated_current_a','A'),('length_mm','mm')] if part.get(key)), '')
            linked=names.get(part.get('part_id'),'')
            if part.get('part_id') and not linked:linked='없는 CAD 부품 · '+part['part_id']
            for col,text in enumerate((part['name'],KIND_NAMES[part['kind']],part['a'],part['b'],linked,notable)):
                item=QTableWidgetItem(str(text));item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable);self.table.setItem(row,col,item)
        self.table.resizeColumnsToContents();self.stale()

    def add(self):
        dialog=ComponentDialog(self,self.parts)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.components.append(dialog.candidate());self.refresh();self.calculate()

    def edit(self,*args):
        row=self.table.currentRow()
        if row<0:return
        dialog=ComponentDialog(self,self.parts,self.components[row])
        if dialog.exec()==QDialog.DialogCode.Accepted:self.components[row]=dialog.candidate();self.refresh();self.calculate()

    def remove(self):
        row=self.table.currentRow()
        if row>=0:self.components.pop(row);self.refresh();self.calculate()

    def demo(self):
        if self.components and QMessageBox.question(self,'예시로 바꾸기','현재 회로를 예시 회로로 교체할까요?')!=QMessageBox.StandardButton.Yes:return
        self.components=[
            dict(id='demo-battery',name='가상 12 V 배터리',kind='battery',a='VPLUS',b='GND',voltage_v=12,internal_resistance_ohm=.08,max_current_a=2),
            dict(id='demo-switch',name='가상 스위치',kind='switch',a='VPLUS',b='SWITCHED',contact_resistance_ohm=.01,closed=True),
            dict(id='demo-wire',name='가상 500 mm 전선',kind='wire',a='SWITCHED',b='MOTORPLUS',length_mm=500,cross_section_mm2=.5,max_current_a=2),
            dict(id='demo-motor',name='가상 DC 모터',kind='motor',a='MOTORPLUS',b='GND',rated_voltage_v=12,rated_current_a=1,startup_current_a=4)]
        self.refresh();self.calculate()

    def candidate(self):
        from ..electrical import ElectricalWorkspace
        nodes=sorted({'GND',*(name for item in self.components for name in (item['a'],item['b']))})
        return ElectricalWorkspace.model_validate(dict(name=self.name.text().strip() or '전장 회로',nodes=nodes,components=self.components))

    def calculate(self):
        from ..electrical import evaluate_electrical
        try:
            workspace=self.candidate();result=evaluate_electrical(workspace)
            if not workspace.components:self.report.setPlainText('회로가 비어 있습니다. 전원·전선·부하를 추가해 두 단자의 노드 이름을 연결하세요.');return
            lines=['정상 상태 · DC 저항 근사',
                   '노드 전압: '+', '.join(f'{name} {value:.4g} V' for name,value in result.node_voltages_v.items())]
            for part in result.components:
                drop='미확정' if part.voltage_drop_v is None else f'{part.voltage_drop_v:.4g} V'
                power=f'공급 {abs(part.power_w):.4g} W' if part.kind=='battery' else f'소비 {part.power_w:.4g} W'
                lines.append(f'{part.name}: {part.current_a:.4g} A · 전압차 {drop} · {power}')
            lines.append(f'공급 / 소비 전력: {result.source_power_w:.4g} / {result.absorbed_power_w:.4g} W')
            if result.warnings:lines.extend(['주의: '+warning for warning in result.warnings])
            if result.startup:
                lines.append('모터 기동 · 입력한 기동 전류로 별도 근사')
                lines.extend(f'{part.name}: {part.current_a:.4g} A · 전압차 {part.voltage_drop_v:.4g} V'
                    for part in result.startup.components if part.kind=='motor' and part.voltage_drop_v is not None)
                lines.extend(['기동 주의: '+warning for warning in result.startup.warnings])
            missing={part.part_id for part in workspace.components if part.part_id and part.part_id not in {p['id'] for p in self.parts}}
            if missing:lines.append('주의: 연결된 CAD 부품을 찾지 못함 · '+', '.join(sorted(missing)))
            self.report.setPlainText('\n'.join(lines))
        except (ValueError,TypeError) as exc:self.report.setPlainText('회로 계산을 완료하지 못했습니다. '+str(exc)[:600])

    def accept(self):
        try:self.workspace=self.candidate()
        except (ValueError,TypeError) as exc:QMessageBox.warning(self,'전장 입력 확인',str(exc)[:1000]);return
        from ..electrical import evaluate_electrical
        if self.workspace.components:
            try:evaluate_electrical(self.workspace)
            except ValueError as exc:
                if QMessageBox.question(self,'미검증 회로 저장',
                    '회로 계산이 완료되지 않았습니다. 배선 초안으로 저장할까요?\n'+str(exc)[:500])!=QMessageBox.StandardButton.Yes:return
        super().accept()
