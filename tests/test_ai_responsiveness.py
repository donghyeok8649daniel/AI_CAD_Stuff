import asyncio
import json
import threading
import time
import httpx
import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from cadstudio.catalog import preset
from cadstudio.models import DraftRequest
from cadstudio.native.local_ai import DraftControl,DraftCancelled,ollama_draft


class Chunks(httpx.AsyncByteStream):
    def __init__(self,data):self.data=data
    async def __aiter__(self):
        for chunk in self.data:yield chunk


def reply():return dict(design=preset('cylinder').model_dump(),summary='원통',assumptions=[])


def test_stream_handles_fragmented_utf8_and_reports_before_completion():
    content=json.dumps(reply(),ensure_ascii=False);events=[]
    wire=b''.join((json.dumps(dict(message=dict(content=part),done=False),ensure_ascii=False)+'\n').encode() for part in (content[:100],content[100:]))+b'{"done":true}\n'
    def handle(request):
        assert json.loads(request.content)['stream'] is True
        return httpx.Response(200,stream=Chunks([wire[i:i+7] for i in range(0,len(wire),7)]))
    result=ollama_draft(DraftRequest(prompt='원통'),'test',httpx.MockTransport(handle),progress=events.append)
    assert result['summary']=='원통' and any('수신' in e for e in events)


def test_cancel_interrupts_wait_before_headers_and_closes_request():
    started=threading.Event();closed=threading.Event();control=DraftControl();errors=[]
    async def handle(request):
        started.set()
        try:await asyncio.sleep(60)
        finally:closed.set()
    def work():
        try:ollama_draft(DraftRequest(prompt='원통'),'test',httpx.MockTransport(handle),control=control)
        except Exception as exc:errors.append(exc)
    worker=threading.Thread(target=work,daemon=True);worker.start();assert started.wait(3)
    control.cancel();worker.join(2)
    assert not worker.is_alive() and closed.is_set() and isinstance(errors[0],DraftCancelled)


def test_deadline_interrupts_a_stalled_server():
    async def handle(request):await asyncio.sleep(60)
    with pytest.raises(ValueError,match='제한 시간'):
        ollama_draft(DraftRequest(prompt='원통'),'test',httpx.MockTransport(handle),deadline=.03)


def test_edit_context_keeps_kinds_dimensions_and_existing_design():
    from cadstudio.models import Design
    current=preset('robot_arm')
    def handle(request):
        data=json.loads(json.loads(request.content)['messages'][1]['content'])['current_design']
        assert Design.model_validate(data).model_dump()==current.model_dump()
        assert all(p['geometry']['kind'] for p in data['parts'])
        return httpx.Response(200,json=dict(done=True,message=dict(content=json.dumps(reply()))))
    ollama_draft(DraftRequest(prompt='관절 변경',current=current),'test',httpx.MockTransport(handle))


@pytest.mark.parametrize('wire,match',[(b'{"error":"model crashed"}\n','생성 오류'),(b'{"message":{"content":"{}"},"done":false}\n','끊어졌'),(b'{"done":true,"done_reason":"length"}\n','출력 길이')])
def test_stream_failures_return_actionable_messages(wire,match):
    with pytest.raises(ValueError,match=match):
        ollama_draft(DraftRequest(prompt='원통'),'test',httpx.MockTransport(lambda r:httpx.Response(200,content=wire)))


def test_gui_remains_editable_cancel_ignores_late_result_and_close_returns(monkeypatch,tmp_path):
    global _APP
    _APP=QApplication.instance() or QApplication([]);_APP.setQuitOnLastWindowClosed(False)
    import cadstudio.native.window as module
    import cadstudio.native.local_ai as provider
    monkeypatch.setattr(module,'DATA_DIR',tmp_path)
    entered=threading.Event();release=threading.Event()
    def fake(request,model,**kwargs):
        entered.set();release.wait(5);return reply()
    monkeypatch.setattr(provider,'ollama_draft',fake)
    w=module.MainWindow(restore=False);w.resize(1024,640);w.show();w.ai_dock.show();w.ai_dock.raise_();_APP.processEvents()
    w.ai_scroll.ensureWidgetVisible(w.accept_draft);_APP.processEvents()
    assert w.ai_scroll.viewport().rect().contains(w.accept_draft.mapTo(w.ai_scroll.viewport(),w.accept_draft.rect().center()))
    w.ai_scroll.ensureWidgetVisible(w.generate_button);_APP.processEvents()
    # Set the provider without making a real discovery request in this test.
    w.provider.blockSignals(True);w.provider.setCurrentIndex(w.provider.findData('ollama'));w.provider.blockSignals(False)
    w.ollama_models.models.addItem('test','test');w.prompt.setPlainText('원통')
    w.generate_button.click();task=w.ai_task;assert entered.wait(2)
    assert not w.busy and w.toolbar.isEnabled() and w.actions['save'].isEnabled()
    assert w.ai_status_button.isVisible() and '경과' in w.ai_result.toPlainText()
    w.cancel_ai();assert not w.ai_task and w.generate_button.isEnabled()
    release.set();task.thread.join(2);_APP.processEvents();assert w.last_draft is None and w.document.design is None
    entered.clear();release.clear();w.generate_button.click();task=w.ai_task;assert entered.wait(2)
    w.operation_serial+=1;release.set();task.thread.join(2);_APP.processEvents()
    assert w.last_draft is None and not w.accept_draft.isEnabled()
    entered.clear();release.clear();w.generate_button.click();task=w.ai_task;assert entered.wait(2)
    start=time.monotonic();w.close();assert time.monotonic()-start<1 and not w.isVisible() and task.control.cancelled.is_set()
    release.set();task.thread.join(2);_APP.processEvents();QThreadPool.globalInstance().waitForDone(5000)
