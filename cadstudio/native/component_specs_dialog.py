from copy import deepcopy
from PySide6.QtCore import QThreadPool,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLineEdit,QListWidget,QPlainTextEdit
from .widgets import label,button,Worker
from ..component_specs import fetch_product_specs,validate_product_url,spec_prompt


class ComponentSpecsDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle('제품 스펙 · 출처 가져오기');self.resize(820,650);self.alive=True;self.running=False;self.record=None;self.mode=None
        layout=QVBoxLayout(self);layout.addWidget(label('공식 제조사 또는 구매 페이지 URL을 넣으세요. 치수 후보와 근거를 확인한 뒤 적용합니다. 로그인·쿠키 없이 공개 HTML만 읽습니다.',True))
        row=QHBoxLayout();self.url=QLineEdit();self.url.setPlaceholderText('https://…');row.addWidget(self.url,1);self.fetch_button=button('스펙 불러오기',self.fetch);row.addWidget(self.fetch_button);layout.addLayout(row)
        self.status=label('제품 변형·치수 순서·장착 도면을 원문과 비교하세요. 자동 적용하지 않습니다.',True);layout.addWidget(self.status)
        self.list=QListWidget();layout.addWidget(self.list);self.details=QPlainTextEdit();self.details.setReadOnly(True);layout.addWidget(self.details,1)
        row=QHBoxLayout();row.addWidget(button('원문 열기',self.open_source));self.use=button('선택 치수 가져오기',lambda:self.finish('dimensions'),True);self.use.setEnabled(False);row.addWidget(self.use);self.ai=button('AI 요청으로 보내기',lambda:self.finish('ai'));self.ai.setEnabled(False);row.addWidget(self.ai);row.addWidget(button('닫기',self.reject));layout.addLayout(row);self.list.currentRowChanged.connect(self.selected)
    def fetch(self):
        if self.running:return
        self.record=None;self.use.setEnabled(False);self.ai.setEnabled(False);self.list.clear();self.details.clear();self.running=True;self.fetch_button.setEnabled(False);self.url.setEnabled(False);self.status.setText('제품 페이지 읽는 중… 닫으면 결과를 적용하지 않습니다.')
        url=self.url.text().strip();worker=Worker(lambda:fetch_product_specs(url));self.worker=worker;worker.signals.done.connect(self.loaded);worker.signals.failed.connect(self.failed);QThreadPool.globalInstance().start(worker)
    def loaded(self,record):
        self.running=False
        if not self.alive:return
        self.record=record;self.fetch_button.setEnabled(True);self.url.setEnabled(True);self.status.setText(record['title']+'\n'+record['url']);self.ai.setEnabled(True)
        for candidate in record['candidates']:self.list.addItem(' × '.join(f'{v:g}' for v in candidate['dimensions_mm'])+' mm · '+candidate['evidence'][:110])
        self.details.setPlainText(record['excerpt'] or '치수 텍스트를 찾지 못했습니다. 원문 도면 또는 PDF를 확인하세요.')
        if record['candidates']:self.list.setCurrentRow(0)
    def failed(self,text):
        self.running=False
        if self.alive:self.fetch_button.setEnabled(True);self.url.setEnabled(True);self.status.setText(text[:700])
    def selected(self,index):
        valid=self.record is not None and 0<=index<len(self.record['candidates']);self.use.setEnabled(valid)
        if valid:self.details.setPlainText(self.record['candidates'][index]['evidence']+'\n\n'+self.record['excerpt'])
    def finish(self,mode):
        if not self.record or mode=='dimensions' and self.list.currentRow()<0:return
        self.record=deepcopy(self.record);index=self.list.currentRow()
        if index>=0:self.record['selected_dimensions_mm']=self.record['candidates'][index]['dimensions_mm']
        self.mode=mode;self.accept()
    def open_source(self):
        try:url=validate_product_url(self.record['url'] if self.record else self.url.text().strip(),resolve=False)
        except ValueError as exc:self.status.setText(str(exc));return
        QDesktopServices.openUrl(QUrl(url))
    def done(self,result):self.alive=False;super().done(result)
