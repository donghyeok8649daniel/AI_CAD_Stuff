"""Before/after review with an explicit apply action and no document mutations."""
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QTextEdit
from .viewport import CADViewport
from .workflows import choice
from .widgets import label,button


class DraftPreviewDialog(QDialog):
    def __init__(self,parent,before,after,summary):
        super().__init__(parent);self.setWindowTitle('AI 설계 · 적용 전 비교');self.resize(1080,760);self.setMinimumSize(800,560)
        self.before=before;self.after=after;layout=QVBoxLayout(self)
        layout.addWidget(label('아직 원본에 적용하지 않았습니다. 변경 전·후 형상과 작업 내용을 확인하세요.',True))
        self.mode=choice([('after','변경 후 · AI 초안'),('before','변경 전 · 현재 설계')]);layout.addWidget(self.mode)
        self.viewport=CADViewport();layout.addWidget(self.viewport,1)
        self.details=QTextEdit();self.details.setReadOnly(True);self.details.setPlainText(summary);self.details.setMaximumHeight(140);layout.addWidget(self.details)
        row=QHBoxLayout();row.addStretch();row.addWidget(button('돌아가기',self.reject));self.apply_button=button('확인 · 설계에 적용',self.accept,True);row.addWidget(self.apply_button);layout.addLayout(row)
        self.mode.currentIndexChanged.connect(self.show_state);self.show_state()
    def show_state(self):
        result=self.after if self.mode.currentData()=='after' else self.before
        # Keep the view orientation/zoom when switching to compare positions.
        self.viewport.load(result,fit=self.viewport.result is None)
    def done(self,result):
        self.viewport.shutdown();super().done(result)
