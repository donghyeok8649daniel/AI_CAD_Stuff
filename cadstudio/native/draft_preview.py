"""Before/after review with an explicit apply action and no document mutations."""
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QTextEdit,QLineEdit
from .viewport import CADViewport
from .workflows import choice
from .widgets import label,button


class DraftPreviewDialog(QDialog):
    def __init__(self,parent,before,after,summary,*,validation=None,repairable=False):
        super().__init__(parent);self.setWindowTitle('AI 설계 · 적용 전 비교');self.resize(1080,760);self.setMinimumSize(800,560)
        self.before=before;self.after=after;self.validation=validation or {};self.blocked=self.validation.get('status')=='needs_repair';layout=QVBoxLayout(self)
        layout.addWidget(label('간섭이 남은 초안입니다. 원본은 그대로이며, 수정 후 검증을 통과하면 적용할 수 있습니다.' if self.blocked else '아직 원본에 적용하지 않았습니다. 변경 전·후 형상과 작업 내용을 확인하세요.',True))
        self.mode=choice([('after','변경 후 · AI 초안'),('before','변경 전 · 현재 설계')]);layout.addWidget(self.mode)
        self.viewport=CADViewport();layout.addWidget(self.viewport,1)
        self.issues=choice([('all','전체 초안 보기')]+[(i,f"{c['a']} ↔ {c['b']} · {c['volume']:.4g} mm³") for i,c in enumerate(self.validation.get('collisions',[]))]);self.issues.setVisible(self.blocked);layout.addWidget(self.issues)
        self.details=QTextEdit();self.details.setReadOnly(True);self.details.setPlainText(summary);self.details.setMaximumHeight(140);layout.addWidget(self.details)
        self.repair_note=QLineEdit();self.repair_note.setMaxLength(1000);self.repair_note.setPlaceholderText('추가 수정 지시 (선택) · 예: 시편 치수는 유지하고 클램프 홈을 넓혀줘');self.repair_note.setVisible(self.blocked and repairable);layout.addWidget(self.repair_note)
        row=QHBoxLayout();row.addWidget(button('돌아가기',self.reject));row.addStretch();self.repair_button=button('AI로 간섭 수정 계속',lambda:self.done(2),True);self.repair_button.setVisible(self.blocked and repairable);row.addWidget(self.repair_button);self.apply_button=button('검증 통과 후 적용 가능' if self.blocked else '확인 · 설계에 적용',self.accept,not self.blocked);self.apply_button.setEnabled(not self.blocked);row.addWidget(self.apply_button);layout.addLayout(row)
        self.issues.currentIndexChanged.connect(self.show_issue)
        self.mode.currentIndexChanged.connect(self.show_state);self.show_state()
    def show_state(self):
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
