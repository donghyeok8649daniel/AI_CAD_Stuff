"""Native board selection, physical pin click and transactional net editing."""
from copy import deepcopy

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from cadstudio.electrical import ElectricalWorkspace
from cadstudio.native.mcu_pin_dialog import McuBoardDialog, McuPinDialog


@pytest.fixture(scope='module')
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    yield instance
    instance.processEvents()


def circuit():
    return ElectricalWorkspace.model_validate(dict(name='Pin review',
        nodes=['GND', 'POWER', 'SIGNAL', 'UNUSED', 'OLD'], components=[
            dict(id='battery', name='Supply', kind='battery', a='POWER', b='GND',
                 voltage_v=5, internal_resistance_ohm=.1),
            dict(id='pi', name='Research Pi', kind='mcu', a='POWER', b='GND',
                 catalog_id='rpi4b', rated_voltage_v=5, rated_current_a=.3, part_id='board'),
            dict(id='uno', name='UNO target', kind='mcu', a='POWER', b='GND',
                 catalog_id='arduino_uno_r3', rated_voltage_v=5, rated_current_a=.05),
            dict(id='pull', name='Sensor equivalent', kind='resistor', a='SIGNAL', b='GND',
                 resistance_ohm=1000),
            dict(id='custom', name='Existing board', kind='mcu', a='POWER', b='GND',
                 rated_voltage_v=5, rated_current_a=.02, signal_pins={'MY_GPIO': 'OLD'}),
        ]))


def select_target(dialog, component_id, terminal):
    # Qt may round-trip a QVariant sequence as a list rather than a tuple.
    index = next((index for index in range(dialog.target_combo.count())
                  if tuple(dialog.target_combo.itemData(index) or ()) == (component_id, terminal)), -1)
    assert index >= 0, (component_id, terminal)
    dialog.target_combo.setCurrentIndex(index)


def test_new_board_leaves_operating_numbers_blank_and_requires_positive_current(app):
    dialog = McuBoardDialog(None, circuit())
    try:
        assert dialog.voltage.value() == dialog.current.value() == 0
        dialog.model_combo.setCurrentIndex(dialog.model_combo.findData('rpi4b'))
        assert dialog.voltage.value() == dialog.current.value() == 0
        dialog.voltage.setValue(5)
        with pytest.raises(ValueError, match='전류'):
            dialog.candidate()
        dialog.current.setValue(.25)
        candidate = dialog.candidate()
        assert candidate.catalog_id == candidate.pinout_catalog_id == 'rpi4b'
        assert candidate.rated_current_a == .25
        assert candidate.source_url.startswith('https://')
    finally:
        dialog.reject()


def test_exact_model_and_linked_cad_part_are_preserved_in_candidate(app):
    original = circuit()
    pi = next(component for component in original.components if component.id == 'pi')
    dialog = McuBoardDialog(None, original, [dict(id='board', name='Controller housing')], pi)
    try:
        candidate = dialog.candidate()
        assert candidate.id == pi.id and candidate.part_id == 'board'
        assert candidate.catalog_id == 'rpi4b' and candidate.rated_voltage_v == 5
        assert candidate.rated_current_a == .3
        assert original == circuit()
    finally:
        dialog.reject()


def test_clicking_a_physical_gpio_updates_the_selected_table_pin(app):
    dialog = McuPinDialog(None, circuit(), mcu_id='pi')
    try:
        dialog.show(); app.processEvents()
        assert dialog.pin_table.rowCount() == 40
        point = dialog.pin_view.mapFromScene(QPointF(*dialog.pin_view.pin_positions['GPIO17']))
        QTest.mouseClick(dialog.pin_view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        app.processEvents()
        assert dialog.selected_pin == 'GPIO17'
        row = dialog.pin_table.currentRow()
        assert dialog.pin_table.item(row, 0).data(Qt.ItemDataRole.UserRole) == 'GPIO17'
        assert 'J8.11' in dialog.pin_table.item(row, 0).text()
        assert dialog.connect_button.isEnabled()
    finally:
        dialog.reject()


def test_power_ground_or_reset_pins_cannot_be_used_as_signal_outputs(app):
    dialog = McuPinDialog(None, circuit(), mcu_id='pi')
    try:
        protected = next(pin for pin in dialog.connections if pin.kind != 'signal')
        dialog.select_pin(protected.key)
        assert not dialog.connect_button.isEnabled()
        assert not dialog.node_button.isEnabled()
        assert dialog.current_mcu().signal_pins == {}
    finally:
        dialog.reject()


def test_target_terminal_connection_changes_only_private_workspace_and_cancel_preserves_input(app):
    original = circuit(); before = original.model_dump()
    dialog = McuPinDialog(None, original, mcu_id='pi')
    try:
        dialog.select_pin('GPIO17'); select_target(dialog, 'pull', 'a')
        dialog.connect_button.click()
        assert dialog.current_mcu().signal_pins['GPIO17'] == 'SIGNAL'
        connection = next(pin for pin in dialog.connections if pin.key == 'GPIO17')
        assert any(target.component_id == 'pull' and target.terminal == 'a' for target in connection.targets)
        assert 'UNUSED' in dialog.workspace.nodes
        assert original.model_dump() == before
        assert dialog.original.model_dump() == before
        dialog.reject()
        assert dialog.accepted_workspace is None and original.model_dump() == before
    finally:
        dialog.reject()


def test_cross_board_unassigned_pins_share_a_named_net_and_disconnect_preserves_target(app):
    dialog = McuPinDialog(None, circuit(), mcu_id='pi')
    try:
        dialog.select_pin('GPIO27'); select_target(dialog, 'uno', 'pin:D2')
        dialog.connect_button.click()
        node = dialog.current_mcu().signal_pins['GPIO27']
        uno = next(component for component in dialog.workspace.components if component.id == 'uno')
        assert uno.signal_pins['D2'] == node and node in dialog.workspace.nodes
        dialog.disconnect_button.click()
        assert 'GPIO27' not in dialog.current_mcu().signal_pins
        assert uno.signal_pins['D2'] == node and node in dialog.workspace.nodes
    finally:
        dialog.reject()


def test_legacy_custom_pin_remains_visible_and_accept_preserves_unrelated_circuit(app):
    original = circuit(); before = original.model_dump()
    dialog = McuPinDialog(None, original, mcu_id='custom')
    try:
        assert dialog.current_mcu().signal_pins == {'MY_GPIO': 'OLD'}
        pin = next(pin for pin in dialog.connections if pin.key == 'MY_GPIO')
        assert pin.legacy and pin.node == 'OLD'
        assert any('*' in dialog.pin_table.item(row, 0).text() for row in range(dialog.pin_table.rowCount()))
        dialog.accept()
        assert dialog.accepted_workspace.model_dump() == before
        assert original.model_dump() == before
    finally:
        dialog.reject()


def test_model_change_requires_explicit_confirmation_before_discarding_pin_assignments(app):
    workspace = circuit(); pi = next(component for component in workspace.components if component.id == 'pi')
    pi = pi.model_copy(update={'signal_pins': {'GPIO17': 'SIGNAL'}})
    dialog = McuBoardDialog(None, workspace, existing=pi)
    try:
        dialog.model_combo.setCurrentIndex(dialog.model_combo.findData('arduino_uno_r3'))
        with pytest.raises(ValueError, match='확인'):
            dialog.candidate()
        assert pi.signal_pins == {'GPIO17': 'SIGNAL'}
        dialog.dropped_confirmed = True
        candidate = dialog.candidate()
        assert candidate.catalog_id == 'arduino_uno_r3' and candidate.signal_pins == {}
        assert pi.signal_pins == {'GPIO17': 'SIGNAL'}
    finally:
        dialog.reject()


def test_generic_mcu_without_prior_pins_allows_first_custom_net_before_show(app):
    workspace = circuit()
    data = workspace.model_dump()
    next(component for component in data['components'] if component['id'] == 'custom')['signal_pins'] = {}
    workspace = ElectricalWorkspace.model_validate(data)
    dialog = McuPinDialog(None, workspace, mcu_id='custom')
    try:
        # isVisible() is false before showing the parent dialog; custom-board
        # permissions must come from the board model, not widget visibility.
        assert dialog.custom_allowed and dialog.node_button.isEnabled()
        dialog.custom_pin.setText('MY_OUTPUT'); dialog.node_combo.setCurrentText('NEW_SIGNAL')
        dialog.node_button.click()
        assert dialog.current_mcu().signal_pins == {'MY_OUTPUT': 'NEW_SIGNAL'}
        assert 'NEW_SIGNAL' in dialog.workspace.nodes and 'NEW_SIGNAL' not in workspace.nodes
    finally:
        dialog.reject()


def test_accepted_pin_change_round_trips_with_cad_project_and_undo_history(app, tmp_path):
    from cadstudio.models import Design, Part
    from cadstudio.native.document import Document, read_project
    original = circuit(); dialog = McuPinDialog(None, original, mcu_id='pi')
    try:
        dialog.select_pin('GPIO17'); select_target(dialog, 'pull', 'a'); dialog.connect_selected(); dialog.accept()
        document = Document()
        design = Design(parts=[Part(id='board', name='Controller', role='electrical',
                                   geometry=dict(kind='cylinder'))], electrical=original).model_dump()
        document.commit(design, 'Original circuit'); original_cursor = document.journal.data['cursor']
        changed = deepcopy(design); changed['electrical'] = dialog.accepted_workspace.model_dump()
        document.commit(changed, 'MCU pin wiring', {'source': 'manual'})
        target = tmp_path / 'pin-wiring.cad.json'; document.write(target)
        project = read_project(target)
        assert next(component for component in project.design.electrical.components if component.id == 'pi').signal_pins['GPIO17'] == 'SIGNAL'
        assert document.journal.at(original_cursor) == design
        assert changed['parts'] == design['parts'] and original.model_dump() == circuit().model_dump()
    finally:
        dialog.reject()


def test_schematic_contains_board_selector_pin_pane_and_cancel_discards_nested_change(app, monkeypatch):
    from cadstudio.native.electrical_schematic import ElectricalSchematicDialog
    original = circuit(); before = original.model_dump()
    def confirm(dialog):
        dialog.select_pin('GPIO17'); select_target(dialog, 'pull', 'a')
        dialog.connect_selected(); dialog.accept()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(McuPinDialog, 'exec', confirm)
    schematic = ElectricalSchematicDialog(None, original)
    try:
        schematic.mcu_combo.setCurrentIndex(schematic.mcu_combo.findData('pi'))
        assert len(schematic.pin_view.pin_items) == 40
        assert not schematic.apply_button.isEnabled()
        schematic.pin_button.click()
        assert schematic.workspace_changed and schematic.apply_button.isEnabled()
        pi = next(component for component in schematic.workspace.components if component.id == 'pi')
        assert pi.signal_pins['GPIO17'] == 'SIGNAL'
        assert schematic.branch_layout['pi']['signals']['GPIO17']['node'] == 'SIGNAL'
        schematic.reject()
        assert schematic.accepted_workspace is None and original.model_dump() == before
    finally:
        schematic.reject()


def test_schematic_cancelled_pin_editor_does_not_change_diagram_or_enable_save(app, monkeypatch):
    from cadstudio.native.electrical_schematic import ElectricalSchematicDialog
    original = circuit()
    def cancel(dialog):
        dialog.select_pin('GPIO17'); select_target(dialog, 'pull', 'a'); dialog.connect_selected()
        dialog.reject(); return QDialog.DialogCode.Rejected
    monkeypatch.setattr(McuPinDialog, 'exec', cancel)
    schematic = ElectricalSchematicDialog(None, original)
    try:
        schematic.pin_button.click()
        assert schematic.workspace.model_dump() == original.model_dump()
        assert not schematic.workspace_changed and not schematic.apply_button.isEnabled()
    finally:
        schematic.reject()


@pytest.mark.parametrize('save_schematic', [False, True])
def test_main_electrical_editor_adopts_only_confirmed_schematic_changes(app, monkeypatch, save_schematic):
    from cadstudio.native.electrical_dialog import ElectricalDialog
    from cadstudio.native.electrical_schematic import ElectricalSchematicDialog
    from cadstudio.mcu_connections import assign_pin
    original = circuit(); before = original.model_dump()
    def inspect(schematic):
        schematic.workspace = assign_pin(schematic.workspace, 'pi', 'GPIO17', 'pull', 'a')
        if save_schematic:
            schematic.accept(); return QDialog.DialogCode.Accepted
        schematic.reject(); return QDialog.DialogCode.Rejected
    monkeypatch.setattr(ElectricalSchematicDialog, 'exec', inspect)
    design = dict(parts=[], electrical=before)
    editor = ElectricalDialog(None, design)
    try:
        editor.schematic_button.click()
        candidate = editor.candidate()
        pi = next(component for component in candidate.components if component.id == 'pi')
        assert ('GPIO17' in pi.signal_pins) == save_schematic
        assert 'UNUSED' in candidate.nodes
        assert design == dict(parts=[], electrical=before)
        assert original.model_dump() == before
    finally:
        editor.reject()
