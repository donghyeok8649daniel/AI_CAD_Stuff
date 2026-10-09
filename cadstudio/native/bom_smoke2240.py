"""Owned native BOM import, measured preview and reversible CAD history smoke."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
import traceback
from uuid import uuid4

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, QRectF, QTimer
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu
from shiboken6 import isValid


TABLE = ("Name\tQuantity\tManufacturer\tModel\tLength mm\tWidth mm\tThickness mm\tRole\tSpec URL\tNotes\n"
         "Mount plate\t2\tOwned Fixture\tMP-60-35-4\t60\t35\t4\tstructure\t"
         "https://example.invalid/owned-mount\tOwned explicit envelope dimensions; mounting fit remains to confirm\n")


def run(app, window, output):
    """Use the real MainWindow and kernel, with no model or hardware requests.

    CLI startup supplies an isolated application profile. Fixture imports,
    projects and screenshots are written only beneath the report directory.
    Every dialog is driven through its actual modal entry and disposed.
    """
    from ..bom_design import BomDocument, reconcile_bom
    from ..kernel import KERNEL_LOCK, preview
    from ..models import Design, DraftRequest
    from .bom_design_dialog import BomDesignDialog
    from .cad_scope import Scope, scope_messages
    from .cad_tools import execute_plan, messages
    from .document import read_project
    from .draft_preview import DraftPreviewDialog
    from .draft_repair import review_candidate
    from .draft_summary import draft_summary
    from .firmware_dialog import FirmwareDialog

    output = Path(output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    owned = output.parent / ("bom-owned2240-" + uuid4().hex[:8]); owned.mkdir()
    fixture = owned / "owned-bom2240.tsv"; fixture.write_text(TABLE, encoding="utf-8-sig")
    report = dict(success=False, checks=[], screenshots=[], live_ai_calls=0,
                  network_calls=0, hardware_calls=0, renderer=os.getenv("CADSTUDIO_RENDERER", "unknown"),
                  frozen=bool(getattr(sys, "frozen", False)), owned_directory=str(owned),
                  profile=os.getenv("CADSTUDIO_DATA_DIR", ""), started_utc=datetime.now(timezone.utc).isoformat())
    dialogs, errors = [], []
    original_error, original_item = window.show_error, QInputDialog.getItem
    idle_ticks = [0]

    def write():
        report["check_count"] = len(report["checks"])
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def check(value, title):
        if not value: raise AssertionError(title)
        report["checks"].append(title); idle_ticks[0] = 0; write()

    def wait(predicate, seconds=45):
        remaining = seconds; previous = time.monotonic()
        while not predicate():
            app.processEvents(); QTest.qWait(10)
            current = time.monotonic(); remaining -= min(current - previous, .1); previous = current
            if errors: raise AssertionError(errors[-1])
            if remaining <= 0: raise TimeoutError("Owned BOM native operation timed out")
        app.processEvents()

    def flush():
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete); app.processEvents()

    def screenshot(widget, name):
        path = owned / (name + ".png")
        pixmap = widget.grab()
        view = getattr(widget, "viewport", None)
        # Native VTK child windows are not included in QWidget.grab. Capture
        # the actual renderer framebuffer and place it at its logical Qt rect.
        if view is not None and view.widget.isVisible() and view.initialized:
            from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
            from vtkmodules.vtkIOImage import vtkPNGWriter
            view.window.Render()
            capture = vtkWindowToImageFilter(); capture.SetInput(view.window)
            capture.ReadFrontBufferOff(); capture.Update()
            viewport_path = owned / (name + "-viewport.png")
            writer = vtkPNGWriter(); writer.SetInputConnection(capture.GetOutputPort())
            writer.SetFileName(str(viewport_path)); writer.Write()
            if not viewport_path.is_file(): raise RuntimeError("Owned BOM renderer readback could not be saved")
            painter = QPainter(pixmap)
            try:
                pos = view.widget.mapTo(widget, QPoint(0, 0))
                painter.drawImage(QRectF(pos.x(), pos.y(), view.widget.width(), view.widget.height()), QImage(str(viewport_path)))
            finally: painter.end()
            report["screenshots"].append(str(viewport_path))
        if not pixmap.save(str(path)): raise RuntimeError("Owned BOM screenshot could not be saved")
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
        if state["child"] is None: raise AssertionError("Owned BOM modal did not open")
        return state["child"]

    def watchdog_tick():
        idle_ticks[0] += 1
        if idle_ticks[0] < 90: return
        child = QApplication.activeModalWidget()
        if child is not None:
            screenshot(child, "bom-unexpected2240"); errors.append("Owned BOM modal stalled: " + child.windowTitle()); child.reject()
    watchdog = QTimer(window); watchdog.timeout.connect(watchdog_tick); watchdog.start(1000)

    def plan(item_id, *, quantity=2, length=60):
        actions = []
        for index, identifier in enumerate(("plate_a", "plate_b")[:quantity]):
            actions += [dict(tool="create", target=identifier, args=dict(name="Mount plate " + str(index + 1),
                geometry=dict(kind="plate", length=length, width=35, thickness=4, hole_count=0),
                role="structure", color="#F2F2F2", transform=dict(x=index * 90))),
                dict(tool="bom_bind", target=identifier, args=dict(item_id=item_id))]
        return dict(name="Owned BOM design", summary="Two explicitly sized plates from the reviewed BOM", actions=actions)

    def candidate(request, item_id, **options):
        with KERNEL_LOCK:
            reply = execute_plan(json.dumps(plan(item_id, **options)), request)
            verified = preview(reply.design)
            review = review_candidate(reply.design, request.current, verified, bom=request.bom)
        response = reply.model_dump(); response["validation"] = review
        return reply, verified, response

    def install_draft(request, reply, verified, response):
        window.last_draft = dict(serial=window.operation_serial, provider="codex", prompt=request.prompt,
                                 response=deepcopy(response), preview=verified, design=reply.design.model_dump())
        window.ai_result.setPlainText(draft_summary(response, verified)); window.accept_draft.setEnabled(True)

    try:
        write(); app.setQuitOnLastWindowClosed(False); window.show_error = errors.append
        check(window.document.design is None and window.ai_task is None, "owned startup is empty and starts no AI job")
        wait(lambda: window.viewport.initialized)
        report["graphics"] = window.viewport.window.ReportCapabilities(); write()
        if report["renderer"] == "software":
            check("llvmpipe" in report["graphics"].lower(), "software native viewport uses the actual llvmpipe renderer")
        menus = [action for menu in window.menuBar().findChildren(QMenu) for action in menu.actions()]
        check(window.actions["bom"] in menus and window.bom_button.objectName() == "bomDesignButton",
              "BOM import is exposed in the native menu and AI panel")
        check(window.actions["bom_bind"] in menus, "selected CAD bodies have a native BOM binding action")
        check(window.actions["firmware"] in menus and window.actions["firmware"] in window.electrical_tools.menu().actions(),
              "existing firmware workflow stays reachable in the main menu and electrical tools")

        def firmware_cancel(child):
            check(child.accepted_workspace is None and child.board.count() == 0,
                  "firmware review opens safely beside the new BOM flow")
            child.reject()
        child = modal(window.actions["firmware"].trigger, FirmwareDialog, firmware_cancel)
        check(not isValid(child) and window.document.design is None, "firmware Cancel preserves the empty native design")

        def cancel_import(child):
            check(child.import_file(fixture), "native BOM dialog imports the actual owned TSV file")
            child.quantity.setText("3"); child.apply_button.click()
            check(child.document.items[0].quantity == 3 and child.accepted_bom is None,
                  "BOM review edits remain private before explicit Save")
            check("SHA-256" in child.source_details.toPlainText() and "MP-60-35-4" in child.source_details.toPlainText(),
                  "review exposes the preserved original row and source fingerprint")
            child.resize(1024, 700); app.processEvents()
            check(child.width() <= 1024 and child.height() <= 700,
                  "actual themed BOM review fits a 1024 by 700 logical window")
            check(all(child.rect().contains(QRect(control.mapTo(child, QPoint(0, 0)), control.size()))
                      and control.visibleRegion().boundingRect() == control.rect() for control in child.controls.buttons()),
                  "small native BOM review keeps Save and Cancel completely visible")
            screenshot(child, "bom-import-review2240"); child.close_button.click()
        child = modal(window.bom_button.click, BomDesignDialog, cancel_import)
        check(not isValid(child) and window.document.design is None and window.document.journal is None,
              "BOM Cancel discards import and edits without a history transaction")

        def save_import(child):
            check(child.import_file(fixture), "reviewed BOM file can be imported again after Cancel")
            check(child.document.items[0].quantity == 2 and not child.document.items[0].issues,
                  "review shows actual two-piece quantity and explicit mm dimensions")
            child.save_button.click()
        child = modal(window.actions["bom"].trigger, BomDesignDialog, save_import)
        wait(lambda: not window.busy)
        imported = deepcopy(window.document.design); bom = BomDocument.model_validate(imported["bom"]); item = bom.items[0]
        check(not isValid(child) and imported["parts"] == [] and imported["bom"]["items"][0]["quantity"] == 2,
              "explicit BOM Save creates design input without silently generating bodies")
        check(window.ai_mode.currentData() == "design" and "BOM" in window.prompt.toPlainText() and bom.source_name in window.prompt.toPlainText(),
              "BOM adoption prepares an editable native design request from the reviewed source")
        check(window.ai_task is None and window.last_draft is None and not window.accept_draft.isEnabled(),
              "prepared BOM request never starts model generation or permits an absent draft")
        check("BOM" in window.bom_status.text() or "owned-bom2240.tsv" in window.bom_status.text(),
              "main window shows the imported BOM reconciliation status")

        request = DraftRequest(prompt=window.prompt.toPlainText(), current=Design.model_validate(imported), bom=bom)
        selector = scope_messages(request); plans = messages(request)
        check("bom_reference" in selector[1]["content"] and item.id in selector[1]["content"] and "BOM" in selector[0]["content"],
              "tool selection receives authoritative BOM rows and source requirements")
        check("bom_bind" in plans[0]["content"] and "part_binding" in plans[1]["content"],
              "plan messages describe real per-instance BOM bindings")
        scope = Scope.parse(json.dumps(dict(intent="assembly", tools=["create", "bom_bind"], shapes=["plate"],
            new_parts=["plate_a", "plate_b"], connections=[])), request)
        reply, verified, response = candidate(request, item.id)
        check(scope.validate_result(reply) is reply, "BOM-aware tool scope accepts the actual two-body plan")
        review = response["validation"]
        check(verified["stats"]["valid"] and verified["stats"]["parts"] == 2 and abs(verified["stats"]["volume"] - 16800) < 1e-6,
              "real CAD kernel measures two 60 by 35 by 4 mm plate solids")
        check(not verified["stats"]["collisions"] and review["status"] == "ready" and review["bom"]["all_matched"],
              "measured candidate verifies two persistent bodies against BOM quantities and dimensions")
        check(all(part.role == "structure" and part.product.model == "MP-60-35-4" and part.bom.item_id == item.id for part in reply.design.parts),
              "bom_bind records physical instance IDs and declared model and role without changing dimensions")
        check(window.document.design == imported, "plan execution and measured review leave the current project unchanged")
        install_draft(request, reply, verified, response)

        def preview_cancel(child):
            check(child.apply_button.isEnabled() and hasattr(child, "bom_table"), "valid measured BOM draft exposes explicit Apply and a native reconciliation table")
            child.tabs.setCurrentWidget(child.bom_tab); app.processEvents()
            check(child.bom_table.rowCount() == 1 and child.bom_table.item(0, 1).text() == "2" and child.bom_table.item(0, 2).text() == "2",
                  "BOM preview compares expected and measured CAD instance counts")
            screenshot(child, "bom-draft-preview2240"); child.reject()
        child = modal(window.accept_draft.click, DraftPreviewDialog, preview_cancel)
        check(not isValid(child) and window.document.design == imported, "preview Back disposes its viewport and preserves the source design")

        def preview_apply(child):
            child.tabs.setCurrentWidget(child.bom_tab); child.apply_button.click()
        child = modal(window.accept_draft.click, DraftPreviewDialog, preview_apply)
        wait(lambda: not window.busy)
        designed = deepcopy(window.document.design)
        check(not isValid(child) and len(designed["parts"]) == 2 and reconcile_bom(designed).all_matched,
              "explicit native preview Apply commits the measured and mapped BOM design")
        check([entry["context"]["tool_actions"][0]["tool"] for entry in window.document.journal.path()[1:]] == ["create", "bom_bind", "create", "bom_bind"],
              "four CAD and BOM operations remain separately restorable in native history")
        check(designed["bom"] == imported["bom"], "draft apply preserves the reviewed authoritative BOM document")
        window.undo(); wait(lambda: not window.busy)
        check(len(window.document.design["parts"]) == 2 and not reconcile_bom(window.document.design).all_matched,
              "Undo of the second mapping keeps two solids and restores the outstanding BOM instance")
        window.redo(); wait(lambda: not window.busy)
        check(window.document.design == designed and reconcile_bom(window.document.design).all_matched,
              "Redo restores the exact persistent mapping and measured BOM agreement")

        # Manual binding follows the visible selected-body action and must keep
        # the actual body, role and preexisting product metadata unchanged.
        unbound = deepcopy(designed); unbound["parts"][1].pop("bom")
        unbound["parts"][1]["product"]["notes"] += "\nOwned product metadata preservation sentinel"
        window.apply_design(unbound, "Owned manual mapping fixture"); wait(lambda: not window.busy)
        before_manual = deepcopy(window.document.design); window.select_parts(["plate_b"])
        QInputDialog.getItem = staticmethod(lambda *args, **kwargs: (args[3][0], True))
        window.actions["bom_bind"].trigger(); wait(lambda: not window.busy); QInputDialog.getItem = original_item
        manually_bound = deepcopy(window.document.design)
        preserved = ("geometry", "transform", "color", "role", "product")
        check(all(manually_bound["parts"][1][key] == before_manual["parts"][1][key] for key in preserved),
              "selected-body BOM mapping preserves geometry placement colors role and existing product evidence")
        check(reconcile_bom(manually_bound).all_matched and len(window.selected_parts) == 1,
              "native selected-body binding completes the outstanding real BOM instance")
        window.undo(); wait(lambda: not window.busy)
        check(window.document.design == before_manual, "manual BOM mapping Undo restores the unbound body's original metadata")
        window.redo(); wait(lambda: not window.busy)
        check(window.document.design == manually_bound, "manual BOM mapping Redo restores the reviewed binding exactly")

        # Rejected candidates are reviewed from the original BOM-only baseline.
        # Their invalid quantity/size cannot bypass native Apply, even when the
        # geometry itself is valid and there is no collision.
        for name, options in (("quantity", dict(quantity=1)), ("size", dict(length=59))):
            bad_reply, bad_preview, bad_response = candidate(request, item.id, **options)
            bad_review = bad_response["validation"]
            check(bad_preview["stats"]["valid"] and not bad_preview["stats"]["collisions"] and bad_review["status"] == "needs_repair",
                  "valid noncolliding solids with wrong BOM " + name + " remain rejected")
            install_draft(request, bad_reply, bad_preview, bad_response); baseline = deepcopy(window.document.design)
            window.apply_draft()
            check(window.document.design == baseline and not window.busy, "direct apply cannot bypass BOM " + name + " validation")
            def blocked(child):
                check(not child.apply_button.isEnabled(), "native preview blocks Apply for BOM " + name + " mismatch")
                child.tabs.setCurrentWidget(child.bom_tab); app.processEvents()
                check(child.bom_table.rowCount() == 1 and child.bom_table.item(0, 4).toolTip(),
                      "native BOM preview exposes actual body IDs and " + name + " mismatch evidence")
                child.accept(); check(child.isVisible(), "Accept call cannot bypass BOM " + name + " review guard")
                screenshot(child, "bom-rejected-" + name + "2240"); child.reject()
            child = modal(window.accept_draft.click, DraftPreviewDialog, blocked)
            check(not isValid(child) and window.document.design == baseline,
                  "closing rejected BOM " + name + " preview preserves the saved live design")
        window.last_draft = None; window.accept_draft.setEnabled(False)

        project = owned / "owned-bom-design2240.cad.json"
        window.document.write(project); reopened = read_project(project)
        check(reopened.design.model_dump() == manually_bound and reconcile_bom(reopened.design).all_matched,
              "native project Save retains reviewed BOM source mappings metadata and full measured agreement")
        check(len(reopened.history.entries) == len(window.document.journal.data["entries"]),
              "project Save retains all CAD and BOM history entries")
        window.open_project(project); wait(lambda: not window.busy)
        check(window.document.design == manually_bound and window.document.path == project and not window.document.dirty,
              "native Open rebuilds actual geometry and restores BOM mappings from the owned project")
        check(window.result["stats"]["parts"] == 2 and len(window.viewport.actors) == 2 and reconcile_bom(window.document.design).all_matched,
              "reopened native viewport renders both measured BOM instances")
        screenshot(window, "bom-main2240")
        check(not errors and window.ai_task is None, "owned native BOM workflow finishes without application errors or AI calls")
        report["project"] = str(project); report["success"] = True
    except Exception:
        report.update(success=False, error=traceback.format_exc())
    finally:
        watchdog.stop(); QInputDialog.getItem = original_item; window.show_error = original_error
        for child in reversed(dialogs):
            if isValid(child): child.reject(); child.deleteLater()
        flush(); window.document.dirty = False; window.close(); flush()
        report["finished_utc"] = datetime.now(timezone.utc).isoformat(); write()
        app.exit(0 if report["success"] else 1)
