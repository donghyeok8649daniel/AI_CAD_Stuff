"""Regressions for covered AI tabs and settings changes during real Qt tasks."""
from copy import deepcopy
import threading
import time

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QToolButton
from test_placement_native import app
from cadstudio.catalog import preset


CATALOG=[dict(model='gpt-6-astra',name='Astra',efforts=['low','medium','high','xhigh','max','ultra']),
         dict(model='gpt-6.1-sol',name='Sol',efforts=['low','medium','high','xhigh','max'])]


@pytest.fixture
def window(app,monkeypatch,tmp_path):
    from cadstudio.native import window as module,codex_connection
    from cadstudio.native.model_picker import LocalModelPicker
    monkeypatch.setattr(module,'DATA_DIR',tmp_path)
    monkeypatch.setattr(LocalModelPicker,'refresh',lambda self:None)
    monkeypatch.setattr(codex_connection,'settings',lambda:dict(executable='mock.exe',model='gpt-6-astra'))
    monkeypatch.setattr(codex_connection,'save_settings',lambda *args:None)
    w=module.MainWindow();w.show();w.codex_catalog=deepcopy(CATALOG)
    w.codex_models.set_catalog(w.codex_catalog,w.codex_config['model']);w.update_codex_effort()
    app.processEvents()
    yield w
    w.cancel_ai();w.document.dirty=False;w.close()
    assert QThreadPool.globalInstance().waitForDone(10000)
    app.processEvents()


def wait(app,predicate):
    end=time.monotonic()+15
    while not predicate() and time.monotonic()<end:app.processEvents();time.sleep(.005)
    assert predicate()


def test_toolbar_opens_covered_or_hidden_tab_and_selection_keeps_ai_target_visible(app,window):
    w=window;w.document.commit(preset('cylinder').model_dump(),'fixture')
    w.rebuild_tree();w.property_dock.show();w.property_dock.raise_();app.processEvents()
    button=w.toolbar.widgetForAction(w.actions['show_ai']);assert isinstance(button,QToolButton)
    button.click();app.processEvents()
    assert w.ai_dock.isVisible() and not w.ai_dock.visibleRegion().isEmpty()
    assert w._ai_panel_active
    w.select_parts([w.document.design['parts'][0]['id']]);app.processEvents()
    assert w._ai_panel_active and not w.ai_target.visibleRegion().isEmpty()
    w.ai_dock.hide();app.processEvents();button.click();app.processEvents()
    assert w.ai_dock.isVisible() and w.prompt.hasFocus()
    w.set_busy(True);w.actions['show_ai'].trigger();app.processEvents()
    assert w.actions['show_ai'].isEnabled() and w.ai_dock.isEnabled()
    w.set_busy(False)


def test_explicit_effort_labels_match_each_model_and_keep_ready_draft(app,window):
    w=window;draft={'serial':w.operation_serial,'marker':'ready'};w.last_draft=draft;w.accept_draft.setEnabled(True)
    assert [w.cloud_effort.itemText(i) for i in range(w.cloud_effort.count())]==['Low','Medium','High','Extra high','Max','Ultra']
    w.codex_models.setCurrentIndex(w.codex_models.findData('gpt-6.1-sol'));app.processEvents()
    assert w.last_draft is draft and w.accept_draft.isEnabled()
    assert w.cloud_effort.findData('ultra')<0 and w.cloud_effort.findData('xhigh')>=0
    w.cloud_effort.setCurrentIndex(w.cloud_effort.findData('high'));assert w.last_draft is draft


def test_model_change_mid_generation_keeps_returned_draft_applicable(app,window,monkeypatch):
    from cadstudio.native import codex_ai
    entered=threading.Event();release=threading.Event();pairs=[]
    def generate(request,model,**options):
        pairs.append(options['runtime_config'].snapshot());entered.set();assert release.wait(5)
        pairs.append(options['runtime_config'].snapshot())
        return dict(design=preset('cylinder').model_dump(),summary='Fixture',assumptions=[],model=model,effort=options['effort'])
    monkeypatch.setattr(codex_ai,'generate',generate)
    w=window;w.prompt.setPlainText('원통 지름 30 mm 높이 20 mm');w.generate_draft();task=w.ai_task
    assert entered.wait(2) and w.codex_models.isEnabled() and w.cloud_effort.isEnabled()
    w.codex_models.setCurrentIndex(w.codex_models.findData('gpt-6.1-sol'))
    w.cloud_effort.setCurrentIndex(w.cloud_effort.findData('xhigh'))
    assert '다음 생성 단계' in w.ai_run_settings.text()
    release.set();wait(app,lambda:w.ai_task is None)
    assert pairs==[('gpt-6-astra','medium'),('gpt-6.1-sol','xhigh')]
    assert w.last_draft and w.accept_draft.isEnabled() and 'gpt-6-astra' in w.ai_result.toPlainText()
    w.apply_draft();wait(app,lambda:not w.busy)
    assert w.document.design['parts'][0]['geometry']['diameter']==30
    context=w.document.journal.data['entries'][-1]['context']
    assert context['model_provenance']=={'model':'gpt-6-astra','effort':'medium'}
    task.thread.join(2)


def test_document_change_still_rejects_stale_response(app,window,monkeypatch):
    from cadstudio.native import codex_ai
    entered=threading.Event();release=threading.Event()
    def generate(*args,**options):
        entered.set();assert release.wait(5)
        return dict(design=preset('cylinder').model_dump(),summary='Fixture',assumptions=[])
    monkeypatch.setattr(codex_ai,'generate',generate)
    w=window;w.prompt.setPlainText('원통');w.generate_draft();task=w.ai_task;assert entered.wait(2)
    w.operation_serial+=1;release.set();wait(app,lambda:w.ai_task is None)
    assert w.last_draft is None and not w.accept_draft.isEnabled()
    assert '설계가 바뀌었습니다' in w.ai_result.toPlainText()
    task.thread.join(2)
