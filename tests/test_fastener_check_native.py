"""The native bolt check asks for actual loads and retains narrow scope."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from cadstudio.native import fastener_check_dialog as check_ui
from cadstudio.native.fastener_check_dialog import FastenerCheckDialog


@pytest.fixture
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    yield instance
    instance.processEvents()


def test_no_default_force_and_explicit_equal_share_and_m8_variant(app):
    dialog = FastenerCheckDialog()
    try:
        assert dialog.force.text() == ""
        assert dialog.bolt_count.text() == ""
        assert dialog.safety_factor.text() == ""
        assert not dialog.equal_sharing.isChecked()
        assert not dialog.head_geometry.isChecked()
        assert dialog.m8_variant.isHidden()
        dialog.calculate()
        assert dialog.check_result is None
        assert not dialog.copy_button.isEnabled()

        dialog.force.setText("1000")
        dialog.bolt_count.setText("2")
        dialog.safety_factor.setText("2")
        dialog.calculate()
        assert dialog.check_result is None
        assert "균등" in dialog.status.text()
        dialog.equal_sharing.setChecked(True)
        dialog.calculate()
        assert dialog.check_result is None
        assert "머리" in dialog.status.text()
        dialog.head_geometry.setChecked(True)
        dialog.calculate()
        assert dialog.check_result and dialog.check_result.within_proof_reference
        assert "조립체 안전 인증 아님" in dialog.output.toPlainText()
        assert dialog.copy_button.isEnabled()

        dialog.thread.setCurrentIndex(dialog.thread.findData("M8"))
        assert not dialog.m8_variant.isHidden()
        assert dialog.check_result is None and not dialog.copy_button.isEnabled()
        dialog.calculate()
        assert dialog.check_result is None
        assert "6az" in dialog.status.text()
        dialog.m8_variant.setChecked(True)
        dialog.calculate()
        assert dialog.check_result and dialog.check_result.spec.thread == "M8"
        assert dialog.check_result.spec.published_proof_load_n == 21200
    finally:
        dialog.close()
        dialog.deleteLater()


def test_source_opens_primary_pdf_and_copy_contains_conditions(app, monkeypatch):
    opened = []
    monkeypatch.setattr(check_ui.QDesktopServices, "openUrl",
                        lambda url: opened.append(url.toString()) or True)
    dialog = FastenerCheckDialog()
    try:
        dialog.open_source()
        dialog.open_pitch_source()
        assert opened == [check_ui.SOURCE_PDF, check_ui.PITCH_SOURCE_PDF]
        dialog.force.setText("1000")
        dialog.bolt_count.setText("1")
        dialog.safety_factor.setText("2")
        dialog.equal_sharing.setChecked(True)
        dialog.head_geometry.setChecked(True)
        dialog.calculate()
        dialog.copy_report()
        assert dialog.copied_report == app._fastener_check_copy
        assert "1000 N" in dialog.copied_report
        assert "프리로드" in dialog.copied_report
        assert "M8" in dialog.copied_report  # documented exclusion appears in report
        assert check_ui.SOURCE_PDF in dialog.copied_report
    finally:
        dialog.close()
        dialog.deleteLater()


def test_english_controls_keep_numeric_inputs_and_report_unchanged(app):
    from cadstudio.native.i18n import install_language

    unused_settings = Path(__file__).with_name("_fastener_language_test_never_written.json")
    language = install_language(unused_settings)
    old_language, old_path = language.language, language.path
    language.path = unused_settings
    language.set_language("en", persist=False)
    dialog = FastenerCheckDialog()
    try:
        dialog.force.setText("1200")
        dialog.bolt_count.setText("3")
        dialog.safety_factor.setText("2")
        dialog.equal_sharing.setChecked(True)
        dialog.head_geometry.setChecked(True)
        dialog.calculate()
        report = dialog.output.toPlainText()
        assert "Preliminary static axial bolt tension check" in report
        assert "not a joint safety certification" in report
        assert "Within the proof reference" in dialog.status.text()
        language.flush()
        assert dialog.windowTitle() == "Bolt axial tension preliminary check"
        assert dialog.calculate_button.text() == "Calculate axial check"
        assert dialog.source_button.text() == "Open Bossard source"
        assert dialog.pitch_source_button.text() == "Open coarse-pitch source"
        assert dialog.force.placeholderText() == "Actual total axial tensile force · N"
        assert dialog.equal_sharing.text() == "I assume identical bolts share the axial force equally"
        assert dialog.force.text() == "1200"
        assert dialog.thread.currentData() == "M4"
        assert dialog.output.toPlainText() == report
        dialog.copy_report()
        assert dialog.copied_report == report
        assert "Copied the result" in dialog.status.text()
    finally:
        dialog.close()
        dialog.deleteLater()
        language.set_language(old_language, persist=False)
        language.path = old_path
        app.processEvents()
