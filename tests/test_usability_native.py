import json,time
from copy import deepcopy
import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QLabel,QLineEdit
from PySide6.QtTest import QTest
from test_placement_native import app


def wait(app,predicate):
    end=time.monotonic()+25
    while not predicate():
        app.processEvents();QTest.qWait(10)
        assert time.monotonic()<end


def test_language_switch_preserves_document_and_user_text_and_grid_state(app,monkeypatch,tmp_path):
    from cadstudio.native import window
    from cadstudio.models import Design,Part
    monkeypatch.setattr(window,'DATA_DIR',tmp_path);monkeypatch.setenv('CADSTUDIO_DATA_DIR',str(tmp_path))
    w=window.MainWindow();w.show();app.processEvents();service=w.language_service;old_path=service.path;service.path=tmp_path/'ui-settings.json'
    try:
        d=Design(parts=[Part(id='p',name='폭',geometry=dict(kind='cylinder',diameter=12,height=20))]);w.apply_design(d.model_dump(),'한글 작업');wait(app,lambda:not w.busy);w.select_part('p');before=deepcopy(w.document.design)
        w.prompt.setPlainText('원통을 설계해줘');edit=QLineEdit('새 설계',w)
        service.set_language('en');app.processEvents()
        assert w.actions['print_profile'].text()=='3D printer · project allowances…'
        assert w.viewport.filter.itemText(3)=='Faces' and w.viewport.filter.itemData(3)=='face'
        assert w.document.design==before and w.prompt.toPlainText()=='원통을 설계해줘' and edit.text()=='새 설계'
        assert any(label.property('cadUserText') and label.text()=='폭' for label in w.findChildren(QLabel))
        from cadstudio.catalog import FIELDS
        from cadstudio.native.i18n import translate
        assert all(translate(title,'en')!=title for title,_ in FIELDS.values())
        caption=w.viewport.caption;full=caption.text();caption.resize(80,38)
        assert caption.text()==full and caption.toolTip()==full
        assert not caption.wordWrap()
        assert json.loads(service.path.read_text())['language']=='en'
        w.actions['grid'].trigger();w.actions['axes'].trigger();app.processEvents()
        assert not w.viewport.grid_actor.GetVisibility() and not w.viewport.axes_widget.GetEnabled()
        assert not w.editor.grid_visible and not w.editor.axes_visible
        w.viewport.make_grid(600);assert w.viewport.grid_spacing==100 and not w.viewport.grid_actor.GetVisibility()
        w.actions['grid'].trigger();w.actions['axes'].trigger();assert '100 mm' in w.viewport.grid_label.text()
        assert w.viewport.axes_widget.GetEnabled() and w.viewport.grid_actor.GetVisibility()
        captured=[];monkeypatch.setattr(window.QMessageBox,'about',lambda *args:captured.append(args[-1]));w.actions['about'].trigger();assert 'v2.10.0' in captured[0]
        service.set_language('ko');app.processEvents();assert w.actions['print_profile'].text()=='3D 프린터 · 전체 여유 / 공차…'
    finally:
        service.set_language('ko',False);service.path=old_path;w.document.dirty=False;w.close();app.processEvents();QThreadPool.globalInstance().waitForDone(5000)


def test_printer_dialog_preview_disable_cancel_and_english(app):
    from cadstudio.native.print_profile_dialog import PrintProfileDialog
    from cadstudio.models import Design,Part
    from cadstudio.native.i18n import install_language
    raw=Design(parts=[Part(id='p',name='한글 부품',geometry=dict(kind='cylinder',diameter=20,bore_diameter=10,height=5))]).model_dump();before=deepcopy(raw)
    dialog=PrintProfileDialog(None,raw);dialog.show()
    try:
        dialog.check_rows(True);wait(app,lambda:dialog.checked is not None)
        assert dialog.checked.parts[0].geometry.bore_diameter==10.2
        service=app.cad_language;service.set_language('en',False);app.processEvents()
        assert dialog.enabled.text()=='Enable printer allowances' and dialog.apply_button.text()=='Apply to design'
        assert dialog.table.item(0,0).text().startswith('한글 부품')
        dialog.inputs['hole_expansion'].setValue(.4);wait(app,lambda:dialog.checked is not None);assert dialog.checked.parts[0].geometry.bore_diameter==10.4
        dialog.enabled.setChecked(False);wait(app,lambda:dialog.checked is not None);assert dialog.checked.parts[0].geometry.bore_diameter==10
    finally:
        dialog.reject();app.cad_language.set_language('ko',False);app.processEvents();QThreadPool.globalInstance().waitForDone(5000)
    assert raw==before


def test_specs_dialog_closing_discards_late_reply_and_prompt_does_not_run_ai(app):
    from cadstudio.native.component_specs_dialog import ComponentSpecsDialog
    from cadstudio.component_specs import parse_product_page
    d=ComponentSpecsDialog();d.show();record=parse_product_page('<title>MCU</title><p>Dimensions: 20 x 30 x 5 mm</p>','https://example.com')
    d.loaded(record);assert d.use.isEnabled();d.finish('dimensions');assert d.record['selected_dimensions_mm']==[20,30,5]
    other=ComponentSpecsDialog();other.show();other.reject();other.loaded(record);assert other.record is None
