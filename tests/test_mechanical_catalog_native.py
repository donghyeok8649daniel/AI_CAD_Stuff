"""Native mechanical browser keeps verified facts and user text separate from UI labels."""

from types import SimpleNamespace
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QPlainTextEdit

from cadstudio.mechanical_catalog import get_catalog_entry
from cadstudio.native import mechanical_catalog_dialog as catalog_ui
from cadstudio.native.mechanical_catalog_dialog import MechanicalCatalogDialog


@pytest.fixture
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    yield instance
    instance.processEvents()


def test_browser_search_category_exact_sku_and_empty_result(app):
    dialog = MechanicalCatalogDialog(query="1759017")
    try:
        assert dialog.selected().catalog_id == "phoenix_mstb_2"
        assert dialog.table.item(0, 2).text() == dialog.selected().model

        wire_index = dialog.category.findData("전선")
        assert wire_index > 0
        dialog.category.setCurrentIndex(wire_index)
        dialog.query.setText("9918")
        assert dialog.table.rowCount() == 1
        assert dialog.selected().catalog_id == "belden_9918"

        dialog.query.setText("1759017")
        assert dialog.table.rowCount() == 0
        assert dialog.selected() is None
        assert not dialog.copy_button.isEnabled()
        assert not dialog.use_button.isEnabled()
        assert not dialog.open_button.isEnabled()
        assert "일치하는 자료가 없습니다" in dialog.details.toPlainText()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_official_source_opens_the_selected_url(app, monkeypatch):
    opened = []
    monkeypatch.setattr(catalog_ui.QDesktopServices, "openUrl",
                        lambda url: opened.append(url.toString()) or True)
    dialog = MechanicalCatalogDialog(query="1759017")
    try:
        entry = dialog.selected()
        assert entry and len(entry.sources) == 2
        dialog.sources.setCurrentIndex(1)
        dialog.open_source()
        assert opened == [entry.sources[1].url]
    finally:
        dialog.close()
        dialog.deleteLater()


def test_copy_and_main_window_append_preserve_original_ai_prompt(app, monkeypatch):
    dialog = MechanicalCatalogDialog(query="1759017")
    try:
        dialog.copy_ai_spec()
        copied = dialog.copied_spec
        assert "1757019" in copied and "1759017" in copied
        assert "조건" in copied and "www.phoenixcontact.com" in copied
        assert app._mechanical_catalog_copy == copied
    finally:
        dialog.close()
        dialog.deleteLater()

    # Exercise the real menu handler without creating a render-heavy MainWindow.
    from cadstudio.native.window import MainWindow

    chosen = get_catalog_entry("phoenix_mstb_2")

    class AcceptedCatalog:
        def __init__(self, _parent):
            self.entry = chosen

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(catalog_ui, "MechanicalCatalogDialog", AcceptedCatalog)
    shown = []
    fake_window = SimpleNamespace(
        busy=False, sketching=False,
        prompt=QPlainTextEdit("Keep the original enclosure dimensions."),
        ai_dock=SimpleNamespace(show=lambda: shown.append("show"),
                                raise_=lambda: shown.append("raise")),
        message=lambda value: shown.append(value),
    )
    MainWindow.mechanical_catalog_dialog(fake_window)
    prompt = fake_window.prompt.toPlainText()
    assert prompt.startswith("Keep the original enclosure dimensions.\n\n")
    assert "1757019" in prompt and "www.phoenixcontact.com" in prompt
    assert shown[:2] == ["show", "raise"]


def test_english_static_controls_preserve_part_number_and_user_query(app):
    from cadstudio.native.i18n import install_language

    unused_settings = Path(__file__).with_name("_mechanical_catalog_language_test_never_written.json")
    language = install_language(unused_settings)
    old_language, old_path = language.language, language.path
    language.path = unused_settings
    language.set_language("en", persist=False)
    dialog = MechanicalCatalogDialog(query="1759017")
    try:
        language.flush()
        entry = dialog.selected()
        assert entry and entry.catalog_id == "phoenix_mstb_2"
        assert dialog.windowTitle() == "Mechanical / power standards · offline"
        assert dialog.table.horizontalHeaderItem(2).text() == "Part number / standard"
        assert dialog.open_button.text() == "Open official source"
        assert dialog.copy_button.text() == "Copy AI spec"
        category_index = dialog.category.findData("전원 커넥터")
        assert dialog.category.itemText(category_index) == "Power connector"
        assert dialog.category.itemData(category_index) == "전원 커넥터"
        assert dialog.table.item(0, 2).text() == entry.model
        assert dialog.sources.itemText(0).startswith(entry.sources[0].title)

        dialog.query.setText("전원 커넥터")
        before_details = dialog.details.toPlainText()
        language.flush()
        assert dialog.query.text() == "전원 커넥터"
        assert dialog.details.toPlainText() == before_details
        assert dialog.selected() is not None
    finally:
        dialog.close()
        dialog.deleteLater()
        language.set_language(old_language, persist=False)
        language.path = old_path
        app.processEvents()
