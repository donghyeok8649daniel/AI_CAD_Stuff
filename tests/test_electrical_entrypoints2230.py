"""Real modal entry points preserve private edits and explicitly saved history.

Run in an isolated CADSTUDIO_DATA_DIR. The software-renderer smoke runner loads
Mesa before Qt/VTK imports; tests do not alter a user's graphics preferences.
"""

import gc
import os
import time

import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMenu

from cadstudio.models import Design
from cadstudio.native.electrical_safety_dialog import ElectricalSafetyDialog
from cadstudio.native.electrical_workbench import ElectricalWorkbenchDialog
from cadstudio.native.program_simulation_dialog import ProgramSimulationDialog
from cadstudio.program_attachment import attach_source


SOURCE = """void setup(){pinMode(9, OUTPUT);}
void loop(){analogWrite(9,128); delay(100); digitalWrite(9,LOW); delay(100);}
"""


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    yield instance
    assert QThreadPool.globalInstance().waitForDone(10000)
    flush_deletions(instance)


def flush_deletions(app):
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def wait(app, predicate, seconds=15):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(); QTest.qWait(10)
    assert predicate(), "Native entry point did not reach its expected state"


def click(button):
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    QApplication.processEvents()


def modal(trigger, expected, action, app):
    """Operate the real nested event loop, keeping exceptions in pytest."""
    children, errors = [], []
    def handle():
        child = QApplication.activeModalWidget()
        try:
            assert isinstance(child, expected), f"Expected {expected.__name__}; got {type(child).__name__}"
            children.append(child)
            action(child)
        except BaseException as exc:
            errors.append(exc)
            if child: child.reject()
    QTimer.singleShot(80, handle)
    trigger()
    assert not errors, errors
    assert children
    flush_deletions(app)
    return children[0]


def design():
    return Design.model_validate(dict(name="User circuit", parameters={"wall": "2 mm"}, parts=[
        dict(id="board_body", name="Arduino carrier", role="electrical", color="#334455",
             geometry=dict(kind="plate", length=50, width=30, thickness=2, hole_count=0)),
        dict(id="driver_body", name="User driver", role="electrical", color="#556677", transform=dict(x=70),
             geometry=dict(kind="plate", length=20, width=20, thickness=2, hole_count=0)),
    ], part_groups=[dict(id="keep", name="Existing group", part_ids=["board_body", "driver_body"])],
        electrical=dict(nodes=["GND", "PWR", "OUT", "PWM", "MOTOR"], components=[
            dict(id="source", name="5 V source", kind="battery", a="PWR", b="GND", voltage_v=5),
            dict(id="board", name="Controller", kind="mcu", part_id="board_body", part_registration=True,
                 catalog_id="arduino_uno_r3", pinout_catalog_id="arduino_uno_r3", analysis_enabled=False,
                 a="PWR", b="GND", signal_pins={"D9": "OUT"}),
            dict(id="driver", name="Driver", kind="load", part_id="driver_body", part_registration=True,
                 analysis_enabled=False, a="MOTOR", b="GND", terminal_pins={"PWM": "PWM"}),
            dict(id="wire", name="User signal wire", kind="wire", a="OUT", b="PWM", analysis_enabled=False,
                 wire_endpoints=[dict(component_id="board", terminal="pin:D9"),
                                 dict(component_id="driver", terminal="port:PWM")]),
        ])))


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    from cadstudio.native import window as module
    from cadstudio.native.model_picker import LocalModelPicker
    monkeypatch.setattr(module, "DATA_DIR", tmp_path / "isolated-ui-profile")
    monkeypatch.setattr(LocalModelPicker, "refresh", lambda _: None)  # No provider requests.
    instance = module.MainWindow(restore=False)
    instance._entry_errors = []
    instance.show_error = instance._entry_errors.append
    instance.show(); app.processEvents()
    wait(app, lambda: instance.viewport.initialized)
    yield instance
    wait(app, lambda: not instance.busy)
    instance.document.dirty = False
    instance.close(); instance.deleteLater(); flush_deletions(app)
    assert not shiboken6.isValid(instance)
    gc.collect()


def test_main_toolbar_menu_and_empty_design_open_actual_dialog_signatures(window, app):
    assert window.document.design is None
    menu_actions = [action for menu in window.menuBar().findChildren(QMenu) for action in menu.actions()]
    tool_actions = window.electrical_tools.menu().actions()
    toolbar_actions = window.toolbar.actions()
    color_index = toolbar_actions.index(window.actions["color"])
    assert toolbar_actions[color_index + 1] is window.actions["wiring_diagram"]
    for key in ("program_simulation", "electrical_safety"):
        assert window.actions[key] in menu_actions and window.actions[key] in tool_actions
        assert window.actions[key].isEnabled()
    if os.getenv("CADSTUDIO_RENDERER") == "software":
        assert "llvmpipe" in window.viewport.window.ReportCapabilities().lower()
    program = modal(window.actions["program_simulation"].trigger, ProgramSimulationDialog,
        lambda child: child.reject(), app)
    assert not shiboken6.isValid(program)
    safety = modal(window.actions["electrical_safety"].trigger, ElectricalSafetyDialog,
        lambda child: child.reject(), app)
    assert not shiboken6.isValid(safety)
    assert window.document.design is None and not window._entry_errors


def test_main_program_upload_uses_selected_cad_board_and_one_explicit_history_commit(window, app):
    original = design(); before = original.model_dump(mode="json")
    window.document.commit(before, "Original")
    window.document.dirty = False; window.selected = "board_body"
    cursor = window.document.journal.data["cursor"]
    def upload(child):
        assert child.parent() is window and child.selected_component_id == "board"
        assert child.workspace == original.electrical and not child.attachments
        child.add_program(attach_source("drive.ino", SOURCE))
        wait(app, lambda: not child._running)
        assert child.result.status == "ready" and child.result.board_component_id == "board"
        assert child.result.events[0].targets == ["driver/port:PWM"]
        assert window.document.design == before  # Upload/trace is still private.
        click(child.apply_button)
    child = modal(window.actions["program_simulation"].trigger, ProgramSimulationDialog, upload, app)
    wait(app, lambda: not window.busy)
    assert not window._entry_errors and not shiboken6.isValid(child)
    updated = window.document.design
    assert len(updated["electrical"]["programs"]) == 1
    assert updated["electrical"]["programs"][0]["board_component_id"] == "board"
    assert updated["electrical"]["components"] == before["electrical"]["components"]
    assert updated["parts"] == before["parts"] and updated["part_groups"] == before["part_groups"]
    assert window.document.journal.at(cursor) == before
    assert len(window.document.journal.path()) == 2
    assert window.document.journal.path()[-1]["context"]["tool"] == "electrical-program"


@pytest.mark.parametrize("child_kind", ["program", "safety"])
def test_child_apply_then_main_workbench_cancel_preserves_live_document(window, app, child_kind):
    original = design(); before = original.model_dump(mode="json")
    window.document.commit(before, "Original"); window.document.dirty = False
    window.selected = "board_body"; cursor = window.document.journal.data["cursor"]
    saved_children = []
    def edit_outer(outer):
        assert outer.parent() is window and outer.selected_row().component_id == "board"
        if child_kind == "program":
            def edit_child(child):
                assert child.parent() is outer and child.selected_component_id == "board"
                child.add_program(attach_source("private.ino", SOURCE))
                wait(app, lambda: not child._running)
                assert child.result.status == "ready"
                click(child.apply_button)
            saved_children.append(modal(outer.program_button.click, ProgramSimulationDialog, edit_child, app))
            assert len(outer.draft.electrical.programs) == 1
        else:
            def edit_child(child):
                assert child.parent() is outer and child.current_id == "board"
                child.inputs["max_voltage_v"].setText("5.5")
                click(child.save_button)
            saved_children.append(modal(outer.safety_button.click, ElectricalSafetyDialog, edit_child, app))
            assert next(c for c in outer.draft.electrical.components if c.id == "board").safety.max_voltage_v == 5.5
        assert outer.apply_button.isEnabled() and outer.checked is None
        assert window.document.design == before
        click(outer.cancel_button)
    outer = modal(window.actions["electrical_workbench"].trigger, ElectricalWorkbenchDialog, edit_outer, app)
    assert not shiboken6.isValid(outer) and all(not shiboken6.isValid(child) for child in saved_children)
    assert window.document.design == before and window.document.journal.data["cursor"] == cursor
    assert len(window.document.journal.path()) == 1 and not window._entry_errors
    assert original.model_dump(mode="json") == before


def test_main_safety_save_only_updates_declared_rating_in_one_history_entry(window, app):
    original = design(); before = original.model_dump(mode="json")
    window.document.commit(before, "Original"); window.document.dirty = False
    window.selected = "driver_body"; cursor = window.document.journal.data["cursor"]
    def declare(child):
        assert child.parent() is window and child.current_id == "driver"
        assert child.inputs["thermal_resistance_k_per_w"].text() == ""
        child.inputs["max_voltage_v"].setText("24")
        click(child.save_button)
    child = modal(window.actions["electrical_safety"].trigger, ElectricalSafetyDialog, declare, app)
    wait(app, lambda: not window.busy)
    assert not shiboken6.isValid(child) and not window._entry_errors
    updated = Design.model_validate(window.document.design)
    changed = next(c for c in updated.electrical.components if c.id == "driver")
    assert changed.safety.max_voltage_v == 24 and changed.safety.thermal_resistance_k_per_w is None
    assert updated.parts == original.parts and updated.part_groups == original.part_groups
    assert [(c.a, c.b) for c in updated.electrical.components] == [(c.a, c.b) for c in original.electrical.components]
    assert updated.electrical.components[1] == original.electrical.components[1]
    assert window.document.journal.at(cursor) == before
    assert len(window.document.journal.path()) == 2
    assert window.document.journal.path()[-1]["context"]["tool"] == "electrical-safety"


def test_reject_running_program_and_delete_owner_cancels_worker_without_committing(app, monkeypatch):
    from cadstudio.native import program_simulation_dialog as module
    original = design(); before = original.model_dump(mode="json")
    outer = ElectricalWorkbenchDialog(None, original, "board_body")
    outer.show(); app.processEvents()
    actual = module.simulate_program
    def cancelled_projection(workspace, attachment, **kwargs):
        kwargs["cancel_event"].wait(.3)
        return actual(workspace, attachment, **kwargs)
    monkeypatch.setattr(module, "simulate_program", cancelled_projection)
    def cancel_child(child):
        child.add_program(attach_source("cancel.ino", SOURCE))
        assert child._running and not child.apply_button.isEnabled()
        child.reject()
    child = modal(outer.program_button.click, ProgramSimulationDialog, cancel_child, app)
    outer.reject(); outer.deleteLater(); flush_deletions(app)
    assert not shiboken6.isValid(outer) and not shiboken6.isValid(child)
    assert QThreadPool.globalInstance().waitForDone(5000)
    app.processEvents(); gc.collect()
    assert original.model_dump(mode="json") == before and "programs" not in before["electrical"]
