"""Native diagnosis form: local attachments, actual DC reports, save and cancel."""
from copy import deepcopy
import gc
import json
from types import SimpleNamespace

import pytest
import shiboken6
from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from cadstudio.electrical import ElectricalWorkspace
from cadstudio.native.electrical_diagnostics_dialog import ElectricalDiagnosticsDialog


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def circuit():
    return ElectricalWorkspace(nodes=["GND", "BAT", "LOAD"], components=[
        dict(id="cell", name="12 V source", kind="battery", a="BAT", b="GND", voltage_v=12,
            internal_resistance_ohm=.1, max_current_a=5),
        dict(id="wire", name="Copper wire", kind="wire", a="BAT", b="LOAD",
            length_mm=1000, cross_section_mm2=.1, max_current_a=1),
        dict(id="load", name="Load", kind="resistor", a="LOAD", b="GND", resistance_ohm=12)])


def dispose(app, dialog):
    dialog.reject(); dialog.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete); app.processEvents(); gc.collect()
    assert not shiboken6.isValid(dialog)


def photo(path):
    image = QImage(24, 20, QImage.Format.Format_RGB32); image.fill(QColor("#ee7711"))
    assert image.save(str(path), "PNG")
    return path


def test_open_and_local_diagnosis_never_call_codex_or_modify_original(app, monkeypatch):
    from cadstudio.native import electrical_diagnostics_ai as ai
    calls = []; monkeypatch.setattr(ai, "diagnose_with_codex", lambda *args, **kwargs: calls.append(args))
    original = circuit(); before = deepcopy(original.model_dump())
    dialog = ElectricalDiagnosticsDialog(None, original, "wire", codex_config=dict(model="selected"))
    dialog.show(); app.processEvents()
    assert dialog.diagnostic_report is None and not calls
    dialog.symptoms.setPlainText("wire feels warm")
    dialog.review()
    assert dialog.diagnostic_report.dc_solved and not calls
    assert dialog.expected.rowCount() == 3
    assert original.model_dump() == before
    dispose(app, dialog)


def test_add_real_current_reading_diagnoses_overload_and_edit_invalidates_snapshot(app):
    dialog = ElectricalDiagnosticsDialog(None, circuit(), "wire")
    dialog.quantity.setCurrentIndex(dialog.quantity.findData("current"))
    dialog.power.setCurrentIndex(dialog.power.findData("powered"))
    dialog.provenance.setCurrentIndex(dialog.provenance.findData("measured"))
    dialog.value.setText("3"); dialog.add_reading(); dialog.review()
    assert len(dialog.measurements) == 1 and dialog.readings.rowCount() == 1
    fault = next(item for item in dialog.diagnostic_report.findings if item.code == "reported_current_limit_exceeded")
    assert fault.evidence[0].value == 3
    dialog.symptoms.setPlainText("new observation")
    assert dialog.diagnostic_report is None and not dialog.export_button.isEnabled()
    dispose(app, dialog)


def test_ol_and_test_conditions_are_explicit_with_no_assumed_isolation(app):
    dialog = ElectricalDiagnosticsDialog(None, circuit(), "wire")
    dialog.quantity.setCurrentIndex(dialog.quantity.findData("resistance")); dialog.value.setText("OL")
    dialog.add_reading(); dialog.review()
    assert "continuity_test_conditions_unknown" in {item.code for item in dialog.diagnostic_report.findings}
    dialog.measurements.clear()
    dialog.power.setCurrentIndex(dialog.power.findData("unpowered")); dialog.isolated.setChecked(True)
    dialog.add_reading(); dialog.review()
    assert "reported_open_path" in {item.code for item in dialog.diagnostic_report.findings}
    assert dialog.workspace.components[1].closed
    dispose(app, dialog)


def test_blank_nan_and_invalid_continuity_do_not_create_measurements(app, monkeypatch):
    dialog = ElectricalDiagnosticsDialog(None, circuit(), "wire")
    errors = []; monkeypatch.setattr(dialog, "show_error", errors.append)
    dialog.add_reading(); dialog.value.setText("nan"); dialog.add_reading()
    dialog.quantity.setCurrentIndex(dialog.quantity.findData("continuity")); dialog.value.setText(".5"); dialog.add_reading()
    assert len(errors) == 3 and not dialog.measurements
    dispose(app, dialog)


def test_photo_attachment_validates_decoding_and_stays_local(app, tmp_path, monkeypatch):
    from cadstudio.native import electrical_diagnostics_ai as ai
    calls = []; monkeypatch.setattr(ai, "diagnose_with_codex", lambda *args, **kwargs: calls.append(args))
    dialog = ElectricalDiagnosticsDialog(None, circuit(), codex_config=dict(model="selected"))
    path = photo(tmp_path / "field.png"); attached = dialog.add_photo(path)
    assert attached.path == str(path.resolve()) and dialog.photo_list.count() == 1 and not calls
    dialog.review()
    assert any("첨부 사진은 로컬" in item or "Attached photos" in item for item in dialog.diagnostic_report.unknowns)
    corrupt = tmp_path / "bad.png"; corrupt.write_bytes(b"\x89PNG\r\n\x1a\nnot-an-image")
    with pytest.raises(ValueError, match="decodable"): dialog.add_photo(corrupt)
    with pytest.raises(ValueError, match="already attached"): dialog.add_photo(path)
    assert len(dialog.photos) == 1 and not calls
    dialog.photo_list.setCurrentRow(0); dialog.remove_photo()
    assert not dialog.photos and not dialog.diagnostic_report
    dispose(app, dialog)


def test_save_separate_report_preserves_project_and_contains_provenance(app, tmp_path):
    project = tmp_path / "original.json"; project.write_text('{"design":"original"}', encoding="utf-8")
    original = circuit(); before = original.model_dump()
    dialog = ElectricalDiagnosticsDialog(None, original, project_path=project)
    dialog.review()
    output = dialog.export_report_to(tmp_path / "review.diagnostics.json")
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["scope"] and payload["available_component_ids"] == ["cell", "wire", "load"]
    text = dialog.export_report_to(tmp_path / "review.txt").read_text(encoding="utf-8")
    assert "DC" in text and "Unknowns" in text
    with pytest.raises(ValueError, match="separate"): dialog.export_report_to(project)
    with pytest.raises(ValueError, match="separate"): dialog.export_report_to(tmp_path / "review.pcad")
    assert project.read_text(encoding="utf-8") == '{"design":"original"}' and original.model_dump() == before
    dispose(app, dialog)


def test_missing_codex_connection_is_actionable_and_has_no_worker(app):
    dialog = ElectricalDiagnosticsDialog(None, circuit())
    dialog.start_codex()
    assert not dialog._running and dialog._worker is None
    assert "Codex" in dialog.status.text()
    dispose(app, dialog)


def test_stale_and_closed_worker_results_cannot_replace_report(app):
    from cadstudio.electrical_diagnostics import diagnose_electrical
    dialog = ElectricalDiagnosticsDialog(None, circuit())
    report = diagnose_electrical(circuit())
    dialog._generation = 4; dialog._completed(3, report)
    assert dialog.diagnostic_report is None
    dialog.reject(); dialog._completed(4, report)
    assert dialog.diagnostic_report is None
    dispose(app, dialog)


def test_native_english_and_repeated_disposal(app, monkeypatch):
    monkeypatch.setattr(app, "cad_language", SimpleNamespace(language="en"), raising=False)
    for _ in range(4):
        dialog = ElectricalDiagnosticsDialog(None, circuit(), "wire")
        dialog.review()
        assert "Electrical diagnosis" in dialog.windowTitle()
        assert "not inspected" in dialog.report_text.toPlainText()
        dispose(app, dialog)
