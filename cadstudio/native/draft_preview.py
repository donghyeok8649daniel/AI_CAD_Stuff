"""Before/after review with an explicit apply action and no document mutations."""
import json
from html import escape
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QTextEdit,QLineEdit,
                              QTabWidget,QWidget,QTableWidget,QTableWidgetItem,QAbstractItemView,QApplication)
from .viewport import CADViewport
from .workflows import choice
from .widgets import label,button


class DraftPreviewDialog(QDialog):
    def __init__(self,parent,before,after,summary,*,validation=None,repairable=False,
                 before_design=None,after_design=None):
        super().__init__(parent)
        self.english=getattr(getattr(QApplication.instance(),'cad_language',None),'language','ko')=='en'
        word=self.word
        self.setWindowTitle(word('AI 설계 · 적용 전 비교','AI design · Review before apply'));self.resize(1080,760);self.setMinimumSize(800,560)
        self.before=before;self.after=after;self.validation=validation or {};self.blocked=self.validation.get('status')=='needs_repair';layout=QVBoxLayout(self)
        layout.addWidget(label(word('간섭이 남은 초안입니다. 원본은 그대로이며, 수정 후 검증을 통과하면 적용할 수 있습니다.','This draft has interference. The original is unchanged; repair and validate before applying.') if self.blocked else word('아직 원본에 적용하지 않았습니다. 변경 전·후 형상과 작업 내용을 확인하세요.','The original is unchanged. Review the before/after geometry and operations.'),True))
        self.mode=choice([('after',word('변경 후 · AI 초안','After · AI draft')),('before',word('변경 전 · 현재 설계','Before · current design'))]);layout.addWidget(self.mode)
        self.tabs=QTabWidget();self.tabs.setObjectName('aiDraftReviewTabs');layout.addWidget(self.tabs,1)
        geometry=QWidget();geometry_layout=QVBoxLayout(geometry);geometry_layout.setContentsMargins(0,0,0,0)
        self.viewport=CADViewport();geometry_layout.addWidget(self.viewport,1)
        self.issues=choice([('all','전체 초안 보기')]+[(i,f"{c['a']} ↔ {c['b']} · {c['volume']:.4g} mm³") for i,c in enumerate(self.validation.get('collisions',[]))]);self.issues.setVisible(self.blocked);geometry_layout.addWidget(self.issues)
        self.tabs.addTab(geometry,word('CAD 형상','CAD geometry'))
        self.before_design=before_design;self.after_design=after_design;self.electrical_panel=None
        from ..electrical_diff import electrical_changes
        self.electrical_changes=(electrical_changes(before_design,after_design)
                                if after_design is not None else ())
        if self.electrical_changes:
            electrical=QWidget();self.electrical_layout=QVBoxLayout(electrical);self.electrical_layout.setContentsMargins(0,0,0,0)
            self.electrical_layout.addWidget(label(word('배선 미리보기입니다. 아래 변경표와 회로를 확인한 뒤 적용하세요. 원본은 아직 변경되지 않았습니다.','Wiring preview. Review the changes and circuit before applying. The original is unchanged.'),True))
            self.change_table=QTableWidget(len(self.electrical_changes),4)
            self.change_table.setObjectName('aiElectricalChangeTable')
            self.change_table.setHorizontalHeaderLabels([word('회로 부품 / ID','Component / ID'),word('변경 항목','Changed field'),word('변경 전','Before'),word('변경 후','After')])
            self.change_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.change_table.setMinimumHeight(100);self.change_table.setMaximumHeight(135)
            self.change_table.setWordWrap(False);self.change_table.horizontalHeader().setStretchLastSection(True)
            fields={'component':'부품 추가 / 삭제','part_id':'대응 CAD 부품 ID','cad_name':'CAD 이름',
                    'part_registration':'CAD 등록','wire_endpoints':'전선 양 끝 단자','signal_pins':'GPIO 연결',
                    'terminal_pins':'제품 단자 연결','board_supply_pins':'보드 전원 핀','closed':'전선 / 스위치 연결 상태',
                    'length_mm':'전선 길이 (mm)','cross_section_mm2':'전선 단면적 (mm²)',
                    'wire_color':'전선 색상','a':'DC A 노드','b':'DC B 노드','catalog_id':'제품 모델',
                    'schematic_positions':'회로 부품 배치','nodes':'회로 노드','ground':'기준 GND',
                    'analysis_enabled':'DC 계산 포함','force_chain':'측정 체인'}
            if self.english:fields={'component':'Component added / removed','part_id':'Linked CAD part ID','cad_name':'CAD name',
                'part_registration':'CAD registration','wire_endpoints':'Wire endpoint terminals','signal_pins':'GPIO connections',
                'terminal_pins':'Product terminals','board_supply_pins':'Physical board supply pins','closed':'Wire / switch closed',
                'length_mm':'Wire length (mm)','cross_section_mm2':'Wire cross section (mm²)','wire_color':'Wire color',
                'a':'DC A node','b':'DC B node','catalog_id':'Product model','schematic_positions':'Component placement',
                'nodes':'Circuit nodes','analysis_enabled':'Include in DC calculation','force_chain':'Measurement chain'}
            for index,change in enumerate(self.electrical_changes):
                values=[change.name+(f' [{change.component_id}]' if change.component_id else ''),
                        fields.get(change.field,change.field),self._display(change.before),self._display(change.after)]
                for column,value in enumerate(values):
                    item=QTableWidgetItem(value[:240]);item.setToolTip(escape(value));self.change_table.setItem(index,column,item)
            for column,width in enumerate((190,160,210)):self.change_table.setColumnWidth(column,width)
            self.electrical_layout.addWidget(self.change_table)
            self.tabs.addTab(electrical,word('배선 / CAD 부품 대응','Wiring / CAD links'))
            self.tabs.setCurrentIndex(1)
        self.details=QTextEdit();self.details.setReadOnly(True);self.details.setPlainText(summary);self.details.setMaximumHeight(80 if self.electrical_changes else 140);layout.addWidget(self.details)
        self.repair_note=QLineEdit();self.repair_note.setMaxLength(1000);self.repair_note.setPlaceholderText('추가 수정 지시 (선택) · 예: 시편 치수는 유지하고 클램프 홈을 넓혀줘');self.repair_note.setVisible(self.blocked and repairable);layout.addWidget(self.repair_note)
        row=QHBoxLayout();row.addWidget(button(word('돌아가기','Back'),self.reject));row.addStretch();self.repair_button=button(word('AI로 간섭 수정 계속','Continue AI interference repair'),lambda:self.done(2),True);self.repair_button.setVisible(self.blocked and repairable);row.addWidget(self.repair_button);self.apply_button=button(word('검증 통과 후 적용 가능','Validation required before apply') if self.blocked else word('확인 · 설계에 적용','Confirm · Apply to design'),self.accept,not self.blocked);self.apply_button.setEnabled(not self.blocked);row.addWidget(self.apply_button);layout.addLayout(row)
        self.issues.currentIndexChanged.connect(self.show_issue)
        self.mode.currentIndexChanged.connect(self.show_state);self.tabs.currentChanged.connect(self.show_state);self.show_state()
    @staticmethod
    def _display(value):
        if value is None:return '—'
        if isinstance(value,str):return value or '—'
        return json.dumps(value,ensure_ascii=False,separators=(',',':'))
    def word(self,ko,en):return en if self.english else ko
    def show_state(self):
        if self.tabs.currentIndex()==1:
            from ..electrical_diff import electrical_snapshot
            from .electrical_schematic import ElectricalSchematicDialog
            design=self.after_design if self.mode.currentData()=='after' else self.before_design
            workspace,names=electrical_snapshot(design)
            parts=[dict(id=identifier,name=name) for identifier,name in names.items()]
            if self.electrical_panel is None:
                self.electrical_panel=ElectricalSchematicDialog(self,workspace,parts=parts,editable=False,inspection_only=True)
                self.electrical_panel.setWindowFlags(Qt.WindowType.Widget)
                self.electrical_layout.addWidget(self.electrical_panel,1)
            else:
                panel=self.electrical_panel;panel.workspace=workspace;panel.parts=tuple(parts)
                panel._draw();panel.refresh_mcu_list()
            self.electrical_panel.fit_scene()
            return
        result=self.after if self.mode.currentData()=='after' else self.before
        # Keep the view orientation/zoom when switching to compare positions.
        self.viewport.load(result,fit=self.viewport.result is None)
        self.show_issue()
    def show_issue(self):
        value=self.issues.currentData()
        ids=[]
        if self.mode.currentData()=='after' and isinstance(value,int):
            hit=self.validation['collisions'][value];ids=[hit['a'],hit['b']]
        self.viewport.select_many(ids)
    def accept(self):
        if not self.blocked:super().accept()
    def done(self,result):
        if result==QDialog.DialogCode.Accepted and self.blocked:return
        self.viewport.shutdown();super().done(result)
