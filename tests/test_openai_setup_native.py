import asyncio
import threading
import time

import httpx
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from test_placement_native import app


def wait(app, predicate):
    deadline=time.monotonic()+10
    while not predicate() and time.monotonic()<deadline:
        app.processEvents();time.sleep(.01)
    assert predicate()
    app.processEvents()


def test_probe_result_is_visible_and_editing_invalidates_it(app,monkeypatch):
    from cadstudio.native import cloud_connection
    from cadstudio.native.openai_setup import OpenAISetupDialog
    original=cloud_connection.check_access;calls=[]
    def handle(request):
        calls.append(request)
        return httpx.Response(404,headers={'x-request-id':'req_example'},json={'error':{'code':'model_not_found','param':'model','message':'private'}})
    monkeypatch.setattr(cloud_connection,'check_access',lambda key,model,**kw:original(key,model,transport=httpx.MockTransport(handle),**kw))
    dialog=OpenAISetupDialog(None,'fake-key','gpt-6-astra');dialog.resize(450,500);dialog.show();app.processEvents()
    try:
        dialog.check_button.click();wait(app,lambda:dialog.task is None)
        assert len(calls)==1 and 'model_not_found' in dialog.status.toPlainText() and 'private' not in dialog.status.toPlainText()
        for item in (dialog.status,dialog.use_button):assert item.visibleRegion().contains(item.rect())
        assert dialog.key.isEnabled() and dialog.model.isEnabled()
        dialog.key.setFocus();QTest.keyClicks(dialog.key,'changed');app.processEvents()
        assert '다시 실행' in dialog.status.toPlainText() and not dialog.has_check_result
    finally:dialog.reject();dialog.key.clear();dialog.deleteLater();app.processEvents()


def test_close_probe_cancels_without_waiting_for_network(app,monkeypatch):
    from cadstudio.native import cloud_connection
    from cadstudio.native.openai_setup import OpenAISetupDialog
    original=cloud_connection.check_access;entered=threading.Event();closed=threading.Event()
    async def handle(request):
        entered.set()
        try:await asyncio.sleep(60)
        finally:closed.set()
    monkeypatch.setattr(cloud_connection,'check_access',lambda key,model,**kw:original(key,model,transport=httpx.MockTransport(handle),**kw))
    dialog=OpenAISetupDialog(None,'fake-key','gpt-6-astra');dialog.show();app.processEvents()
    dialog.check_button.click();wait(app,entered.is_set);task=dialog.task
    start=time.monotonic();dialog.reject()
    assert time.monotonic()-start<.5 and dialog.task is None
    wait(app,closed.is_set);task.thread.join(2)
    assert not task.thread.is_alive()
    dialog.key.clear();dialog.deleteLater();app.processEvents()
