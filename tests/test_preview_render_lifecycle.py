"""A finished hidden preview must never render an uncreated native WGL surface."""
from copy import deepcopy
from types import SimpleNamespace
import time

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from cadstudio.models import Design, Part
from cadstudio.native.document import Document
from cadstudio.native.viewport import CADViewport
from cadstudio.native.workflows import PreviewDialog
from cadstudio.native.window import MainWindow


@pytest.fixture(scope='module')
def app():
    instance=QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    yield instance
    assert QThreadPool.globalInstance().waitForDone(10000)
    instance.processEvents()


def test_hidden_viewport_cannot_initialize_or_render_before_show_or_after_close(app):
    view=CADViewport();calls=[];view.window.Render=lambda:calls.append('raw render')
    try:
        view.render();view.initialize();app.processEvents()
        assert not view.initialized and calls==[]
        view.shutdown();view.render();view.initialize();app.processEvents()
        assert view.closed and calls==[]
    finally:view.close();view.deleteLater();app.processEvents()


def test_actual_async_hidden_collision_completion_and_close_never_calls_raw_render(app):
    raw=Design(parts=[Part(id='a',name='a',geometry=dict(kind='cylinder',height=10,diameter=10)),
                      Part(id='b',name='b',geometry=dict(kind='cylinder',height=10,diameter=10),transform=dict(x=2))]).model_dump()
    class HiddenPreview(PreviewDialog):
        def candidate(self):return deepcopy(raw)
    dialog=HiddenPreview(None,'Hidden lifecycle regression','No native window is ever shown.')
    calls=[];dialog.viewport.window.Render=lambda:calls.append('raw render')
    try:
        dialog.schedule();deadline=time.monotonic()+30
        while dialog.checked is None and time.monotonic()<deadline:app.processEvents();QTest.qWait(10)
        assert dialog.checked is not None and dialog.interference['blocked'],dialog.status.text()
        assert not dialog.apply_button.isEnabled() and not dialog.viewport.initialized
        assert len(dialog.viewport.actors)==2 and calls==[]
        dialog.reject();app.processEvents();assert dialog.viewport.closed and calls==[]
    finally:
        if dialog.alive:dialog.reject()
        assert QThreadPool.globalInstance().waitForDone(10000)
        dialog.deleteLater();app.processEvents()


def context_fixture():
    document=Document()
    initial=Design(parts=[Part(id='chamber-case',name='case',geometry=dict(kind='cylinder')),
                          Part(id='chamber-door',name='door',geometry=dict(kind='cylinder'),transform=dict(x=100))])
    document.commit(initial,'Before factory');root=document.journal.data['cursor']
    after=initial.model_dump();after['parts'][0]['name']='Factory case'
    context=dict(tool='chamber',chamber_part_ids=['chamber-case','chamber-door'],
                 chamber_requirements=dict(protected_swept_bounds=dict(minimum_mm=[-30,-40,-60],maximum_mm=[30,40,60])))
    document.commit(after,'Factory entry',context);future=document.journal.data['cursor']
    window=SimpleNamespace(document=document,selected_parts=['chamber-case'],selected='chamber-case')
    return window,root,future,context


def test_chamber_factory_context_is_scoped_to_current_cursor_and_complete_component_set():
    window,root,future,context=context_fixture();doc=window.document
    assert MainWindow.chamber_context(window)==context
    copied=MainWindow.chamber_context(window);copied['chamber_part_ids'].clear()
    assert MainWindow.chamber_context(window)==context
    doc.commit(doc.journal.at(root),'Move before factory',cursor=root)
    assert MainWindow.chamber_context(window) is None
    branch=deepcopy(doc.design);branch['parts'][1]['name']='Other branch'
    doc.commit(branch,'Alternate branch')
    assert MainWindow.chamber_context(window) is None
    doc.commit(doc.journal.at(future),'Restore factory branch',cursor=future)
    partial=deepcopy(doc.design);partial['parts']=partial['parts'][:1];doc.commit(partial,'One component removed')
    assert MainWindow.chamber_context(window) is None


def test_main_window_cancelled_chamber_dialog_preserves_document_and_factory_context(monkeypatch):
    import cadstudio.native.chamber_dialog as module
    window,_,_,context=context_fixture();before=window.document.project().model_dump();events=[]
    class CancelledDialog:
        def __init__(self,parent,raw,**options):
            assert raw==window.document.design and options['replace_ids']==context['chamber_part_ids']
            assert options['requirements']==context['chamber_requirements'];events.append('constructed')
        def exec(self):events.append('cancelled');return QDialog.DialogCode.Rejected
        def deleteLater(self):events.append('disposed')
    monkeypatch.setattr(module,'ChamberDialog',CancelledDialog)
    window.busy=False;window.sketching=False
    window.chamber_context=lambda:MainWindow.chamber_context(window)
    window.apply_design=lambda *_args,**_kwargs:events.append('unexpected commit')
    MainWindow.chamber_dialog(window)
    assert events==['constructed','cancelled','disposed'] and window.document.project().model_dump()==before


def test_engineering_actions_are_in_the_real_native_main_window(app,monkeypatch,tmp_path):
    from cadstudio.native import window as module
    from cadstudio.native.model_picker import LocalModelPicker
    monkeypatch.setattr(module,'DATA_DIR',tmp_path);monkeypatch.setenv('CADSTUDIO_DATA_DIR',str(tmp_path))
    monkeypatch.setattr(LocalModelPicker,'refresh',lambda self:None)
    window=MainWindow()
    try:
        for key in ('materials','force_acquisition','chamber','specimen'):
            assert key in window.actions and window.actions[key].isEnabled()
        assert window.document.design is None and not window.viewport.initialized
    finally:
        window.document.dirty=False;window.close();app.processEvents()
