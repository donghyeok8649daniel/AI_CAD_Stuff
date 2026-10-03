"""Owned native CAD part registration, physical diagram and wiring workflow."""
from copy import deepcopy
import json
import math
import time
import traceback

from PySide6.QtCore import QPointF, QThreadPool, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QTreeWidgetItemIterator


def run(app, window, path):
    from ..electrical import evaluate_electrical
    from ..electrical_registration import registration_for_part, unregister_part
    from ..kernel import build
    from ..models import Design, DraftRequest, Part
    from .cad_tools import execute_plan
    from .document import read_project
    from .electrical_dialog import ComponentDialog
    from .electrical_part_dialog import ElectricalPartDialog
    from .electrical_schematic import ElectricalSchematicDialog

    path.parent.mkdir(parents=True, exist_ok=True)
    report = {'checks': [], 'live_ai_calls': 0}; dialogs = []; errors = []
    last_check = [time.monotonic()]

    def check(condition, title):
        if not condition: raise AssertionError(title)
        report['checks'].append(title)
        last_check[0] = time.monotonic()
        path.write_text(json.dumps(dict(report, success=False, phase='running'), ensure_ascii=False, indent=2), encoding='utf-8')

    def modal_watchdog():
        if time.monotonic() - last_check[0] < 45: return
        child = QApplication.activeModalWidget()
        if child is not None:
            child.grab().save(str(path.with_name('electrical-registration-unexpected-modal2180.png')))
            errors.append('Owned native modal stalled: ' + child.windowTitle())
            child.reject()
    watchdog = QTimer(window); watchdog.timeout.connect(modal_watchdog); watchdog.start(1000)

    def wait(predicate):
        end = time.monotonic() + 60
        while not predicate():
            app.processEvents(); QTest.qWait(10)
            if errors: raise AssertionError(errors[-1])
            if time.monotonic() > end: raise TimeoutError('Owned electrical registration native flow')
        app.processEvents()

    def apply(data, title):
        window.apply_design(data, title); wait(lambda: not window.busy)

    def own_modal(callback, expected_type=ElectricalPartDialog):
        state = {'done': False}
        deadline = time.monotonic() + 10
        def handle():
            child = QApplication.activeModalWidget()
            # Frozen startup/layout can outlast a single-shot delay. Wait for
            # the requested visible child rather than calling a callback on
            # None or on the outer registration dialog of a nested editor.
            if not isinstance(child, expected_type) or not child.isVisible():
                if time.monotonic() < deadline:
                    QTimer.singleShot(20, handle)
                    return
                errors.append('Owned expected modal did not open: ' + expected_type.__name__)
                state['done'] = True
                if child is not None: child.reject()
                return
            try:
                dialogs.append(child)
                callback(child)
            except Exception:
                errors.append(traceback.format_exc())
                if child is not None: child.reject()
            finally: state['done'] = True
        QTimer.singleShot(70, handle)
        return state

    def model(dialog, identifier):
        index = dialog.model_combo.findData(identifier)
        check(index >= 0, 'actual product chooser exposes ' + identifier)
        dialog.model_combo.setCurrentIndex(index)

    def target(dialog, identifier, terminal):
        index = next((i for i in range(dialog.target.count())
                      if tuple(dialog.target.itemData(i) or ()) == (identifier, terminal)), -1)
        check(index >= 0, f'endpoint chooser exposes {identifier} {terminal}')
        dialog.target.setCurrentIndex(index)

    def click_terminal(dialog, key):
        dialog.diagram.fit(); app.processEvents()
        point = dialog.diagram.mapFromScene(QPointF(*dialog.diagram.pin_positions[key]))
        QTest.mouseClick(dialog.diagram.viewport(), Qt.MouseButton.LeftButton, pos=point)
        app.processEvents(); check(dialog.selected_terminal == key, 'physical diagram click selects ' + key)

    def tree_feature(identifier):
        iterator = QTreeWidgetItemIterator(window.tree)
        while iterator.value():
            item = iterator.value(); data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] == 'electrical_feature' and data[1] == identifier: return item
            iterator += 1
        return None

    try:
        app.setQuitOnLastWindowClosed(False); window.show_error = errors.append
        check(window.document.design is None, 'owned native startup has an empty CAD document')
        original = Design(parts=[Part(id=identifier, name=identifier + ' body', color='#123456',
            geometry=dict(kind='cylinder', diameter=35, height=12, bore_diameter=0),
            transform=dict(x=index * 70)) for index, identifier in enumerate(('board', 'sensor', 'motor'))],
            part_groups=[dict(id='mixed', name='Original CAD group', part_ids=['board', 'sensor'])],
            electrical=dict(name='Existing supply', nodes=['GND', 'POWER', 'UNUSED'], components=[
                dict(id='cell', name='Sample 5 V source', kind='battery', a='POWER', b='GND',
                     voltage_v=5, internal_resistance_ohm=.1)])).model_dump()
        apply(original, 'Original CAD bodies'); actors = {key: value[0] for key, value in window.viewport.actors.items()}
        window.select_parts(['board']); app.processEvents()
        entry = window.findChild(QPushButton, 'partElectricalRegister')
        check(entry is not None and entry.isVisible(), 'selected CAD part exposes a direct registration property button')
        check('electrical_register' in window.actions, 'engineering and assembly expose the electrical registration action')

        def register_board(child):
            check(isinstance(child, ElectricalPartDialog), 'part property button opens the native registration editor')
            check(child.current_part_id() == 'board', 'registration editor follows the selected CAD part')
            check(not child.apply_button.isEnabled(), 'unchanged registration editor starts with Save disabled')
            model(child, 'rpi4b'); child.name.setText('Research Raspberry Pi 4'); child.register_button.click()
            component = child.component()
            check(component.part_registration and component.part_id == 'board', 'MCU model becomes a persistent CAD-linked electrical feature')
            check(not component.analysis_enabled and component.rated_current_a == 0,
                  'unknown consumption remains pending rather than an invented DC load')
            check(component.rated_voltage_v == 5 and component.source_url.startswith('https://'),
                  'documented Pi supply identity and official source remain attached')
            check(len(child.diagram.pin_items) == 40, 'registered Pi 4 diagram contains all 40 physical J8 pins')
            check(child.draft.parts[0].color == '#123456', 'registration preserves the existing custom part color by default')
            check(child.draft.part_groups == Design.model_validate(original).part_groups,
                  'registering an existing body preserves its original group')
            check('DC' in child.status.text(), 'pending analysis state is visible before saving')
            child.resize(1130, 800); app.processEvents(); child.diagram.fit()
            child.grab().save(str(path.with_name('electrical-registration-board2180.png')))
            child.apply_button.click()
        own_modal(register_board); QTest.mouseClick(entry, Qt.MouseButton.LeftButton); wait(lambda: not window.busy)
        if errors: raise AssertionError(errors[-1])
        registered_board = registration_for_part(window.document.design, 'board')
        check(registered_board.catalog_id == 'rpi4b', 'native Save commits the exact selected MCU model')
        check(tree_feature('board') is not None, 'CAD tree shows the attached electrical feature under its actual body')
        check(window.viewport.actors['board'][0] is actors['board'], 'nongeometric registration reuses the existing CAD actor')
        check(not window.document.design['parts'][0]['features'], 'electrical registration does not enter the geometric feature chain')

        before = deepcopy(window.document.design)
        def cancel_rename(child):
            check(child.component().id == registered_board.id, 'reopening an attached feature retains its stable identity')
            viewport = child.diagram.viewport().rect()
            visible_pins = [child.diagram.mapFromScene(item.sceneBoundingRect()).boundingRect()
                            for item in child.diagram.pin_items.values()]
            check(len(visible_pins) == 40 and all(viewport.contains(rectangle) for rectangle in visible_pins),
                  'reopened physical board pins fit inside the visible viewport without manual zoom')
            check(min(rectangle.height() for rectangle in visible_pins) >= 5
                  and max(rectangle.bottom() for rectangle in visible_pins)
                    - min(rectangle.top() for rectangle in visible_pins) >= viewport.height() * .5,
                  'reopened board diagram automatically uses a readable pin scale')
            child.grab().save(str(path.with_name('electrical-registration-reopen2180.png')))
            child.name.setText('Discarded name'); child.register_button.click(); child.reject()
        item = tree_feature('board'); window.tree.scrollToItem(item); app.processEvents()
        QTest.mouseClick(window.tree.viewport(), Qt.MouseButton.LeftButton,
                         pos=window.tree.visualItemRect(item).center()); app.processEvents()
        state = own_modal(cancel_rename)
        QTest.mouseDClick(window.tree.viewport(), Qt.MouseButton.LeftButton,
                         pos=window.tree.visualItemRect(item).center()); wait(lambda: state['done'])
        if errors: raise AssertionError(errors[-1])
        check(window.document.design == before, 'double-click feature editing and Cancel preserve the complete CAD document')

        def register_sensor(child):
            model(child, 'ams_as5600_asot'); child.register_button.click()
            check(child.component().kind == 'load', 'exact sensor model selects its electronic-product kind')
            check(set(child.diagram.pin_items) == {'VDD5V', 'VDD3V3', 'OUT', 'GND', 'PGO', 'SDA', 'SCL', 'DIR'},
                  'AS5600 diagram shows the eight exact SOIC-8 terminals')
            click_terminal(child, 'OUT'); target(child, 'board', 'pin:GPIO17'); child.connect_button.click()
            sensor = child.component(); board = registration_for_part(child.draft, 'board')
            check(sensor.terminal_pins['OUT'] == board.signal_pins['GPIO17'], 'sensor physical OUT and selected MCU GPIO share the saved signal net')
            check('VDD5V' not in sensor.terminal_pins and 'VDD3V3' not in sensor.terminal_pins,
                  'sensor signal connection does not silently connect or merge its distinct voltage rails')
            child.grab().save(str(path.with_name('electrical-registration-sensor2180.png')))
            child.apply_button.click()
        own_modal(register_sensor); window.electrical_part_dialog('sensor'); wait(lambda: not window.busy)
        if errors: raise AssertionError(errors[-1])
        check(window.viewport.actors['sensor'][0] is actors['sensor'], 'exact product registration preserves sensor solid and viewport actor')

        def register_motor(child):
            model(child, 'pololu_4755'); child.default_color.setChecked(True); child.register_button.click()
            check(len(child.diagram.pin_items) == 6, 'exact motor and encoder diagram shows all six documented lead functions')
            click_terminal(child, 'ENCODER_A'); target(child, 'board', 'pin:GPIO18'); child.connect_button.click()
            check(child.draft.parts[2].color == '#FFD400', 'explicit default-color choice applies the electrical yellow only to that body')
            check(child.draft.parts[0].color == child.draft.parts[1].color == '#123456', 'other original custom part colors survive the optional yellow choice')
            def check_operating(operating):
                check(isinstance(operating, ComponentDialog), 'Edit ratings opens the native operating-input dialog')
                check(not operating.analysis_enabled.isChecked(), 'pending model stays excluded when reopening operating-input controls')
                check(operating.inputs['rated_current_a'].value() == 0, 'model registration does not invent motor running current')
                operating.reject()
            own_modal(check_operating, ComponentDialog); child.power_button.click(); app.processEvents()
            child.apply_button.click()
        own_modal(register_motor); window.electrical_part_dialog('motor'); wait(lambda: not window.busy)
        if errors: raise AssertionError(errors[-1])
        final = deepcopy(window.document.design); board = registration_for_part(final, 'board')
        motor = registration_for_part(final, 'motor'); sensor = registration_for_part(final, 'sensor')
        check(board.signal_pins['GPIO17'] == sensor.terminal_pins['OUT'] and board.signal_pins['GPIO18'] == motor.terminal_pins['ENCODER_A'],
              'two independent real product outputs retain their distinct selected MCU pins')
        check(board.signal_pins['GPIO17'] != board.signal_pins['GPIO18'], 'independent sensor and encoder signals do not short into one net')
        review = ElectricalPartDialog(window, final, 'motor'); dialogs.append(review)
        review.show(); app.processEvents()
        check(review.warnings.isVisible() and '3.5' in review.warnings.toPlainText() and '3.3' in review.warnings.toPlainText(),
              'product connection review warns about separate encoder supply and MCU signal input voltage')
        review.reject()
        check('UNUSED' in final['electrical']['nodes'], 'unrelated stored circuit nodes survive registration and pin wiring')
        check(all(tree_feature(identifier) is not None for identifier in ('board', 'sensor', 'motor')),
              'all three CAD bodies expose their own persistent electrical feature')
        check(not window.result['stats']['collisions'], 'registered sample CAD bodies remain free of geometric interference')
        calculation = evaluate_electrical(Design.model_validate(final).electrical)
        pending = [branch for branch in calculation.components if branch.part_id]
        check(len(pending) == 3 and all(not branch.analysis_enabled and branch.resistance_ohm is None for branch in pending),
              'DC results explicitly mark every unconfirmed device as excluded without an equivalent load')
        check(all(branch.voltage_drop_v is None for branch in pending), 'pending devices do not display an evaluated voltage drop')
        saved = path.with_suffix('.cad.json'); window.document.write(saved); loaded = read_project(saved)
        check(loaded.design.model_dump() == final, 'CAD project round trip preserves exact model identity, physical connections and groups')
        check(loaded.history is not None and len(loaded.history.entries) >= 4, 'saved project includes each native registration transaction in history')
        window.undo(); wait(lambda: not window.busy)
        check(registration_for_part(window.document.design, 'motor') is None, 'Undo removes the latest electrical feature while retaining its CAD body')
        check(len(window.document.design['parts']) == 3, 'Undo registration preserves all original solid bodies')
        window.redo(); wait(lambda: not window.busy)
        check(window.document.design == final, 'Redo restores the complete model, color and pin wiring transaction')

        schematic = ElectricalSchematicDialog(window, loaded.design.electrical, calculation,
                                              loaded.design.model_dump()['parts']); dialogs.append(schematic)
        schematic.show(); app.processEvents()
        check(schematic.branch_layout[board.id]['signals']['GPIO17']['node'] == sensor.terminal_pins['OUT'],
              'separate schematic resolves the actual registered sensor to its MCU pin')
        check(schematic.branch_layout[motor.id]['signals']['ENCODER_A']['node'] == board.signal_pins['GPIO18'],
              'separate schematic resolves the motor encoder lead independently of motor supply')
        schematic.grab().save(str(path.with_name('electrical-registration-schematic2180.png'))); schematic.reject()

        # Exercise common AI tools without making any network/model calls.
        plan = dict(name='CAD electronics', summary='Register existing bodies', assumptions=[], actions=[
            dict(tool='electrical_register', target='board', args=dict(catalog_id='arduino_uno_r3')),
            dict(tool='electrical_register', target='sensor', args=dict(catalog_id='pololu_2130')),
            dict(tool='electrical_connect', target='board', args=dict(pin='D5', target_part_id='sensor', target_terminal='port:AIN1'))])
        ai = execute_plan(json.dumps(plan), DraftRequest(prompt='Register the existing controller and driver', current=original))
        ai_board = registration_for_part(ai.design, 'board'); ai_driver = registration_for_part(ai.design, 'sensor')
        check(ai_board.signal_pins['D5'] == ai_driver.terminal_pins['AIN1'], 'AI registration and wiring use the same exact model and terminal contract as native editing')
        check(len(ai.journal_steps) == 3 and all(action['validated'] for action in ai.tool_actions), 'AI electrical transactions preserve individually validated history steps')
        check([shape.Volume() for shape in build(ai.design)] == [shape.Volume() for shape in build(Design.model_validate(original))],
              'AI model registration changes no solid volume')
        hole_plan = dict(name='Drilled controller body', summary='Drill after registration', assumptions=[], actions=[
            dict(tool='hole', target='board', args=dict(face='+Z', diameter=4))])
        drilled = execute_plan(json.dumps(hole_plan), DraftRequest(prompt='Drill the registered body', current=ai.design))
        expected = math.pi * (17.5 ** 2 - 2 ** 2) * 12
        check(abs(build(drilled.design)[0].Volume() - expected) < .001, 'geometric hole editing still resolves the original support after electrical registration')
        check(registration_for_part(drilled.design, 'board').signal_pins['D5'] == ai_board.signal_pins['D5'],
              'normal solid editing preserves the registered MCU feature and wiring')
        removed = unregister_part(final, 'sensor')
        check(registration_for_part(removed, 'sensor') is None and len(removed.parts) == 3, 'unregistering a device removes its circuit identity while keeping its CAD solid')
        check(registration_for_part(removed, 'board').signal_pins == board.signal_pins, 'unregistering a product does not erase the other board pin assignments')

        language = getattr(app, 'cad_language', None)
        if language:
            previous = language.language; language.set_language('en', persist=False)
            editor = ElectricalPartDialog(window, final, 'motor'); dialogs.append(editor)
            editor.show(); app.processEvents(); editor.diagram.fit()
            check('electrical registration' in editor.windowTitle().lower() and 'Ratings pending' in editor.status.text(),
                  'English mode shows a readable registration workflow and truthful pending state')
            check('Connect terminal' == editor.connect_button.text(), 'English diagram connection controls use clear terminal wording')
            check('encoder' in editor.warnings.toPlainText() and '3.3' in editor.warnings.toPlainText(),
                  'English product wiring review retains actual encoder and GPIO voltage conditions')
            editor.grab().save(str(path.with_name('electrical-registration-english2180.png')))
            editor.reject(); language.set_language(previous, persist=False)
        check(not errors, 'owned native registration workflow completes without application or worker errors')
        report['success'] = True
    except Exception:
        report.update(success=False, error=traceback.format_exc())
    finally:
        watchdog.stop()
        for dialog in reversed(dialogs): dialog.reject()
        QThreadPool.globalInstance().waitForDone(10000)
        window.document.dirty = False; window.close()
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        app.exit(0 if report.get('success') else 1)
