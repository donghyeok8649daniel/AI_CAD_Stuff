import threading
from copy import deepcopy

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QTreeWidgetItemIterator

from test_cad_feature_edits import hole
from test_placement_native import app, wait


def test_keyboard_feature_selection_reaches_ai_and_clears_on_part_selection(app, monkeypatch, tmp_path):
    from cadstudio.native import window, local_ai
    from cadstudio.native.model_picker import LocalModelPicker
    monkeypatch.setattr(LocalModelPicker,'refresh',lambda self:None)
    monkeypatch.setattr(window,'DATA_DIR',tmp_path)
    w=window.MainWindow();w.resize(1024,700);w.show();w.activateWindow()
    captured=[];entered=threading.Event();release=threading.Event();errors=[];w.show_error=errors.append
    def fake(request,model,**kwargs):
        captured.append(request);entered.set();release.wait(5);kwargs['control'].check()
        return dict(design=request.current.model_dump(),summary='test',assumptions=[])
    monkeypatch.setattr(local_ai,'ollama_draft',fake)
    try:
        w.apply_design(hole().model_dump(),'hole fixture');wait(app,lambda:not w.busy)
        before=deepcopy(w.document.design);items={};it=QTreeWidgetItemIterator(w.tree)
        while it.value():
            item=it.value();data=item.data(0,Qt.ItemDataRole.UserRole)
            if data:items[data[0]]=item
            item.setExpanded(True);it+=1
        w.tree.setCurrentItem(items['base']);w.tree.setFocus();app.processEvents()
        QTest.keyClick(w.tree,Qt.Key.Key_Down);app.processEvents()
        assert w.tree.currentItem()==items['feature']
        assert w.selected=='part' and w.selected_feature=='ai-feature-1'
        w.provider.setCurrentIndex(w.provider.findData('ollama'))
        w.ollama_models.models.addItem('test','test');w.prompt.setPlainText('이 구멍을 6 mm로 줄여줘')
        w.generate_draft();task=w.ai_task;assert entered.wait(3)
        assert captured[0].selected_part=='part' and captured[0].selected_feature=='ai-feature-1'
        w.cancel_ai();release.set();task.thread.join(3);app.processEvents()
        assert w.document.design==before and w.last_draft is None
        w.select_parts(['part']);assert w.selected_feature is None
        assert not errors
    finally:
        release.set()
        if w.ai_task:w.cancel_ai()
        w.document.dirty=False;w.close();QThreadPool.globalInstance().waitForDone(10000);app.processEvents()
