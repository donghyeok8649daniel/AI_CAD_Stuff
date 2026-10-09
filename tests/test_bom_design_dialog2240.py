"""Native BOM review owns edits until the user explicitly saves."""
from copy import deepcopy
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog

from cadstudio.bom_design import parse_bom_text
from cadstudio.native.bom_design_dialog import BomDesignDialog


TABLE = ("Name\tQuantity\tManufacturer\tModel\tLength mm\tWidth mm\tHeight mm\tRole\n"
         "Controller\t1\tRaspberry Pi\t4 Model B\t85\t56\t17\telectrical\n"
         "Mount plate\t2\t\t\t60\t35\t4\tstructure\n")


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    return instance


def dispose(app, dialog):
    dialog.reject(); dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete); app.processEvents()
    assert not shiboken6.isValid(dialog)


def fixture():
    return parse_bom_text(TABLE, source_name="owned-bom.tsv", source="owned fixture")


def test_empty_dialog_requires_rows_and_has_no_accepted_bom(app):
    dialog = BomDesignDialog(language="en")
    dialog.show(); app.processEvents()
    assert dialog.document is None and dialog.accepted_bom is None
    assert not dialog.save_button.isEnabled() and dialog.table.rowCount() == 0
    dialog.accept()
    assert dialog.accepted_bom is None and dialog.result() == QDialog.DialogCode.Rejected
    assert "at least one" in dialog.status.text()
    dispose(app, dialog)


def test_edit_apply_import_remove_and_cancel_preserve_callers_document(app):
    bom = fixture(); before = deepcopy(bom.model_dump(mode="json"))
    dialog = BomDesignDialog(bom, language="en")
    assert dialog.document is not bom and dialog.document.items[0] is not bom.items[0]
    dialog.fields["name"].setText("Reviewed controller")
    dialog.quantity.setText("3")
    assert dialog.apply_row()
    assert dialog.document.items[0].name == "Reviewed controller" and dialog.document.items[0].quantity == 3
    assert dialog.accepted_bom is None and bom.model_dump(mode="json") == before
    assert dialog.import_text("Name\tQuantity\nReplacement\t4\n")
    dialog.add_row(); dialog.remove_row()
    assert bom.model_dump(mode="json") == before and dialog.accepted_bom is None
    dispose(app, dialog)
    assert bom.model_dump(mode="json") == before


def test_save_flushes_row_edits_into_independent_authoritative_copy(app):
    bom = fixture(); before = deepcopy(bom.model_dump(mode="json"))
    dialog = BomDesignDialog(bom, language="en")
    dialog.fields["name"].setText("Controller reviewed")
    dialog.quantity.setText("3")
    dialog.dimensions["length"].setText("86.5")
    dialog.notes.setPlainText("Explicit fit measurement from the reviewed table")
    dialog.save_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted and dialog.accepted_bom is not None
    accepted = dialog.accepted_bom
    assert accepted is not dialog.document and accepted.items[0] is not dialog.document.items[0]
    assert accepted.items[0].quantity == 3 and accepted.items[0].dimensions_mm["length"] == 86.5
    assert accepted.items[0].name == "Controller reviewed"
    assert accepted.items[0].raw_fields == bom.items[0].raw_fields
    assert accepted.source_sha256 == bom.source_sha256 and bom.model_dump(mode="json") == before
    dialog.document.items[0].name = "Later private mutation"
    assert accepted.items[0].name == "Controller reviewed"
    dialog.deleteLater(); QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete); app.processEvents()


@pytest.mark.parametrize("quantity", ["-1", "0", "1.5", "1e3", "NaN"])
def test_invalid_quantity_blocks_save_and_keeps_valid_private_row(app, quantity):
    dialog = BomDesignDialog(fixture(), language="en"); before = dialog.document.model_dump(mode="json")
    dialog.quantity.setText(quantity); dialog.save_button.click()
    assert dialog.accepted_bom is None and dialog.document.model_dump(mode="json") == before
    assert dialog.quantity.text() == quantity and "positive integer" in dialog.status.text()
    dispose(app, dialog)


@pytest.mark.parametrize("dimension", ["-2", "0", "nan", "inf", "2x3"])
def test_invalid_dimensions_block_save_and_keep_edit_visible(app, dimension):
    dialog = BomDesignDialog(fixture(), language="en"); before = dialog.document.model_dump(mode="json")
    dialog.dimensions["width"].setText(dimension); dialog.save_button.click()
    assert dialog.accepted_bom is None and dialog.document.model_dump(mode="json") == before
    assert dialog.dimensions["width"].text() == dimension and dialog.status.text()
    dispose(app, dialog)


def test_unknown_values_are_retained_and_can_be_saved_for_pending_design(app):
    dialog = BomDesignDialog(language="en")
    assert dialog.import_text("Name\tQuantity\tModel\tDimensions\nUnknown mount\t\t\t50x20x4 mm\n")
    assert dialog.document.items[0].quantity is None and not dialog.document.items[0].dimensions_mm
    assert dialog.pending.toPlainText() and "50x20x4 mm" in dialog.source_details.toPlainText()
    dialog.quantity.setText("2"); dialog.quantity_unit.setCurrentIndex(dialog.quantity_unit.findData("ea"))
    dialog.dimensions["length"].setText("50"); dialog.dimensions["width"].setText("20"); dialog.dimensions["thickness"].setText("4")
    dialog.save_button.click()
    assert dialog.accepted_bom is not None
    item = dialog.accepted_bom.items[0]
    assert item.quantity == 2 and item.dimensions_mm == {"length": 50, "width": 20, "thickness": 4}
    assert item.dimensions_text == "50x20x4 mm" and item.raw_fields["Dimensions"] == "50x20x4 mm"
    dialog.deleteLater(); QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete); app.processEvents()


def test_actual_exact_catalog_match_requires_explicit_selection(app):
    dialog = BomDesignDialog(fixture(), language="en")
    assert dialog.catalog.count() >= 1 and dialog.catalog.currentData() is not None
    match = dialog.catalog.currentData()
    assert match["namespace"] == "electrical" and match["catalog_id"] == "rpi4b"
    assert "electrical/rpi4b" in dialog.catalog.currentText()
    before = deepcopy(dialog.document.items[0].dimensions_mm)
    dialog.match_button.click()
    item = dialog.document.items[0]
    assert item.catalog_namespace == "electrical" and item.catalog_id == "rpi4b"
    assert item.manufacturer == "Raspberry Pi" and item.model == "4 Model B"
    assert item.dimensions_mm == before and dialog.accepted_bom is None
    dialog.fields["model"].setText("Unknown custom model"); assert dialog.apply_row()
    assert not dialog.document.items[0].catalog_id and dialog.catalog.currentData() is None
    dispose(app, dialog)


def test_row_selection_commits_valid_edits_and_keeps_invalid_edits_on_old_row(app):
    dialog = BomDesignDialog(fixture(), language="en")
    dialog.fields["name"].setText("Edited first")
    dialog.table.selectRow(1)
    assert dialog.document.items[0].name == "Edited first"
    assert dialog._row == 1 and dialog.table.currentRow() == 1
    dialog.quantity.setText("1.5"); dialog.table.selectRow(0)
    assert dialog._row == 1 and dialog.table.currentRow() == 1 and dialog.quantity.text() == "1.5"
    assert dialog.accepted_bom is None
    dispose(app, dialog)


def test_failed_import_preserves_valid_review_and_unapplied_edits(app, tmp_path):
    dialog = BomDesignDialog(fixture(), language="en")
    before = dialog.document.model_dump(mode="json")
    dialog.fields["name"].setText("Unapplied review")
    assert not dialog.import_file(tmp_path / "missing.xlsx")
    assert dialog.document.model_dump(mode="json") == before and dialog.fields["name"].text() == "Unapplied review"
    assert dialog.accepted_bom is None and dialog.status.text()
    dispose(app, dialog)


def write_xlsx(path: Path, multiple=False):
    rows = (("Name", "Quantity", "Model", "Length mm", "Role"),
            ("Workbook mount", "2", "", "50", "structure"))
    cells = []
    for number, values in enumerate(rows, 1):
        cells.append(f'<row r="{number}">' + ''.join(
            f'<c r="{chr(65 + column)}{number}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
            for column, value in enumerate(values)) + '</row>')
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        archive.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        other_sheet = '<sheet name="Notes" sheetId="2" r:id="rId2"/>' if multiple else ""
        other_relation = '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>' if multiple else ""
        archive.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="BOM" sheetId="1" r:id="rId1"/>' + other_sheet + '</sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>' + other_relation + '</Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + ''.join(cells) + '</sheetData></worksheet>')
        if multiple: archive.writestr("xl/worksheets/sheet2.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/></worksheet>')


@pytest.mark.parametrize("suffix", [".csv", ".tsv", ".xlsx"])
def test_file_import_button_uses_native_file_picker_and_real_parser(app, tmp_path, monkeypatch, suffix):
    path = tmp_path / ("owned-table" + suffix)
    if suffix == ".xlsx": write_xlsx(path)
    elif suffix == ".csv": path.write_text("Name,Quantity,Model,Length mm,Role\nWorkbook mount,2,,50,structure\n", encoding="utf-8-sig")
    else: path.write_text("Name\tQuantity\tModel\tLength mm\tRole\nWorkbook mount\t2\t\t50\tstructure\n", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), "BOM"))
    dialog = BomDesignDialog(language="en"); dialog.import_button.click()
    assert dialog.document is not None, dialog.status.text()
    assert dialog.document.items[0].name == "Workbook mount" and dialog.document.items[0].quantity == 2
    assert dialog.document.items[0].dimensions_mm["length"] == 50
    assert dialog.document.source_name == path.name and dialog.accepted_bom is None
    dispose(app, dialog)


def test_add_and_remove_all_rows_keeps_save_disabled_until_rows_exist(app):
    dialog = BomDesignDialog(language="en"); dialog.add_button.click()
    assert dialog.document is not None and len(dialog.document.items) == 1
    assert dialog.document.items[0].quantity is None and dialog.save_button.isEnabled()
    dialog.remove_button.click()
    assert dialog.table.rowCount() == 0 and not dialog.save_button.isEnabled()
    assert dialog.accepted_bom is None
    dialog.add_button.click()
    assert dialog.table.rowCount() == 1 and dialog.save_button.isEnabled()
    dispose(app, dialog)


def test_multiple_sheet_workbook_requires_explicit_sheet_and_preserves_prior_on_failure(app, tmp_path):
    path = tmp_path / "two-sheets.xlsx"; write_xlsx(path, multiple=True)
    dialog = BomDesignDialog(fixture(), language="en"); before = dialog.document.model_dump(mode="json")
    assert not dialog.import_file(path) and dialog.document.model_dump(mode="json") == before
    dialog.sheet_name.setText("BOM")
    assert dialog.import_file(path), dialog.status.text()
    assert dialog.document.sheet_name == "BOM" and dialog.document.items[0].name == "Workbook mount"
    assert dialog.accepted_bom is None
    dispose(app, dialog)


def test_catalog_id_can_be_corrected_explicitly_without_guessing_a_model(app):
    dialog = BomDesignDialog(language="en")
    assert dialog.import_text("Name\tQuantity\tLength mm\nController to identify\t1\t85\n")
    dialog.fields["catalog_id"].setText("rpi4b")
    dialog.catalog_namespace.setCurrentIndex(dialog.catalog_namespace.findData("electrical"))
    assert dialog.apply_row()
    assert dialog.document.items[0].model == "" and dialog.catalog.currentData()["catalog_id"] == "rpi4b"
    dialog.match_button.click()
    assert dialog.document.items[0].model == "4 Model B" and dialog.document.items[0].catalog_id == "rpi4b"
    assert dialog.accepted_bom is None
    dispose(app, dialog)


def test_small_layout_keeps_save_and_cancel_visible_with_source_review(app, tmp_path):
    dialog = BomDesignDialog(fixture(), language="en")
    dialog.show(); dialog.resize(1024, 700); app.processEvents(); QTest.qWait(30)
    assert dialog.width() <= 1024 and dialog.height() <= 700, dialog.size()
    for control in dialog.controls.buttons():
        area = QRect(control.mapTo(dialog, QPoint(0, 0)), control.size())
        assert dialog.rect().contains(area) and control.visibleRegion().boundingRect() == control.rect()
    assert "SHA-256" in dialog.source_details.toPlainText()
    assert "owned-bom.tsv" in dialog.summary.text()
    assert dialog.grab().save(str(tmp_path / "bom-review-small2240.png"))
    dispose(app, dialog)


@pytest.mark.parametrize("language,verified,retained", [
    ("ko", True, False), ("en", False, False), ("ko", False, True), ("en", True, True),
])
def test_bom_worker_input_error_preserves_connection_checkpoint_and_design(app, monkeypatch, tmp_path, language, verified, retained):
    from cadstudio.bom_design import BomInputRequired
    from cadstudio.models import Design
    from cadstudio.kernel import preview
    from cadstudio.native.ai_task import AITask
    from cadstudio.native import window
    from cadstudio.native.model_picker import LocalModelPicker
    monkeypatch.setattr(window, "DATA_DIR", tmp_path / "profile")
    monkeypatch.setattr(LocalModelPicker, "refresh", lambda self: None)
    # The focused check exercises the worker packet and actual native controls.
    # Earlier native smoke verifies the rendered checkpoint under both renderers.
    monkeypatch.setattr(window.CADViewport, "initialize", lambda self: None)
    w = window.MainWindow(restore=False)
    prior_language = w.language_service.language
    w.language_service.set_language(language, persist=False)
    current = Design(name="Owned BOM", bom=fixture(), parts=[dict(id="plate", name="Reviewed plate",
        geometry=dict(kind="plate", length=60, width=35, thickness=4, hole_count=0))])
    w.document.commit(current, "Owned input")
    before = deepcopy(w.document.project().model_dump(mode="json"))
    blocked = w.provider.blockSignals(True)
    w.provider.setCurrentIndex(w.provider.findData("codex"))
    w.provider.blockSignals(blocked)
    w.codex_connection_verified = verified
    w.codex_status.setText("Existing verified connection" if verified else "Existing unverified connection")
    w.codex_status.setStyleSheet("color:#abcdef;")
    w.codex_status.setToolTip("Original connection details")
    connection = (w.codex_status.text(), w.codex_status.styleSheet(), w.codex_status.toolTip())
    error = BomInputRequired("BOM에 추가할 CAD 부품이 최소 33개입니다. 부품표를 나누어 다시 생성하세요.")
    def needs_bom_inputs(*args):
        raise error
    task = AITask(needs_bom_inputs)
    packets = []
    task.failed.connect(packets.append)
    task.failed.connect(w.ai_failed)
    w.ai_task = task
    w.ai_draft_context = dict(serial=w.operation_serial, provider="codex", prompt="Reviewed BOM",
                              request=dict(prompt="Reviewed BOM", current=current.model_dump(), bom=current.bom.model_dump()))
    if retained:
        task.control.keep_draft(dict(design=current.model_dump(), summary="Preserved BOM preview",
            validation=dict(status="needs_repair", issues=["BOM quantity needs review"])), preview(current))
    w.ai_controls(True); w.ai_timer.start()
    try:
        task._run(); app.processEvents()
        assert packets == [(task, error)]
        assert w.ai_task is None and not w.ai_timer.isActive()
        assert w.codex_connection_verified is verified
        assert (w.codex_status.text(), w.codex_status.styleSheet(), w.codex_status.toolTip()) == connection
        assert w.document.project().model_dump(mode="json") == before and w.document.dirty
        text = w.ai_result.toPlainText()
        assert ("BOM 입력 확인 필요" if language == "ko" else "BOM inputs need review") in text
        assert ("BOM 보고 설계…" if language == "ko" else "Design from BOM…") in text
        assert str(error) in text and "초안 생성 실패" not in text
        assert w.generate_button.isEnabled() and w.bom_button.isEnabled()
        if retained:
            assert w.last_draft["design"] == current.model_dump()
            assert w.last_draft["response"]["summary"] == "Preserved BOM preview"
            assert w.accept_draft.isEnabled() and "Preserved BOM preview" in text
        else:
            assert w.last_draft is None
        w.ai_failed((object(), error))
        assert w.ai_result.toPlainText() == text and w.codex_connection_verified is verified
    finally:
        w.language_service.set_language(prior_language, persist=False)
        w.document.dirty = False
        w.close(); w.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete); app.processEvents()


def test_bom_worker_cancel_guard_never_publishes_input_error(app):
    from cadstudio.bom_design import BomInputRequired
    from cadstudio.native.ai_task import AITask
    invoked = []
    def needs_bom_inputs(*args):
        invoked.append(True)
        raise BomInputRequired("BOM inputs need correction")
    task = AITask(needs_bom_inputs); packets = []
    task.failed.connect(packets.append)
    task.cancel(); task._run(); app.processEvents()
    assert not packets and not invoked
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete); app.processEvents()
