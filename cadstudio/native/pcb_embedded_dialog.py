"""Product references plus explicitly entered physical footprints, never guessed pads."""
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,
    QComboBox,QTableWidget,QTableWidgetItem,QPlainTextEdit,QCheckBox,QPushButton,QDialogButtonBox,QScrollArea,QWidget)
from ..pcb import PCBProject,new_component
from ..pcb_embedded import search_embedded,component_from_catalog,bind_catalog_product
from ..pcb_editor_data import PIN_SPEC_COLUMNS,pin_specs_from_rows


class PCBEmbeddedDialog(QDialog):
    def __init__(self,parent,project,selected_ref=None):
        super().__init__(parent);self.setWindowTitle('임베디드 부품 · 제품과 실제 패드 연결');self.resize(1080,760)
        self.project=PCBProject.model_validate(project).model_copy(deep=True);self.checked=None
        self.existing=next((c for c in self.project.components if c.ref==selected_ref),None)
        used={c.ref for c in self.project.components};index=1
        while 'U'+str(index) in used:index+=1
        self.footprint=(self.existing.model_copy(deep=True) if self.existing else new_component('unsupported','U'+str(index),self.project.width_mm/2,self.project.height_mm/2))
        self.rows=[];self.selected_catalog_id=None
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True);content=QWidget();root=QVBoxLayout(content);scroll.setWidget(content);outer.addWidget(scroll)
        hint=QLabel('제품 검색은 저장된 규격·논리 핀 참고자료입니다. 실제 패드 좌표·핀 피치·방향은 자동 생성하지 않습니다.\n치수와 핀을 입력해 확인한 후 PCB 초안에 추가합니다. CAD 원본 저장은 별도입니다.')
        hint.setWordWrap(True);root.addWidget(hint)
        row=QHBoxLayout();self.query=QLineEdit();self.query.setMaxLength(200);self.query.setPlaceholderText('제품명·제조사·MCU/MPU·모듈 검색');row.addWidget(self.query)
        search=QPushButton('제품 찾기');search.clicked.connect(self.populate);self.query.returnPressed.connect(self.populate);row.addWidget(search);root.addLayout(row)
        self.products=QTableWidget(0,3);self.products.setObjectName('pcbEmbeddedProducts');self.products.setHorizontalHeaderLabels(['제조사','모델','종류'])
        self.products.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);self.products.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.products.itemSelectionChanged.connect(self.show_reference);self.products.setMaximumHeight(150);root.addWidget(self.products)
        self.reference=QPlainTextEdit();self.reference.setReadOnly(True);self.reference.setMaximumHeight(150);root.addWidget(self.reference)
        form=QFormLayout();root.addLayout(form)
        self.model=QLineEdit();self.product_source=QLineEdit();self.revision=QLineEdit();self.pin1=QComboBox();self.side=QComboBox();self.side.addItem('실장 면 선택',None);self.side.addItem('앞면 / F','F');self.side.addItem('뒷면 / B','B')
        self.model.textEdited.connect(self.product_identity_edited)
        self.orientation=QLineEdit();self.orientation.setPlaceholderText('예: 커넥터 키와 1번 핀 방향의 도면 기준')
        self.height=QLineEdit();self.clearance=QLineEdit()
        for title,widget in [('정확한 제품 모델',self.model),('제품 도면 출처',self.product_source),('데이터시트 리비전 (모르면 빈칸)',self.revision),('1번 핀',self.pin1),('실장 면',self.side),('방향·키 기준',self.orientation),('실제 몸체 높이 mm',self.height),('필요한 서비스 여유 mm',self.clearance)]:form.addRow(title,widget)
        edit=QPushButton('패드·핀 번호·치수 편집…');edit.setObjectName('pcbEmbeddedFootprint');edit.clicked.connect(self.edit_footprint);root.addWidget(edit)
        self.physical=QLabel();self.physical.setWordWrap(True);root.addWidget(self.physical)
        self.specs=QTableWidget(0,len(PIN_SPEC_COLUMNS));self.specs.setObjectName('pcbEmbeddedPinSpecs');self.specs.setMinimumHeight(100);self.specs.setMaximumHeight(190)
        self.specs.setHorizontalHeaderLabels(['물리 핀','논리 핀 키','기능','역할','최소 V','최대 V','소비 A','한도 A','기준 GND net','규격 출처','동작 조건'])
        root.addWidget(QLabel('핀별 규격 · 빈칸은 미확인 · 전원 권장값과 실제 소비전류를 구분하세요.'));root.addWidget(self.specs)
        self.confirm=QCheckBox('입력한 패드·핀 번호·치수·방향을 선택 제품의 실제 도면과 대조했습니다. 자동 검증 결과가 아닌 사용자 선언으로 저장합니다.')
        self.confirm.setObjectName('pcbEmbeddedGeometryDeclaration');root.addWidget(self.confirm)
        self.review_record=QCheckBox('도면 대조 담당·날짜·근거를 함께 기록 (앱의 독립 검증이 아님)');root.addWidget(self.review_record)
        form=QFormLayout();self.reviewer=QLineEdit();self.review_date=QLineEdit();self.review_date.setPlaceholderText('YYYY-MM-DD');self.review_note=QLineEdit()
        for label,widget in [('대조 담당',self.reviewer),('대조 날짜',self.review_date),('확인한 도면·기준',self.review_note)]:form.addRow(label,widget)
        root.addLayout(form)
        self.error=QLabel();self.error.setWordWrap(True);root.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);outer.addWidget(buttons)
        self.update_footprint();self.populate()

    def populate(self):
        self.selected_catalog_id=None;self.confirm.setChecked(False);self.review_record.setChecked(False);self.checked=None
        self.reviewer.clear();self.review_date.clear();self.review_note.clear()
        for control in (self.model,self.product_source,self.revision,self.orientation,self.height,self.clearance):control.clear()
        self.reference.clear();self.side.setCurrentIndex(0);self.update_specs([])
        self.products.blockSignals(True)
        try:
            self.products.clearSelection();self.products.setCurrentCell(-1,-1);self.products.setRowCount(0)
            self.rows=search_embedded(self.query.text(),limit=40);self.products.setRowCount(len(self.rows))
            for index,row in enumerate(self.rows):
                for col,key in enumerate(('manufacturer','model','category')):self.products.setItem(index,col,QTableWidgetItem(str(row.get(key,''))))
        finally:self.products.blockSignals(False)
        self.products.resizeColumnsToContents()

    def product_identity_edited(self,*_):
        self.confirm.setChecked(False);self.review_record.setChecked(False);self.update_specs([])
        self.reviewer.clear();self.review_date.clear();self.review_note.clear()
        self.revision.clear();self.orientation.clear();self.height.clear();self.clearance.clear();self.side.setCurrentIndex(0)

    def show_reference(self):
        index=self.products.currentRow()
        if not 0<=index<len(self.rows):return
        entry=self.rows[index];self.selected_catalog_id=entry['catalog_id']
        lines=[str(entry.get('manufacturer',''))+' '+str(entry.get('model','')),str(entry.get('source_url','')),str(entry.get('spec_summary','')),
            '핀 기능은 참고용이며, 아래 목록은 물리 패드 좌표가 아닙니다.']
        lines.extend(str(pin.get('key',''))+' · '+str(pin.get('label',''))+' · '+', '.join(pin.get('functions',[])) for pin in entry.get('logical_pins',[]))
        self.reference.setPlainText('\n'.join(lines));self.model.setText(entry['model']);self.product_source.setText(entry['source_url']);self.confirm.setChecked(False)
        # A prior product's logical mapping/ratings cannot be inherited by a new SKU.
        old=self.existing.library_metadata if self.existing else None
        same=old is not None and old.catalog_id==entry['catalog_id']
        self.revision.setText(old.revision if same else '');self.orientation.setText(old.orientation_reference if same else '')
        self.height.setText(str(old.body_height_mm) if same and old.body_height_mm is not None else '')
        self.clearance.setText(str(old.service_clearance_mm) if same and old.service_clearance_mm is not None else '')
        self.side.setCurrentIndex(max(0,self.side.findData(old.mounted_side if same else None)))
        self.review_record.setChecked(False);self.reviewer.clear();self.review_date.clear();self.review_note.clear()
        if same:
            self.model.setText(old.model);self.product_source.setText(old.source_url)
            if old.pin1_number:self.pin1.setCurrentText(old.pin1_number)
        self.update_specs([spec.model_dump(mode='json') for spec in old.pin_specs] if same else [])

    def update_footprint(self):
        selected=self.pin1.currentText();self.pin1.clear();self.pin1.addItems([pin.number for pin in self.footprint.pins])
        if self.pin1.findText(selected)>=0:self.pin1.setCurrentText(selected)
        self.physical.setText(f'{self.footprint.ref} · {len(self.footprint.pins)}핀 · {self.footprint.body_width_mm:g} × {self.footprint.body_height_mm:g} mm · {self.footprint.footprint}\n논리 핀 목록으로 좌표를 추정하지 않습니다. 기성 보드 전체를 추가할 때는 그 보드의 실제 커넥터·패드 도면을 입력하세요.')
        old=[]
        for row in range(self.specs.rowCount()):
            old.append({key:(self.specs.cellWidget(row,col).currentData() if key=='role' else self.specs.item(row,col).text() if self.specs.item(row,col) else '') for col,key in enumerate(PIN_SPEC_COLUMNS)})
        self.update_specs(old)

    def update_specs(self,rows):
        old={row['number']:row for row in rows};self.specs.setRowCount(len(self.footprint.pins))
        roles=[('미확인','unknown'),('전원 입력','power_in'),('전원 출력','power_out'),('GND/반환','ground'),('신호 입력','signal_in'),('신호 출력','signal_out'),('양방향','bidirectional'),('수동 소자','passive')]
        for r,pin in enumerate(self.footprint.pins):
            row=old.get(pin.number,{'number':pin.number})
            for c,key in enumerate(PIN_SPEC_COLUMNS):
                if key=='role':
                    control=QComboBox()
                    for label,value in roles:control.addItem(label,value)
                    control.setCurrentIndex(max(0,control.findData(row.get('role','unknown'))));self.specs.setCellWidget(r,c,control)
                else:
                    item=QTableWidgetItem(str(row.get(key,'')) if row.get(key) is not None else '')
                    if key=='number':
                        from PySide6.QtCore import Qt
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.specs.setItem(r,c,item)

    def edit_footprint(self):
        from .pcb_workbench import PCBComponentEditor
        dialog=PCBComponentEditor(self,self.footprint,self.project.nets)
        try:
            if dialog.exec()==QDialog.DialogCode.Accepted:
                self.footprint=dialog.checked;self.confirm.setChecked(False);self.review_record.setChecked(False);self.reviewer.clear();self.review_date.clear();self.review_note.clear();self.update_footprint()
        finally:dialog.deleteLater()

    def accept(self):
        self.checked=None
        try:
            index=self.products.currentRow()
            if not 0<=index<len(self.rows):raise ValueError('정확한 제품 모델을 선택하세요.')
            if not self.confirm.isChecked():raise ValueError('선택 제품의 실제 패드 도면을 확인하세요. 확인 전에는 제품 형상으로 등록하지 않습니다.')
            if self.side.currentData() is None:raise ValueError('실장 면을 선택하세요.')
            if not self.orientation.text().strip():raise ValueError('1번 핀과 커넥터 키의 방향 기준을 입력하세요.')
            if not self.model.text().strip():raise ValueError('정확한 제품 모델을 입력하세요.')
            if not self.height.text().strip() or not self.clearance.text().strip():raise ValueError('실제 몸체 높이와 서비스 여유를 mm로 입력하세요. 모르면 완전한 제품 등록을 보류하세요.')
            entry=self.rows[index]
            if entry['catalog_id']!=self.selected_catalog_id:raise ValueError('검색 결과에서 제품을 다시 선택하세요.')
            rows=[{key:(self.specs.cellWidget(r,c).currentData() if key=='role' else self.specs.item(r,c).text()) for c,key in enumerate(PIN_SPEC_COLUMNS)} for r in range(self.specs.rowCount())]
            metadata=dict(manufacturer=entry['manufacturer'],model=self.model.text().strip(),catalog_id=entry['catalog_id'],source_url=self.product_source.text().strip(),
                revision=self.revision.text().strip(),coordinate_units='mm',pin1_number=self.pin1.currentText(),mounted_side=self.side.currentData(),
                orientation_reference=self.orientation.text().strip(),body_height_mm=float(self.height.text()),service_clearance_mm=float(self.clearance.text()),
                geometry_complete_declared=True,footprint_review_state='user_declared',pin_specs=pin_specs_from_rows(rows),bom_role='purchased')
            if self.review_record.isChecked():
                metadata.update(footprint_review_state='source_reviewed',reviewed_by=self.reviewer.text().strip(),
                    reviewed_date=self.review_date.text().strip(),review_note=self.review_note.text().strip())
            raw=self.project.model_dump(mode='json')
            if self.existing is not None:
                if self.footprint.ref!=self.existing.ref:raise ValueError('기존 부품의 식별자는 바꾸지 마세요.')
                candidate=bind_catalog_product(self.project,self.existing.ref,entry['catalog_id'],footprint=self.footprint.model_dump(mode='json'),library_metadata=metadata)
            else:
                component=component_from_catalog(entry['catalog_id'],self.footprint.model_dump(mode='json'),library_metadata=metadata)
                raw['components'].append(component.model_dump(mode='json'));candidate=PCBProject.model_validate(raw)
            self.checked=PCBProject.model_validate(candidate)
        except (ValueError,TypeError,KeyError) as exc:self.error.setText(str(exc));return
        super().accept()
