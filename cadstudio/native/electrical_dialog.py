"""Native electrical workbench: explicit component pins and bounded DC checks."""
from copy import deepcopy
from uuid import uuid4

from PySide6.QtCore import Qt,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox,QComboBox,QDialog,QDialogButtonBox,QFormLayout,
    QHBoxLayout,QLabel,QLineEdit,QMessageBox,QPlainTextEdit,QScrollArea,
    QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget)

from .widgets import button,label,number


KINDS=[('battery','배터리 / DC 전원'),('wire','전선'),('switch','스위치'),
       ('resistor','저항'),('load','일반 부하'),('motor','모터'),('mcu','MCU / 보드 전원 부하')]
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
DEFAULTS={'battery':{},
          'wire':dict(length_mm=500,cross_section_mm2=.5,resistivity_ohm_mm2_per_m=.01724,max_current_a=2),
          'switch':dict(contact_resistance_ohm=.01,closed=True),
          'resistor':dict(resistance_ohm=100),
          'load':dict(rated_voltage_v=12,rated_current_a=.5),
          'motor':dict(rated_voltage_v=12,rated_current_a=1),
          'mcu':dict(rated_voltage_v=5,rated_current_a=.15)}


class CatalogDialog(QDialog):
    """Local, source-linked parts finder; reference-only rows cannot prefill a circuit."""

    def __init__(self,parent,query=''):
        super().__init__(parent)
        self.setWindowTitle('제품 자료 찾기 · 오프라인 카탈로그')
        self.resize(860,560)
        self.entry=None
        layout=QVBoxLayout(self)
        layout.addWidget(label('특정 모델만 회로 항목에 적용합니다. 제품군과 미지원 소자는 공식 자료를 열어 볼 수 있지만, 검증되지 않은 수치를 자동 입력하지 않습니다.',True))
        row=QHBoxLayout()
        self.query=QLineEdit(query)
        self.query.setPlaceholderText('모델명 · 제조사 · 제품군 검색')
        row.addWidget(self.query,1)
        row.addWidget(button('검색',self.search))
        layout.addLayout(row)
        self.table=QTableWidget(0,4)
        self.table.setHorizontalHeaderLabels(['분류','제조사','모델 / 제품군','회로 적용'])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table,1)
        self.details=QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(120)
        layout.addWidget(self.details)
        actions=QHBoxLayout()
        self.open_button=button('공식 자료 열기',self.open_source)
        self.use_button=button('선택 모델 입력',self.choose,True)
        actions.addWidget(self.open_button)
        actions.addStretch(1)
        actions.addWidget(self.use_button)
        actions.addWidget(button('닫기',self.reject))
        layout.addLayout(actions)
        self.query.returnPressed.connect(self.search)
        self.table.itemSelectionChanged.connect(self.update_selection)
        self.table.doubleClicked.connect(lambda *_:self.choose())
        self.search()

    def search(self):
        from ..electrical_catalog import search_catalog

        self.entries=search_catalog(self.query.text())
        self.table.setRowCount(len(self.entries))
        for row,entry in enumerate(self.entries):
            values=(entry.category,entry.manufacturer,entry.model,
                    '자료만 열람' if entry.reference_only or entry.suggested_kind is None else '특정 모델 · 입력 가능')
            for col,value in enumerate(values):
                self.table.setItem(row,col,QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
        if self.entries:self.table.selectRow(0)
        else:self.details.setPlainText('일치하는 자료가 없습니다. 정확한 모델명이나 제품군 이름으로 검색하세요.')
        self.update_selection()

    def selected(self):
        row=self.table.currentRow()
        return self.entries[row] if 0<=row<len(self.entries) else None

    def update_selection(self):
        entry=self.selected()
        self.open_button.setEnabled(bool(entry and entry.source_url))
        self.use_button.setEnabled(bool(entry and entry.suggested_kind and not entry.reference_only))
        if entry:
            use='자료 열람 전용 · 이 항목은 DC 회로 모델로 자동 변환하지 않습니다.' if entry.reference_only or not entry.suggested_kind else '특정 모델 · 확인된 사양만 입력됩니다. 빠진 수치는 직접 입력하세요.'
            self.details.setPlainText(f'{entry.display_name}\n{entry.spec_summary}\n{use}\n출처: {entry.source_url}')

    def open_source(self):
        entry=self.selected()
        if entry and entry.source_url:QDesktopServices.openUrl(QUrl(entry.source_url))

    def choose(self):
        entry=self.selected()
        if not entry:return
        if entry.reference_only or not entry.suggested_kind:
            QMessageBox.information(self,'자료 열람 전용','이 항목은 특정 동작 정격을 확정할 수 없어 회로 입력을 자동 생성하지 않습니다. 공식 자료에서 제품 변형과 조건을 확인하세요.')
            return
        self.entry=entry
        self.accept()


class ComponentDialog(QDialog):
    def __init__(self,parent,parts,existing=None):
        super().__init__(parent);self.setWindowTitle('전장 부품 / 배선 편집');self.resize(470,620)
        old=deepcopy(existing or {});layout=QVBoxLayout(self);body=QWidget();form=QFormLayout(body)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(body);layout.addWidget(scroll,1)
        self.old=old
        self.name=QLineEdit(old.get('name',''));form.addRow('이름',self.name)
        self.analysis_enabled=QCheckBox('정격 입력 완료 · DC 계산에 포함');self.analysis_enabled.setObjectName('electricalAnalysisEnabled');self.analysis_enabled.setChecked(old.get('analysis_enabled',True));form.addRow(self.analysis_enabled)
        self.catalog_id=old.get('catalog_id','')
        self.source_url=old.get('source_url','')
        self.catalog_kind=old.get('kind','battery')
        catalog_row=QWidget();catalog_layout=QHBoxLayout(catalog_row)
        catalog_layout.setContentsMargins(0,0,0,0)
        self.catalog_button=button('모델 찾기…',self.select_catalog);self.catalog_button.setEnabled(not old.get('part_registration',False));catalog_layout.addWidget(self.catalog_button)
        self.source_button=button('출처 열기',self.open_source)
        catalog_layout.addWidget(self.source_button)
        self.catalog_note=QLabel()
        self.catalog_note.setWordWrap(True)
        catalog_layout.addWidget(self.catalog_note,1)
        form.addRow('제품 자료',catalog_row)
        self.update_catalog_note()
        self.kind=QComboBox()
        for key,title in KINDS:self.kind.addItem(title,key)
        self.kind.setCurrentIndex(max(0,self.kind.findData(old.get('kind','battery'))));form.addRow('종류',self.kind)
        self.a=QLineEdit(old.get('a','VPLUS'));self.b=QLineEdit(old.get('b','GND'))
        form.addRow('첫 번째 단자 / 노드',self.a);form.addRow('두 번째 단자 / 노드',self.b)
        self.a_caption=form.labelForField(self.a);self.b_caption=form.labelForField(self.b)
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
        self.wire_connected=QCheckBox('전선 연결됨 · 해제하면 단선')
        self.wire_connected.setChecked(old.get('closed',True));form.addRow(self.wire_connected)
        self.power_enabled=QCheckBox('전원 인가 · 배터리 출력 켜기')
        self.power_enabled.setChecked(old.get('closed',True));form.addRow(self.power_enabled)
        pins=old.get('signal_pins') or {}
        self.signal_pins=QPlainTextEdit('\n'.join(f'{pin}={node}' for pin,node in pins.items()))
        self.signal_pins.setPlaceholderText('예: GPIO1=SIGNAL_A\nGPIO2=SIGNAL_B')
        self.signal_pins.setMinimumHeight(68)
        self.signal_pins.setMaximumHeight(110)
        form.addRow('MCU 신호 핀 = 노드 · 한 줄씩',self.signal_pins)
        self.signal_caption=form.labelForField(self.signal_pins)
        ports=old.get('terminal_pins') or {}
        self.terminal_pins=QPlainTextEdit('\n'.join(f'{pin}={node}' for pin,node in ports.items()))
        self.terminal_pins.setObjectName('electricalSignalTerminals')
        self.terminal_pins.setPlaceholderText('예: OUT_A=ENCODER_A\nPWM=MOTOR_PWM')
        self.terminal_pins.setMinimumHeight(68);self.terminal_pins.setMaximumHeight(110)
        form.addRow('추가 신호 단자 = 노드 · 센서 / 드라이버',self.terminal_pins)
        self.terminal_caption=form.labelForField(self.terminal_pins)
        self.pinout_catalog_id=old.get('pinout_catalog_id','')
        self.supply_fields={key:deepcopy(old[key]) for key in ('board_supply_pins','supply_pinout_catalog_id') if key in old}
        layout.addWidget(label('초기 수치는 가상 예시입니다. 실제 정격·전선 치수로 바꾸세요. 노드 이름은 영문·숫자·_·-만 쓰며 회로 계산은 DC 정상 상태 근사입니다.',True))
        layout.addWidget(label('MCU의 첫 단자는 VCC, 둘째 단자는 GND/리턴입니다. 신호 핀은 도통만 검사하며 코드·논리 동작은 검증하지 않습니다.',True))
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(self.accept);controls.rejected.connect(self.reject);layout.addWidget(controls)
        self.kind.setEnabled(not old.get('part_registration',False));self.part.setEnabled(not old.get('part_registration',False))
        self.kind.currentIndexChanged.connect(self.refresh_fields);self.refresh_fields()
        self.identifier=old.get('id') or 'electrical-'+uuid4().hex[:10]

    def refresh_fields(self):
        kind=self.kind.currentData()
        if self.catalog_id and kind!=self.catalog_kind:
            self.catalog_id='';self.source_url='';self.update_catalog_note()
        self.a_caption.setText('MCU VCC / 노드' if kind=='mcu' else '배터리 + / 공급 노드' if kind=='battery' else '첫 번째 단자 / 노드')
        self.b_caption.setText('MCU GND / 리턴 노드' if kind=='mcu' else '배터리 - / 리턴 노드' if kind=='battery' else '두 번째 단자 / 노드')
        for key,(caption,field,kinds) in self.rows.items():
            caption.setVisible(kind in kinds);field.setVisible(kind in kinds)
            if self.analysis_enabled.isChecked() and kind in kinds and field.value()==0 and key in DEFAULTS.get(kind,{}):
                field.setValue(DEFAULTS[kind][key])
        self.closed.setVisible(kind=='switch')
        self.wire_connected.setVisible(kind=='wire')
        self.power_enabled.setVisible(kind=='battery')
        self.signal_caption.setVisible(kind=='mcu');self.signal_pins.setVisible(kind=='mcu')
        self.terminal_caption.setVisible(kind in ('load','motor'));self.terminal_pins.setVisible(kind in ('load','motor'))

    def update_catalog_note(self):
        from ..electrical_catalog import get_catalog_entry

        entry=get_catalog_entry(self.catalog_id)
        self.catalog_note.setText(f'{entry.display_name} · 자료 연결' if entry else self.catalog_id or '수동 입력 · 자료 연결 없음')
        self.source_button.setEnabled(bool(self.source_url))

    def open_source(self):
        if self.source_url:QDesktopServices.openUrl(QUrl(self.source_url))

    def select_catalog(self):
        from ..electrical_catalog import component_prefill

        catalog=CatalogDialog(self,self.name.text().strip())
        if catalog.exec()!=QDialog.DialogCode.Accepted or not catalog.entry:return
        values=component_prefill(catalog.entry)
        if not values:return
        if values['catalog_id']!=self.catalog_id and (self.signal_pins.toPlainText().strip() or self.supply_fields.get('board_supply_pins')):
            if QMessageBox.question(self,'핀 연결 해제 확인','모델을 바꾸면 기존 MCU 핀 연결을 해제합니다. 계속할까요?')!=QMessageBox.StandardButton.Yes:return
            self.signal_pins.clear();self.pinout_catalog_id=''
            self.supply_fields={}
        self.catalog_id=''
        kind=values['kind']
        self.kind.setCurrentIndex(self.kind.findData(kind))
        self.catalog_kind=kind
        self.name.setText(values['name'])
        for key,field in self.inputs.items():
            if kind not in self.rows[key][2]:continue
            if key in values:field.setValue(values[key])
            elif key in ('rated_voltage_v','rated_current_a','voltage_v','length_mm','cross_section_mm2'):
                field.setValue(0)  # Missing operating data must not inherit fictional demo defaults.
        self.catalog_id=values['catalog_id']
        self.source_url=values['source_url']
        self.update_catalog_note()

    def parsed_signal_pins(self):
        return self.parsed_terminals(self.signal_pins)

    def parsed_terminals(self,field):
        pins={}
        for number,line in enumerate(field.toPlainText().splitlines(),1):
            line=line.strip()
            if not line:continue
            if line.count('=')!=1:
                raise ValueError(f'MCU 신호 핀 {number}행: 핀=노드 형식으로 입력하세요.')
            pin,node=(part.strip() for part in line.split('=',1))
            if not pin or not node or pin in pins:
                raise ValueError(f'MCU 신호 핀 {number}행: 핀과 노드를 쓰고 핀 이름을 중복하지 마세요.')
            pins[pin]=node
        return pins

    def candidate(self):
        kind=self.kind.currentData()
        values={key:field.value() for key,field in self.inputs.items()
                for _,_,kinds in [self.rows[key]] if kind in kinds}
        for optional in ('max_current_a','startup_current_a'):
            if values.get(optional)==0:values[optional]=None
        return dict(id=self.identifier,name=self.name.text().strip() or KIND_NAMES[kind],kind=kind,
                    a=self.a.text().strip(),b=self.b.text().strip(),part_id=self.part.currentData(),
                    catalog_id=self.catalog_id,source_url=self.source_url,analysis_enabled=self.analysis_enabled.isChecked(),
                    part_registration=self.old.get('part_registration',False),product_pinout_catalog_id=self.old.get('product_pinout_catalog_id',''),
                    closed=(self.wire_connected.isChecked() if kind=='wire' else self.power_enabled.isChecked() if kind=='battery' else self.closed.isChecked()),
                    **({'signal_pins':self.parsed_signal_pins(),'pinout_catalog_id':self.pinout_catalog_id if self.pinout_catalog_id==self.catalog_id else ''} if kind=='mcu' else {}),
                    **({'terminal_pins':self.parsed_terminals(self.terminal_pins)} if kind in ('load','motor') else {}),
                    **self.supply_fields,**values)

    def accept(self):
        from ..electrical import ElectricalComponent
        try:ElectricalComponent.model_validate(self.candidate())
        except ValueError as exc:QMessageBox.warning(self,'전장 부품 입력 확인',str(exc)[:1000]);return
        super().accept()


class ElectricalDialog(QDialog):
    def __init__(self,parent,design):
        super().__init__(parent);self.setWindowTitle('전장 · 배선 / 전압강하 검사');self.resize(900,730)
        self.parts=(design or {}).get('parts',[]);self.components=deepcopy((design or {}).get('electrical',{} ) or {}).get('components',[])
        self.original_nodes=tuple(((design or {}).get('electrical') or {}).get('nodes',()))
        self.schematic_positions=deepcopy(((design or {}).get('electrical') or {}).get('schematic_positions',{}))
        self.has_schematic_positions='schematic_positions' in ((design or {}).get('electrical') or {})
        layout=QVBoxLayout(self);layout.addWidget(label('배터리 +는 공급, -는 리턴입니다. 같은 노드 이름으로 단자를 연결하고 실제 배터리 전압·정격·전선 치수를 입력하세요.',True))
        header=QHBoxLayout();self.name=QLineEdit(((design or {}).get('electrical') or {}).get('name','전장 회로'))
        header.addWidget(QLabel('회로 이름'));header.addWidget(self.name,1);layout.addLayout(header)
        self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(['이름','종류','첫 단자','둘째 단자','CAD 부품','주요 입력'])
        self.table.setObjectName('electricalComponents')
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True);layout.addWidget(self.table,1)
        row=QHBoxLayout();row.addWidget(button('부품 / 전선 추가…',self.add,True));row.addWidget(button('선택 편집…',self.edit));row.addWidget(button('선택 제거',self.remove));
        row.addWidget(button('예시 회로 · 가상값',self.demo));layout.addLayout(row)
        circuit_actions=QHBoxLayout()
        self.power_path_button=button('전원 연결 설계…',self.new_power_path)
        self.power_path_button.setObjectName('electricalPowerPathButton')
        circuit_actions.addWidget(self.power_path_button)
        self.power_button=button('선택 배터리 전원 켜기/끄기',self.toggle_power)
        self.power_button.setObjectName('electricalPowerToggle')
        circuit_actions.addWidget(self.power_button)
        self.schematic_button=button('회로도 보기…',self.show_schematic)
        self.schematic_button.setObjectName('electricalSchematicButton')
        circuit_actions.addWidget(self.schematic_button)
        circuit_actions.addStretch(1)
        layout.addLayout(circuit_actions)
        pin_actions=QHBoxLayout()
        self.mcu_pin_button=button('MCU 선택 / 핀 연결…',self.edit_mcu_pins)
        self.mcu_pin_button.setObjectName('electricalMcuPinsButton');pin_actions.addWidget(self.mcu_pin_button)
        pin_actions.addWidget(label('MCU 핀을 클릭해 센서·드라이버·다른 보드 단자와 연결합니다.',True),1)
        layout.addLayout(pin_actions)
        layout.addWidget(label('GND는 기준 전위입니다. 이름이 다른 단자는 이어지지 않습니다. 보고서의 PASS / WARN / FAIL은 입력한 배선 모델에 대한 결과입니다.',True))
        self.report=QPlainTextEdit();self.report.setReadOnly(True);self.report.setMinimumHeight(130);layout.addWidget(self.report)
        self.report.setObjectName('electricalReport')
        bottom=QDialogButtonBox();self.check_button=bottom.addButton('회로 다시 계산',QDialogButtonBox.ButtonRole.ActionRole)
        self.apply_button=bottom.addButton('설계에 저장',QDialogButtonBox.ButtonRole.AcceptRole)
        bottom.addButton('닫기',QDialogButtonBox.ButtonRole.RejectRole)
        self.check_button.clicked.connect(self.calculate);self.apply_button.clicked.connect(self.accept)
        bottom.rejected.connect(self.reject);layout.addWidget(bottom)
        self.name.textChanged.connect(self.stale);self.table.doubleClicked.connect(self.edit)
        self.table.itemSelectionChanged.connect(self.update_power_button)
        self.refresh();self.calculate()

    def stale(self):self.report.setPlainText('입력이 바뀌었습니다. 회로를 다시 계산하세요.')
    def refresh(self):
        names={part['id']:part['name'] for part in self.parts};self.table.setRowCount(len(self.components))
        for row,part in enumerate(self.components):
            notable=next((f'{part[key]:g} {unit}' for key,unit in [('voltage_v','V'),('resistance_ohm','Ω'),('rated_current_a','A'),('length_mm','mm')] if part.get(key)), '')
            if not part.get('analysis_enabled',True):notable='정격 입력 전 · DC 계산 제외'
            elif part['kind']=='battery':notable=('전원 ON · ' if part.get('closed',True) else '전원 OFF · ')+notable
            if part['kind']=='wire' and not part.get('closed',True):notable='단선 · '+notable
            if part['kind']=='mcu' and part.get('signal_pins'):notable+=f" · 신호 {len(part['signal_pins'])}핀"
            linked=names.get(part.get('part_id'),'')
            if part.get('part_id') and not linked:linked='없는 CAD 부품 · '+part['part_id']
            for col,text in enumerate((part['name'],KIND_NAMES[part['kind']],part['a'],part['b'],linked,notable)):
                item=QTableWidgetItem(str(text));item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable);self.table.setItem(row,col,item)
        self.table.resizeColumnsToContents();self.update_power_button();self.stale()

    def update_power_button(self):
        row=self.table.currentRow()
        battery=0<=row<len(self.components) and self.components[row]['kind']=='battery'
        self.power_button.setEnabled(battery)
        if battery:
            self.power_button.setText('선택 배터리 전원 차단' if self.components[row].get('closed',True) else '선택 배터리 전원 인가')
        else:self.power_button.setText('배터리를 선택해 전원 전환')

    def toggle_power(self):
        row=self.table.currentRow()
        if row<0 or self.components[row]['kind']!='battery':return
        self.components[row]['closed']=not self.components[row].get('closed',True)
        self.refresh();self.table.selectRow(row);self.calculate()

    def show_schematic(self):
        from ..electrical import evaluate_electrical
        from .electrical_schematic import ElectricalSchematicDialog

        try:workspace=self.candidate()
        except (ValueError,TypeError) as exc:
            QMessageBox.warning(self,'회로도 입력 확인',str(exc)[:800]);return
        try:result=evaluate_electrical(workspace)
        except (ValueError,TypeError):result=None
        schematic=ElectricalSchematicDialog(self,workspace,result,self.parts)
        if schematic.exec()==QDialog.DialogCode.Accepted and schematic.accepted_workspace is not None:
            self.adopt_workspace(schematic.accepted_workspace)

    def adopt_workspace(self,workspace):
        self.components=[component.model_dump() for component in workspace.components]
        self.original_nodes=tuple(workspace.nodes)
        self.schematic_positions={key:position.model_dump() for key,position in workspace.schematic_positions.items()}
        self.has_schematic_positions='schematic_positions' in workspace.model_fields_set or bool(self.schematic_positions)
        self.refresh();self.calculate()

    def edit_mcu_pins(self):
        from .mcu_pin_dialog import McuPinDialog
        try:workspace=self.candidate()
        except (ValueError,TypeError) as exc:
            QMessageBox.warning(self,'MCU 입력 확인',str(exc)[:800]);return
        selected=self.table.currentRow()
        mcu_id=self.components[selected]['id'] if 0<=selected<len(self.components) and self.components[selected]['kind']=='mcu' else None
        dialog=McuPinDialog(self,workspace,self.parts,mcu_id)
        if dialog.exec()==QDialog.DialogCode.Accepted and dialog.accepted_workspace is not None:
            self.adopt_workspace(dialog.accepted_workspace)

    def new_power_path(self):
        from .power_path_dialog import PowerPathDialog

        try:workspace=self.candidate()
        except (ValueError,TypeError) as exc:
            QMessageBox.warning(self,'전원 연결 입력 확인',str(exc)[:800]);return
        dialog=PowerPathDialog(self,workspace,self.parts)
        if dialog.exec()!=QDialog.DialogCode.Accepted or dialog.build is None:return
        # Preserve the exact serialized shape of existing rows. The preview's
        # validated model expands defaults, but those need not rewrite old data.
        new_ids=set(dialog.build.ids.values())
        self.components.extend(component.model_dump() for component in dialog.build.workspace.components
                               if component.id in new_ids)
        self.refresh();self.calculate()

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
        nodes=sorted({'GND',*self.original_nodes,*(name for item in self.components for name in (item['a'],item['b'])),
                      *(node for item in self.components for node in item.get('signal_pins',{}).values()),
                      *(node for item in self.components for node in item.get('terminal_pins',{}).values()),
                      *(node for item in self.components for node in item.get('board_supply_pins',{}).values())})
        raw=dict(name=self.name.text().strip() or '전장 회로',nodes=nodes,components=self.components)
        if self.has_schematic_positions:
            ids={component['id'] for component in self.components}
            raw['schematic_positions']={key:position for key,position in self.schematic_positions.items() if key in ids}
        return ElectricalWorkspace.model_validate(raw)

    def calculate(self):
        from ..electrical import evaluate_electrical
        try:
            workspace=self.candidate();result=evaluate_electrical(workspace)
            if not workspace.components:self.report.setPlainText('회로가 비어 있습니다. 전원·전선·부하를 추가해 두 단자의 노드 이름을 연결하세요.');return
            lines=['정상 상태 · DC 저항 근사',
                   '노드 전압: '+', '.join(f'{name} {value:.4g} V' for name,value in result.node_voltages_v.items())]
            for part in result.components:
                if not part.analysis_enabled:
                    lines.append(part.name+': 정격 입력 전 · DC 계산 제외 · 소비전류 미확정');continue
                drop='미확정' if part.voltage_drop_v is None else f'{part.voltage_drop_v:.4g} V'
                power=f'공급 {abs(part.power_w):.4g} W' if part.kind=='battery' else f'소비 {part.power_w:.4g} W'
                lines.append(f'{part.name}: {part.current_a:.4g} A · 전압차 {drop} · {power}')
                if part.kind=='battery':
                    source=next(item for item in workspace.components if item.id==part.id)
                    lines.append(f"{'POWER ON' if source.closed else 'POWER OFF'} · {part.name}: 지정 전압 {source.voltage_v:.4g} V · "
                                 +('출력 허용' if source.closed else '출력 차단 · 저장된 전압 정격은 유지'))
            lines.append('전원·배선 정격 점검 · 입력값 기준이며 실제 제품 안전 인증은 아닙니다')
            source_by_id={part.id:part for part in workspace.components}
            for branch in result.components:
                if not branch.analysis_enabled:continue
                source=source_by_id[branch.id]
                current=abs(branch.current_a)
                if branch.kind=='battery':
                    open_power=source.voltage_v*branch.current_a
                    internal_loss=branch.current_a**2*source.internal_resistance_ohm
                    lines.append(f'{branch.name}: 개방전압×전류 {open_power:.4g} W · 단자 출력 {-branch.power_w:.4g} W · 배터리 내부 I²R {internal_loss:.4g} W')
                elif branch.kind=='wire':
                    lines.append(f'{branch.name}: 배선 전압강하 {abs(branch.voltage_drop_v or 0):.4g} V · 도체 I²R {branch.power_w:.4g} W')
                if branch.kind in ('battery','wire','switch'):
                    if source.max_current_a is None:
                        lines.append(f'WARN · {branch.name}: 허용 전류 미입력 · 용량 미검증')
                    elif current>source.max_current_a*(1+1e-8):
                        lines.append(f'FAIL · {branch.name}: {current:.4g} A > 입력 한계 {source.max_current_a:.4g} A')
                    else:
                        lines.append(f'CHECK · {branch.name}: 입력 한계까지 {source.max_current_a-current:.4g} A 여유')
            lines.append('결선 점검 · 입력한 모델의 도통과 MCU 전원 경로만 확인')
            for branch in result.components:
                if not branch.analysis_enabled:continue
                source=source_by_id[branch.id]
                if branch.kind=='wire' and not source.closed:
                    lines.append(f'FAIL · {branch.name}: 전선 단선 · {branch.a} ↔ {branch.b}')
                if branch.kind!='mcu':continue
                for title,value in (('VCC → DC 전원 양극 경로',getattr(branch,'supply_connected',None)),
                                    ('GND/리턴 → DC 전원 음극 경로',getattr(branch,'return_connected',None))):
                    status='PASS' if value is True else 'FAIL' if value is False else 'WARN'
                    description='연결' if value is True else '경로 없음' if value is False else '미확정'
                    lines.append(f'{status} · {branch.name}: {title} {description}')
                if getattr(branch,'supply_connected',None) is True and getattr(branch,'return_connected',None) is True:
                    value=branch.voltage_drop_v;rating=source.rated_voltage_v
                    if value is None:status='WARN';description='전압 미확정'
                    elif value<=0:status='FAIL';description=f'역극성 또는 전원 없음 · {value:.4g} V'
                    elif not .9*rating<=value<=1.1*rating:
                        status='WARN';description=f'{value:.4g} V · 입력 정격 {rating:.4g} V의 ±10% 밖'
                    else:status='PASS';description=f'{value:.4g} V · 입력 정격 {rating:.4g} V의 ±10% 안'
                    lines.append(f'{status} · {branch.name}: MCU 공급 전압 {description}')
                else:
                    lines.append(f'WARN · {branch.name}: 전원/리턴 배선이 불완전하여 공급 전압 판정을 보류합니다.')
                for pin,node in getattr(source,'signal_pins',{}).items():
                    connected=getattr(branch,'signal_pin_connected',{}).get(pin)
                    status='PASS' if connected is True else 'FAIL' if connected is False else 'WARN'
                    description='다른 단자까지 수동 도통 경로 있음' if connected is True else '다른 단자까지 도통 경로 없음' if connected is False else '미확정'
                    lines.append(f'{status} · {branch.name} {pin} ({node}): {description}')
            lines.append(f'전원 단자 출력 / 부하·저항 소비: {result.source_power_w:.4g} / {result.absorbed_power_w:.4g} W')
            if result.warnings:lines.extend(['주의: '+warning for warning in result.warnings])
            if result.startup:
                lines.append('모터 기동 · 입력한 기동 전류로 별도 근사')
                lines.extend(f'{part.name}: {part.current_a:.4g} A · 전압차 {part.voltage_drop_v:.4g} V'
                    for part in result.startup.components if part.kind=='motor' and part.voltage_drop_v is not None)
                for branch in result.startup.components:
                    if not branch.analysis_enabled:continue
                    source=source_by_id[branch.id]
                    if branch.kind not in ('battery','wire','switch'):continue
                    if source.max_current_a is None:
                        lines.append(f'WARN · 기동 {branch.name}: 허용 전류 미입력 · 용량 미검증')
                    elif abs(branch.current_a)>source.max_current_a*(1+1e-8):
                        lines.append(f'FAIL · 기동 {branch.name}: {abs(branch.current_a):.4g} A > 입력 한계 {source.max_current_a:.4g} A')
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
