"""Owned native workspace flow; no network, hardware or user document writes."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import time
import traceback

from PySide6.QtCore import QThreadPool, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def run(app, window, path):
    from ..models import Design, Part
    from ..electrical_readiness import build_electrical_readiness
    from ..electrical_catalog import catalog_counts, catalog_support
    from .document import read_project
    from .electrical_part_dialog import ElectricalPartDialog, ElectricalCadLinkDialog
    from .electrical_dialog import ComponentDialog, ElectricalDialog
    from .electrical_schematic import ElectricalSchematicDialog
    from .electrical_workbench import ElectricalWorkbenchDialog

    path.parent.mkdir(parents=True, exist_ok=True)
    report = dict(checks=[], live_ai_calls=0, hardware_calls=0)
    dialogs = []
    errors = []
    last_check = [time.monotonic()]

    def check(condition, title):
        if not condition: raise AssertionError(title)
        report['checks'].append(title)
        last_check[0] = time.monotonic()
        path.write_text(json.dumps(dict(report, success=False, phase='running'), ensure_ascii=False, indent=2), encoding='utf-8')

    def wait(predicate):
        deadline = time.monotonic() + 60
        while not predicate():
            app.processEvents(); QTest.qWait(10)
            if errors: raise AssertionError(errors[-1])
            if time.monotonic() > deadline: raise TimeoutError('Owned electrical workspace flow')
        app.processEvents()

    def own_modal(callback, expected_type):
        state = dict(done=False)
        deadline = time.monotonic() + 15
        def handle():
            child = QApplication.activeModalWidget()
            if not isinstance(child, expected_type) or not child.isVisible():
                if time.monotonic() < deadline:
                    QTimer.singleShot(20, handle); return
                errors.append('Expected owned modal did not open: ' + expected_type.__name__)
                state['done'] = True
                if child is not None: child.reject()
                return
            try:
                dialogs.append(child); callback(child)
            except Exception:
                errors.append(traceback.format_exc()); child.reject()
            finally: state['done'] = True
        QTimer.singleShot(60, handle)
        return state

    def watchdog_tick():
        if time.monotonic() - last_check[0] < 45: return
        child = QApplication.activeModalWidget()
        if child is not None:
            child.grab().save(str(path.with_name('electrical-workbench-unexpected-modal2210.png')))
            errors.append('Owned modal stalled: ' + child.windowTitle()); child.reject()
    watchdog = QTimer(window); watchdog.timeout.connect(watchdog_tick); watchdog.start(1000)

    def select_body(child, identifier):
        row = next(index for index, row in enumerate(child._visible_rows) if row.part_id == identifier)
        child.table.selectRow(row); app.processEvents()

    def register_model(child, catalog_id):
        index = child.model_combo.findData(catalog_id)
        check(index >= 0, 'registration editor exposes exact model ' + catalog_id)
        child.model_combo.setCurrentIndex(index); child.register_button.click()
        check(child.component().catalog_id == catalog_id, 'native preview registers selected exact model ' + catalog_id)
        check(not child.component().analysis_enabled, 'model identity does not invent operating current')
        child.apply_button.click()

    try:
        app.setQuitOnLastWindowClosed(False); window.show_error = errors.append
        check(window.document.design is None, 'owned native startup has no CAD model')
        original = Design(name='Electrical workbench native test', parts=[
            Part(id='board', name='Main controller', role='electrical', color='#123456', geometry=dict(kind='cylinder', diameter=35, height=12)),
            Part(id='sensor', name='Force sensor', role='electrical', color='#446688', geometry=dict(kind='cylinder', diameter=25, height=12), transform=dict(x=70)),
            Part(id='motor', name='Drive motor', role='transmission', color='#336633', geometry=dict(kind='cylinder', diameter=25, height=12), transform=dict(x=140)),
            Part(id='yellow_housing', name='Yellow enclosure', role='structure', color='#FFD400', geometry=dict(kind='cylinder', diameter=25, height=12), transform=dict(x=210))],
            part_groups=[dict(id='original_group', name='Original group', part_ids=['board', 'yellow_housing'])],
            electrical=dict(name='Original supply', nodes=['GND', 'PWR', 'KEEP'], components=[
                dict(id='source', name='Declared 5 V source', kind='battery', a='PWR', b='GND', voltage_v=5),
                dict(id='legacy', name='Legacy motor', kind='motor', a='PWR', b='GND', part_id='motor', rated_voltage_v=5, rated_current_a=.2)])).model_dump(mode='json')
        window.apply_design(original, 'Original bodies and supply'); wait(lambda: not window.busy)
        original_cursor = window.document.journal.data['cursor']
        original_entries = len(window.document.journal.data['entries'])
        actors = {identifier: value[0] for identifier, value in window.viewport.actors.items()}
        window.select_parts(['board'])
        check('electrical_workbench' in window.actions, 'native menus expose Electrical workspace action')
        tool = window.findChild(type(window.electrical_tools), 'electricalWorkspaceTools')
        app.processEvents(); window.grab().save(str(path.with_name('electrical-workbench-main-toolbar2210.png')))
        check(tool is not None and tool.isVisible(), 'top toolbar exposes the electrical workspace beside part color')
        direct=window.toolbar.widgetForAction(window.actions['wiring_diagram'])
        check(direct is not None and direct.isVisible(), 'top toolbar exposes a direct circuit button outside the electrical menu')
        toolbar_order=window.toolbar.actions()
        check(toolbar_order.index(window.actions['wiring_diagram'])==toolbar_order.index(window.actions['color'])+1,
              'direct circuit button immediately follows selected part color')

        def edit_workspace(child):
            check(child.report.counts['electrical_parts'] == 2 and child.report.counts['unregistered_parts'] == 2,
                  'workspace counts actual role-based unregistered CAD electronics')
            check({'board', 'sensor', 'motor'} == {row.part_id for row in child._visible_rows if row.part_id},
                  'default list includes unregistered role bodies and legacy linked bodies')
            check(not child.report.dc_calculation_performed and not child.report.hardware_execution_supported,
                  'opening the workspace inspects documentation without approving or solving hardware')
            child.resize(1040, 600); app.processEvents()
            check(child.height() == 600 and all(child.rect().contains(widget.mapTo(child, widget.rect().bottomRight()))
                for widget in (child.apply_button, child.cancel_button, child.register_button, child.schematic_button, child.power_button)),
                '600 px native workspace retains Save Cancel registration schematic and power controls')
            child.grab().save(str(path.with_name('electrical-workbench-ko2210.png')))
            select_body(child, 'board')
            state = own_modal(lambda editor: register_model(editor, 'rpi4b'), ElectricalPartDialog)
            child.register_button.click(); wait(lambda: state['done'])
            check(window.document.design == original, 'accepted child registration stays private until outer workspace Save')
            check(child.report.counts['registered_electrical_parts'] == 1, 'registration refresh updates actual body coverage')
            child.query.setText('rpi4b')
            check(len(child._visible_rows) == 1 and child.selected_row().part_id == 'board', 'search resolves exact registered model identity')
            check(len(child.diagram.pin_items) == 40, 'selected Pi physical diagram retains all forty header pads')
            child.detail_tabs.setCurrentIndex(1); app.processEvents(); child.diagram.fit()
            child.grab().save(str(path.with_name('electrical-workbench-board2210.png')))
            child.query.clear(); child.state_filter.setCurrentIndex(child.state_filter.findData('unregistered'))
            check([row.part_id for row in child._visible_rows] == ['sensor'], 'unregistered filter shows the remaining real CAD sensor')
            child.state_filter.setCurrentIndex(0); child.all_cad.setChecked(True)
            check('yellow_housing' in {row.part_id for row in child._visible_rows}, 'All CAD bodies enables manual registration without guessing from yellow')
            select_body(child, 'sensor'); child.tabs.setCurrentIndex(1)
            child.catalog_registerable.setChecked(True)
            check(len(child._catalog_rows) == catalog_counts()['registerable'], 'catalog reports registerable models separately from discovery references')
            child.catalog_query.setText('ams_as5600_asot')
            check(len(child._catalog_rows) == 1 and child.catalog_use_button.isEnabled(), 'catalog model can target the selected existing CAD body')
            child.grab().save(str(path.with_name('electrical-workbench-catalog2210.png')))
            state = own_modal(lambda editor: register_model(editor, 'ams_as5600_asot'), ElectricalPartDialog)
            child.catalog_use_button.click(); wait(lambda: state['done'])
            child.tabs.setCurrentIndex(0)
            check(child.report.counts['registered_electrical_parts'] == 2, 'two native product registrations share one private workspace draft')

            def circuit_preview(schematic):
                check(schematic.editable and len(schematic.workspace.components) == 4, 'workspace opens the actual editable native physical circuit')
                schematic.kind_combo.setCurrentIndex(schematic.kind_combo.findData('resistor'))
                def resistor(component):
                    component.name.setText('Reference resistor')
                    component.a.setText('PWR'); component.b.setText('GND')
                    component.inputs['resistance_ohm'].setValue(1000)
                    component.accept()
                state = own_modal(resistor, ComponentDialog)
                schematic.add_button.click(); wait(lambda: state['done'])
                check(any(item.name == 'Reference resistor' for item in schematic.workspace.components), 'schematic child editor adds a real circuit resistor in its own draft')
                schematic.grab().save(str(path.with_name('electrical-workbench-circuit2210.png')))
                schematic.apply_button.click()
            state = own_modal(circuit_preview, ElectricalSchematicDialog)
            child.schematic_button.click(); wait(lambda: state['done'])
            check(any(item.name == 'Reference resistor' for item in child.draft.electrical.components), 'accepted schematic edits join the same workspace draft')
            before_power = child.draft.model_dump(mode='json')
            def inspect_power(editor):
                check(isinstance(editor, ElectricalDialog), 'power action opens the native supply rating and wire editor')
                editor.reject()
            state = own_modal(inspect_power, ElectricalDialog)
            child.power_button.click(); wait(lambda: state['done'])
            check(child.draft.model_dump(mode='json') == before_power, 'Cancel in operating editor preserves the complete workspace draft')
            select_body(child, 'board'); child.focus_button.click()
            check(window.selected == 'board', 'Show in CAD selects the actual linked body without another modal')
            check(window.document.design == original, 'all accepted child edits are still absent from the live document before outer Save')
            child.apply_button.click()

        state = own_modal(edit_workspace, ElectricalWorkbenchDialog)
        window.actions['electrical_workbench'].trigger(); wait(lambda: state['done']); wait(lambda: not window.busy)
        final = deepcopy(window.document.design)
        check(len(window.document.journal.data['entries']) == original_entries + 1, 'outer Save commits registration and schematic edits as one history transaction')
        check(window.document.journal.at(original_cursor) == original, 'previous history snapshot remains exact')
        check([part['color'] for part in final['parts']] == [part['color'] for part in original['parts']], 'default registration preserves all original custom colors')
        check(final['part_groups'] == original['part_groups'], 'workspace saves preserve original mixed CAD groups')
        check(all(window.viewport.actors[key][0] is actor for key, actor in actors.items()), 'electrical metadata edits reuse the same CAD render actors')
        check('KEEP' in final['electrical']['nodes'], 'unrelated existing circuit nets survive workspace and child edits')
        saved = path.with_suffix('.cad.json'); window.document.write(saved)
        loaded = read_project(saved)
        check(loaded.design.model_dump(mode='json') == final, 'native project save and reopen preserve the complete electrical workspace')
        window.undo(); wait(lambda: not window.busy)
        check(window.document.design == original, 'Undo removes the complete workspace transaction')
        window.redo(); wait(lambda: not window.busy)
        check(window.document.design == final, 'Redo restores all exact model registrations and resistor wiring')

        window.select_parts(['board']); QTest.mouseClick(direct,Qt.MouseButton.LeftButton); app.processEvents()
        panel=window.wiring_window
        board_component=next(c for c in panel.workspace.components if c.part_id=='board')
        check(panel._selected_id()==board_component.id,'direct circuit button finds the selected CAD body in the circuit')
        panel.focus_component('source')
        check(window.selected is None,'selecting an unlinked circuit source does not keep a misleading CAD selection')
        window.select_parts(['board'])
        check(panel._selected_id()==board_component.id,'CAD selection highlights the corresponding saved circuit component')
        panel.view.fitInView(panel.component_items[board_component.id].sceneBoundingRect(),Qt.AspectRatioMode.KeepAspectRatio)
        item=panel.component_items[board_component.id]
        point=panel.view.mapFromScene(item.mapToScene(item.boundingRect().center()))
        window.select_parts([])
        QTest.mouseClick(panel.view.viewport(),Qt.MouseButton.LeftButton,pos=point); app.processEvents()
        check(window.selected=='board','actual circuit-body click keeps the CAD association selected')
        QTest.mouseClick(panel.cad_button,Qt.MouseButton.LeftButton);app.processEvents()
        check(window.selected=='board' and window.workspace.currentData()=='model','Show CAD part returns to the actual 3D body')
        panel.focus_component('source'); before_link=deepcopy(window.document.design)
        link_entries=len(window.document.journal.data['entries'])
        def link_supply(editor):
            check(editor.component_combo.currentData()=='source','saved circuit link action selects the existing source ID')
            editor.part_combo.setCurrentIndex(editor.part_combo.findData('yellow_housing'))
            QTest.mouseClick(editor.bind_button,Qt.MouseButton.LeftButton)
            check(window.document.design==before_link,'link preview leaves the live CAD and circuit unchanged')
            editor.grab().save(str(path.with_name('electrical-cad-link2220.png')))
            QTest.mouseClick(editor.apply_button,Qt.MouseButton.LeftButton)
        state=own_modal(link_supply,ElectricalCadLinkDialog)
        QTest.mouseClick(panel.link_button,Qt.MouseButton.LeftButton);wait(lambda:state['done']);wait(lambda:not window.busy)
        final=deepcopy(window.document.design)
        check(len(window.document.journal.data['entries'])==link_entries+1,'saved existing circuit correspondence adds one history transaction')
        source=next(c for c in final['electrical']['components'] if c['id']=='source')
        check(source['part_id']=='yellow_housing' and source['part_registration'],'link save retains the source ID and registers its selected body')
        check(final['parts'][-1]['role']=='electrical' and final['parts'][-1]['color']=='#FFD400','link save updates only declared role while preserving custom color')
        check(len(final['electrical']['components'])==len(before_link['electrical']['components']),'link save never duplicates circuit components')
        window.document.write(saved);check(read_project(saved).design.model_dump(mode='json')==final,'save and reopen retain the exact circuit and CAD correspondence')
        window.undo();wait(lambda:not window.busy);check(window.document.design==before_link,'Undo restores the prior association and body role')
        window.redo();wait(lambda:not window.busy);check(window.document.design==final,'Redo restores the saved association and body role')
        window.select_parts(['yellow_housing']);panel=window.wiring_window
        check(panel._selected_id()=='source','newly linked CAD body finds its existing circuit item without a second registration')
        panel.focus_component('source',notify=False)
        panel.grab().save(str(path.with_name('electrical-cad-correspondence2220.png')))

        def cancel_link(editor):
            QTest.mouseClick(editor.unbind_button,Qt.MouseButton.LeftButton)
            check(not next(c for c in editor.draft.electrical.components if c.id=='source').part_id,'unlink preview only changes the private link draft')
            editor.reject()
        state=own_modal(cancel_link,ElectricalCadLinkDialog)
        QTest.mouseClick(panel.link_button,Qt.MouseButton.LeftButton);wait(lambda:state['done'])
        check(window.document.design==final,'Cancel leaves the saved existing component and CAD correspondence intact')

        def cancel_workspace(child):
            select_body(child, 'board')
            def rename(editor):
                editor.name.setText('Discarded controller rename'); editor.register_button.click(); editor.apply_button.click()
            state = own_modal(rename, ElectricalPartDialog)
            child.register_button.click(); wait(lambda: state['done'])
            check(child.apply_button.isEnabled(), 'accepted child rename marks the outer workspace as changed')
            child.reject()
        state = own_modal(cancel_workspace, ElectricalWorkbenchDialog)
        window.actions['electrical_workbench'].trigger(); wait(lambda: state['done'])
        check(window.document.design == final, 'outer Cancel discards even accepted nested editor changes')

        language = getattr(app, 'cad_language', None)
        if language:
            previous_language = language.language
            language.set_language('en', persist=False)
            try:
                child = ElectricalWorkbenchDialog(window, final, 'board'); dialogs.append(child)
                child.resize(1040, 600); child.show(); app.processEvents()
                check('Electrical workspace' in child.windowTitle() and child.apply_button.text() == 'Save electrical changes',
                      'English mode localizes workspace title and final Save action')
                check(child.rect().contains(child.cancel_button.mapTo(child, child.cancel_button.rect().bottomRight())),
                      'English 600 px workspace retains the final Cancel control')
                child.grab().save(str(path.with_name('electrical-workbench-en2210.png'))); child.reject()
            finally: language.set_language(previous_language, persist=False)

        # Exercise the redraw + disposal path that previously exposed native
        # graphics-wrapper GC faults, using only owned private circuit drafts.
        import gc
        from shiboken6 import isValid
        from PySide6.QtCore import QCoreApplication, QEvent
        for index in range(2):
            draft_panel=ElectricalSchematicDialog(window,final['electrical'],parts=final['parts'],design=final)
            draft_panel.show();draft_panel.focus_component('legacy');app.processEvents()
            def unlink_private(editor):
                QTest.mouseClick(editor.unbind_button,Qt.MouseButton.LeftButton)
                QTest.mouseClick(editor.apply_button,Qt.MouseButton.LeftButton)
            state=own_modal(unlink_private,ElectricalCadLinkDialog)
            QTest.mouseClick(draft_panel.link_button,Qt.MouseButton.LeftButton);wait(lambda:state['done'])
            check(not next(c for c in draft_panel.workspace.components if c.id=='legacy').part_id,
                  f'owned lifetime cycle {index+1}: child correspondence Save redraws the private circuit')
            draft_panel.reject();draft_panel.deleteLater()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            dialogs[:]=[dialog for dialog in dialogs if isValid(dialog)]
            del draft_panel
            gc.collect();app.processEvents()
            check(window.document.design==final,
                  f'owned lifetime cycle {index+1}: parent Cancel and graphics GC preserve the live design')

        fixture = os.environ.get('CADSTUDIO_ELECTRICAL_FIXTURE', '')
        if fixture:
            candidate_path = Path(fixture)
            raw_bytes = candidate_path.read_bytes(); before_hash = hashlib.sha256(raw_bytes).hexdigest()
            raw = json.loads(raw_bytes); fixture_design = Design.model_validate(raw.get('design', raw))
            inspection = build_electrical_readiness(fixture_design)
            report['fixture_audit'] = dict(input_sha256=before_hash, counts=inspection.counts,
                issues_by_severity={key: sum(issue.severity == key for issue in inspection.issues) for key in ('blocked', 'pending', 'info')},
                dc_calculation_performed=inspection.dc_calculation_performed, hardware_execution_supported=False)
            check(hashlib.sha256(candidate_path.read_bytes()).hexdigest() == before_hash, 'optional actual project coverage inspection leaves its input bytes unchanged')
        check(not errors, 'owned native electrical workspace workflow completes without application errors')
        report['success'] = True
    except Exception:
        report.update(success=False, error=traceback.format_exc())
    finally:
        watchdog.stop()
        for dialog in reversed(dialogs):
            try: dialog.reject()
            except RuntimeError: pass
        QThreadPool.globalInstance().waitForDone(10000)
        window.document.dirty = False; window.close()
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        app.exit(0 if report.get('success') else 1)
