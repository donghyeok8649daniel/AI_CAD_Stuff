import pytest
from PySide6.QtCore import QThreadPool
from test_placement_native import app


@pytest.mark.parametrize('size',[(1180,780),(820,560)])
def test_prompt_is_visible_on_open_and_settings_leave_actions_accessible(app,monkeypatch,tmp_path,size):
    from cadstudio.native import window
    from cadstudio.native.model_picker import LocalModelPicker
    monkeypatch.setattr(window,'DATA_DIR',tmp_path);monkeypatch.setattr(LocalModelPicker,'refresh',lambda self:None)
    w=window.MainWindow();w.resize(*size);w.show();w.ai_dock.show();w.ai_dock.raise_();app.processEvents()
    try:
        w.ai_scroll.verticalScrollBar().setValue(0);app.processEvents()
        assert not w.ai_settings.isVisible() and not w.ai_settings_toggle.isChecked()
        assert w.prompt.visibleRegion().contains(w.prompt.rect())
        assert w.ai_settings_toggle.visibleRegion().contains(w.ai_settings_toggle.rect())
        assert w.generate_button.visibleRegion().contains(w.generate_button.rect())
        for opened in (True,False):
            w.ai_settings_toggle.setChecked(opened);app.processEvents()
            assert w.ai_settings.isVisible()==opened
            for value in (0,w.ai_scroll.verticalScrollBar().maximum()):
                w.ai_scroll.verticalScrollBar().setValue(value);app.processEvents()
                for widget in (w.generate_button,w.accept_draft):assert widget.visibleRegion().contains(widget.rect())
        w.provider.setCurrentIndex(w.provider.findData('openai'));app.processEvents()
        assert w.ai_settings.isVisible() and w.key.isVisible() and w.astra_button.isVisible()
        assert '유료' in w.ai_info.text() and '전송' in w.ai_info.text()
        w.ai_settings_toggle.setChecked(False);app.processEvents()
        assert '유료' in w.ai_info.text() and not w.key.isVisible()
        w.provider.setCurrentIndex(w.provider.findData('ollama'))
        w.prompt.setPlainText('디스크를 만들어줘');w.generate_draft();app.processEvents()
        assert w.ai_settings_toggle.isChecked() and w.ai_task is None
        assert '설정' in w.ai_result.toPlainText()
    finally:
        w.document.dirty=False;w.close();QThreadPool.globalInstance().waitForDone(10000);app.processEvents()
