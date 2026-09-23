"""Optional local AI installer included in the native CAD package."""
import threading
from PySide6.QtCore import Signal,QThreadPool
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QPlainTextEdit,QProgressBar
from .widgets import label,button,Worker
from .workflows import choice
from ..ollama_setup import setup,MODELS,installed_models


class AISetupDialog(QDialog):
    progress=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle('로컬 AI 설치 · Ollama');self.resize(610,430);self.running=False;self.cancel=threading.Event();self.model_name=None
        v=QVBoxLayout(self);v.addWidget(label('Ollama와 선택한 모델 1개를 설치합니다. 인터넷 연결이 필요합니다.'))
        v.addWidget(label('Ollama 프로그램은 약 1.6GB 설치 파일을 사용합니다. 모델은 CAD 폴더마다 복제하지 않고 사용자 폴더에 한 번 저장합니다. 설치 파일은 완료 후 삭제합니다.',True))
        self.model=choice([(name,name+' · '+size) for name,size in MODELS.items()]);self.model.setCurrentIndex(1);v.addWidget(self.model);self.log=QPlainTextEdit();self.log.setReadOnly(True);v.addWidget(self.log,1);self.bar=QProgressBar();self.bar.setRange(0,0);self.bar.hide();v.addWidget(self.bar);row=QHBoxLayout();self.start_button=button('설치 / 이어받기',self.start,True);row.addWidget(self.start_button);row.addWidget(button('연결 확인',self.check));row.addWidget(button('닫기 / 중단',self.reject));v.addLayout(row);self.progress.connect(self.log.appendPlainText)
    def check(self):self.log.appendPlainText('설치된 모델: '+(', '.join(installed_models()) or '연결되지 않았거나 모델이 없습니다.'))
    def start(self):
        if self.running:return
        self.cancel.clear();self.running=True;self.start_button.setEnabled(False);self.model.setEnabled(False);self.bar.show();model=self.model.currentData();worker=Worker(lambda:setup(model,self.progress.emit,self.cancel));self.worker=worker
        def finish(value):self.running=False;self.start_button.setEnabled(True);self.model.setEnabled(True);self.bar.hide();self.model_name=value;self.log.appendPlainText('완료 · CAD의 로컬 AI 모델: '+value)
        def fail(message):self.running=False;self.start_button.setEnabled(True);self.model.setEnabled(True);self.bar.hide();self.log.appendPlainText(message)
        worker.signals.done.connect(finish);worker.signals.failed.connect(fail);QThreadPool.globalInstance().start(worker)
    def reject(self):
        if self.running:self.cancel.set();self.log.appendPlainText('중단 요청됨 · 진행 중인 설치 작업이 끝나면 닫을 수 있습니다.');return
        super().reject()
