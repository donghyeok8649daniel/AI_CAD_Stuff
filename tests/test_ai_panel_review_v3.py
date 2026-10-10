"""Independent review regression: honor the latest tab click during CAD apply."""
import threading
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit

from test_ai_settings_v3 import app, window, wait
from cadstudio.catalog import preset


def test_ai_click_during_async_cad_apply_is_preserved_when_worker_finishes(app,window,monkeypatch):
    from cadstudio.native import window as module
    w=window;entered=threading.Event();release=threading.Event()
    original=module.preview
    def delayed_preview(*args,**kwargs):
        entered.set();assert release.wait(5)
        return original(*args,**kwargs)
    monkeypatch.setattr(module,'preview',delayed_preview)
    w.property_dock.show();w.property_dock.raise_();app.processEvents()
    assert not w._ai_panel_active
    try:
        w.apply_design(preset('cylinder').model_dump(),'Review async tab fixture')
        assert entered.wait(2) and w.busy
        w.toolbar.widgetForAction(w.actions['show_ai']).click();app.processEvents()
        assert w._ai_panel_active
        release.set();wait(app,lambda:not w.busy)
        app.processEvents()
        assert w._ai_panel_active and not w.prompt.visibleRegion().isEmpty()
    finally:
        release.set()


def test_explicit_ai_shortcut_opens_panel_while_property_text_field_has_focus(app,window):
    w=window;w.document.commit(preset('cylinder').model_dump(),'Review shortcut fixture')
    w.rebuild_tree();w.select_parts([w.document.design['parts'][0]['id']])
    w.property_dock.show();w.property_dock.raise_();app.processEvents()
    field=w.properties.findChild(QLineEdit,'partName')
    assert field is not None
    field.setFocus();app.processEvents();assert field.hasFocus() and not w._ai_panel_active
    QTest.keyClick(field,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.ShiftModifier)
    app.processEvents()
    assert w._ai_panel_active and w.prompt.hasFocus()
