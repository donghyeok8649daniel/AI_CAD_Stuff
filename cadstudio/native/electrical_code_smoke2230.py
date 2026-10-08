"""Owned frozen workbench flow: code, wiring, explicit saves and cancellation."""
from copy import deepcopy
import gc
import json
import os
from pathlib import Path
import sys
import time
import traceback

from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu
from shiboken6 import isValid


SOURCE = """void setup(){pinMode(9, OUTPUT);}
void loop(){analogWrite(9,128); delay(100); digitalWrite(9,LOW); delay(100);}
"""


def fixture():
    from ..models import Design
    return Design.model_validate(dict(name="Owned code and wiring smoke", parameters={"wall": "2 mm"}, parts=[
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


def run(app, window, output):
    from ..models import Design
    from ..program_attachment import attach_source, read_program
    from .document import read_project
    from .electrical_workbench import ElectricalWorkbenchDialog
    from .electrical_safety_dialog import ElectricalSafetyDialog
    from .program_simulation_dialog import ProgramSimulationDialog

    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(checks=[], screenshots=[], live_ai_calls=0, network_calls=0, hardware_calls=0,
                  frozen=bool(getattr(sys, "frozen", False)), renderer=os.getenv("CADSTUDIO_RENDERER", "unknown"))
    dialogs, errors = [], []
    last_check = [time.monotonic()]

    def write():
        report["check_count"] = len(report["checks"])
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def check(condition, title):
        if not condition: raise AssertionError(title)
        report["checks"].append(title); last_check[0] = time.monotonic(); write()

    def wait(predicate, seconds=45):
        deadline = time.monotonic() + seconds
        while not predicate():
            app.processEvents(); QTest.qWait(10)
            if errors: raise AssertionError(errors[-1])
            if time.monotonic() > deadline: raise TimeoutError("Owned code/wiring flow timed out")
        app.processEvents()

    def flush():
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete); app.processEvents()

    def screenshot(widget, label):
        app.processEvents()
        path = output.with_name(label + ".png")
        if not widget.grab().save(str(path)): raise RuntimeError("Native screenshot was not saved")
        report["screenshots"].append(str(path))

    def modal(trigger, expected, action):
        state = dict(done=False, child=None)
        deadline = time.monotonic() + 12
        def handle():
            child = QApplication.activeModalWidget()
            if not isinstance(child, expected) or not child.isVisible():
                if time.monotonic() < deadline: QTimer.singleShot(20, handle); return
                errors.append("Expected owned modal: " + expected.__name__); state["done"] = True
                if child is not None: child.reject()
                return
            state["child"] = child; dialogs.append(child)
            try: action(child)
            except Exception:
                errors.append(traceback.format_exc()); child.reject()
            finally: state["done"] = True
        QTimer.singleShot(60, handle); trigger(); wait(lambda: state["done"]); flush()
        if errors: raise AssertionError(errors[-1])
        return state["child"]

    def watchdog_tick():
        if time.monotonic() - last_check[0] < 40: return
        child = QApplication.activeModalWidget()
        if child is not None:
            screenshot(child, "electrical-code-unexpected2230")
            errors.append("Owned modal stalled: " + child.windowTitle()); child.reject()
    watchdog = QTimer(window); watchdog.timeout.connect(watchdog_tick); watchdog.start(1000)

    try:
        report["success"] = False; write()
        app.setQuitOnLastWindowClosed(False); window.show_error = errors.append
        check(window.document.design is None, "owned startup is empty")
        wait(lambda: window.viewport.initialized)
        capabilities = window.viewport.window.ReportCapabilities()
        report["graphics"] = capabilities
        if report["renderer"] == "software":
            check("llvmpipe" in capabilities.lower(), "actual software renderer is llvmpipe")
        menu_actions = [a for menu in window.menuBar().findChildren(QMenu) for a in menu.actions()]
        for key in ("program_simulation", "electrical_safety"):
            check(window.actions[key] in menu_actions and window.actions[key] in window.electrical_tools.menu().actions(),
                  key + " is exposed in main menu and electrical toolbar menu")
        order = window.toolbar.actions()
        check(order.index(window.actions["wiring_diagram"]) == order.index(window.actions["color"]) + 1,
              "direct circuit button remains immediately after part color")
        original = fixture().model_dump(mode="json")
        window.apply_design(original, "Owned fixture"); wait(lambda: not window.busy)
        check(window.document.design == original, "real CAD kernel accepts the bounded synthetic fixture")
        cursor = window.document.journal.data["cursor"]
        actors = {key: value[0] for key, value in window.viewport.actors.items()}
        window.select_parts(["board_body"])
        source_path = output.with_name("owned-drive2230.ino"); source_path.write_text(SOURCE, encoding="utf-8")

        def upload(child):
            check(child.parent() is window and child.selected_component_id == "board", "selected CAD board forwards its actual circuit ID")
            check(child.workspace.model_dump(mode="json") == original["electrical"], "program dialog owns an exact copy of the current wiring")
            child.add_program(read_program(source_path)); wait(lambda: not child._running)
            check(child.result.status == "ready" and child.result.board_component_id == "board", "uploaded source resolves the exact Arduino automatically")
            check(child.result.events[0].targets == ["driver/port:PWM"], "saved physical wire routes D9 commands to the driver's actual PWM terminal")
            check(not child.result.complete_program, "GPIO trace does not claim full hardware or firmware execution")
            check(window.document.design == original, "upload and automatic trace are private before Apply")
            screenshot(child, "electrical-code-trace2230"); child.apply_button.click()
        child = modal(window.actions["program_simulation"].trigger, ProgramSimulationDialog, upload)
        wait(lambda: not window.busy)
        check(not isValid(child), "main program dialog is destroyed after Apply")
        programs = deepcopy(window.document.design)
        check(len(programs["electrical"]["programs"]) == 1 and programs["electrical"]["programs"][0]["board_component_id"] == "board",
              "explicit program Apply stores one portable source bound to its exact board")
        check(programs["electrical"]["components"] == original["electrical"]["components"], "program Apply does not rewire the circuit")
        check(programs["parts"] == original["parts"] and programs["part_groups"] == original["part_groups"], "program Apply preserves geometry colors transforms and groups")
        check(len(window.document.journal.path()) == 2 and window.document.journal.at(cursor) == original,
              "program Apply makes one history entry and preserves the prior snapshot")
        check(all(window.viewport.actors[key][0] is actor for key, actor in actors.items()), "code metadata save reuses existing CAD render actors")
        saved = output.with_suffix(".cad.json"); window.document.write(saved)
        check(read_project(saved).design.model_dump(mode="json") == programs, "native save and project parser retain code and wiring")
        window.undo(); wait(lambda: not window.busy)
        check(window.document.design == original, "Undo removes only the complete program transaction")
        window.redo(); wait(lambda: not window.busy)
        check(window.document.design == programs, "Redo restores the saved source and exact board binding")
        window.document.write(saved); window.open_project(saved); wait(lambda: not window.busy)
        check(window.document.design == programs, "actual main-window reopen loads the saved code project")

        window.select_parts(["driver_body"])
        def cancel_ratings(child):
            check(child.current_id == "driver", "selected CAD driver forwards its circuit ID to safety review")
            child.inputs["max_voltage_v"].setText("24"); child.review()
            check(child.workspace is None and window.document.design == programs, "safety review does not commit a preview")
            child.reject()
        child = modal(window.actions["electrical_safety"].trigger, ElectricalSafetyDialog, cancel_ratings)
        check(not isValid(child) and window.document.design == programs, "safety Cancel disposes the dialog and preserves the project")

        safety_cursor = window.document.journal.data["cursor"]
        def save_ratings(child):
            check(child.inputs["thermal_resistance_k_per_w"].text() == "", "unknown assembled thermal resistance stays blank")
            child.inputs["max_voltage_v"].setText("24"); child.review()
            check(child.safety_report.status == "pending", "missing operating models remain pending rather than approved")
            screenshot(child, "electrical-code-safety2230"); child.save_button.click()
        child = modal(window.actions["electrical_safety"].trigger, ElectricalSafetyDialog, save_ratings)
        wait(lambda: not window.busy)
        final = deepcopy(window.document.design)
        component = next(c for c in Design.model_validate(final).electrical.components if c.id == "driver")
        check(component.safety.max_voltage_v == 24 and component.safety.thermal_resistance_k_per_w is None,
              "explicit safety Save stores only the declared limit without invented heat data")
        check(len(window.document.journal.path()) == 3 and window.document.journal.at(safety_cursor) == programs,
              "safety Save makes one additional history entry")
        check(final["parts"] == original["parts"] and final["electrical"]["programs"] == programs["electrical"]["programs"],
              "rating edits preserve CAD bodies and uploaded source")
        check([(c["a"], c["b"]) for c in final["electrical"]["components"]] ==
              [(c["a"], c["b"]) for c in original["electrical"]["components"]], "rating edits leave all circuit terminals unchanged")
        window.document.write(saved)
        check(read_project(saved).design.model_dump(mode="json") == final, "save and reopen preserve both source and declared safety limits")

        window.select_parts(["board_body"])
        final_cursor = window.document.journal.data["cursor"]
        for kind in ("program", "safety"):
            def outer_edit(outer):
                check(outer.selected_row().component_id == "board", kind + " nested workspace selects the actual board")
                if kind == "program":
                    def edit(child):
                        child.add_program(attach_source("private.ino", SOURCE.replace("100", "200")))
                        wait(lambda: not child._running); child.apply_button.click()
                    nested = modal(outer.program_button.click, ProgramSimulationDialog, edit)
                    changed = len(outer.draft.electrical.programs) == 2
                else:
                    def edit(child):
                        child.inputs["max_voltage_v"].setText("5.5"); child.save_button.click()
                    nested = modal(outer.safety_button.click, ElectricalSafetyDialog, edit)
                    changed = next(c for c in outer.draft.electrical.components if c.id == "board").safety.max_voltage_v == 5.5
                check(changed and outer.apply_button.isEnabled() and not isValid(nested), kind + " child Apply changes only the private draft and disposes child")
                check(window.document.design == final, kind + " accepted child has not changed the live document")
                outer.cancel_button.click()
            outer = modal(window.actions["electrical_workbench"].trigger, ElectricalWorkbenchDialog, outer_edit)
            check(not isValid(outer) and window.document.design == final and window.document.journal.data["cursor"] == final_cursor,
                  kind + " outer Cancel discards accepted child edits and preserves history")

        def cancel_active(outer):
            def cancel(child):
                child.add_program(attach_source("cancel.ino", SOURCE.replace("100", "300")))
                check(child._running and not child.apply_button.isEnabled(), "running trace disables Apply")
                child.reject()
            child = modal(outer.program_button.click, ProgramSimulationDialog, cancel)
            check(not isValid(child), "rejecting an active trace destroys its owned dialog")
            outer.reject()
        outer = modal(window.actions["electrical_workbench"].trigger, ElectricalWorkbenchDialog, cancel_active)
        check(QThreadPool.globalInstance().waitForDone(10000), "cancelled trace worker finishes without an orphan")
        flush(); gc.collect(); app.processEvents()
        check(not isValid(outer) and window.document.design == final and window.document.journal.data["cursor"] == final_cursor,
              "worker cancellation and owner deletion preserve the live design and history")
        screenshot(window, "electrical-code-main2230")
        check(not errors, "native code and safety workflow completes without application errors")
        report["success"] = True
    except Exception:
        report.update(success=False, error=traceback.format_exc())
    finally:
        watchdog.stop()
        for dialog in reversed(dialogs):
            if isValid(dialog): dialog.reject(); dialog.deleteLater()
        QThreadPool.globalInstance().waitForDone(10000); flush()
        window.document.dirty = False; window.close(); flush()
        write(); app.exit(0 if report.get("success") else 1)
