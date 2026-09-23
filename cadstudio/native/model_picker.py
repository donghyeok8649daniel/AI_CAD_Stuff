"""Non-blocking discovery of models already installed on this PC."""
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QComboBox
from .widgets import Worker,label,button
from ..ollama_setup import discover_models


class LocalModelPicker(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.running=False;self.preferred='qwen3:8b'
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);row=QHBoxLayout()
        self.models=QComboBox();self.models.setMinimumContentsLength(10);self.models.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.refresh_button=button('새로 찾기',self.refresh);row.addWidget(self.models,1);row.addWidget(self.refresh_button);layout.addLayout(row)
        self.status=label('로컬 AI를 선택하면 설치된 모델을 자동으로 찾습니다.',True);layout.addWidget(self.status)
    def model_name(self):return self.models.currentData() or ''
    def refresh(self):
        if self.running:return
        self.preferred=self.model_name() or self.preferred;self.running=True;self.refresh_button.setEnabled(False);self.status.setText('이 PC에서 설치된 모델을 찾는 중…')
        self.worker=Worker(discover_models);self.worker.signals.done.connect(self.found);self.worker.signals.failed.connect(self.failed);QThreadPool.globalInstance().start(self.worker)
    def found(self,names):
        self.running=False;self.refresh_button.setEnabled(True);self.models.clear()
        for name in names:self.models.addItem(name,name)
        if names:
            index=self.models.findData(self.preferred);self.models.setCurrentIndex(index if index>=0 else 0);self.status.setText(f'설치된 모델 {len(names)}개 · API 키 불필요')
        else:self.status.setText('설치된 모델이 없습니다. 아래 모델 다운로드 버튼을 사용하세요.')
    def failed(self,message):
        self.running=False;self.refresh_button.setEnabled(True);self.models.clear();self.status.setText(message)
