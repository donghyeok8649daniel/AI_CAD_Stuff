"""Dimension expressions and project parameters in native Qt controls."""
from copy import deepcopy
from PySide6.QtCore import Signal,Qt
from PySide6.QtWidgets import QWidget,QHBoxLayout,QLineEdit,QLabel,QTableWidget,QTableWidgetItem,QHeaderView
from .widgets import button,label
from .workflows import PreviewDialog
from ..parameters import expression_value,parameter_values


class ExpressionField(QWidget):
    valueChanged=Signal()
    def __init__(self,value=0,minimum=-1e9,maximum=1e9,suffix=' mm',variables=None,expression=''):
        super().__init__();self.variables=variables or {};self.minimum=minimum;self.maximum=maximum;self._suffix=suffix
        row=QHBoxLayout(self);row.setContentsMargins(0,0,0,0);row.setSpacing(5)
        self.input=QLineEdit(expression or f'{value:.14g}');self.input.setPlaceholderText('예: 두께 * 2');self.result=QLabel();self.result.setMinimumWidth(62);row.addWidget(self.input,1);row.addWidget(self.result);self.setFocusProxy(self.input)
        self.input.setToolTip('숫자 또는 변수 식을 입력하세요. 예: 두께*2 + 1 mm');self.input.textChanged.connect(self.changed);self.changed()
    def expression(self):return self.input.text().strip().removeprefix('=').strip()
    def value(self):
        value=expression_value(self.expression(),self.variables)
        if not self.minimum<=value<=self.maximum:raise ValueError(f'치수는 {self.minimum:g}~{self.maximum:g}{self._suffix} 범위여야 합니다.')
        return value
    def formula(self):
        try:float(self.expression());return ''
        except ValueError:return self.expression()
    def setValue(self,value):self.input.setText(f'{value:.14g}')
    def setExpression(self,text):self.input.setText(text)
    def suffix(self):return self._suffix
    def setSuffix(self,text):self._suffix=text;self.changed()
    def selectAll(self):self.input.selectAll()
    def changed(self,*args):
        try:self.result.setText(f'= {self.value():g}{self._suffix}');self.result.setStyleSheet('color:#81cdbc;');self.result.setToolTip('')
        except ValueError as exc:self.result.setText('식 오류');self.result.setStyleSheet('color:#f17e83;');self.result.setToolTip(str(exc))
        self.valueChanged.emit()


class ParameterDialog(PreviewDialog):
    def __init__(self,parent,design):
        super().__init__(parent,'변수 / 연결 치수 · U','변수 값이 바뀌면 연결된 부품 치수·스케치 치수·돌출 깊이를 함께 다시 계산합니다. 길이의 기본 단위는 mm입니다.')
        self.base=deepcopy(design);self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['이름','값 / 식','계산값']);self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.table.setMinimumHeight(240);self.controls.addWidget(self.table)
        for name,expr in design.get('parameters',{}).items():self.add_row(name,expr)
        self.controls.addWidget(button('변수 추가',lambda:self.add_row()));self.controls.addWidget(button('선택 변수 삭제',self.remove_row));self.controls.addWidget(label('예: 두께 = 5\n폭 = 두께 * 4\n부품 속성이나 치수 입력란에서 이름을 사용하세요.\n사용 중인 변수 삭제·순환 참조·잘못된 형상은 적용하지 않습니다.',True))
        self.bindings=QTableWidget(0,2);self.bindings.setHorizontalHeaderLabels(['연결 치수','식']);self.bindings.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for b in design.get('dimension_bindings',[]):
            i=self.bindings.rowCount();self.bindings.insertRow(i)
            for col,text in enumerate(('/'.join(map(str,b['path'])),b['expression'])):
                item=QTableWidgetItem(text);item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable);self.bindings.setItem(i,col,item)
        self.controls.addWidget(label('부품 속성에서 연결한 식'));self.controls.addWidget(self.bindings);self.controls.addWidget(button('선택 연결 해제 · 현재 값 유지',self.unlink));self.controls.addStretch();self.table.itemChanged.connect(self.schedule);self.schedule();self.resize(1150,800)
    def add_row(self,name='',expr='0'):
        i=self.table.rowCount();self.table.insertRow(i);self.table.setItem(i,0,QTableWidgetItem(name));self.table.setItem(i,1,QTableWidgetItem(str(expr)));item=QTableWidgetItem();item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable);self.table.setItem(i,2,item)
    def remove_row(self):
        if self.table.currentRow()>=0:self.table.removeRow(self.table.currentRow());self.schedule()
    def unlink(self):
        i=self.bindings.currentRow()
        if i>=0:self.base['dimension_bindings'].pop(i);self.bindings.removeRow(i);self.schedule()
    def candidate(self):
        params={}
        for i in range(self.table.rowCount()):
            name=self.table.item(i,0).text().strip();expr=self.table.item(i,1).text().strip()
            if not name:raise ValueError('변수 이름을 입력하세요.')
            if name in params:raise ValueError('중복된 변수 이름: '+name)
            params[name]=expr
        values=parameter_values(params);self.table.blockSignals(True)
        try:
            for i in range(self.table.rowCount()):self.table.item(i,2).setText(f"{values[self.table.item(i,0).text().strip()]:g}")
        finally:self.table.blockSignals(False)
        raw=deepcopy(self.base);raw['parameters']=params;return raw
