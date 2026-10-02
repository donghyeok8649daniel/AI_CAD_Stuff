"""Owned Qt/VTK smoke for temporary role views and electrical supply/schematic."""

from copy import deepcopy
import json
import time
import traceback

from PySide6.QtCore import QPoint, QRectF, QThreadPool
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog


def run(app, window, path):
    from ..electrical import evaluate_electrical
    from ..models import Design, Part
    from ..part_roles import COLORS
    from .electrical_dialog import ElectricalDialog

    path.parent.mkdir(parents=True, exist_ok=True)
    report = {"checks": [], "live_ai_calls": 0}
    dialogs = []
    errors = []

    def check(value, description):
        if not value:
            raise AssertionError(description)
        report["checks"].append(description)

    def wait(predicate, timeout=75):
        deadline = time.monotonic() + timeout
        while not predicate():
            app.processEvents()
            QTest.qWait(10)
            if errors:
                raise AssertionError(errors[-1])
            if time.monotonic() >= deadline:
                raise TimeoutError("role / electrical native flow")
        app.processEvents()

    def visible_parts():
        return {identifier for identifier, (actor, _) in window.viewport.actors.items()
                if actor.GetVisibility()}

    def snapshot(name):
        from vtkmodules.vtkIOImage import vtkPNGWriter
        from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter

        viewport = window.viewport
        viewport.window.Render()
        capture = vtkWindowToImageFilter()
        capture.SetInput(viewport.window)
        capture.ReadFrontBufferOff()
        capture.Update()
        frame = path.with_name(name + "-viewport.png")
        writer = vtkPNGWriter()
        writer.SetFileName(str(frame))
        writer.SetInputConnection(capture.GetOutputPort())
        writer.Write()
        pixels = window.grab()
        painter = QPainter(pixels)
        origin = viewport.widget.mapTo(window, QPoint(0, 0))
        painter.drawImage(QRectF(origin.x(), origin.y(), viewport.widget.width(), viewport.widget.height()),
                          QImage(str(frame)))
        painter.end()
        pixels.save(str(path.with_name(name + ".png")))

    try:
        window.show_error = errors.append
        app.setQuitOnLastWindowClosed(False)
        check(window.document.design is None, "owned CAD starts with a blank design")
        roles = ("electrical", "structure", "transmission", "specimen")
        parts = [Part(id=role, name=role, role=role, color="#123456",
                      geometry={"kind": "cylinder"}, transform={"x": index * 50})
                 for index, role in enumerate(roles)]
        design = Design(parts=parts, part_groups=[{
            "id": "mixed", "name": "Mixed roles", "part_ids": ["electrical", "structure"]
        }]).model_dump()
        window.apply_design(design, "role smoke", fit=True)
        wait(lambda: not window.busy)
        baseline = deepcopy(window.document.design)
        check(all("role_" + role in window.actions for role in
                  ("all", "electrical", "structure", "transmission")),
              "native inspection toolbar exposes All and three role buttons")
        window.viewport.visibility("specimen", False)
        for role in ("electrical", "structure", "transmission"):
            window.actions["role_" + role].trigger()
            app.processEvents()
            check(window.role_view == role and window.selected_parts == [role] and
                  visible_parts() == {role},
                  role + " button shows and selects only matching parts")
            red, green, blue = (int(COLORS[role][offset:offset + 2], 16) / 255
                                for offset in (1, 3, 5))
            actual = window.viewport.actors[role][0].GetProperty().GetColor()
            check(all(abs(a - b) < 1e-5 for a, b in zip(actual, (red, green, blue))),
                  role + " inspection color matches its role")
            check(window.expand_groups([role]) == [role],
                  role + " selection does not pull in hidden mixed-group members")
            if role == "electrical":
                snapshot("role-electrical2150")
        original_size = window.size()
        window.showNormal()
        window.resize(820, 640)
        app.processEvents()
        bar = window.role_toolbar
        buttons = [bar.widgetForAction(window.actions["role_" + role])
                   for role in ("all", "electrical", "structure", "transmission")]
        check(window.width() == 820 and bar.isVisible() and
              all(button is not None and button.isVisible() and
                  bar.rect().contains(button.geometry()) for button in buttons),
              "all four role buttons remain visible in an 820-pixel CAD window")
        snapshot("role-compact2150")
        window.resize(original_size)
        app.processEvents()
        window.actions["role_all"].trigger()
        app.processEvents()
        restored_color = window.viewport.actors["transmission"][0].GetProperty().GetColor()
        check(window.role_view is None and window.viewport.hidden == {"specimen"} and
              all(abs(a - b) < 1e-5 for a, b in
                  zip(restored_color, (18 / 255, 52 / 255, 86 / 255))),
              "All restores manual visibility and original part colors")
        check(window.document.design == baseline,
              "role-only inspection does not alter saved CAD geometry or groups")

        wiring = ElectricalDialog(window, None)
        dialogs.append(wiring)
        wiring.show()
        wiring.components = [
            dict(id="supply", name="5 V battery", kind="battery", a="PLUS", b="GND",
                 voltage_v=5, closed=True),
            dict(id="lead", name="VCC wire", kind="wire", a="PLUS", b="VCC",
                 length_mm=100, cross_section_mm2=.5, closed=True),
            dict(id="board", name="Controller", kind="mcu", a="VCC", b="GND",
                 rated_voltage_v=5, rated_current_a=.1, signal_pins={"GPIO1": "SIGNAL"}),
            dict(id="signal", name="GPIO wire", kind="wire", a="SIGNAL", b="INPUT",
                 length_mm=100, cross_section_mm2=.5, closed=False),
            dict(id="receiver", name="Sensor input", kind="resistor", a="INPUT", b="GND",
                 resistance_ohm=1000),
        ]
        wiring.refresh()
        wiring.calculate()
        wiring.table.selectRow(0)
        check(wiring.power_button.isEnabled() and wiring.schematic_button.isEnabled(),
              "battery toggle and separate schematic buttons are available")
        check("POWER ON" in wiring.report.toPlainText() and
              "PASS · Controller: VCC" in wiring.report.toPlainText(),
              "energized battery supplies the MCU through a closed lead")

        wiring.power_button.click()
        off = evaluate_electrical(wiring.candidate())
        mcu = next(branch for branch in off.components if branch.id == "board")
        check(wiring.components[0]["closed"] is False and
              "POWER OFF" in wiring.report.toPlainText() and
              "전원 OFF" in wiring.table.item(0, 5).text(),
              "native battery control reports disabled supply clearly")
        check(all(abs(branch.current_a) < 1e-12 for branch in off.components) and
              mcu.supply_connected is False,
              "disabled battery produces zero DC current and no MCU supply path")

        from .electrical_schematic import ElectricalSchematicDialog
        original_exec = ElectricalSchematicDialog.exec
        opened = []

        def capture_schematic(dialog):
            dialog.show()
            app.processEvents()
            opened.append(dialog)
            return QDialog.DialogCode.Accepted

        try:
            ElectricalSchematicDialog.exec = capture_schematic
            wiring.schematic_button.click()
        finally:
            ElectricalSchematicDialog.exec = original_exec
        check(len(opened) == 1 and opened[0].scene.items() and
              {"PLUS", "GND", "VCC"} <= set(opened[0].node_positions),
              "schematic button opens a distinct drawn node-and-component window")
        schematic = opened[0]
        dialogs.append(schematic)
        check(schematic.branch_layout["supply"]["active"] is False and
              schematic.branch_layout["signal"]["active"] is False and
              schematic.branch_layout["board"]["signals"]["GPIO1"]["connected"] is False,
              "schematic marks disabled supply, broken signal wire and disconnected GPIO")
        schematic.grab().save(str(path.with_name("electrical-schematic2150.png")))

        wiring.power_button.click()
        restored = evaluate_electrical(wiring.candidate())
        restored_mcu = next(branch for branch in restored.components if branch.id == "board")
        check(wiring.components[0]["closed"] is True and restored_mcu.supply_connected is True and
              restored_mcu.current_a > 0 and "POWER ON" in wiring.report.toPlainText(),
              "reenabling supply restores the DC current and MCU power report")
        check("FAIL · GPIO wire: 전선 단선" in wiring.report.toPlainText() and
              "FAIL · Controller GPIO1" in wiring.report.toPlainText(),
              "schematic circuit still warns about the independent broken signal lead")
        check(window.document.design == baseline,
              "electrical inspection and supply preview leave the CAD document unchanged")
        report["success"] = True
    except Exception:
        report["success"] = False
        report["error"] = traceback.format_exc()
    finally:
        for dialog in dialogs:
            if dialog.isVisible():
                dialog.reject()
        QThreadPool.globalInstance().waitForDone(10000)
        window.document.dirty = False
        window.close()
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        app.exit(0 if report["success"] else 1)
