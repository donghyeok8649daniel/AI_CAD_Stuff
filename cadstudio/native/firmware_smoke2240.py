"""Owned MainWindow firmware flow, usable unchanged inside the frozen EXE."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from uuid import uuid4
import sys
import time
import traceback

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu
from shiboken6 import isValid


SOURCE = "# Owned generated candidate.\ndef stop():\n    return 0\n"


def fixture():
    from .electrical_code_smoke2230 import fixture as old_fixture
    from ..models import Design
    from ..program_attachment import attach_source
    raw = old_fixture().model_dump(mode="json")
    raw["name"] = "Owned firmware UI smoke"
    board = next(row for row in raw["electrical"]["components"] if row["id"] == "board")
    board.update(catalog_id="rpi4b", pinout_catalog_id="rpi4b", signal_pins={"GPIO18": "OUT"})
    wire = next(row for row in raw["electrical"]["components"] if row["id"] == "wire")
    wire["wire_endpoints"][0]["terminal"] = "pin:GPIO18"
    raw["electrical"]["programs"] = [attach_source("existing.py", "value = 7\n", board_component_id="board").model_dump(mode="json")]
    return Design.model_validate(raw)


def run(app, window, output):
    from .. import firmware_generation as generation
    from ..firmware_bundle import create_bundle
    from .document import read_project
    from .electrical_workbench import ElectricalWorkbenchDialog
    from .firmware_dialog import FirmwareDialog

    output = Path(output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(success=False, checks=[], screenshots=[], live_ai_calls=0, network_calls=0, hardware_calls=0,
                  started_utc=datetime.now(timezone.utc).isoformat(), frozen=bool(getattr(sys, "frozen", False)),
                  renderer=os.getenv("CADSTUDIO_RENDERER", "unknown"))
    dialogs, errors, calls = [], [], []
    original_generate = generation.generate_firmware
    idle_ticks = [0]

    def write():
        report["check_count"] = len(report["checks"])
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def check(condition, title):
        if not condition: raise AssertionError(title)
        report["checks"].append(title); idle_ticks[0] = 0; write()

    def wait(predicate, seconds=45):
        # Count active event-loop work, not a machine's suspended clock interval.
        remaining = seconds; previous = time.monotonic()
        while not predicate():
            app.processEvents(); QTest.qWait(10)
            current = time.monotonic(); remaining -= min(current - previous, .1); previous = current
            if errors: raise AssertionError(errors[-1])
            if remaining <= 0: raise TimeoutError("Owned firmware UI did not reach expected state")
        app.processEvents()

    def flush():
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete); app.processEvents()

    def screenshot(widget, name):
        path = output.with_name(name + ".png")
        if not widget.grab().save(str(path)): raise RuntimeError("Owned firmware screenshot was not saved")
        report["screenshots"].append(str(path)); write()

    def modal(trigger, expected, callback):
        state = dict(child=None, attempts=0)
        def operate():
            child = QApplication.activeModalWidget(); state["attempts"] += 1
            if not isinstance(child, expected) or not child.isVisible():
                if state["attempts"] < 600: QTimer.singleShot(20, operate); return
                errors.append("Expected owned modal " + expected.__name__)
                if child is not None: child.reject()
                return
            state["child"] = child; dialogs.append(child)
            try: callback(child)
            except Exception: errors.append(traceback.format_exc()); child.reject()
        QTimer.singleShot(60, operate); trigger(); flush()
        if errors: raise AssertionError(errors[-1])
        if state["child"] is None: raise AssertionError("Owned firmware modal did not open")
        return state["child"]

    def fake_generate(work, board, operation, model, **options):
        options["control"].check(); options["progress"]("Reconnected · owned fake transport")
        calls.append(dict(board=board, model=model, target=options["target"], deadline=options["deadline"],
                          referenced=options.get("existing_bundle") is not None))
        bundle = create_bundle("Owned generated code", options["target"], work, board,
            [dict(path="main.py", content=SOURCE), dict(path="README.md", content="Runtime and driver calibration require confirmation.\n", role="documentation")],
            "main.py", pin_bindings=[dict(pin="GPIO18", node="OUT", function="stored driver signal")],
            missing_parameters=["Driver calibration and full runtime integration are unverified"],
            generation=dict(request=operation, model=model, effort=options["effort"], created_utc=datetime.now(timezone.utc), attempts=1))
        return SimpleNamespace(bundle=bundle, message="Owned code draft ready", pending_checks=("No full firmware emulation",))

    def watchdog_tick():
        idle_ticks[0] += 1
        if idle_ticks[0] < 90: return
        child = QApplication.activeModalWidget()
        if child is not None:
            screenshot(child, "firmware-unexpected2240"); errors.append("Owned firmware modal stalled: " + child.windowTitle()); child.reject()
    watchdog = QTimer(window); watchdog.timeout.connect(watchdog_tick); watchdog.start(1000)

    try:
        write(); app.setQuitOnLastWindowClosed(False); window.show_error = errors.append
        generation.generate_firmware = fake_generate
        window.codex_config = dict(model="owned-model", executable="")
        window.codex_catalog = [dict(model="owned-model", name="Owned model", default=True, efforts=["low", "medium", "high"])]
        window.codex_models.set_catalog(window.codex_catalog, "owned-model")
        check(window.document.design is None, "owned startup remains empty")
        wait(lambda: window.viewport.initialized)
        report["graphics"] = window.viewport.window.ReportCapabilities()
        if report["renderer"] == "software": check("llvmpipe" in report["graphics"].lower(), "actual native software renderer is llvmpipe")
        menus = [action for menu in window.menuBar().findChildren(QMenu) for action in menu.actions()]
        check(window.actions["firmware"] in menus and window.actions["firmware"] in window.electrical_tools.menu().actions(),
              "firmware entry is exposed in main menu and circuit dropdown")
        order = window.toolbar.actions()
        check(order.index(window.actions["wiring_diagram"]) == order.index(window.actions["color"]) + 1,
              "circuit button stays beside selected-part color")
        def empty(child):
            check(child.board.count() == 0 and not child.generate_button.isEnabled(), "empty circuit prompts exact board registration")
            check(child.accepted_workspace is None and callable(child.result), "opening review never commits or shadows QDialog.result")
            child.reject()
        child = modal(window.actions["firmware"].trigger, FirmwareDialog, empty)
        check(not isValid(child) and window.document.design is None, "empty firmware Cancel disposes child and preserves blank design")

        original = fixture().model_dump(mode="json")
        window.apply_design(original, "Owned fixture"); wait(lambda: not window.busy)
        check(window.document.design == original, "CAD kernel accepts bounded owned board and driver fixture")
        cursor = window.document.journal.data["cursor"]
        actors = {key: value[0] for key, value in window.viewport.actors.items()}
        window.select_parts(["board_body"])
        def generate_and_save(child):
            check(child.board.currentData() == "board" and child.codex_config["model"] == "owned-model",
                  "selected CAD body forwards exact registered board and current Codex model")
            child.operation.setPlainText("Control the saved GPIO18 driver signal with explicit stop")
            child.generate(); check(child.task is not None and not child.save_button.isEnabled(), "running generation keeps Save disabled")
            wait(lambda: child.task is None)
            check(child.bundle is not None and len(child.bundle.files) == 2, "completed fake Codex transport produces editable multifile draft")
            check(calls[-1]["board"] == "board" and calls[-1]["target"] == "raspberry_python", "generation uses actual board target instead of an invented model or pin map")
            row = next(i for i in range(child.mapping.rowCount()) if child.mapping.item(i, 0).text() == "GPIO18")
            check("driver" in child.mapping.item(row, 3).text(), "pin preview shows the driver's actual saved wire endpoint")
            check(window.document.design == original and child.accepted_workspace is None, "draft generation leaves the live CAD and uploaded source unchanged")
            child._editors[0][1].appendPlainText("# Owned manual revision")
            child.check_build(); wait(lambda: child.task is None)
            check(any(item.name == "main.py" and item.status == "passed" for item in child.build_report.checks), "explicit build checks Python syntax without executing source")
            check(child.build_report.status == "pending" and not child.build_report.full_target_build and not child.build_report.executed_generated_code,
                  "missing runtime calibration stays pending and never claims full firmware simulation")
            export = output.with_name("firmware-export2240-" + uuid4().hex[:8])
            child.export_bundle(export); wait(lambda: child.task is None)
            report["export_directory"] = str(export)
            check((export / "main.py").is_file() and "Owned manual revision" in (export / "main.py").read_text(encoding="utf-8"),
                  "export creates portable edited sources in a new folder")
            check(child.accepted_workspace is None and window.document.design == original, "export and build do not implicitly save the CAD project")
            child.tabs.setCurrentIndex(0); screenshot(child, "firmware-review2240")
            child.save_button.click()
        child = modal(window.actions["firmware"].trigger, FirmwareDialog, generate_and_save)
        wait(lambda: not window.busy)
        saved = deepcopy(window.document.design)
        check(not isValid(child) and len(saved["electrical"]["firmware_bundles"]) == 1, "explicit Save stores one bundle and destroys the owned child")
        check(saved["electrical"]["programs"] == original["electrical"]["programs"] and saved["electrical"]["components"] == original["electrical"]["components"],
              "firmware save preserves preexisting uploads and physical circuit terminals")
        check(saved["parts"] == original["parts"] and saved["part_groups"] == original["part_groups"], "firmware save preserves CAD geometry colors transforms and groups")
        check(window.document.journal.at(cursor) == original and len(window.document.journal.path()) == 2,
              "explicit firmware Save creates one reversible history transaction")
        check(all(window.viewport.actors[key][0] is actor for key, actor in actors.items()), "firmware metadata save reuses existing render actors")
        project = output.with_suffix(".cad.json"); window.document.write(project)
        check(read_project(project).design.model_dump(mode="json") == saved, "native project parser retains portable firmware sources and provenance")
        window.undo(); wait(lambda: not window.busy); check(window.document.design == original, "Undo removes only the firmware transaction")
        window.redo(); wait(lambda: not window.busy); check(window.document.design == saved, "Redo restores the exact firmware and wiring binding")
        window.document.write(project); window.open_project(project); wait(lambda: not window.busy)
        check(window.document.design == saved, "actual MainWindow reopen retains all uploaded and generated files")

        prior_revision = deepcopy(saved); identifier = saved["electrical"]["firmware_bundles"][0]["id"]
        revision_cursor = window.document.journal.data["cursor"]
        def regenerate(child):
            check(child.bundle.id == identifier and len(child._available_bundles()) == 1,
                  "saved firmware reopens as one explicit selected code bundle")
            child.operation.setPlainText("Revise the saved GPIO18 stop behavior without rewiring")
            child.generate(); wait(lambda: child.task is None)
            check(child.bundle.id == identifier and len(child._available_bundles()) == 1 and calls[-1]["referenced"],
                  "regeneration references edited code and replaces its app-owned ID without duplicating versions")
            check(window.document.design == prior_revision, "regenerated replacement remains private before Save")
            child._editors[0][1].appendPlainText("# Saved second revision")
            child.save_button.click()
        child = modal(window.actions["firmware"].trigger, FirmwareDialog, regenerate)
        wait(lambda: not window.busy); saved = deepcopy(window.document.design)
        check(not isValid(child) and len(saved["electrical"]["firmware_bundles"]) == 1 and
              saved["electrical"]["firmware_bundles"][0]["id"] == identifier,
              "explicit revision Save retains exactly one stable bundle")
        check(window.document.journal.at(revision_cursor) == prior_revision, "revision Save preserves the complete prior source in normal history")
        window.undo(); wait(lambda: not window.busy); check(window.document.design == prior_revision, "Undo restores the prior firmware revision")
        window.redo(); wait(lambda: not window.busy); check(window.document.design == saved, "Redo restores the replacement firmware revision")
        window.document.write(project)
        check(read_project(project).design.model_dump(mode="json") == saved, "native save retains regenerated source and UTC provenance after history replay")

        def outer_cancel(outer):
            check(outer.firmware_button.isEnabled(), "electrical workbench exposes the firmware review entry")
            def detach(child):
                check(child.saved_bundles.count() == 2 and len(child._available_bundles()) == 1, "saved bundle is selectable beside an explicit new-draft choice")
                child.delete_bundle(); check(child.bundle is None and child.save_button.isEnabled(), "explicit detach can save without an active candidate")
                child.save_button.click()
            nested = modal(outer.firmware_button.click, FirmwareDialog, detach)
            check(not isValid(nested) and not outer.draft.electrical.firmware_bundles, "accepted child detaches code only in the private workbench")
            check(window.document.design == saved, "accepted nested child does not bypass the outer Save boundary")
            outer.cancel_button.click()
        outer = modal(window.actions["electrical_workbench"].trigger, ElectricalWorkbenchDialog, outer_cancel)
        check(not isValid(outer) and window.document.design == saved, "outer workbench Cancel discards accepted child detach")

        started, stopped = Event(), Event()
        def slow(work, board, operation, model, **options):
            started.set()
            try:
                while not options["control"].cancelled.wait(.01): pass
                options["control"].check()
            finally: stopped.set()
        generation.generate_firmware = slow
        def active_cancel(child):
            child.operation.setPlainText("Owned cancellation probe"); child.generate(); wait(started.is_set)
            check(child.task is not None and not child.save_button.isEnabled(), "regeneration disables Save until a complete candidate exists")
            child.reject()
        child = modal(window.actions["firmware"].trigger, FirmwareDialog, active_cancel)
        wait(stopped.is_set); flush()
        check(not isValid(child) and window.document.design == saved, "closing a running generator cancels the worker and ignores late signals safely")
        screenshot(window, "firmware-main2240")
        check(not errors, "owned native firmware workflow finishes without application errors")
        report["success"] = True
    except Exception: report.update(success=False, error=traceback.format_exc())
    finally:
        watchdog.stop(); generation.generate_firmware = original_generate
        for dialog in reversed(dialogs):
            if isValid(dialog): dialog.reject(); dialog.deleteLater()
        flush(); window.document.dirty = False; window.close(); flush()
        report["finished_utc"] = datetime.now(timezone.utc).isoformat(); write()
        app.exit(0 if report["success"] else 1)
