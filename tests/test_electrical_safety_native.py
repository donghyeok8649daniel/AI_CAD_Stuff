"""Ratings are opt-in private edits; fault review cannot switch off hardware."""
from copy import deepcopy
from types import SimpleNamespace
import gc

import pytest
import shiboken6
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QDialog

from cadstudio.electrical import ElectricalWorkspace
from cadstudio.native.electrical_safety_dialog import ElectricalSafetyDialog


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    return instance


def circuit():
    return ElectricalWorkspace(nodes=["GND", "BAT"], components=[
        dict(id="source", name="Cell", kind="battery", a="BAT", b="GND", voltage_v=12, max_current_a=1),
        dict(id="load", name="Resistor", kind="resistor", a="BAT", b="GND", resistance_ohm=120)])


def dispose(app, dialog):
    dialog.deleteLater(); app.sendPostedEvents(None, QEvent.Type.DeferredDelete); app.processEvents(); gc.collect()
    assert not shiboken6.isValid(dialog)


def test_review_and_cancel_preserve_original_circuit_and_unknown_temperature(app):
    original = circuit(); before = deepcopy(original.model_dump())
    dialog = ElectricalSafetyDialog(None, original, "load")
    dialog.show(); app.processEvents()
    assert dialog.current_id == "load" and dialog.inputs["ambient_temperature_c"].text() == ""
    assert dialog.safety_report.branches[1].estimated_temperature_c is None
    dialog.inputs["rated_power_w"].setText("0.25")
    dialog.review(); app.processEvents()
    assert dialog.safety_report.status == "fault"
    assert "dissipation_rating_exceeded" in {issue.code for issue in dialog.safety_report.issues}
    assert original.model_dump() == before and dialog.workspace is None
    dialog.reject()
    assert dialog.workspace is None and original.model_dump() == before
    dispose(app, dialog)


def test_save_records_only_declared_ratings_without_rewiring_or_setting_assumptions(app):
    original = circuit(); before = deepcopy(original.model_dump())
    dialog = ElectricalSafetyDialog(None, original, "load")
    dialog.inputs["rated_power_w"].setText("2")
    dialog.inputs["thermal_resistance_k_per_w"].setText("10")
    dialog.inputs["ambient_temperature_c"].setText("25")
    dialog.inputs["duty_cycle"].setText("1")
    dialog.inputs["max_temperature_c"].setText("50")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    saved = dialog.workspace
    assert saved.components[1].safety.rated_power_w == 2
    assert saved.components[1].safety.heat_loss_fraction is None
    assert saved.components[0].model_dump() == original.components[0].model_dump()
    assert [(item.a, item.b) for item in saved.components] == [("BAT", "GND"), ("BAT", "GND")]
    assert original.model_dump() == before
    dispose(app, dialog)


def test_switching_component_preserves_private_edits_and_blocks_invalid_values(app, monkeypatch):
    original = circuit(); before = deepcopy(original.model_dump())
    dialog = ElectricalSafetyDialog(None, original, "load")
    dialog.inputs["rated_power_w"].setText("2")
    dialog.choice.setCurrentIndex(dialog.choice.findData("source"))
    assert dialog.draft.components[1].safety.rated_power_w == 2
    assert dialog.current_id == "source"
    messages = []; monkeypatch.setattr(dialog, "show_error", messages.append)
    dialog.max_current.setText("-1")
    dialog.choice.setCurrentIndex(dialog.choice.findData("load"))
    assert messages and dialog.current_id == "source" and dialog.choice.currentData() == "source"
    dialog.accept()
    assert dialog.workspace is None and original.model_dump() == before
    dialog.reject(); dispose(app, dialog)


def test_repeated_dialog_disposal_retains_no_removed_widget_wrappers(app):
    original = circuit(); before = original.model_dump()
    for _ in range(6):
        dialog = ElectricalSafetyDialog(None, original, "source")
        dialog.show(); app.processEvents(); dialog.review(); dialog.reject(); dispose(app, dialog)
    assert original.model_dump() == before


def test_native_review_text_changes_language_without_assuming_thermal_defaults(app, monkeypatch):
    monkeypatch.setattr(app, "cad_language", SimpleNamespace(language="en"), raising=False)
    dialog = ElectricalSafetyDialog(None, circuit(), "load")
    assert "thermal review" in dialog.windowTitle()
    assert "not guessed" in dialog.report.toPlainText()
    assert dialog.inputs["duty_cycle"].text() == ""
    dialog.reject(); dispose(app, dialog)


def test_generic_component_editor_retains_safety_on_name_edits_and_drops_wrong_kind(app):
    from cadstudio.native.electrical_dialog import ComponentDialog
    from cadstudio.electrical import ElectricalComponent
    item = circuit().components[1].model_dump()
    item["safety"] = dict(rated_power_w=2, max_temperature_c=80)
    original = ElectricalComponent.model_validate(item).model_dump()
    dialog = ComponentDialog(None, [], original)
    dialog.name.setText("Renamed resistor")
    assert dialog.candidate()["safety"] == original["safety"]
    assert ElectricalComponent.model_validate(dialog.candidate()).safety.rated_power_w == 2
    dialog.kind.setCurrentIndex(dialog.kind.findData("wire"))
    assert "safety" not in dialog.candidate()
    dialog.reject(); dispose(app, dialog)


def test_catalog_component_editor_receives_fuse_limits_without_old_device_limits(app, monkeypatch):
    from cadstudio.native import electrical_dialog as module
    from cadstudio import electrical_catalog as catalog
    from cadstudio.electrical import ElectricalComponent
    item = circuit().components[1].model_dump(); item["safety"] = dict(rated_power_w=2)
    dialog = module.ComponentDialog(None, [], item)
    class Selected:
        entry = object()
        def __init__(self, *_): pass
        def exec(self): return QDialog.DialogCode.Accepted
    monkeypatch.setattr(module, "CatalogDialog", Selected)
    monkeypatch.setattr(catalog, "component_prefill", lambda _: dict(name="Declared fuse", kind="switch",
        catalog_id="test-fuse", source_url="https://example.com/fuse",
        contact_resistance_ohm=.02, safety=dict(fuse_current_a=2, max_voltage_v=32)))
    dialog.select_catalog()
    result = ElectricalComponent.model_validate(dialog.candidate())
    assert result.safety.fuse_current_a == 2 and result.safety.max_voltage_v == 32
    assert result.safety.rated_power_w is None
    dialog.reject(); dispose(app, dialog)


def test_legacy_electrical_editor_preserves_programs_and_rejects_orphan_delete(app, monkeypatch):
    from cadstudio.native import electrical_dialog as module
    from cadstudio.program_attachment import attach_source
    board = dict(id="board", name="Board", kind="mcu", a="BAT", b="GND", analysis_enabled=False)
    attachment = attach_source("test.ino", "void setup() { pinMode(13, OUTPUT); }", board_component_id="board")
    raw = circuit().model_dump(); raw["components"].append(board); raw["programs"] = [attachment.model_dump()]
    workspace = ElectricalWorkspace.model_validate(raw)
    original = workspace.model_dump(); dialog = module.ElectricalDialog(None, dict(parts=[], electrical=original))
    assert dialog.candidate().programs == workspace.programs
    dialog.adopt_workspace(workspace)
    assert dialog.candidate().programs == workspace.programs
    messages = []; monkeypatch.setattr(module.QMessageBox, "warning", lambda *args: messages.append(args))
    dialog.table.selectRow(2); dialog.remove()
    assert messages and len(dialog.components) == 3
    assert dialog.candidate().programs == workspace.programs and workspace.model_dump() == original
    dialog.reject(); dispose(app, dialog)


def test_legacy_electrical_editor_retains_explicit_empty_programs_but_omits_absent(app):
    from cadstudio.native.electrical_dialog import ElectricalDialog
    raw = circuit().model_dump()
    dialog = ElectricalDialog(None, dict(parts=[], electrical=raw))
    assert "programs" not in dialog.candidate().model_dump()
    dialog.reject(); dispose(app, dialog)
    raw["programs"] = []
    dialog = ElectricalDialog(None, dict(parts=[], electrical=raw))
    assert dialog.candidate().model_dump()["programs"] == []
    dialog.reject(); dispose(app, dialog)
