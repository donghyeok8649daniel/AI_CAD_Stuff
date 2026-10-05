"""Register an existing CAD body as an electrical feature in a private draft."""
from copy import deepcopy
from types import SimpleNamespace

from PySide6.QtCore import Qt,QUrl,QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox,QDialog,QDialogButtonBox,QFormLayout,QHBoxLayout,
    QLabel,QLineEdit,QMessageBox,QSplitter,QVBoxLayout,QWidget,QCheckBox,QPlainTextEdit)

from ..models import Design
from ..electrical_registration import register_part,unregister_part
from ..electrical_catalog import CATALOG,get_catalog_entry
from ..board_pins import board_pinout
from ..product_diagrams import product_diagram
from .mcu_pin_dialog import PinDiagramView,word,english
from .widgets import button


def feature_connections(component,workspace):
    from ..mcu_connections import pin_connections,connection_endpoints
    if component.kind=='mcu':return pin_connections(workspace,component.id)
    diagram=product_diagram(component.catalog_id)
    physical=list(diagram.terminals) if diagram else []
    known={p.key for p in physical}
    physical.extend(SimpleNamespace(key=key,label=key,functions=(),kind='signal')
                    for key in component.terminal_pins if key not in known)
    endpoints=connection_endpoints(workspace,exclude_mcu_id=component.id)
    return [SimpleNamespace(key=p.key,label=p.label,functions=p.functions,kind=p.kind,
                            node=component.terminal_pins.get(p.key),legacy=p.key not in known,
                            targets=tuple(e for e in endpoints if e.node is not None and e.node==component.terminal_pins.get(p.key)))
            for p in physical]


class ElectricalPartDialog(QDialog):
    def __init__(self,parent,design,part_id=None):
        super().__init__(parent);self.setWindowTitle(word('CAD 부품 · 전장 등록 / 모식도','CAD part · electrical registration / diagram'))
        self.resize(1100,800);self.original=Design.model_validate(design);self.draft=self.original.model_copy(deep=True)
        self.checked=None;self.selected_terminal='';self.confirm_drop=False;self._refreshing=False
        layout=QVBoxLayout(self);header=QFormLayout()
        self.part_combo=QComboBox();self.part_combo.setObjectName('electricalRegisterPart')
        for p in self.draft.parts:self.part_combo.addItem(p.name+' · '+p.id,p.id)
        if part_id:self.part_combo.setCurrentIndex(max(0,self.part_combo.findData(part_id)))
        header.addRow(word('등록할 CAD 부품','CAD part to register'),self.part_combo)
        layout.addLayout(header)
        splitter=QSplitter(Qt.Orientation.Horizontal);fields=QWidget();form=QFormLayout(fields)
        self.model_filter=QLineEdit();self.model_filter.setObjectName('electricalModelFilter')
        self.model_filter.setPlaceholderText(word('정확한 모델명 검색 · 예: Raspberry Pi 4','Find an exact model · e.g. Raspberry Pi 4'))
        form.addRow(word('모델 검색','Find model'),self.model_filter)
        self.model_combo=QComboBox();self.model_combo.setObjectName('electricalRegisterModel');self.model_combo.setMinimumContentsLength(25)
        self.model_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        form.addRow(word('실제 제품 모델','Actual product model'),self.model_combo)
        self.kind_combo=QComboBox();self.kind_combo.setObjectName('electricalRegisterKind')
        for key,ko,en in [('mcu','MCU / MPU 보드','MCU / MPU board'),('motor','모터','Motor'),('actuator','액추에이터','Actuator'),('load','센서 / 드라이버 / 전자제품','Sensor / driver / electronics'),('battery','배터리 / 전원','Battery / source'),('wire','전선','Wire'),('switch','스위치','Switch'),('resistor','저항','Resistor'),('capacitor','커패시터 / 콘덴서','Capacitor'),('inductor','코일 / 인덕터','Coil / inductor')]:
            self.kind_combo.addItem(word(ko,en),key)
        form.addRow(word('회로에서의 종류','Circuit kind'),self.kind_combo)
        self.name=QLineEdit();self.name.setObjectName('electricalRegisterName');form.addRow(word('전장 피처 이름','Electrical feature name'),self.name)
        self.default_color=QCheckBox(word('전장 기본색 · 노란색 적용','Apply electrical default color · yellow'));self.default_color.setObjectName('electricalRegisterColor');form.addRow(self.default_color)
        self.note=QPlainTextEdit();self.note.setReadOnly(True);self.note.setFixedHeight(125);self.note.setObjectName('electricalModelNotes');form.addRow(self.note)
        self.source_button=button(word('공식 제품 / 핀 자료 열기','Open official product / pin reference'),self.open_source);form.addRow(self.source_button)
        self.register_button=button(word('전장 등록 · 미리보기','Register electrical feature · preview'),self.register_preview,True);self.register_button.setObjectName('electricalRegisterPreview');form.addRow(self.register_button)
        self.power_button=button(word('정격 / 전원 · 신호 단자 편집…','Edit ratings / power / signal terminals…'),self.edit_operating);self.power_button.setObjectName('electricalRegisterPower');form.addRow(self.power_button)
        self.pins_button=button(word('MCU 핀 연결…','MCU pin connections…'),self.edit_pins);self.pins_button.setObjectName('electricalRegisterPins');form.addRow(self.pins_button)
        self.unregister_button=button(word('전장 등록 해제 · CAD 형상 유지','Unregister electrical feature · retain CAD body'),self.unregister_preview);self.unregister_button.setObjectName('electricalUnregister');form.addRow(self.unregister_button)
        splitter.addWidget(fields)
        self.diagram=PinDiagramView(self);self.diagram.setObjectName('electricalFeatureDiagram');splitter.addWidget(self.diagram);splitter.setSizes([380,680]);layout.addWidget(splitter,1)
        self.status=QLabel();self.status.setWordWrap(True);self.status.setObjectName('electricalRegistrationStatus');layout.addWidget(self.status)
        self.warnings=QPlainTextEdit();self.warnings.setReadOnly(True);self.warnings.setMaximumHeight(88);self.warnings.setObjectName('electricalRegistrationWarnings');layout.addWidget(self.warnings)
        link=QHBoxLayout();self.terminal_label=QLabel(word('모식도의 단자를 클릭하세요.','Click a terminal in the diagram.'));link.addWidget(self.terminal_label)
        self.target=QComboBox();self.target.setObjectName('electricalFeatureTarget');link.addWidget(self.target,1)
        self.connect_button=button(word('단자 연결','Connect terminal'),self.connect_terminal);self.connect_button.setObjectName('electricalFeatureConnect');link.addWidget(self.connect_button);layout.addLayout(link)
        hint=QLabel(word('제품 등록은 형상을 변경하지 않습니다. 정격이 없으면 DC 계산에서 제외됩니다. 모식도는 공식 핀/단자 자료이며 내부 회로·PCB 치수·코드 동작을 재현하지 않습니다.',
                        'Registration preserves geometry. Missing ratings exclude the feature from DC analysis. Diagrams use official pin/terminal references, not internal circuit, PCB dimension or firmware models.'))
        hint.setWordWrap(True);layout.addWidget(hint)
        controls=QDialogButtonBox();self.apply_button=controls.addButton(word('설계에 저장','Save to design'),QDialogButtonBox.ButtonRole.AcceptRole);self.apply_button.setObjectName('electricalRegisterApply')
        controls.addButton(word('취소','Cancel'),QDialogButtonBox.ButtonRole.RejectRole);controls.accepted.connect(self.accept);controls.rejected.connect(self.reject);layout.addWidget(controls)
        self.part_combo.currentIndexChanged.connect(self.load_part);self.model_filter.textChanged.connect(self.filter_models);self.model_combo.currentIndexChanged.connect(self.model_changed)
        self.diagram.pin_clicked.connect(self.select_terminal);self.load_part()

    def showEvent(self,event):
        super().showEvent(event)
        self.diagram.fit()
        # Fit after the splitter has its actual visible viewport dimensions.
        QTimer.singleShot(0,self.diagram.fit)

    def current_part_id(self):return self.part_combo.currentData()
    def component(self):
        matches=[c for c in self.draft.electrical.components if c.part_id==self.current_part_id()] if self.draft.electrical else []
        if len(matches)>1:raise ValueError(word('이 CAD 부품에 연결된 전장 항목이 여러 개입니다. 전장 회로에서 중복 연결을 정리하세요.','Multiple circuit items reference this CAD part. Resolve the duplicate links in the circuit editor.'))
        return matches[0] if matches else None

    def filter_models(self,*_):
        prior=self.model_combo.currentData();query=self.model_filter.text().casefold().strip()
        self.model_combo.blockSignals(True);self.model_combo.clear();self.model_combo.addItem(word('사용자 정의 · 공식 모식도 없음','Custom · no verified diagram'),'')
        for entry in CATALOG:
            if (not entry.reference_only or product_diagram(entry.catalog_id)) and (not query or query in (entry.display_name+' '+entry.catalog_id+' '+entry.category+' '+' '.join(entry.aliases)).casefold()):
                self.model_combo.addItem(entry.display_name,entry.catalog_id)
        if prior and self.model_combo.findData(prior)<0:
            entry=get_catalog_entry(prior)
            if entry:self.model_combo.addItem(entry.display_name,prior)
        self.model_combo.setCurrentIndex(max(0,self.model_combo.findData(prior)));self.model_combo.blockSignals(False);self.model_changed()

    def load_part(self,*_):
        if not self.current_part_id():self.apply_button.setEnabled(False);return
        component=self.component();self.model_filter.blockSignals(True);self.model_filter.clear();self.model_filter.blockSignals(False)
        self.filter_models();self.model_combo.setCurrentIndex(max(0,self.model_combo.findData(component.catalog_id if component else '')))
        if component:self.kind_combo.setCurrentIndex(max(0,self.kind_combo.findData(component.kind)))
        elif not self.model_combo.currentData():self.kind_combo.setCurrentIndex(self.kind_combo.findData('load'))
        part=next(p for p in self.draft.parts if p.id==self.current_part_id());self.name.setText(component.name if component else part.name)
        self.default_color.setChecked(False);self.confirm_drop=False;self.refresh_feature()

    def model_changed(self,*_):
        self.confirm_drop=False
        entry=get_catalog_entry(self.model_combo.currentData() or '')
        if entry and (entry.suggested_kind or product_diagram(entry.catalog_id)):
            self.kind_combo.setCurrentIndex(max(0,self.kind_combo.findData(entry.suggested_kind or 'load')))
        self.kind_combo.setEnabled(not(entry and (entry.suggested_kind or product_diagram(entry.catalog_id))))
        board=board_pinout(entry.catalog_id) if entry else None;product=product_diagram(entry.catalog_id) if entry else None
        note=(getattr(board or product,'note_en','') if english() else getattr(board or product,'note',''))
        diagram_note=(word('공식 단자 모식도 포함','Official terminal diagram included') if board or product else
                      word('이 모델의 확인된 모식도 없음 · 직접 입력한 단자만 표시','No verified diagram for this model · only manually declared terminals shown'))
        self.note.setPlainText('\n'.join(text for text in (entry.spec_summary if entry else '',note,diagram_note) if text))
        self.source_button.setEnabled(bool(entry and entry.source_url))

    def candidate(self):
        return register_part(self.draft,self.current_part_id(),dict(catalog_id=self.model_combo.currentData() or '',kind=self.kind_combo.currentData(),
            name=self.name.text().strip() or self.part_combo.currentText(),apply_default_color=self.default_color.isChecked(),allow_drop_connections=self.confirm_drop))

    def register_preview(self):
        old=self.component()
        if old and (old.catalog_id!=(self.model_combo.currentData() or '') or old.kind!=self.kind_combo.currentData()) and (old.signal_pins or old.terminal_pins) and not self.confirm_drop:
            if QMessageBox.question(self,word('모델 변경 / 연결 해제','Model change / disconnect pins'),word('모델이 바뀌어 이 부품의 기존 핀 연결을 해제합니다. 계속할까요?','The model changes, so this part loses its current pin assignments. Continue?'))!=QMessageBox.StandardButton.Yes:return
            self.confirm_drop=True
        try:self.draft=self.candidate();self.confirm_drop=False;self.refresh_feature()
        except (ValueError,TypeError) as exc:QMessageBox.warning(self,word('전장 등록 확인','Check electrical registration'),str(exc)[:1200])

    def refresh_feature(self):
        component=self.component();registered=component is not None
        from ..mcu_connections import topology_warnings
        warnings=topology_warnings(self.draft.electrical,language='en' if english() else 'ko') if self.draft.electrical else ()
        self.warnings.setPlainText('\n'.join(warnings));self.warnings.setVisible(bool(warnings))
        self.power_button.setEnabled(registered);self.unregister_button.setEnabled(registered);self.pins_button.setEnabled(bool(component and component.kind=='mcu'))
        self.apply_button.setEnabled(bool(self.draft!=self.original))
        self.selected_terminal='';self.connect_button.setEnabled(False);self.target.clear()
        if not component:
            self.diagram.draw(None,());self.status.setText(word('CAD 부품을 선택하고 실제 모델을 등록하세요.','Select a CAD part and register its actual model.'));return
        connections=feature_connections(component,self.draft.electrical);diagram=product_diagram(component.catalog_id)
        self.diagram.draw(component,connections,diagram=diagram);self.diagram.fit()
        self.status.setText(component.name+' · '+word('전장 피처 등록됨','Electrical feature registered')+' · '+
                            (word('DC 계산 포함 · 입력값 기준','Included in DC · entered values') if component.analysis_enabled else word('정격 입력 전 · DC 계산 제외','Ratings pending · excluded from DC')))
        from ..mcu_connections import connection_endpoints
        for endpoint in connection_endpoints(self.draft.electrical,exclude_mcu_id=component.id):
            target_component=next(c for c in self.draft.electrical.components if c.id==endpoint.component_id)
            if target_component.part_id:self.target.addItem(endpoint.label,(target_component.part_id,endpoint.terminal))

    def select_terminal(self,key):
        component=self.component()
        if not component:return
        self.selected_terminal=key;pin=next((p for p in feature_connections(component,self.draft.electrical) if p.key==key),None)
        self.terminal_label.setText(pin.label if pin else key)
        allowed=bool(pin and (component.kind!='mcu' or (pin.kind=='signal' and not pin.legacy)))
        self.connect_button.setEnabled(allowed and self.target.count()>0)
        self.diagram.draw(component,feature_connections(component,self.draft.electrical),key,diagram=product_diagram(component.catalog_id))

    def connect_terminal(self):
        component=self.component();destination=self.target.currentData()
        if not component or not self.selected_terminal or not destination:return
        from ..electrical_registration import connect_registered_pin,connect_registered_terminal
        try:
            connector=connect_registered_pin if component.kind=='mcu' else connect_registered_terminal
            self.draft=connector(self.draft,self.current_part_id(),self.selected_terminal,*destination)
            self.refresh_feature()
        except (ValueError,TypeError) as exc:QMessageBox.warning(self,word('핀 연결 확인','Check pin connection'),str(exc)[:1000])

    def edit_operating(self):
        component=self.component()
        if not component:return
        from .electrical_dialog import ComponentDialog
        dialog=ComponentDialog(self,[p.model_dump() for p in self.draft.parts],component.model_dump())
        if dialog.exec()==QDialog.DialogCode.Accepted:
            raw=self.draft.model_dump();workspace=raw['electrical'];workspace['components']=[dialog.candidate() if c['id']==component.id else c for c in workspace['components']]
            updated=next(c for c in workspace['components'] if c['id']==component.id)
            workspace['nodes']=list(dict.fromkeys([*workspace['nodes'],updated['a'],updated['b'],*updated.get('signal_pins',{}).values(),*updated.get('terminal_pins',{}).values()]))
            try:self.draft=Design.model_validate(raw);self.refresh_feature()
            except ValueError as exc:QMessageBox.warning(self,word('전장 입력 확인','Check electrical inputs'),str(exc)[:1000])

    def edit_pins(self):
        component=self.component()
        if not component:return
        from .mcu_pin_dialog import McuPinDialog
        dialog=McuPinDialog(self,self.draft.electrical,[p.model_dump() for p in self.draft.parts],component.id)
        if dialog.exec()==QDialog.DialogCode.Accepted and dialog.accepted_workspace is not None:
            raw=self.draft.model_dump();raw['electrical']=dialog.accepted_workspace.model_dump();self.draft=Design.model_validate(raw);self.refresh_feature()

    def unregister_preview(self):
        if QMessageBox.question(self,word('전장 등록 해제','Unregister electrical feature'),word('이 부품의 전장 등록과 핀 연결을 해제합니다. CAD 형상과 다른 부품의 연결은 유지됩니다.','Remove this electrical feature and its pin assignments? The CAD body and other devices remain.'))!=QMessageBox.StandardButton.Yes:return
        self.draft=unregister_part(self.draft,self.current_part_id());self.load_part()

    def open_source(self):
        entry=get_catalog_entry(self.model_combo.currentData() or '')
        diagram=board_pinout(entry.catalog_id) or product_diagram(entry.catalog_id) if entry else None
        url=diagram.source_url if diagram else entry.source_url if entry else ''
        if url:QDesktopServices.openUrl(QUrl(url))

    def reject(self):
        self.checked=None;super().reject()

    def accept(self):
        try:self.checked=Design.model_validate(self.draft.model_dump())
        except ValueError as exc:QMessageBox.warning(self,word('전장 저장 확인','Check electrical save'),str(exc)[:1000]);return
        if self.checked==self.original:return
        super().accept()
