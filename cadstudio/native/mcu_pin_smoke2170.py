"""Owned native Windows flow for board pin diagrams and transactional wiring."""
from copy import deepcopy
import json
import time
import traceback

from PySide6.QtCore import QPointF, QThreadPool, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def run(app, window, path):
    from ..electrical import ElectricalWorkspace, evaluate_electrical
    from ..models import Design, Part
    from ..mcu_connections import pin_connections
    from .document import read_project
    from .electrical_dialog import ComponentDialog, ElectricalDialog
    from .electrical_schematic import ElectricalSchematicDialog
    from .mcu_pin_dialog import McuBoardDialog, McuPinDialog

    path.parent.mkdir(parents=True, exist_ok=True)
    report = {'checks': [], 'live_ai_calls': 0}
    dialogs = []; errors = []

    def check(condition, title):
        if not condition: raise AssertionError(title)
        report['checks'].append(title)

    def wait(predicate):
        end = time.monotonic() + 60
        while not predicate():
            app.processEvents(); QTest.qWait(10)
            if errors: raise AssertionError(errors[-1])
            if time.monotonic() > end: raise TimeoutError('Owned MCU native flow')
        app.processEvents()

    def apply(data, label):
        window.apply_design(data, label); wait(lambda: not window.busy)

    def target(dialog, identifier, terminal):
        found = next((index for index in range(dialog.target_combo.count())
                      if tuple(dialog.target_combo.itemData(index) or ()) == (identifier, terminal)), -1)
        check(found >= 0, f'target chooser exposes {identifier} {terminal}')
        dialog.target_combo.setCurrentIndex(found)

    def own_modal(callback):
        # This callback only touches the test-created modal child. A callback
        # failure rejects that child so it cannot hang the verification runner.
        def handle():
            child = QApplication.activeModalWidget()
            try: callback(child)
            except Exception:
                errors.append(traceback.format_exc())
                if child is not None: child.reject()
        QTimer.singleShot(60, handle)

    try:
        app.setQuitOnLastWindowClosed(False); window.show_error = errors.append
        check(window.document.design is None, 'native startup remains an empty CAD document')
        sensor_form = ComponentDialog(window, []); dialogs.append(sensor_form)
        sensor_form.kind.setCurrentIndex(sensor_form.kind.findData('load'))
        sensor_form.name.setText('Demo encoder · sample values')
        sensor_form.a.setText('POWER'); sensor_form.b.setText('GND')
        sensor_form.inputs['rated_voltage_v'].setValue(5)
        sensor_form.inputs['rated_current_a'].setValue(.02)
        sensor_form.show(); app.processEvents()
        check(sensor_form.terminal_pins.isVisible(), 'sensor load editor exposes explicit additional signal terminals')
        sensor_form.terminal_pins.setFocus(); QTest.keyClicks(sensor_form.terminal_pins, 'OUT_A=ENCODER_A')
        sensor_form.accept(); sensor = sensor_form.candidate(); sensor_id = sensor['id']
        check(sensor['terminal_pins'] == {'OUT_A': 'ENCODER_A'},
              'typed sensor output terminal is captured independently of its supply and return')
        workspace = ElectricalWorkspace.model_validate(dict(name='Pin wiring review',
            nodes=['GND', 'POWER', 'SIGNAL', 'OLD', 'UNUSED', 'ENCODER_A'], components=[
                dict(id='cell', name='5 V supply', kind='battery', a='POWER', b='GND',
                     voltage_v=5, internal_resistance_ohm=.1),
                dict(id='pi', name='Research Pi 4', kind='mcu', a='POWER', b='GND',
                     catalog_id='rpi4b', rated_voltage_v=5, rated_current_a=.3, part_id='board'),
                dict(id='uno', name='UNO target', kind='mcu', a='POWER', b='GND',
                     catalog_id='arduino_uno_r3', rated_voltage_v=5, rated_current_a=.05),
                dict(id='pull', name='Sensor equivalent', kind='resistor', a='SIGNAL', b='GND',
                     resistance_ohm=1000),
                dict(id='custom', name='Existing custom MCU', kind='mcu', a='POWER', b='GND',
                     rated_voltage_v=5, rated_current_a=.02, signal_pins={'MY_GPIO': 'OLD'}),
                sensor,
            ]))
        original = workspace.model_dump()
        design = Design(parts=[Part(id='board', name='Controller housing', role='electrical',
                                    geometry=dict(kind='cylinder')),
                               Part(id='frame', name='Support', role='structure',
                                    geometry=dict(kind='cylinder'), transform=dict(x=65))],
                        electrical=workspace).model_dump()
        apply(design, 'Original circuit'); actor = window.viewport.actors['board'][0]
        editor = McuPinDialog(window, workspace, design['parts'], 'pi'); dialogs.append(editor)
        editor.show(); app.processEvents()
        check(editor.pin_table.rowCount() == 40, 'Pi 4 connector view lists all 40 J8 pins')
        check(editor.current_mcu().catalog_id == 'rpi4b', 'MCU selector retains the exact board model')
        pos = editor.pin_view.mapFromScene(QPointF(*editor.pin_view.pin_positions['GPIO17']))
        QTest.mouseClick(editor.pin_view.viewport(), Qt.MouseButton.LeftButton, pos=pos); app.processEvents()
        check(editor.selected_pin == 'GPIO17', 'actual mouse click on the pin diagram selects GPIO17')
        check('J8.11' in editor.pin_table.item(editor.pin_table.currentRow(), 0).text(),
              'selected signal shows its physical J8.11 header location')
        protected = next(pin for pin in editor.connections if pin.kind != 'signal')
        editor.select_pin(protected.key)
        check(not editor.connect_button.isEnabled() and not editor.node_button.isEnabled(),
              'physical power and ground pins cannot be assigned as signal outputs')
        editor.select_pin('GPIO17'); target(editor, 'pull', 'a'); editor.connect_button.click()
        check(editor.current_mcu().signal_pins['GPIO17'] == 'SIGNAL',
              'pin to component terminal connection records the actual target net')
        selected = next(pin for pin in editor.connections if pin.key == 'GPIO17')
        check(any(endpoint.component_id == 'pull' and endpoint.terminal == 'a' for endpoint in selected.targets),
              'pin diagram and table resolve the target component name and terminal')
        check(workspace.model_dump() == original and editor.original.model_dump() == original,
              'pin editing is private and preserves the input electrical workspace')
        check('UNUSED' in editor.workspace.nodes, 'unused saved circuit nodes are retained')
        check(editor.disconnect_button.isEnabled(), 'connected pin exposes an enabled disconnect action')
        editor.disconnect_button.click()
        check('GPIO17' not in editor.current_mcu().signal_pins, 'disconnect removes only the selected pin assignment')
        editor.select_pin('GPIO17'); target(editor, 'pull', 'a'); editor.connect_button.click()
        editor.select_pin('GPIO18'); target(editor, sensor_id, 'port:OUT_A'); editor.connect_button.click()
        check(editor.current_mcu().signal_pins['GPIO18'] == 'ENCODER_A'
              and editor.current_mcu().signal_pins['GPIO17'] == 'SIGNAL',
              'MCU signal pin connects to the named encoder output without joining the other GPIO net')
        sensor_pin = next(pin for pin in editor.connections if pin.key == 'GPIO18')
        check(any(endpoint.component_id == sensor_id and endpoint.terminal == 'port:OUT_A'
                  for endpoint in sensor_pin.targets),
              'pin table resolves the chosen encoder output name and component')
        editor.select_pin('GPIO27'); target(editor, 'uno', 'pin:D2'); editor.connect_button.click()
        shared = editor.current_mcu().signal_pins['GPIO27']
        uno = next(component for component in editor.workspace.components if component.id == 'uno')
        check(uno.signal_pins['D2'] == shared and shared in editor.workspace.nodes,
              'two previously unassigned board pins receive the same fresh named net')
        check('3.3' in editor.warnings.toPlainText() and '5' in editor.warnings.toPlainText(),
              'different documented board logic voltages produce a visible wiring warning')
        editor.disconnect_button.click()
        uno = next(component for component in editor.workspace.components if component.id == 'uno')
        check('GPIO27' not in editor.current_mcu().signal_pins and uno.signal_pins['D2'] == shared,
              'disconnecting one MCU does not erase the other MCU connection')
        editor.mcu_combo.setCurrentIndex(editor.mcu_combo.findData('custom')); app.processEvents()
        custom = next(pin for pin in editor.connections if pin.key == 'MY_GPIO')
        check(custom.legacy and custom.node == 'OLD', 'legacy custom board pin remains identified and connected')
        check(any('*' in editor.pin_table.item(row, 0).text() for row in range(editor.pin_table.rowCount())),
              'unverified custom pin names are visually distinguished from official pins')

        def fill_board(child):
            check(isinstance(child, McuBoardDialog), 'Add MCU opens a native model and operating-input dialog')
            check(child.voltage.value() == child.current.value() == 0,
                  'new MCU model starts without invented voltage or consumption')
            child.model_combo.setCurrentIndex(child.model_combo.findData('rpi_pico'))
            child.voltage.setValue(3.3)
            try: child.candidate()
            except ValueError: missing = True
            else: missing = False
            check(missing, 'zero or missing operating current blocks a new board candidate')
            child.current.setValue(.04); child.name.setText('Test Pico'); child.a.setCurrentText('POWER')
            child.part.setCurrentIndex(child.part.findData('board')); child.accept()
        own_modal(fill_board); editor.add_button.click(); app.processEvents()
        if errors: raise AssertionError(errors[-1])
        added = editor.current_mcu()
        check(added.catalog_id == 'rpi_pico' and added.pinout_catalog_id == 'rpi_pico',
              'confirmed Add MCU records the chosen source-backed physical pin model')
        check(added.part_id == 'board' and added.rated_current_a == .04,
              'new MCU keeps the selected CAD link and user-entered operating current')
        check(editor.pin_table.rowCount() == 40, 'Pico diagram shows the 40 supported edge connector pins')
        editor.mcu_combo.setCurrentIndex(editor.mcu_combo.findData('pi')); editor.select_pin('GPIO17')
        editor.resize(1180, 760); app.processEvents(); editor.pin_view.fit()
        editor.grab().save(str(path.with_name('mcu-pin-editor2170.png')))
        editor.apply_button.click(); app.processEvents()
        check(editor.accepted_workspace is not None, 'Save pin connections produces a validated accepted workspace')
        check(workspace.model_dump() == original, 'acceptance still leaves the input workspace immutable')
        updated = deepcopy(window.document.design); updated['electrical'] = editor.accepted_workspace.model_dump()
        apply(updated, 'MCU pin wiring')
        check(window.viewport.actors['board'][0] is actor, 'circuit-only pin edits reuse the existing CAD geometry actors')
        project_path = path.with_suffix('.cad.json'); window.document.write(project_path)
        loaded = read_project(project_path)
        pi = next(component for component in loaded.design.electrical.components if component.id == 'pi')
        check(pi.signal_pins['GPIO17'] == 'SIGNAL' and pi.catalog_id == 'rpi4b',
              'CAD project reopening retains exact MCU model and physical pin connection')
        loaded_sensor = next(component for component in loaded.design.electrical.components if component.id == sensor_id)
        check(pi.signal_pins['GPIO18'] == 'ENCODER_A' and loaded_sensor.terminal_pins == {'OUT_A': 'ENCODER_A'},
              'project round trip preserves encoder named terminal and its selected MCU pin')
        check(len(loaded.design.electrical.components) == 7 and 'UNUSED' in loaded.design.electrical.nodes,
              'project serialization retains added board and unrelated saved nodes')
        window.undo(); wait(lambda: not window.busy)
        check(window.document.design['electrical'] == original, 'undo restores the complete pre-edit electrical workspace')
        window.redo(); wait(lambda: not window.busy)
        check(next(component for component in window.document.design['electrical']['components'] if component['id'] == 'pi')['signal_pins']['GPIO17'] == 'SIGNAL',
              'redo restores saved pin wiring without changing solid geometry')

        accepted = editor.accepted_workspace
        result = evaluate_electrical(accepted)
        schematic = ElectricalSchematicDialog(window, accepted, result, design['parts'], view_mode='symbols'); dialogs.append(schematic)
        schematic.show(); app.processEvents()
        schematic.show_pin_details(); app.processEvents()
        schematic.mcu_combo.setCurrentIndex(schematic.mcu_combo.findData('pi')); app.processEvents()
        check(len(schematic.pin_view.pin_items) == 40,
              'separate circuit schematic includes the selected board physical pin pane')
        check(schematic.branch_layout['pi']['signals']['GPIO17']['node'] == 'SIGNAL',
              'schematic branch follows the saved MCU signal net')
        gpio17 = schematic.branch_layout['pi']['signals']['GPIO17']
        gpio18 = schematic.branch_layout['pi']['signals']['GPIO18']
        check(gpio18['node'] == 'ENCODER_A' and gpio18['connected'] is True,
              'encoder output target is found by passive MCU continuity review')
        check((gpio17['origin_x'],gpio17['origin_y']) != (gpio18['origin_x'],gpio18['origin_y']) and
              gpio17['node'] != gpio18['node'],
              'separate MCU GPIO nets use independent physical pads without a shared signal stem')
        check(schematic.branch_layout[sensor_id]['signals']['OUT_A']['node'] == 'ENCODER_A',
              'schematic displays the actual sensor output terminal apart from its power branch')
        drawn_text=' '.join([*(item.toPlainText() for item in schematic.scene.items() if hasattr(item, 'toPlainText')),
                             *(port.label for item in schematic.component_items.values() for port in item.ports.values())])
        check('J8.11' in drawn_text,
              'schematic signal label includes the physical header pin location')
        before = accepted.model_dump()
        def edit_schematic_pin(child):
            check(isinstance(child, McuPinDialog), 'clicking a schematic pin opens its native pin editor')
            check(child.selected_pin == 'GPIO22', 'schematic click forwards the selected physical pin to editor')
            target(child, 'pull', 'a'); child.connect_button.click(); child.apply_button.click()
        own_modal(edit_schematic_pin)
        point = schematic.pin_view.mapFromScene(QPointF(*schematic.pin_view.pin_positions['GPIO22']))
        QTest.mouseClick(schematic.pin_view.viewport(), Qt.MouseButton.LeftButton, pos=point); app.processEvents()
        if errors: raise AssertionError(errors[-1])
        check(schematic.workspace_changed and schematic.apply_button.isEnabled(),
              'schematic exposes a save action only after a confirmed pin change')
        check(next(component for component in schematic.workspace.components if component.id == 'pi').signal_pins['GPIO22'] == 'SIGNAL',
              'schematic regenerates the updated connection diagram')
        check(accepted.model_dump() == before, 'schematic edits do not mutate its input circuit')
        schematic.grab().save(str(path.with_name('mcu-pin-schematic2170.png')))
        schematic.reject()
        check(schematic.accepted_workspace is None, 'canceling the schematic discards its uncommitted circuit changes')
        electrical = ElectricalDialog(window, window.document.design); dialogs.append(electrical)
        check(electrical.mcu_pin_button.isEnabled(), 'electrical workbench directly exposes MCU selection and pin editing')
        check(set(window.viewport.actors) == {'board', 'frame'}, 'MCU wiring keeps all original CAD bodies available')
        check(not window.result['stats']['collisions'], 'CAD sample bodies remain free of solid interference')
        language = getattr(app, 'cad_language', None)
        if language:
            previous = language.language; language.set_language('en', persist=False)
            english_editor = McuPinDialog(window, accepted, design['parts'], 'pi'); dialogs.append(english_editor)
            english_editor.show(); app.processEvents()
            check('pin' in english_editor.windowTitle().lower() and 'Choose' in english_editor.target_combo.itemText(0),
                  'English mode exposes a readable board pin workflow')
            english_editor.grab().save(str(path.with_name('mcu-pin-english2170.png')))
            english_editor.reject(); language.set_language(previous, persist=False)
        check(not errors, 'no native application or electrical worker errors')
        report['success'] = True
    except Exception:
        report.update(success=False, error=traceback.format_exc())
    finally:
        for dialog in reversed(dialogs): dialog.reject()
        QThreadPool.globalInstance().waitForDone(10000)
        window.document.dirty = False; window.close()
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        app.exit(0 if report.get('success') else 1)
