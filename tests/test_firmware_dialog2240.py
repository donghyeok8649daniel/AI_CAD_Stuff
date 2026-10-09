"""Owned native firmware review preserves explicit save / cancel boundaries."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from threading import Event
from types import SimpleNamespace
import time

import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox

from cadstudio.electrical import ElectricalWorkspace
from cadstudio.firmware_bundle import create_bundle
from cadstudio.native.firmware_dialog import FirmwareDialog
from cadstudio.program_attachment import attach_source


SOURCE = """# Generated candidate for the saved GPIO18 net.
def stop():
    return 0
"""
CONFIG = dict(model="owned-model", effort="high", deadline=None,
              catalog=[dict(model="owned-model", name="Owned model", efforts=["low", "medium", "high"]),
                       dict(model="owned-other", name="Owned other", efforts=["medium", "high"])])


def workspace():
    return ElectricalWorkspace.model_validate(dict(nodes=["GND", "PWR", "OUT", "PWM", "MOTOR"], components=[
        dict(id="source", name="5 V source", kind="battery", a="PWR", b="GND", voltage_v=5),
        dict(id="board", name="Registered Pi", kind="mcu", part_id="board_body", part_registration=True,
             catalog_id="rpi4b", pinout_catalog_id="rpi4b", analysis_enabled=False,
             a="PWR", b="GND", signal_pins={"GPIO18": "OUT"}),
        dict(id="driver", name="User driver", kind="load", part_id="driver_body", part_registration=True,
             analysis_enabled=False, a="MOTOR", b="GND", terminal_pins={"PWM": "PWM"}),
        dict(id="wire", name="User signal wire", kind="wire", a="OUT", b="PWM", analysis_enabled=False,
             wire_endpoints=[dict(component_id="board", terminal="pin:GPIO18"), dict(component_id="driver", terminal="port:PWM")]),
    ], programs=[attach_source("existing.py", "old_value = 7\n", board_component_id="board").model_dump(mode="json")]))


def candidate(work, source=SOURCE, name="Owned candidate", operation="Read encoder and stop safely", model="owned-model"):
    return create_bundle(name, "raspberry_python", work, "board", [dict(path="main.py", content=source),
        dict(path="README.md", content="Board runtime and motor calibration require verification.\n", role="documentation")],
        "main.py", missing_parameters=["Motor calibration is unknown"],
        pin_bindings=[dict(pin="GPIO18", node="OUT", function="saved driver PWM signal")],
        generation=dict(request=operation, model=model, effort="high", created_utc=datetime.now(timezone.utc), attempts=1))


def fake_generator(work, board_id, operation, model, **options):
    options["control"].check()
    options["progress"]("Reconnected · owned fake transport")
    return SimpleNamespace(bundle=candidate(work, operation=operation, model=model), message="Owned candidate ready",
                           pending_checks=("Full target build and hardware behavior remain unverified",))


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    return instance


def wait(app, predicate, seconds=8):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(); QTest.qWait(10)
    assert predicate(), "Owned firmware UI did not reach expected state"
    app.processEvents()


def dispose(app, dialog):
    dialog.reject(); dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete); app.processEvents()
    assert not shiboken6.isValid(dialog)


def generated(app, work=None, generator=fake_generator):
    dialog = FirmwareDialog(work or workspace(), language="en", selected_component_id="board",
                            codex_config=CONFIG, generation_transport=generator)
    dialog.show(); dialog.operation.setPlainText("Read encoder and stop safely")
    dialog.generate(); wait(app, lambda: dialog.task is None)
    assert dialog.bundle is not None, dialog.status.text()
    return dialog


def test_empty_workspace_opens_without_network_or_implicit_model(app):
    dialog = FirmwareDialog(ElectricalWorkspace(), language="en")
    assert dialog.board.count() == 0 and not dialog.generate_button.isEnabled()
    assert not dialog.save_button.isEnabled() and dialog.accepted_workspace is None
    assert callable(dialog.result) and dialog.task is None
    dispose(app, dialog)


def test_selected_model_and_saved_wiring_are_used_without_mutating_uploads(app):
    work = workspace(); before = work.model_dump(mode="json"); seen = []
    def generate(work, board, operation, model, **options):
        seen.append((work.model_dump(mode="json"), board, model, options["deadline"], options["effort"]))
        return fake_generator(work, board, operation, model, **options)
    dialog = FirmwareDialog(work, language="en", codex_config=CONFIG, generation_transport=generate)
    dialog.models.setCurrentIndex(dialog.models.findData("owned-other"))
    dialog.operation.setPlainText("Use the stored encoder wire")
    dialog.generate(); wait(app, lambda: dialog.task is None)
    assert seen == [(before, "board", "owned-other", None, "high")]
    assert dialog.mapping.rowCount() == 40
    row = next(i for i in range(dialog.mapping.rowCount()) if dialog.mapping.item(i, 0).text() == "GPIO18")
    assert "driver" in dialog.mapping.item(row, 3).text()
    assert work.model_dump(mode="json") == before and dialog.accepted_workspace is None
    dialog._editors[0][1].appendPlainText("# Manual revision")
    dialog.save_button.click()
    wait(app, lambda: dialog.accepted_workspace is not None)
    assert dialog.result() == QDialog.DialogCode.Accepted
    saved = dialog.accepted_workspace.model_dump(mode="json")
    assert saved["programs"] == before["programs"] and saved["components"] == before["components"]
    file = dialog.accepted_workspace.firmware_bundles[0].files[0]
    assert "Manual revision" in file.content and file.sha256 == sha256(file.content.encode()).hexdigest()
    assert dialog.accepted_workspace.firmware_bundles[0].generation.model == "owned-other"
    dispose(app, dialog)


def test_saved_bundle_picker_caches_manual_edits_and_detaches_only_on_save(app):
    work = workspace(); first = candidate(work, name="First"); second = candidate(work, name="Second")
    work = ElectricalWorkspace.model_validate({**work.model_dump(mode="json"), "firmware_bundles": [first.model_dump(mode="json"), second.model_dump(mode="json")]})
    before = work.model_dump(mode="json")
    dialog = FirmwareDialog(work, language="en", codex_config=CONFIG)
    assert dialog.saved_bundles.count() == 3 and dialog.bundle.id == second.id
    dialog._editors[0][1].appendPlainText("# kept while switching")
    dialog.saved_bundles.setCurrentIndex(dialog.saved_bundles.findData(first.id))
    dialog.saved_bundles.setCurrentIndex(dialog.saved_bundles.findData(second.id))
    assert "kept while switching" in dialog._editors[0][1].toPlainText()
    dialog.delete_bundle(); dialog.delete_bundle()
    assert dialog.bundle is None and dialog.save_button.isEnabled() and work.model_dump(mode="json") == before
    dialog.accept()
    wait(app, lambda: dialog.accepted_workspace is not None)
    assert dialog.accepted_workspace.firmware_bundles == [] and work.model_dump(mode="json") == before
    dispose(app, dialog)


def test_stale_wiring_blocks_save_build_but_allows_explicit_regeneration(app):
    work = workspace(); bundle = candidate(work)
    raw = work.model_dump(mode="json"); raw["firmware_bundles"] = [bundle.model_dump(mode="json")]
    next(item for item in raw["components"] if item["id"] == "wire")["closed"] = False
    dialog = FirmwareDialog(ElectricalWorkspace.model_validate(raw), language="en", codex_config=CONFIG, generation_transport=fake_generator)
    dialog.accept(); assert dialog.accepted_workspace is None and "wiring changed" in dialog.status.text()
    dialog.check_build(); assert dialog.task is None and dialog.build_report is None
    dialog.operation.setPlainText("Regenerate against the now open wire")
    dialog.generate(); wait(app, lambda: dialog.task is None)
    assert dialog.bundle.id == bundle.id and dialog.bundle.binding != bundle.binding, dialog.status.text()
    dialog.accept(); wait(app, lambda: dialog.accepted_workspace is not None)
    dispose(app, dialog)


def test_save_keeps_edits_in_inactive_saved_bundles_atomically(app):
    work = workspace(); first = candidate(work, name="First"); second = candidate(work, name="Second")
    raw = work.model_dump(mode="json"); raw["firmware_bundles"] = [first.model_dump(mode="json"), second.model_dump(mode="json")]
    dialog = FirmwareDialog(ElectricalWorkspace.model_validate(raw), language="en", codex_config=CONFIG)
    dialog.saved_bundles.setCurrentIndex(dialog.saved_bundles.findData(first.id))
    dialog._editors[0][1].appendPlainText("# inactive edit must survive Save")
    dialog.saved_bundles.setCurrentIndex(dialog.saved_bundles.findData(second.id))
    dialog._editors[0][1].appendPlainText("# active edit")
    dialog.accept()
    wait(app, lambda: dialog.accepted_workspace is not None)
    saved = {bundle.id: bundle for bundle in dialog.accepted_workspace.firmware_bundles}
    assert "inactive edit" in saved[first.id].files[0].content and "active edit" in saved[second.id].files[0].content
    assert len(saved) == 2
    dispose(app, dialog)


def test_cancel_and_delete_during_generation_ignores_late_results(app):
    started = Event(); stopped = Event()
    def slow(work, board, operation, model, **options):
        started.set()
        try:
            while not options["control"].cancelled.wait(.01): pass
            options["control"].check()
        finally: stopped.set()
    dialog = generated(app)
    baseline = dialog.bundle.model_dump(mode="json")
    dialog.generation_transport = slow; dialog.generate(); wait(app, started.is_set)
    assert not dialog.save_button.isEnabled() and dialog.cancel_button.isVisible()
    dialog.cancel_task(); wait(app, stopped.is_set)
    assert dialog.bundle.model_dump(mode="json") == baseline and dialog.accepted_workspace is None
    started.clear(); stopped.clear(); dialog.generate(); wait(app, started.is_set)
    dispose(app, dialog); wait(app, stopped.is_set)


def test_python_build_is_compile_only_and_export_keeps_project_private(app, tmp_path):
    marker = tmp_path / "must-not-execute.txt"
    source = "from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('executed')\n"
    def generator(work, board, operation, model, **options):
        result = fake_generator(work, board, operation, model, **options)
        result.bundle = candidate(work, source=source)
        return result
    dialog = generated(app, generator=generator)
    dialog.check_build(); wait(app, lambda: dialog.task is None)
    assert dialog.build_report.status == "pending" and not dialog.build_report.full_target_build
    assert any(check.name == "main.py" and check.status == "passed" for check in dialog.build_report.checks)
    assert not marker.exists() and dialog.accepted_workspace is None
    destination = tmp_path / "new-firmware"
    dialog.export_bundle(destination); wait(app, lambda: dialog.task is None)
    assert (destination / "main.py").read_text(encoding="utf-8") == source
    assert (destination / "firmware-bundle.json").is_file() and dialog.accepted_workspace is None
    dialog.export_bundle(destination); wait(app, lambda: dialog.task is None)
    assert "existing" in dialog.status.text().lower() and (destination / "main.py").read_text(encoding="utf-8") == source
    assert not marker.exists()
    dialog._editors[0][1].appendPlainText("# changed after source check")
    assert dialog.build_report is None and "code changed" in dialog.status.text().lower()
    dispose(app, dialog)


def test_needs_parameters_preserves_existing_editable_candidate(app):
    dialog = generated(app); identifier = dialog.bundle.id
    dialog._editors[0][1].appendPlainText("# private edit")
    dialog.generation_transport = lambda *args, **kwargs: SimpleNamespace(bundle=None,
        message="Specify encoder counts and active stop level", pending_checks=("Calibration required",))
    dialog.generate(); wait(app, lambda: dialog.task is None)
    assert dialog.bundle.id == identifier and "private edit" in dialog._editors[0][1].toPlainText()
    assert "Calibration required" in dialog.details.toPlainText() and dialog.accepted_workspace is None
    dispose(app, dialog)


def test_manual_gpio_edit_must_match_actual_saved_wiring_before_save_build_export(app, tmp_path):
    dialog = generated(app); identifier = dialog.bundle.id
    dialog._editors[0][1].setPlainText("from gpiozero import LED\nLED(17)\n")
    dialog.accept(); wait(app, lambda: dialog.task is None)
    assert dialog.accepted_workspace is None and "pin_bindings" in dialog.status.text()
    dialog.check_build(); wait(app, lambda: dialog.task is None)
    assert dialog.build_report is None and dialog.accepted_workspace is None
    folder = tmp_path / "unmapped-source"
    dialog.export_bundle(folder); wait(app, lambda: dialog.task is None)
    assert not folder.exists()
    dialog._editors[0][1].setPlainText("from gpiozero import LED\nLED(18)\n")
    dialog.accept(); wait(app, lambda: dialog.accepted_workspace is not None)
    assert dialog.accepted_workspace.firmware_bundles[0].id == identifier
    assert "LED(18)" in dialog.accepted_workspace.firmware_bundles[0].files[0].content
    dispose(app, dialog)


def test_closing_during_explicit_save_audit_does_not_commit_or_destroy_running_qthread(app, monkeypatch):
    from cadstudio import firmware_generation
    dialog = generated(app); started, stopped = Event(), Event()
    def slow_audit(bundle, work, *, check):
        started.set()
        try:
            while True: check(); time.sleep(.01)
        finally: stopped.set()
    monkeypatch.setattr(firmware_generation, "audit_bundle_sources", slow_audit)
    dialog.accept(); wait(app, started.is_set)
    assert dialog.task is not None and dialog.accepted_workspace is None
    dispose(app, dialog); wait(app, stopped.is_set)


def test_model_switch_uses_supported_effort_and_preserves_compatible_choice(app):
    config = dict(CONFIG, effort="xhigh")
    dialog = FirmwareDialog(workspace(), language="en", codex_config=config)
    assert dialog.effort.currentData() == "medium" and dialog.effort.findData("xhigh") < 0
    dialog.effort.setCurrentIndex(dialog.effort.findData("high"))
    dialog.models.setCurrentIndex(dialog.models.findData("owned-other"))
    assert dialog.effort.currentData() == "high" and dialog.codex_config["effort"] == "high"
    assert dialog.effort.findData("low") < 0
    dispose(app, dialog)


def test_attached_references_are_forwarded_exactly_with_delivery_summary(app):
    reference = dict(name="Research evidence", source="https://example.invalid/research", text="Actual measured encoder notes")
    config = dict(CONFIG, references=[reference]); seen = []
    def generator(work, board, operation, model, **options):
        seen.append(deepcopy(options["references"]))
        return fake_generator(work, board, operation, model, **options)
    dialog = FirmwareDialog(workspace(), language="en", codex_config=config, generation_transport=generator)
    assert "1 references attached" in dialog.reference_summary.text()
    dialog.operation.setPlainText("Use attached evidence without fetching URLs")
    dialog.generate(); wait(app, lambda: dialog.task is None)
    assert seen == [[reference]] and "Sent 1 attached references" in dialog.reference_summary.text()
    assert reference == config["references"][0]
    dispose(app, dialog)


def test_selected_regeneration_replaces_same_bundle_once_and_cancel_preserves_original(app):
    work = workspace(); bundle = candidate(work, name="Stored code")
    raw = work.model_dump(mode="json"); raw["firmware_bundles"] = [bundle.model_dump(mode="json")]
    registered = ElectricalWorkspace.model_validate(raw)
    dialog = generated(app, work=registered)
    assert dialog.bundle.id == bundle.id and dialog.saved_bundles.count() == 2
    assert len(dialog._available_bundles()) == 1
    assert registered.model_dump(mode="json") == raw and dialog.accepted_workspace is None
    dialog._editors[0][1].appendPlainText("# revision edit")
    dialog.generate(); wait(app, lambda: dialog.task is None)
    assert dialog.bundle.id == bundle.id and len(dialog._available_bundles()) == 1
    assert "revision edit" not in dialog._editors[0][1].toPlainText()  # Generated replacement wins over old cache.
    dispose(app, dialog)
    assert registered.model_dump(mode="json") == raw
    dialog = generated(app, work=registered)
    dialog.accept(); wait(app, lambda: dialog.accepted_workspace is not None)
    assert len(dialog.accepted_workspace.firmware_bundles) == 1 and dialog.accepted_workspace.firmware_bundles[0].id == bundle.id
    dispose(app, dialog)


def test_explicit_new_draft_preserves_stored_bundle_as_separate_candidate(app):
    work = workspace(); bundle = candidate(work, name="Stored code")
    raw = work.model_dump(mode="json"); raw["firmware_bundles"] = [bundle.model_dump(mode="json")]
    dialog = FirmwareDialog(ElectricalWorkspace.model_validate(raw), language="en", codex_config=CONFIG, generation_transport=fake_generator)
    dialog.saved_bundles.setCurrentIndex(dialog.saved_bundles.findData(""))
    assert dialog.bundle is None and "new code" in dialog.generate_button.text().lower()
    dialog.operation.setPlainText("Create an explicit separate candidate")
    dialog.generate(); wait(app, lambda: dialog.task is None)
    assert dialog.bundle.id != bundle.id and len(dialog._available_bundles()) == 2
    dialog.accept(); wait(app, lambda: dialog.accepted_workspace is not None)
    assert len(dialog.accepted_workspace.firmware_bundles) == 2
    dispose(app, dialog)


def test_small_layout_keeps_save_and_close_visible(app, tmp_path):
    dialog = generated(app)
    dialog.resize(1024, 700); app.processEvents()
    assert dialog.width() <= 1024 and dialog.height() <= 700, dialog.size()
    box = dialog.findChild(QDialogButtonBox)
    assert box is not None
    for control in box.buttons():
        area = QRect(control.mapTo(dialog, QPoint(0, 0)), control.size())
        assert dialog.rect().contains(area) and control.visibleRegion().boundingRect() == control.rect()
    assert dialog.board.toolTip() == dialog.board.currentText()
    assert dialog.saved_bundles.toolTip() == dialog.saved_bundles.currentText()
    assert dialog.grab().save(str(tmp_path / "firmware-small2240.png"))
    dispose(app, dialog)


def test_save_all_remains_enabled_for_inactive_edits_after_new_draft_selection(app):
    work = workspace(); bundle = candidate(work)
    raw = work.model_dump(mode="json"); raw["firmware_bundles"] = [bundle.model_dump(mode="json")]
    dialog = FirmwareDialog(ElectricalWorkspace.model_validate(raw), language="en", codex_config=CONFIG)
    dialog._editors[0][1].appendPlainText("# queued inactive edit")
    dialog.saved_bundles.setCurrentIndex(dialog.saved_bundles.findData(""))
    assert dialog.bundle is None and dialog.save_button.isEnabled()
    dialog.save_button.click(); wait(app, lambda: dialog.accepted_workspace is not None)
    assert "queued inactive edit" in dialog.accepted_workspace.firmware_bundles[0].files[0].content
    dispose(app, dialog)


def test_save_all_remains_enabled_for_generated_candidate_after_switching_empty_board(app):
    raw = workspace().model_dump(mode="json")
    other = deepcopy(next(item for item in raw["components"] if item["id"] == "board"))
    other.update(id="other_board", name="Second registered Pi", part_id="other_body", catalog_id="rpi3bplus",
                 pinout_catalog_id="rpi3bplus", signal_pins={})
    raw["components"].append(other)
    dialog = generated(app, work=ElectricalWorkspace.model_validate(raw))
    dialog.board.setCurrentIndex(dialog.board.findData("other_board"))
    assert dialog.bundle is None and dialog.save_button.isEnabled()
    dialog.save_button.click(); wait(app, lambda: dialog.accepted_workspace is not None)
    assert len(dialog.accepted_workspace.firmware_bundles) == 1
    assert dialog.accepted_workspace.firmware_bundles[0].binding.board_component_id == "board"
    dispose(app, dialog)
