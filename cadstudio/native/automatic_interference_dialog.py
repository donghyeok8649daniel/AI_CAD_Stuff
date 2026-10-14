"""Explicit search -> exact preview -> optional Codex advice -> user apply."""
from copy import deepcopy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout,QPlainTextEdit
from .widgets import number,label,button
from .workflows import PreviewDialog,choice
from .interference_adjustment import SelectedPairGate
from ..automatic_interference import automatic_separation,review_request,design_digest
from ..kernel import preview
from ..models import Design


class AutomaticInterferenceDialog(SelectedPairGate,PreviewDialog):
    def __init__(self,parent,raw,identifier,pair):
        self.base=deepcopy(raw);self.adjust_pair=list(pair);self.moved_ids=[];self.proposal=None;self.search_requested=False;self.advice_task=None
        super().__init__(parent,'간섭 자동 조정 미리보기','구속·치수를 유지한 이동 후보를 자동 검사합니다. 전체 부품과 새 간섭이 없는 후보만 제시하며 확인 후 적용합니다.')
        names={p['id']:p['name'] for p in raw['parts']};self.side=choice([(None,'움직일 수 있는 쪽 자동 선택')]+[(p,names[p]) for p in pair])
        self.axes=choice([('xyz','X / Y / Z'),('xy','X / Y'),('x','X'),('y','Y'),('z','Z')])
        self.clearance=number(.2,0,100,' mm');self.max_distance=number(25,.001,5000,' mm',decimals=3)
        form=QFormLayout();self.controls.addLayout(form)
        for title,w in [('이동 부품',self.side),('검색 축',self.axes),('분리 여유',self.clearance),('최대 이동',self.max_distance)]:form.addRow(title,w)
        for w in (self.side,self.axes):w.currentIndexChanged.connect(self.schedule)
        for w in (self.clearance,self.max_distance):w.valueChanged.connect(self.schedule)
        self.search_button=button('자동 조정안 찾기',self.search,True);self.search_button.setObjectName('automaticInterferenceSearch');self.controls.addWidget(self.search_button)
        self.summary=label('아직 검색하지 않았습니다.',True);self.controls.addWidget(self.summary)
        self.review_button=button('Codex로 조정안 재검토',self.review);self.review_button.setObjectName('interferenceCodexReview');self.review_button.setEnabled(False);self.controls.addWidget(self.review_button)
        self.advice=QPlainTextEdit();self.advice.setReadOnly(True);self.advice.setPlaceholderText('AI 자문 검토 · 정확한 형상 검사를 대체하거나 설계를 자동 변경하지 않습니다.');self.advice.setMaximumHeight(180);self.controls.addWidget(self.advice)
        self.cancel_review=button('AI 검토 취소',self.stop_advice);self.cancel_review.hide();self.controls.addWidget(self.cancel_review)
        self.controls.addWidget(label('정해진 축 방향 후보 중 가장 짧은 유효 이동입니다. 회전·자동 절삭·구속 해제는 하지 않습니다. 현재 자세만 검사하며 구동 범위·조립·공차·강도는 별도 확인합니다.',True));self.controls.addStretch()
        self.status.setText('자동 조정안 찾기를 누르세요. 원본 설계는 유지됩니다.');self.timer.stop()

    def schedule(self,*args):
        self.revision+=1;self.checked=None;self.result=None;self.interference=None;self.travel=None;self.proposal=None
        self.timer.stop();self.apply_button.setEnabled(False);self.stop_advice()
        if hasattr(self,'review_button'):self.review_button.setEnabled(False);self.advice.clear();self.summary.setText('설정이 바뀌었습니다. 다시 검색하세요.')

    def search(self):
        if self.running:return
        self.schedule();self.search_requested=True;self.calculate()

    def calculate(self):
        # The inherited preview's stale-result timer must not start a new
        # automatic search without another explicit click.
        if not self.search_requested:return
        self.search_requested=False;super().calculate()

    def candidate(self):
        revision=self.revision
        def check():
            if not self.alive or revision!=self.revision:raise RuntimeError('자동 조정 검색이 취소되었습니다.')
        return dict(raw=deepcopy(self.base),identifiers=list(self.adjust_pair),moving=self.side.currentData(),axes=self.axes.currentData(),
                    clearance=self.clearance.value(),max_distance=self.max_distance.value(),check=check)

    def compute(self,payload):
        proposal=automatic_separation(**payload)
        # Worker data is only published by PreviewDialog for the current revision.
        design=Design.model_validate(proposal['candidate']);result=preview(design);result['automatic_adjustment']=proposal
        return design,result

    def present(self):
        super().present();self.proposal=deepcopy(self.result['automatic_adjustment']);self.moved_ids=self.proposal['moved_ids']
        self.summary.setText(f"{len(self.moved_ids)}개 연결 부품 · 이동 {self.proposal['distance_mm']:.3f} mm\nΔX/Y/Z: "+' / '.join(f'{v:.3f}' for v in self.proposal['translation'])+f" mm\n남은 체적 간섭 {len(self.proposal['remaining_physical'])}쌍")
        self.viewport.select_many(self.moved_ids);self.review_button.setEnabled(True)

    def failed(self,message):
        super().failed(message);self.proposal=None;self.review_button.setEnabled(False)

    def stop_advice(self):
        task=self.advice_task;self.advice_task=None
        if task:task.cancel()
        if hasattr(self,'cancel_review'):self.cancel_review.hide()

    def review(self):
        if self.proposal is None or self.checked is None or self.advice_task:return
        parent=self.parent()
        if getattr(parent,'ai_task',None):self.advice.setPlainText('진행 중인 설계 AI 요청이 끝난 후 검토하세요.');return
        config=deepcopy(getattr(parent,'codex_config',{}));catalog=getattr(parent,'codex_catalog',[])
        model=config.get('model','')
        if not model:self.advice.setPlainText('설계 명령 / AI에서 Codex 연결과 모델 선택을 먼저 완료하세요.');return
        chosen=next((m for m in catalog if m.get('model')==model),None)
        effort=parent.cloud_effort.currentData() if hasattr(parent,'cloud_effort') else 'medium'
        if chosen and effort not in chosen.get('efforts',[]):effort=chosen.get('default_effort') or 'medium'
        try:request=review_request(self.base,self.checked.model_dump(),self.proposal)
        except ValueError as exc:self.advice.setPlainText(str(exc));return
        revision=self.revision;candidate_sha=self.proposal['candidate_digest']
        from .ai_task import AITask
        from .ai_chat import answer
        task=AITask(lambda control,progress:answer(request,'codex',model,executable=config.get('executable',''),effort=effort,
                           control=control,progress=progress,deadline=180),parent)
        self.advice_task=task;self.cancel_review.show();self.advice.setPlainText('Codex 자문 검토 중 · ChatGPT 구독 사용량 적용')
        def valid(sender):return self.alive and sender is self.advice_task and revision==self.revision and self.proposal and self.proposal['candidate_digest']==candidate_sha
        def completed(packet):
            sender,text=packet
            if not valid(sender):return
            self.advice_task=None;self.cancel_review.hide();self.advice.setPlainText('Codex 자문 · '+model+' / '+effort+'\n'+text+'\n\n현재 자세의 형상 검사만 완료했습니다. AI 답변은 제작·구동 승인이나 자동 변경이 아닙니다.')
        def failed(packet):
            sender,text=packet
            if not valid(sender):return
            self.advice_task=None;self.cancel_review.hide();self.advice.setPlainText('AI 검토를 완료하지 못했습니다. 형상 검사 결과는 보존됩니다.\n'+str(text))
        task.completed.connect(completed,Qt.ConnectionType.QueuedConnection);task.failed.connect(failed,Qt.ConnectionType.QueuedConnection);task.start()

    def accept(self):
        if self.advice_task:
            self.advice.setPlainText('AI 검토 중입니다. 완료 후 적용하거나 AI 검토 취소를 누르세요.');return
        if not self.proposal or self.checked is None:return
        if design_digest(self.checked.model_dump())!=self.proposal['candidate_digest']:self.failed('검사한 조정안과 적용 형상이 다릅니다. 다시 검색하세요.');return
        super().accept()

    def done(self,result):
        self.stop_advice();super().done(result)
