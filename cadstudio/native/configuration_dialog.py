from copy import deepcopy
from PySide6.QtWidgets import QTableWidget,QTableWidgetItem,QHeaderView,QLineEdit
from .workflows import PreviewDialog,choice
from .widgets import label,button
from ..configurations import apply_configuration


class ConfigurationDialog(PreviewDialog):
    def __init__(self,parent,design):
        super().__init__(parent,'설계 구성표','변수 조합을 이름으로 보관하고, 선택한 구성으로 형상을 다시 계산합니다. 각 구성의 적용은 작업기록에 남습니다.')
        self.raw=deepcopy(design);self.names=list(design.get('parameters',{}));self.selector=choice([(k,k) for k in design.get('configurations',{})]);self.controls.addWidget(self.selector);self.name=QLineEdit();self.name.setPlaceholderText('구성 이름 · 예: 소형 / 대형');self.controls.addWidget(self.name)
        self.table=QTableWidget(len(self.names),2);self.table.setHorizontalHeaderLabels(['변수','값 / 식']);self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.controls.addWidget(self.table)
        from PySide6.QtCore import Qt
        for i,k in enumerate(self.names):
            item=QTableWidgetItem(k);item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable);self.table.setItem(i,0,item);self.table.setItem(i,1,QTableWidgetItem(design['parameters'][k]))
        self.controls.addWidget(button('현재 값으로 새 구성',self.new_row));self.controls.addWidget(button('선택 구성 삭제',self.delete));self.controls.addWidget(label('구성표는 변수 값을 관리합니다. 피처 유무와 재질 구성은 별도 기능입니다. 먼저 변수 창에서 변수를 만드세요.',True));self.controls.addStretch()
        self.table.itemChanged.connect(self.schedule);self.name.textChanged.connect(self.schedule);self.selector.currentIndexChanged.connect(self.select);self.select();self.schedule()
    def select(self,*args):
        name=self.selector.currentData();self.name.setText(name or '기본');values=self.raw.get('configurations',{}).get(name,self.raw.get('parameters',{}));self.table.blockSignals(True)
        for i,key in enumerate(self.names):self.table.item(i,1).setText(values.get(key,self.raw['parameters'][key]))
        self.table.blockSignals(False);self.schedule()
    def new_row(self):
        try:self.raw=self.candidate()
        except ValueError as exc:self.failed(str(exc));return
        self.selector.blockSignals(True);self.selector.clear()
        for key in self.raw.get('configurations',{}):self.selector.addItem(key,key)
        self.selector.blockSignals(False);self.selector.setCurrentIndex(-1);self.name.setText('새 구성');self.schedule()
    def delete(self):
        name=self.selector.currentData()
        if name:
            self.raw.get('configurations',{}).pop(name,None);self.selector.removeItem(self.selector.currentIndex())
            if not self.selector.count():self.name.clear()
            self.schedule()
    def candidate(self):
        raw=deepcopy(self.raw)
        if not self.names:raise ValueError('변수 창에서 설계 변수를 먼저 추가하세요.')
        name=self.name.text().strip()
        if not name:
            if not raw.get('configurations'):return raw
            raise ValueError('구성 이름을 입력하세요.')
        raw.setdefault('configurations',{})[name]={k:self.table.item(i,1).text() for i,k in enumerate(self.names)}
        return apply_configuration(raw,name).model_dump()
