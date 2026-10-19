"""Saved quote inputs and explicit adoption of separately tagged AI estimates."""
from copy import deepcopy
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QTableWidget,
    QTableWidgetItem,QComboBox,QPushButton,QDialogButtonBox,QPlainTextEdit,QCheckBox,
    QScrollArea,QWidget)
from ..pcb_cost_workflow import read_cost_inputs,with_cost_inputs,validate_cost_proposal,adopt_cost_proposal


def cell(table,row,col):
    control=table.cellWidget(row,col)
    if control:
        value=control.currentData();return '' if value is None else str(value)
    return table.item(row,col).text().strip() if table.item(row,col) else ''


def choice(values,selected):
    box=QComboBox()
    for label,value in values:box.addItem(label,value)
    box.setCurrentIndex(max(0,box.findData(selected)));return box


class PCBCostInputsDialog(QDialog):
    def __init__(self,parent,project):
        super().__init__(parent);self.setWindowTitle('견적 조건 · 수량별 단가');self.resize(1100,740)
        self.project=project.model_copy(deep=True);self.checked=None;self.error=QLabel()
        self.saved=read_cost_inputs(self.project).model_dump(mode='json')
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True);page=QWidget();root=QVBoxLayout(page);scroll.setWidget(page);outer.addWidget(scroll)
        note=QLabel('수량별 단가와 별도 비용을 PCB 초안에 저장합니다. 실제 부품 견적은 자동으로 덮어쓰지 않습니다.\n빈 비용은 미정입니다. 0원은 최소·최대에 0을 직접 입력하세요. 통화는 서로 환산하지 않습니다.');note.setWordWrap(True);root.addWidget(note)
        root.addWidget(QLabel('수량별 단가 · 참조/품번별로 여러 구간 추가 · MOQ와 포장 수량은 부품 가격 편집에서 설정'))
        self.keys=sorted({c.ref for c in project.components}|{c.mpn for c in project.components if c.mpn}|set(self.saved['quantity_breaks']))
        self.tiers=QTableWidget(0,9);self.tiers.setObjectName('pcbPriceTiers');self.tiers.setMinimumHeight(180)
        self.tiers.setHorizontalHeaderLabels(['참조 / 품번','이 수량 이상','개당 가격','통화','입력 상태','기준일','공급사','출처','근거 / 비고']);root.addWidget(self.tiers)
        row=QHBoxLayout();add=QPushButton('가격 구간 추가');add.clicked.connect(lambda:self.add_tier());row.addWidget(add)
        remove=QPushButton('선택 구간 삭제');remove.clicked.connect(lambda:self.tiers.removeRow(self.tiers.currentRow()));row.addWidget(remove);root.addLayout(row)
        for key,tiers in self.saved['quantity_breaks'].items():
            for tier in tiers:self.add_tier(key,tier)
        self.additional=QTableWidget(4,8);self.additional.setObjectName('pcbAdditionalCosts');self.additional.setMinimumHeight(165)
        self.additional.setHorizontalHeaderLabels(['별도 비용','최소','최대','통화','입력 상태','기준일','출처','추정 / 견적 근거']);root.addWidget(self.additional)
        self.cost_kinds=('pcb_fabrication','assembly_consumables','shipping','tax_import')
        labels=('PCB 제작','조립·소모품','배송','세금·통관')
        for r,key in enumerate(self.cost_kinds):
            value=self.saved['additional_costs'].get(key) or {}
            label=QTableWidgetItem(labels[r])
            from PySide6.QtCore import Qt
            label.setFlags(label.flags() & ~Qt.ItemFlag.ItemIsEditable);self.additional.setItem(r,0,label)
            for col,field in enumerate(('minimum','maximum','currency','status','as_of','source_url','basis'),1):
                if field=='status':self.additional.setCellWidget(r,col,choice([('사용자 추정','user_estimate'),('참고 견적','reference'),('확인 견적','quoted')],value.get(field,'user_estimate')))
                else:self.additional.setItem(r,col,QTableWidgetItem(str(value.get(field) or '') if field!='currency' else value.get(field,self.project.budget.currency)))
        hint=QLabel('확정된 단일 금액은 최소와 최대를 같게 입력하세요. 입력 금액은 근거가 있는 조건부 비용이며 공급사 보장이나 발주가 아닙니다.');hint.setWordWrap(True);root.addWidget(hint)
        self.clear_ai=QCheckBox('저장된 AI 가격 추정만 제거 (실제 부품 견적은 유지)');root.addWidget(self.clear_ai)
        self.rebind_tiers=QCheckBox('제품과 견적의 통화·기준일·출처, 수량별 단가를 다시 검토했으며 단가표를 현재 조건에 재연결합니다.');root.addWidget(self.rebind_tiers)
        self.error.setWordWrap(True);outer.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);outer.addWidget(buttons)

    def add_tier(self,key=None,tier=None):
        if self.tiers.rowCount()>=1024:self.error.setText('전체 가격 구간은 최대 1024개입니다.');return
        tier=tier or {};row=self.tiers.rowCount();self.tiers.insertRow(row)
        self.tiers.setCellWidget(row,0,choice([(key,key) for key in self.keys],key or (self.keys[0] if self.keys else '')))
        fields=('minimum_quantity','unit_price','currency','status','as_of','supplier','source_url','note')
        for col,field in enumerate(fields,1):
            if field=='status':self.tiers.setCellWidget(row,col,choice([('참고 견적','reference'),('확인 견적','quoted')],tier.get(field,'reference')))
            else:
                value=tier.get(field,self.project.budget.currency if field=='currency' else '')
                self.tiers.setItem(row,col,QTableWidgetItem('' if value is None else str(value)))

    def inputs(self):
        schedules={}
        for row in range(self.tiers.rowCount()):
            key=cell(self.tiers,row,0)
            if not key or not cell(self.tiers,row,1) or not cell(self.tiers,row,2):raise ValueError('각 가격 구간의 품번·최소 수량·단가를 입력하세요.')
            tier=dict(minimum_quantity=int(cell(self.tiers,row,1)),unit_price=cell(self.tiers,row,2),currency=cell(self.tiers,row,3),status=cell(self.tiers,row,4),
                as_of=cell(self.tiers,row,5) or None,supplier=cell(self.tiers,row,6),source_url=cell(self.tiers,row,7),note=cell(self.tiers,row,8))
            schedules.setdefault(key,[]).append(tier)
        extras={}
        for row,key in enumerate(self.cost_kinds):
            fields=[cell(self.additional,row,col) for col in range(1,8)]
            if not any(fields[index] for index in (0,1,4,5,6)):continue
            if not fields[0] or not fields[1]:raise ValueError('별도 비용은 최소·최대를 함께 입력하세요. 빈칸은 미정이며 0으로 바꾸지 않습니다.')
            extras[key]=dict(minimum=fields[0],maximum=fields[1],currency=fields[2],status=fields[3],as_of=fields[4] or None,source_url=fields[5],basis=fields[6])
        result=deepcopy(self.saved)
        result.update(quantity_breaks=schedules,additional_costs=extras,
            quantity_break_bindings=self.saved.get('quantity_break_bindings',{}),
            accepted_ai_estimates=[] if self.clear_ai.isChecked() else self.saved['accepted_ai_estimates'])
        if self.clear_ai.isChecked():result['accepted_ai_bindings']={}
        return result

    def accept(self):
        self.checked=None
        try:self.checked=with_cost_inputs(self.project,self.inputs(),rebind_quantity_breaks=self.rebind_tiers.isChecked())
        except (ValueError,TypeError) as error:self.error.setText(str(error));return
        super().accept()


class PCBCostProposalDialog(QDialog):
    def __init__(self,parent,project,proposal):
        super().__init__(parent);self.setWindowTitle('AI 가격 추정 미리보기');self.resize(1060,650)
        self.project=project.model_copy(deep=True);self.proposal=validate_cost_proposal(project,proposal);self.checked=None
        data=self.proposal.model_dump(mode='json');root=QVBoxLayout(self)
        note=QLabel('AI가 제시한 조건부 가격 범위입니다. 실시간 가격·재고·공급사 견적을 확인한 결과가 아닙니다.\n채택하면 AI 추정으로 따로 저장하며, 실제 부품 견적·원본 CAD는 자동 변경하지 않습니다.');note.setWordWrap(True);root.addWidget(note)
        table=QTableWidget(len(data['rows']),8);table.setObjectName('pcbAIPricePreview');table.setHorizontalHeaderLabels(['참조','품번','필요 / 구매','개당 최소','개당 최대','통화','기준일','출처 / 추정 근거'])
        from PySide6.QtWidgets import QAbstractItemView
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);root.addWidget(table,1)
        for r,row in enumerate(data['rows']):
            values=[', '.join(row['refs']),row['mpn'],str(row['required_quantity'])+' / '+str(row['purchase_quantity']),row['minimum_unit_price'],row['maximum_unit_price'],row['currency'],row['as_of'],row['source_url']+'\n'+row['basis']]
            for col,value in enumerate(values):table.setItem(r,col,QTableWidgetItem('미정' if value is None else str(value)))
        summary=QPlainTextEdit(data['summary']);summary.setReadOnly(True);summary.setMaximumHeight(100);root.addWidget(summary)
        self.confirm=QCheckBox('범위·수량·통화·근거를 검토했으며 AI 추정 상태로 PCB 초안에 채택합니다.');root.addWidget(self.confirm)
        self.error=QLabel();self.error.setWordWrap(True);root.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.button(QDialogButtonBox.StandardButton.Ok).setText('검토한 AI 추정 채택');buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);root.addWidget(buttons)

    def accept(self):
        self.checked=None
        try:
            if not self.confirm.isChecked():raise ValueError('가격안의 근거와 AI 추정 상태를 먼저 확인하세요.')
            self.checked=adopt_cost_proposal(self.project,self.proposal)
        except (ValueError,TypeError) as error:self.error.setText(str(error));return
        super().accept()
