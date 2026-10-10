"""Owned native G474 connector/persistence smoke; no network or firmware."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import marshal
import os
from pathlib import Path
import sys
import time
import traceback

from PySide6.QtCore import QPointF, QThreadPool, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QDialogButtonBox, QPushButton


NEW_PINS = ('PA11', 'PA12', 'PB10', 'PB11', 'PB12', 'PB8', 'PB9', 'PC6',
            'PA8', 'PA9', 'PC0', 'PC1', 'PC2', 'PC3', 'PB0', 'PB1')
LEGACY_PINS = ('PA5', 'PA6', 'PA7', 'PB6', 'PC7', 'PB5')


def fixture():
    """Every node is used by real wire branches with physical endpoint refs."""
    from ..circuit_connections import add_schematic_wire
    from ..electrical_registration import register_part, registration_for_part
    from ..models import Design, Part

    design = Design(name='Owned synthetic G474 connector validation', parts=[
        Part(id=key, name=key + ' synthetic CAD envelope', role='electrical',
             geometry=dict(kind='plate', length=45, width=25, thickness=3, hole_count=0),
             transform=dict(x=index * 90))
        for index, key in enumerate(('board', 'harness_left', 'harness_right'))],
        electrical=dict(name='Owned passive physical wiring', nodes=['GND', 'POWER'], components=[]))
    for side in ('left', 'right'):
        design = register_part(design, 'harness_' + side, dict(name='Synthetic ' + side + ' harness',
            kind='load', analysis_enabled=False, a='POWER', b='GND',
            terminal_pins={f'P{i:02d}': f'{side.upper()}_{i:02d}' for i in range(64)}))
    design = register_part(design, 'board', dict(catalog_id='st_nucleo_g474re',
        name='Owned registered NUCLEO-G474RE', analysis_enabled=False, a='POWER', b='GND'))
    ids = {key: registration_for_part(design, key).id
           for key in ('board', 'harness_left', 'harness_right')}

    def wire(source, terminal, target, other, name):
        design.electrical = add_schematic_wire(design.electrical, ids[source], terminal,
            ids[target], other, name=name, length_mm=100, cross_section_mm2=.25,
            wire_color='#2765CA', analysis_enabled=False)

    for i in range(64):
        wire('harness_left', f'port:P{i:02d}', 'harness_right', f'port:P{i:02d}',
             f'Owned physical harness branch {i:02d}')
    wire('board', 'a', 'harness_left', 'a', 'Owned abstract supply branch')
    wire('board', 'b', 'harness_left', 'b', 'Owned abstract return branch')
    for i, pin in enumerate((*LEGACY_PINS, *NEW_PINS)):
        wire('board', 'pin:' + pin, 'harness_left', f'port:P{i:02d}', 'Owned GPIO wire ' + pin)
    return Design.model_validate(design.model_dump()), ids


def run(app, window, output):
    from .. import __version__, board_pins, circuit_connections, electrical, mcu_connections
    from ..electrical import ElectricalWorkspace
    from . import mcu_pin_dialog
    from .document import Document, read_project
    from .mcu_pin_dialog import McuBoardDialog, McuPinDialog

    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(success=False, phase='running', version=__version__,
        frozen=bool(getattr(sys, 'frozen', False)), started_utc=datetime.now(timezone.utc).isoformat(),
        synthetic_only=True, live_ai_calls=0, hardware_calls=0, generated_code_executed=False,
        model_refresh_disabled=True, checks=[], screenshots=[], module_identity={},
        scope_note='Native GPIO table/diagram and project persistence only; synthetic CAD envelopes do not validate board dimensions, electronics or firmware.')
    errors = []
    dialogs = []
    original_show_error = window.show_error
    last_progress = [time.monotonic()]

    def write():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    def check(value, title):
        if not value:
            raise AssertionError(title)
        report['checks'].append(title)
        last_progress[0] = time.monotonic()
        write()

    def wait(predicate, title, seconds=45):
        deadline = time.monotonic() + seconds
        while not predicate():
            app.processEvents()
            QTest.qWait(10)
            if errors:
                raise AssertionError(errors[-1])
            if time.monotonic() >= deadline:
                raise TimeoutError(title)
        app.processEvents()
        if errors:
            raise AssertionError(errors[-1])

    def shot(widget, name):
        target = output.with_name(output.stem + '-' + name + '.png')
        check(widget.grab().save(str(target)), 'Native screenshot saved: ' + name)
        report['screenshots'].append(str(target))
        write()

    def modal(callback, opener, expected=McuPinDialog):
        state = {'done': False}
        deadline = time.monotonic() + 12

        def handle():
            child = QApplication.activeModalWidget()
            if not isinstance(child, expected) or not child.isVisible():
                if time.monotonic() < deadline:
                    QTimer.singleShot(20, handle)
                    return
                errors.append('Expected owned modal did not open: ' + expected.__name__)
                state['done'] = True
                if child is not None:
                    child.reject()
                return
            dialogs.append(child)
            try:
                callback(child)
            except Exception:
                errors.append(traceback.format_exc())
                target = output.with_name(output.stem + '-failed-dialog.png')
                if child.grab().save(str(target)):
                    report['screenshots'].append(str(target))
                child.reject()
            finally:
                state['done'] = True

        QTimer.singleShot(30, handle)
        opener()
        wait(lambda: state['done'], 'Owned native modal did not complete')

    def rename_board(dialog, name):
        def edit(child):
            check(child.model_combo.currentData() == 'st_nucleo_g474re', 'Nested editor keeps exact G474 model')
            check(not child.model_combo.isEnabled(), 'Registered physical board cannot silently change product')
            child.name.selectAll()
            QTest.keyClicks(child.name, name)
            controls = child.findChild(QDialogButtonBox)
            check(controls is not None, 'Actual board editor exposes native confirmation controls')
            QTest.mouseClick(controls.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton)
        modal(edit, lambda: QTest.mouseClick(dialog.edit_button, Qt.MouseButton.LeftButton), McuBoardDialog)
        check(dialog.current_mcu().name == name, 'Nested name edit changes only the private dialog workspace')

    def inspect_pins(dialog):
        check(dialog.current_mcu().id == ids['board'], 'Native MCU selector follows registered CAD board')
        check(dialog.pin_table.rowCount() == 32, 'Expanded selected G474 connector view contains 32 rows')
        check(set(NEW_PINS) <= set(dialog.pin_view.pin_items), 'Diagram includes all 16 canonical new GPIOs')
        for index, key in enumerate(NEW_PINS):
            row = next(i for i, pin in enumerate(dialog.connections) if pin.key == key)
            if index % 2:
                dialog.pin_table.scrollToItem(dialog.pin_table.item(row, 0))
                app.processEvents()
                rect = dialog.pin_table.visualItemRect(dialog.pin_table.item(row, 0))
                QTest.mouseClick(dialog.pin_table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
            else:
                dialog.pin_view.fit()
                app.processEvents()
                QTest.qWait(30)
                point = dialog.pin_view.mapFromScene(QPointF(*dialog.pin_view.pin_positions[key]))
                hits = dialog.pin_view.items(point)
                report.setdefault('diagram_hit_checks', []).append(dict(pin=key,
                    viewport_x=point.x(), viewport_y=point.y(), selected_before=dialog.selected_pin,
                    top_item_type=type(hits[0]).__name__ if hits else None,
                    item_keys_in_paint_order=[item.data(0) for item in hits]))
                check(dialog.pin_view.viewport().rect().contains(point) and any(item.data(0) == key for item in hits),
                      'Requested diagram centre hits its rendered physical pin: ' + key)
                if index == 0:
                    shot(dialog, 'before-first-diagram-click')
                QTest.mouseClick(dialog.pin_view.viewport(), Qt.MouseButton.LeftButton, pos=point)
            app.processEvents()
            pin = next(pin for pin in dialog.connections if pin.key == key)
            check(dialog.selected_pin == key and dialog.pin_table.currentRow() == row,
                  'Actual table/diagram interaction selects ' + key)
            check(not pin.legacy and pin.node is not None and dialog.connect_button.isEnabled(),
                  'Official selected signal is connected and editable: ' + key)
            branch = next(wire for wire in wires if any(endpoint.component_id == ids['board']
                          and endpoint.terminal == 'pin:' + key for endpoint in wire.wire_endpoints))
            check(any(target.component_id == branch.id for target in pin.targets)
                  and any(endpoint.component_id == ids['harness_left'] for endpoint in branch.wire_endpoints),
                  'Pin table resolves the physical wire to its actual harness endpoint: ' + key)
            check('CN' in dialog.pin_table.item(row, 0).text(), 'Physical connector label is visible: ' + key)
        protected = next(pin for pin in dialog.connections if pin.kind != 'signal')
        dialog.select_pin(protected.key)
        check(not dialog.connect_button.isEnabled() and not dialog.node_button.isEnabled(),
              'Supply/reset/reference rows cannot become signal assignments')
        dialog.select_pin('PA11')
        same = dialog.current_mcu().signal_pins['PA11']
        dialog.node_combo.setCurrentText(same)
        QTest.mouseClick(dialog.node_button, Qt.MouseButton.LeftButton)
        check(dialog.current_mcu().signal_pins['PA11'] == same,
              'Actual same-net assignment preserves the saved physical wire')

    def save_as(target):
        previous = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = lambda *_args, **_kwargs: (str(target), 'Prompt CAD project (*.pcad)')
        try:
            window.actions['save_as'].trigger()
        finally:
            QFileDialog.getSaveFileName = previous
        check(target.is_file() and window.document.path == target, 'Actual MainWindow Save As writes owned project')

    def watchdog_tick():
        if time.monotonic() - last_progress[0] > 60:
            errors.append('Owned G474 native smoke stopped progressing')
            child = QApplication.activeModalWidget()
            if child is not None:
                child.reject()

    watchdog = QTimer(window)
    watchdog.timeout.connect(watchdog_tick)
    watchdog.start(1000)
    try:
        app.setQuitOnLastWindowClosed(False)
        window.show_error = lambda message: errors.append(str(message))
        window.completion_notifier.enabled = False
        check(window.document.design is None, 'Normal private MainWindow starts without a user project')
        expected_profile = output.parent / 'test-profile-g474'
        check(Path(os.environ['CADSTUDIO_DATA_DIR']).resolve() == expected_profile,
              'Native startup is isolated to the smoke-owned profile')
        report['private_profile'] = str(expected_profile)
        report['runtime_node_limit'] = electrical.MAX_ELECTRICAL_NODES
        check(electrical.MAX_ELECTRICAL_NODES == 512, 'Actual imported electrical runtime limit is 512')
        check(circuit_connections.MAX_ELECTRICAL_NODES == mcu_connections.MAX_ELECTRICAL_NODES == 512,
              'Both loaded connection modules share the runtime node limit')
        for module in (electrical, circuit_connections, mcu_connections, board_pins, mcu_pin_dialog, sys.modules[__name__]):
            source = Path(module.__file__).resolve()
            report['module_identity'][module.__name__] = dict(path=str(source),
                file_sha256=sha256(source.read_bytes()).hexdigest() if source.is_file() else None,
                loader=type(module.__loader__).__name__, origin=module.__spec__.origin,
                function_code_sha256={name: sha256(marshal.dumps(value.__code__)).hexdigest()
                    for name, value in vars(module).items()
                    if callable(value) and getattr(value, '__module__', None) == module.__name__
                    and hasattr(value, '__code__')})
        report['runtime_executable'] = sys.executable
        pinout = board_pins.board_pinout('st_nucleo_g474re')
        check(pinout is not None and len(pinout.pins) == 32, 'Actual imported board catalogue has 32 selected rows')
        report['board_pins'] = [dict(key=p.key, label=p.label, kind=p.kind, functions=list(p.functions)) for p in pinout.pins]

        design, ids = fixture()
        workspace = design.electrical
        wires = [c for c in workspace.components if c.kind == 'wire']
        wire_nodes = {node for c in wires for node in (c.a, c.b)}
        check(len(workspace.nodes) > 128 and wire_nodes == set(workspace.nodes),
              'Every node in the >128-node fixture belongs to a physical wire branch')
        check(all(len(c.wire_endpoints) == 2 for c in wires), 'Every synthetic wire retains two physical endpoint references')
        check(all(not c.analysis_enabled for c in workspace.components), 'Unqualified synthetic circuit stays outside DC analysis')
        board = next(c for c in workspace.components if c.id == ids['board'])
        check(board.part_registration and board.catalog_id == board.pinout_catalog_id == 'st_nucleo_g474re',
              'Synthetic MCU is registered to an actual CAD Part with exact G474 identity')
        check(set(board.signal_pins) == set((*LEGACY_PINS, *NEW_PINS)), 'Six legacy and 16 new canonical GPIOs are physically wired')
        for key in NEW_PINS:
            check(any(any(e.component_id == ids['board'] and e.terminal == 'pin:' + key
                          for e in wire.wire_endpoints) for wire in wires), 'Physical wire endpoint names canonical GPIO ' + key)
        report['counts'] = dict(nodes=len(workspace.nodes), wire_used_nodes=len(wire_nodes),
            components=len(workspace.components), wires=len(wires), parts=len(design.parts),
            board_rows=len(pinout.pins), signal_assignments=len(board.signal_pins), new_signal_assignments=len(NEW_PINS))

        original_path = output.with_name(output.stem + '-original.pcad')
        document = Document()
        document.commit(design, 'Owned synthetic G474 pin fixture')
        document.write(original_path)
        original_bytes = original_path.read_bytes()
        report['original_project'] = str(original_path)
        report['original_sha256'] = sha256(original_bytes).hexdigest()
        window.open_project(original_path)
        wait(lambda: not window.busy and window.document.path == original_path, 'Normal MainWindow fixture open')
        check(window.document.design == design.model_dump(), 'MainWindow open preserves every registered body and physical wire')
        before = deepcopy(window.document.project().model_dump(mode='json'))
        actors = {key: id(value[0]) for key, value in window.viewport.actors.items()}

        def cancel(dialog):
            inspect_pins(dialog)
            rename_board(dialog, 'Owned cancelled name')
            check(dialog.workspace.model_dump() != dialog.original.model_dump(), 'Cancellation covers a real private edit')
            shot(dialog, 'cancel-dialog')
            cancel_button = next(button for button in dialog.findChildren(QPushButton)
                                 if button.isVisible() and button.text() in ('취소', 'Cancel'))
            QTest.mouseClick(cancel_button, Qt.MouseButton.LeftButton)
        modal(cancel, window.actions['mcu_pins'].trigger)
        check(window.document.project().model_dump(mode='json') == before and not window.document.dirty,
              'Cancelling actual MainWindow MCU modal preserves full project and history')
        check(original_path.read_bytes() == original_bytes, 'Cancellation preserves original project bytes exactly')

        def accept(dialog):
            inspect_pins(dialog)
            rename_board(dialog, 'Owned accepted G474 name')
            shot(dialog, 'accepted-dialog')
            QTest.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
        modal(accept, window.actions['mcu_pins'].trigger)
        wait(lambda: not window.busy, 'Actual accepted native pin edit')
        current = ElectricalWorkspace.model_validate(window.document.design['electrical'])
        accepted_board = next(c for c in current.components if c.id == ids['board'])
        check(accepted_board.name == 'Owned accepted G474 name' and accepted_board.signal_pins == board.signal_pins,
              'Explicit native acceptance commits name and preserves all 22 physical GPIO wires')
        check({key: id(value[0]) for key, value in window.viewport.actors.items()} == actors,
              'Electrical-only modal acceptance preserves actual CAD actors')
        check(window.document.journal.data['entries'][-1]['context']['tool'] == 'electrical-mcu-pins',
              'Actual MainWindow pin acceptance enters normal operation history')
        saved = output.with_name(output.stem + '-roundtrip.pcad')
        save_as(saved)
        expected = deepcopy(window.document.project().model_dump(mode='json'))
        window.open_project(saved)
        wait(lambda: not window.busy and window.document.path == saved, 'Normal MainWindow roundtrip reopen')
        check(window.document.project().model_dump(mode='json') == expected, 'Actual open/save/reopen preserves full project and history')
        check(read_project(saved).model_dump(mode='json') == expected, 'Saved native bytes validate to the same roundtrip project')
        check(original_path.read_bytes() == original_bytes, 'Separate save/reopen leaves original fixture bytes unchanged')
        check(window.ai_task is None and window.codex_probe_task is None, 'Native flow starts no model or provider task')
        shot(window, 'main-window')
        report['roundtrip_project'] = str(saved)
        report['roundtrip_sha256'] = sha256(saved.read_bytes()).hexdigest()
        from .mechanical_function_dialog import MechanicalFunctionDialog
        mechanical_before = deepcopy(window.document.design)
        mechanical_actors = {key:id(value[0]) for key,value in window.viewport.actors.items()}
        selected_body = mechanical_before['parts'][0]['id']
        window.select_parts([selected_body])
        def purpose(dialog, accepted):
            dialog.function.setCurrentIndex(dialog.function.findData('fastener'))
            shot(dialog, 'mechanical-function-' + ('accepted' if accepted else 'cancelled'))
            QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok if accepted else QDialogButtonBox.StandardButton.Cancel), Qt.MouseButton.LeftButton)
        mechanical_history = deepcopy(window.document.journal.data)
        modal(lambda dialog:purpose(dialog,False), window.actions['mechanical_function'].trigger, MechanicalFunctionDialog)
        check(window.document.design==mechanical_before and window.document.journal.data==mechanical_history, 'Native mechanical function cancellation preserves design and history')
        modal(lambda dialog:purpose(dialog,True), window.actions['mechanical_function'].trigger, MechanicalFunctionDialog)
        wait(lambda:not window.busy, 'Native mechanical function acceptance')
        purpose_design=deepcopy(window.document.design)
        declared=next(part for part in purpose_design['parts'] if part['id']==selected_body)
        check(declared.get('mechanical_function')=='fastener', 'Native explicit acceptance records fastener purpose')
        expected_purpose=deepcopy(mechanical_before)
        next(part for part in expected_purpose['parts'] if part['id']==selected_body)['mechanical_function']='fastener'
        check(purpose_design==expected_purpose, 'Purpose edit preserves all colors, roles, wires, geometry and registrations')
        check({key:id(value[0]) for key,value in window.viewport.actors.items()}==mechanical_actors, 'Purpose metadata change preserves real native CAD actors')
        window.actions['undo'].trigger();wait(lambda:not window.busy, 'Native purpose Undo')
        check(window.document.design==mechanical_before, 'Actual native Undo clears only new mechanical declaration')
        window.actions['redo'].trigger();wait(lambda:not window.busy, 'Native purpose Redo')
        check(window.document.design==purpose_design, 'Actual native Redo restores mechanical declaration')
        purpose_saved=output.with_name(output.stem+'-purpose-roundtrip.pcad')
        save_as(purpose_saved)
        purpose_project=deepcopy(window.document.project().model_dump(mode='json'))
        window.open_project(purpose_saved);wait(lambda:not window.busy and window.document.path==purpose_saved, 'Normal MainWindow purpose reopen')
        check(window.document.project().model_dump(mode='json')==purpose_project, 'Actual native purpose save/reopen preserves full project history')
        check(original_path.read_bytes()==original_bytes, 'Mechanical classification leaves original synthetic input untouched')
        report['mechanical_function_review']=dict(saved_path=str(purpose_saved),sha256=sha256(purpose_saved.read_bytes()).hexdigest(),declared_part=selected_body,scope='Explicit synthetic purpose; not actuator, product or powered operation certification')
        report['success'] = True
        report['phase'] = 'complete'
    except Exception:
        report.update(success=False, phase='failed', error=traceback.format_exc())
    finally:
        watchdog.stop()
        for dialog in reversed(dialogs):
            try:
                dialog.reject()
                dialog.deleteLater()
            except RuntimeError:
                pass
        QThreadPool.globalInstance().waitForDone(10000)
        window.show_error = original_show_error
        window.document.dirty = False
        window.close()
        app.processEvents()
        report['check_count'] = len(report['checks'])
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        write()
        app.exit(0 if report['success'] else 1)
