"""Native CAD identity registration and passive wiring remain transactional."""
import json

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from cadstudio.models import Design, DraftRequest, Part
from cadstudio.native.electrical_part_dialog import ElectricalPartDialog


@pytest.fixture(scope='module')
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    yield instance
    instance.processEvents()


def original_design():
    return Design(parts=[Part(id=identifier, name=identifier, color='#123456',
                             role='structure', geometry=dict(kind='cylinder'),
                             transform=dict(x=index * 70))
                         for index, identifier in enumerate(('board', 'sensor', 'motor'))],
                  part_groups=[dict(id='mixed', name='Original group', part_ids=['board', 'sensor'])],
                  electrical=dict(name='Original power', nodes=['GND', 'POWER', 'UNUSED'], components=[
                      dict(id='cell', name='Source', kind='battery', a='POWER', b='GND',
                           voltage_v=5, internal_resistance_ohm=.1)]))


def choose_model(dialog, identifier, catalog_id, kind=None):
    dialog.part_combo.setCurrentIndex(dialog.part_combo.findData(identifier))
    index = dialog.model_combo.findData(catalog_id)
    assert index >= 0, catalog_id
    dialog.model_combo.setCurrentIndex(index)
    if kind is not None:
        dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData(kind))


def target(dialog, part_id, terminal):
    index = next((index for index in range(dialog.target.count())
                  if tuple(dialog.target.itemData(index) or ()) == (part_id, terminal)), -1)
    assert index >= 0, (part_id, terminal)
    dialog.target.setCurrentIndex(index)


def test_reopened_registered_pin_diagram_fits_visible_viewport_without_manual_fit(app):
    from cadstudio.electrical_registration import register_part
    design=register_part(original_design(),'board',dict(catalog_id='rpi4b'))
    dialog=ElectricalPartDialog(None,design,'board')
    try:
        dialog.show();app.processEvents();QTest.qWait(30)
        view=dialog.diagram;scene=view.scene().sceneRect();viewport=view.viewport().rect()
        expected=min((viewport.width()-12)/scene.width(),(viewport.height()-12)/scene.height())
        assert view.transform().m11()>=expected*.9
        assert all(viewport.contains(view.mapFromScene(QPointF(*point)))
                   for point in view.pin_positions.values())
    finally:dialog.reject()


def test_register_preview_is_private_pending_and_preserves_geometry_colors_groups(app):
    from cadstudio.electrical import evaluate_electrical
    design = original_design(); before = design.model_dump()
    dialog = ElectricalPartDialog(None, design, 'board')
    try:
        assert not dialog.apply_button.isEnabled()
        choose_model(dialog, 'board', 'rpi4b'); dialog.register_button.click()
        component = dialog.component()
        assert component.part_id == 'board' and component.catalog_id == 'rpi4b'
        assert component.part_registration and not component.analysis_enabled
        assert component.rated_current_a == 0 and component.rated_voltage_v == 5
        assert component.source_url.startswith('https://')
        assert len(dialog.diagram.pin_items) == 40
        assert 'DC' in dialog.status.text() and dialog.apply_button.isEnabled()
        for original, updated in zip(design.parts, dialog.draft.parts):
            assert updated.geometry == original.geometry and updated.transform == original.transform
            assert updated.color == original.color and updated.features == original.features
        assert dialog.draft.part_groups == design.part_groups
        result = evaluate_electrical(dialog.draft.electrical)
        pending = next(branch for branch in result.components if branch.id == component.id)
        assert not pending.analysis_enabled and pending.resistance_ohm is None
        assert pending.voltage_drop_v is None
        assert design.model_dump() == before
        dialog.reject(); assert dialog.checked is None
    finally:
        dialog.reject()


def test_optional_default_color_does_not_modify_other_parts_and_reopen_retains_id(app):
    design = original_design(); dialog = ElectricalPartDialog(None, design, 'board')
    try:
        choose_model(dialog, 'board', 'rpi4b'); dialog.default_color.setChecked(True)
        dialog.register_preview(); identifier = dialog.component().id
        assert next(part for part in dialog.draft.parts if part.id == 'board').color == '#FFD400'
        assert next(part for part in dialog.draft.parts if part.id == 'sensor').color == '#123456'
        dialog.accept(); assert dialog.checked is not None
        second = ElectricalPartDialog(None, dialog.checked, 'board')
        try:
            second.name.setText('Controller renamed'); second.register_preview()
            assert second.component().id == identifier and second.component().name == 'Controller renamed'
            assert second.component().catalog_id == 'rpi4b'
            assert 'UNUSED' in second.draft.electrical.nodes
        finally:
            second.reject()
    finally:
        dialog.reject()


def test_exact_sensor_diagram_and_actual_pin_click_connect_to_registered_mcu(app):
    design = original_design(); dialog = ElectricalPartDialog(None, design, 'board')
    try:
        choose_model(dialog, 'board', 'rpi4b'); dialog.register_preview()
        choose_model(dialog, 'sensor', 'ams_as5600_asot', 'load'); dialog.register_preview()
        assert set(dialog.diagram.pin_items) == {'VDD5V', 'VDD3V3', 'OUT', 'GND', 'DIR', 'SCL', 'SDA', 'PGO'}
        dialog.show(); app.processEvents(); dialog.diagram.fit()
        point = dialog.diagram.mapFromScene(QPointF(*dialog.diagram.pin_positions['OUT']))
        QTest.mouseClick(dialog.diagram.viewport(), Qt.MouseButton.LeftButton, pos=point)
        app.processEvents()
        assert dialog.selected_terminal == 'OUT'
        target(dialog, 'board', 'pin:GPIO17'); dialog.connect_button.click()
        sensor = dialog.component(); node = sensor.terminal_pins['OUT']
        board = next(component for component in dialog.draft.electrical.components if component.part_id == 'board')
        assert board.signal_pins['GPIO17'] == node
        assert 'VDD5V' not in sensor.terminal_pins and 'VDD3V3' not in sensor.terminal_pins
        assert sensor.analysis_enabled is False and board.analysis_enabled is False
        assert design.model_dump() == original_design().model_dump()
    finally:
        dialog.reject()


def test_registered_part_and_product_ports_round_trip_with_history(app, tmp_path):
    from cadstudio.native.document import Document, read_project
    design = original_design(); dialog = ElectricalPartDialog(None, design, 'board')
    try:
        choose_model(dialog, 'board', 'rpi4b'); dialog.register_preview()
        choose_model(dialog, 'motor', 'pololu_4755', 'motor'); dialog.register_preview()
        dialog.select_terminal('ENCODER_A'); target(dialog, 'board', 'pin:GPIO18'); dialog.connect_terminal()
        dialog.accept(); assert dialog.checked is not None
        document = Document(); document.commit(design, 'Original'); original_cursor = document.journal.data['cursor']
        document.commit(dialog.checked, 'Register motor encoder'); saved = tmp_path / 'registered.cad.json'
        document.write(saved); project = read_project(saved)
        board = next(component for component in project.design.electrical.components if component.part_id == 'board')
        motor = next(component for component in project.design.electrical.components if component.part_id == 'motor')
        assert motor.terminal_pins['ENCODER_A'] == board.signal_pins['GPIO18']
        assert motor.catalog_id == 'pololu_4755' and not motor.analysis_enabled
        assert document.journal.at(original_cursor) == design.model_dump()
        assert project.design.parts[2].geometry == design.parts[2].geometry
    finally:
        dialog.reject()


def test_each_later_model_change_requires_new_connection_drop_confirmation(app, monkeypatch):
    confirmations = []
    def confirm(*args):
        confirmations.append(args[2])
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, 'question', confirm)
    dialog = ElectricalPartDialog(None, original_design(), 'board')
    try:
        choose_model(dialog, 'board', 'rpi4b'); dialog.register_preview()
        choose_model(dialog, 'sensor', 'ams_as5600_asot'); dialog.register_preview()
        choose_model(dialog, 'board', 'rpi4b'); dialog.select_terminal('GPIO17')
        target(dialog, 'sensor', 'port:OUT'); dialog.connect_terminal()
        choose_model(dialog, 'board', 'arduino_uno_r3'); dialog.register_preview()
        assert len(confirmations) == 1 and not dialog.component().signal_pins
        dialog.select_terminal('D2'); target(dialog, 'sensor', 'port:OUT'); dialog.connect_terminal()
        assert dialog.component().signal_pins['D2']
        choose_model(dialog, 'board', 'rpi_pico'); dialog.register_preview()
        assert len(confirmations) == 2 and not dialog.component().signal_pins
        assert dialog.component().catalog_id == 'rpi_pico'
    finally:
        dialog.reject()


@pytest.mark.parametrize('board_id,product_id,pin,port,kind', [
    ('rpi4b', 'ams_as5600_asot', 'GPIO17', 'OUT', 'load'),
    ('arduino_uno_r3', 'pololu_2130', 'D5', 'AIN1', 'load'),
    ('nucleo_f446re', 'pololu_4755', 'D2', 'ENCODER_A', 'motor'),
])
def test_ai_registration_and_pin_tools_share_native_identity_and_keep_exact_solids(board_id, product_id, pin, port, kind):
    from cadstudio.kernel import build
    from cadstudio.native.cad_tools import execute_plan
    from cadstudio.electrical_registration import registration_for_part
    original = original_design(); before = original.model_dump()
    plan = dict(name='Registered electronics', summary='Register existing bodies and connect a pin', assumptions=[], actions=[
        dict(tool='electrical_register', target='board', args=dict(catalog_id=board_id, kind='mcu')),
        dict(tool='electrical_register', target='sensor', args=dict(catalog_id=product_id, kind=kind)),
        dict(tool='electrical_connect', target='board', args=dict(pin=pin, target_part_id='sensor', target_terminal='port:' + port)),
    ])
    result = execute_plan(json.dumps(plan), DraftRequest(prompt='Register electronics without changing bodies', current=original))
    board = registration_for_part(result.design, 'board'); product = registration_for_part(result.design, 'sensor')
    assert board.catalog_id == board_id and product.catalog_id == product_id
    assert board.signal_pins[pin] == product.terminal_pins[port]
    assert not board.analysis_enabled and not product.analysis_enabled
    assert [shape.Volume() for shape in build(result.design)] == pytest.approx([shape.Volume() for shape in build(original)])
    assert original.model_dump() == before and result.design.part_groups == original.part_groups
    assert [part.color for part in result.design.parts] == [part.color for part in original.parts]
    assert len(result.journal_steps) == 3 and all(action['validated'] for action in result.tool_actions)
