"""Actual Qt link controls keep circuit identity and private-save semantics."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QPushButton

from cadstudio.models import Design, Part
from cadstudio.electrical_registration import register_part
from cadstudio.native.electrical_part_dialog import ElectricalCadLinkDialog
from cadstudio.native.electrical_schematic import ElectricalSchematicDialog
from cadstudio.native.electrical_workbench import ElectricalWorkbenchDialog


@pytest.fixture(scope='module')
def app():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app
    app.processEvents()


@pytest.fixture(autouse=True)
def finish_owned_dialog_deletion(app):
    # A real event loop dispatches deleteLater after the modal handler returns.
    # processEvents alone does not dispatch these queued QObject destructions.
    yield
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def design_fixture():
    original = Design(name='Private correspondence test', parts=[
        Part(id='board', name='Controller body', role='electrical', color='#123456', geometry=dict(kind='cylinder')),
        Part(id='sensor', name='Force sensor', role='structure', color='#ABCDEF', geometry=dict(kind='cylinder'))],
        electrical=dict(name='Keep this circuit', nodes=['GND', 'PWR', 'KEEP'], components=[
            dict(id='source', name='Bench supply', kind='battery', a='PWR', b='GND', voltage_v=5),
            dict(id='custom', name='Custom amplifier', kind='load', a='PWR', b='GND', analysis_enabled=False,
                 terminal_pins={'OUT': 'KEEP', 'GND': 'GND'}, rated_voltage_v=0, rated_current_a=0)]))
    return register_part(original, 'board', dict(catalog_id='rpi4b'))


def click(widget):
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
    QApplication.processEvents()


def modal(expected, action):
    errors = []
    def handle():
        child = QApplication.activeModalWidget()
        try:
            assert isinstance(child, expected), f'Expected {expected.__name__}, got {type(child).__name__}'
            action(child)
        except BaseException as exc:
            errors.append(exc)
            if child: child.reject()
    QTimer.singleShot(80, handle)
    return errors


def link_sensor(child):
    QTest.keyClicks(child.search, 'Force sensor')
    assert child.part_combo.currentData() == 'sensor'
    click(child.bind_button)
    assert child.apply_button.isEnabled()
    click(child.apply_button)


def test_actual_bind_click_preserves_component_pins_colors_and_no_duplicate(app):
    original = design_fixture(); before = original.model_dump(mode='json')
    dialog = ElectricalCadLinkDialog(None, original, 'custom', 'sensor')
    dialog.show(); app.processEvents()
    try:
        board_index = dialog.part_combo.findData('board')
        assert not dialog.part_combo.model().item(board_index).isEnabled()
        click(dialog.bind_button); click(dialog.apply_button)
        checked = dialog.checked
        assert 'Force sensor' in dialog.component_combo.currentText() and 'CAD 연결 없음' not in dialog.component_combo.currentText()
        assert checked and checked.parts[1].role == 'electrical'
        assert checked.parts[1].color == '#ABCDEF'
        assert checked.parts[1].geometry == original.parts[1].geometry
        custom = next(c for c in checked.electrical.components if c.id == 'custom')
        assert custom.part_id == 'sensor' and custom.part_registration
        assert custom.terminal_pins == {'OUT': 'KEEP', 'GND': 'GND'}
        assert len(checked.electrical.components) == len(original.electrical.components)
        assert original.model_dump(mode='json') == before
    finally: dialog.close(); dialog.deleteLater()


def test_schematic_child_save_remains_private_and_outer_cancel_discards(app):
    original = design_fixture(); before = original.model_dump(mode='json')
    dialog = ElectricalSchematicDialog(None, original.electrical, parts=before['parts'])
    dialog.show(); dialog.focus_component('custom'); app.processEvents()
    try:
        errors = modal(ElectricalCadLinkDialog, link_sensor)
        click(dialog.link_button)
        assert not errors
        custom = next(c for c in dialog.workspace.components if c.id == 'custom')
        assert custom.part_id == 'sensor' and custom.terminal_pins == {'OUT': 'KEEP', 'GND': 'GND'}
        assert dialog.parts[1]['role'] == 'electrical'
        assert 'Force sensor [sensor]' in dialog.inspector.text()
        assert original.model_dump(mode='json') == before
        dialog.reject()
        assert dialog.accepted_workspace is None and dialog.accepted_parts is None
        assert original.model_dump(mode='json') == before
    finally: dialog.deleteLater()


def test_linking_preserves_shared_sketch_and_dimension_context(app):
    from cadstudio.models import SavedSketch
    original=design_fixture();raw=original.model_dump(mode='json')
    sketch=SavedSketch(id='profile',name='Linked profile',geometry=dict(kind='extrusion',thickness=12))
    raw['sketches']=[sketch.model_dump(mode='json')]
    raw['parts'][1]['geometry']=sketch.geometry.model_dump(mode='json')
    raw['parts'][1]['profile_sketch_id']='profile'
    original=Design.model_validate(raw);before=original.model_dump(mode='json')
    dialog=ElectricalSchematicDialog(None,original.electrical,parts=before['parts'],design=original)
    dialog.show();dialog.focus_component('custom');app.processEvents()
    try:
        errors=modal(ElectricalCadLinkDialog,link_sensor)
        click(dialog.link_button);assert not errors
        click(dialog.apply_button)
        merged=deepcopy(before);merged.update(parts=dialog.accepted_parts,electrical=dialog.accepted_workspace.model_dump(mode='json'))
        checked=Design.model_validate(merged)
        assert checked.parts[1].profile_sketch_id=='profile'
        assert checked.sketches==original.sketches
        assert checked.parts[1].geometry==original.parts[1].geometry
        assert original.model_dump(mode='json')==before
    finally:dialog.close();dialog.deleteLater()


def test_generic_component_edit_cannot_duplicate_a_registered_body(app):
    from cadstudio.native.electrical_part_dialog import validate_circuit_cad_assignment
    from cadstudio.electrical import ElectricalWorkspace
    original=design_fixture();raw=original.electrical.model_dump(mode='json')
    raw['components'][1]['part_id']='board'
    with pytest.raises(ValueError,match='다른 회로 부품'):
        validate_circuit_cad_assignment(original.model_dump(mode='json')['parts'],ElectricalWorkspace.model_validate(raw),'custom')
    assert not original.electrical.components[1].part_id


def test_legacy_operating_editor_receives_child_roles_but_cancel_is_private(app):
    from cadstudio.native.electrical_dialog import ElectricalDialog
    original=design_fixture();before=original.model_dump(mode='json')
    dialog=ElectricalDialog(None,before);dialog.show();app.processEvents()
    def schematic(child):
        child.focus_component('custom')
        errors=modal(ElectricalCadLinkDialog,link_sensor)
        click(child.link_button);assert not errors
        click(child.apply_button)
    try:
        errors=modal(ElectricalSchematicDialog,schematic)
        click(dialog.schematic_button);assert not errors
        assert dialog.parts[1]['role']=='electrical'
        assert next(c for c in dialog.components if c['id']=='custom')['part_id']=='sensor'
        assert before==original.model_dump(mode='json')
        dialog.reject();assert dialog.accepted_parts is None
        assert before==original.model_dump(mode='json')
    finally:dialog.deleteLater()


def test_child_ai_request_waits_for_outer_workbench_save(app):
    original=design_fixture();dialog=ElectricalWorkbenchDialog(None,original)
    dialog.show();app.processEvents()
    def schematic(child):
        child.focus_component('custom')
        child.ai_request=dict(prompt='Connect the amplifier OUT to an ADC input.',component_id='custom',part_id='',terminal='port:OUT')
        child.apply_button.setEnabled(True)
        click(child.apply_button)
    try:
        errors=modal(ElectricalSchematicDialog,schematic)
        click(dialog.schematic_button);assert not errors
        assert dialog.ai_request['component_id']=='custom'
        assert dialog.draft==original
        assert dialog.apply_button.isEnabled()
        click(dialog.apply_button)
        assert dialog.checked==original and dialog.ai_request['terminal']=='port:OUT'
    finally:dialog.close();dialog.deleteLater()


def test_workbench_save_returns_parts_and_one_document_transaction(app, tmp_path):
    from cadstudio.native.document import Document, read_project
    original = design_fixture(); raw = original.model_dump(mode='json')
    dialog = ElectricalWorkbenchDialog(None, original)
    dialog.show(); app.processEvents()
    try:
        row = next(i for i, r in enumerate(dialog._visible_rows) if r.component_id == 'custom')
        dialog.table.selectRow(row)
        errors = modal(ElectricalCadLinkDialog, link_sensor)
        click(dialog.link_button); assert not errors
        assert dialog.draft.parts[1].role == 'electrical'
        assert original.model_dump(mode='json') == raw
        click(dialog.apply_button)
        document = Document(); document.commit(raw, 'Original')
        cursor=document.journal.data['cursor'];prior = len(document.journal.data['entries'])
        document.commit(dialog.checked.model_dump(mode='json'), 'Circuit CAD link')
        head=document.journal.data['cursor']
        assert len(document.journal.data['entries']) == prior + 1
        assert document.design['parts'][1]['role'] == 'electrical'
        path = tmp_path / 'linked.cad.json'; document.write(path)
        reopened = read_project(path)
        assert reopened.design.electrical.components[1].part_id == 'sensor'
        document.commit(document.journal.at(cursor),'Undo',cursor=cursor); assert not document.design['electrical']['components'][1]['part_id']
        document.commit(document.journal.at(head),'Redo',cursor=head); assert document.design['electrical']['components'][1]['part_id'] == 'sensor'
    finally: dialog.close(); dialog.deleteLater()


def test_unlink_preserves_device_and_cad_role_color(app):
    from cadstudio.electrical_registration import bind_component_to_part
    original = bind_component_to_part(design_fixture(), 'custom', 'sensor')
    dialog = ElectricalCadLinkDialog(None, original, 'custom')
    dialog.show(); app.processEvents()
    try:
        click(dialog.unbind_button); click(dialog.apply_button)
        custom = next(c for c in dialog.checked.electrical.components if c.id == 'custom')
        assert not custom.part_id and not custom.part_registration
        assert custom.terminal_pins == original.electrical.components[1].terminal_pins
        assert dialog.checked.parts[1].role == 'electrical' and dialog.checked.parts[1].color == '#ABCDEF'
    finally: dialog.close(); dialog.deleteLater()


def test_selection_signal_and_cad_focus_are_distinct_and_synchronization_is_quiet(app):
    original = design_fixture()
    dialog = ElectricalSchematicDialog(None, original.electrical, parts=original.model_dump(mode='json')['parts'], editable=False)
    dialog.show(); app.processEvents()
    selected = QSignalSpy(dialog.componentSelected); focused = QSignalSpy(dialog.partActivated)
    try:
        component = next(c for c in dialog.workspace.components if c.part_id == 'board')
        assert dialog.focus_part('board', zoom=False)
        assert selected.count() == 0 and focused.count() == 0
        click(dialog.cad_button); assert focused.count() == 1 and focused.at(0) == ['board']
        dialog.focus_component('custom'); assert selected.at(selected.count() - 1) == ['custom']
        assert 'CAD 대응 없음' in dialog.inspector.text() and not dialog.cad_button.isEnabled()
        assert component.id in dialog.component_items
    finally: dialog.close(); dialog.deleteLater()


def test_route_and_fit_preserve_selection_without_rebroadcasting_cad_focus(app):
    original=design_fixture()
    dialog=ElectricalSchematicDialog(None,original.electrical,parts=original.model_dump(mode='json')['parts'],editable=False)
    dialog.show();app.processEvents()
    selected=QSignalSpy(dialog.componentSelected)
    try:
        identifier=next(c.id for c in dialog.workspace.components if c.part_id=='board')
        dialog.focus_component(identifier)
        assert selected.count()==1 and selected.at(0)==[identifier]
        dialog._route();dialog.fit_scene();dialog.resize(1180,710);app.processEvents()
        assert dialog._selected_id()==identifier
        assert selected.count()==1
        dialog.focus_component('custom')
        assert selected.count()==2 and selected.at(1)==['custom']
        assert 'Custom amplifier' in dialog.inspector.text()
    finally:dialog.close();dialog.deleteLater()


@pytest.mark.parametrize('focused',[False,True])
def test_show_cad_restores_focused_dock_preferences_and_normal_properties(app,monkeypatch,tmp_path,focused):
    from cadstudio.native import window
    from cadstudio.native.model_picker import LocalModelPicker
    monkeypatch.setattr(window,'DATA_DIR',tmp_path)
    monkeypatch.setattr(LocalModelPicker,'refresh',lambda _:None)
    # Actual main-window controls and selection handlers are under test. Native
    # smoke exercises these same controls with both complete 3D renderers.
    monkeypatch.setattr(window.CADViewport,'initialize',lambda _:None)
    w=window.MainWindow(restore=False)
    raw=design_fixture().model_dump(mode='json');w.document.commit(raw,'Fixture')
    w.document.dirty=False;w.rebuild_tree();w.show();app.processEvents()
    try:
        w.show_circuit_workspace();panel=w.circuit_panel;panel.focus_part('board',zoom=False)
        docks=(w.browser_dock,w.property_dock,w.ai_dock,w.timeline_dock)
        saved=[True,False,True,False]
        for dock,visible in zip(docks,saved):dock.setVisible(visible)
        app.processEvents()
        if focused:
            focus=next(b for b in panel.findChildren(QPushButton) if b.text().startswith(('회로도 크게 보기','Focus circuit')))
            click(focus)
            assert w.circuit_focus_panels==saved and not any(d.isVisible() for d in docks)
        click(panel.cad_button)
        assert w.workspace.currentData()=='model' and w.selected=='board'
        assert getattr(w,'circuit_focus_panels',None) is None
        assert [d.isVisible() for d in docks]==(saved if focused else [True,True,True,False])
        assert w.document.design==raw and not getattr(w,'wiring_window',None)
    finally:
        w.document.dirty=False;w.close();w.deleteLater()


def test_inspection_only_does_not_emit_mutation_requests_or_change_workspace(app):
    original = design_fixture()
    dialog = ElectricalSchematicDialog(None, original.electrical, parts=original.model_dump(mode='json')['parts'], editable=False, inspection_only=True)
    dialog.resize(640,320);dialog.show(); app.processEvents()
    before = dialog.workspace.model_dump(mode='json')
    requests = [QSignalSpy(signal) for signal in (dialog.editRequested, dialog.linkRequested, dialog.aiRequested, dialog.wireActionRequested, dialog.simulationRequested)]
    try:
        for widget in (dialog.edit_button, dialog.link_button, dialog.ai_button, dialog.add_wire_button, dialog.delete_wire_button, dialog.simulation_button):
            assert not widget.isVisible()
        for action in (dialog.edit_selected, dialog.edit_cad_link, dialog.prepare_ai_request, dialog.add_wire,
                       dialog.delete_selected_wire, dialog.add_component, dialog.open_simulation, dialog.auto_arrange): action()
        assert not dialog.connect_terminals('custom', 'OUT', 'source', 'a')
        dialog.accept()
        assert all(spy.count() == 0 for spy in requests)
        assert dialog.workspace.model_dump(mode='json') == before
        assert dialog.accepted_workspace is None
        assert dialog.focus_part('board')
        assert dialog.view.height() > dialog.height() * .6
    finally: dialog.close(); dialog.deleteLater()


def test_physical_preview_fit_ignores_distant_hidden_wire_symbols(app):
    from cadstudio.circuit_connections import add_schematic_wire
    original=design_fixture()
    workspace=add_schematic_wire(original.electrical,'source','a','custom','a',name='Physical supply wire',length_mm=100,cross_section_mm2=.5)
    wire=next(c for c in workspace.components if c.kind=='wire')
    from cadstudio.electrical import ElectricalSchematicPosition
    workspace.schematic_positions[wire.id]=ElectricalSchematicPosition(x=20000,y=20000)
    dialog=ElectricalSchematicDialog(None,workspace,parts=original.model_dump(mode='json')['parts'],editable=False,inspection_only=True)
    dialog.resize(860,420);dialog.show();app.processEvents();QTest.qWait(25);app.processEvents()
    try:
        assert not dialog.component_items[wire.id].isVisible()
        assert dialog.scene.itemsBoundingRect().bottom()>20000
        assert dialog.scene.sceneRect().bottom()<2000
        assert dialog.scene.sceneRect().contains(dialog.wire_paths[wire.id].sceneBoundingRect())
        board=next(item for item in dialog.component_items.values() if item.component.part_id=='board')
        displayed=dialog.view.mapFromScene(board.sceneBoundingRect()).boundingRect()
        assert displayed.height()>=dialog.view.viewport().height()*.3
    finally:dialog.close();dialog.deleteLater()


def test_repeated_owned_preview_close_and_deferred_delete_before_gc(app):
    import gc
    import shiboken6
    original=design_fixture()
    for inspection in (False, True)*6:
        dialog=ElectricalSchematicDialog(None,original.electrical,editable=False,inspection_only=inspection)
        dialog.resize(760,420);dialog.show();app.processEvents()
        scene=dialog.scene
        dialog.close();dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        assert not shiboken6.isValid(scene)
        del scene,dialog
        gc.collect()
        app.processEvents()


def test_child_link_save_parent_cancel_deletion_and_gc_retains_live_design(app):
    import gc
    original=design_fixture();before=original.model_dump(mode='json')
    for _ in range(3):
        dialog=ElectricalSchematicDialog(None,original.electrical,parts=before['parts'],design=original)
        dialog.show();dialog.focus_component('custom');app.processEvents()
        errors=modal(ElectricalCadLinkDialog,link_sensor)
        click(dialog.link_button);assert not errors
        assert dialog.parts[1]['role']=='electrical'
        dialog.reject();assert dialog.accepted_workspace is None
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        del dialog
        gc.collect();app.processEvents()
        assert original.model_dump(mode='json')==before


def test_inspection_power_warning_has_bounded_badge_without_orphan_widgets(app):
    from cadstudio.electrical import evaluate_electrical,ElectricalWorkspace
    original=design_fixture();raw=original.electrical.model_dump(mode='json')
    raw['components'][0]['voltage_v']=12
    board=next(c for c in raw['components'] if c['kind']=='mcu')
    board.update(board_supply_pins={'5V_2':'PWR'},supply_pinout_catalog_id='rpi4b')
    workspace=ElectricalWorkspace.model_validate(raw)
    dialog=ElectricalSchematicDialog(None,workspace,evaluate_electrical(workspace),editable=False,inspection_only=True)
    dialog.resize(760,420);dialog.show();app.processEvents()
    try:
        assert dialog.preview_warnings.isVisible() and '1' in dialog.preview_warnings.text()
        assert '12 V' in dialog.preview_warnings.toolTip()
        assert not dialog.supply_warnings.isVisible() and not dialog.editor_controls.isVisible()
        assert dialog.rect().contains(dialog.preview_warnings.mapTo(dialog,dialog.preview_warnings.rect().bottomRight()))
        assert dialog.view.height()>dialog.height()*.6
        dialog._route();app.processEvents()
        assert not dialog.supply_warnings.isVisible()
    finally:dialog.close();dialog.deleteLater()


def test_ai_request_is_queued_until_editor_save_and_discarded_on_cancel(app):
    original = design_fixture()
    dialog = ElectricalSchematicDialog(None, original.electrical, parts=original.model_dump(mode='json')['parts'])
    dialog.show(); dialog.focus_component('custom'); app.processEvents()
    emitted = QSignalSpy(dialog.aiRequested)
    def input_request(child):
        child.setTextValue('Connect OUT to the controller input; retain the existing supply.'); child.accept()
    try:
        errors = modal(QInputDialog, input_request)
        click(dialog.ai_button); assert not errors
        assert dialog.ai_request['component_id'] == 'custom'
        assert emitted.count() == 0 and dialog.apply_button.isEnabled()
        dialog.reject(); assert dialog.ai_request is None
        assert dialog.accepted_workspace is None
    finally: dialog.deleteLater()


@pytest.mark.parametrize('language', ['ko', 'en'])
def test_new_link_controls_and_explicit_save_fit_short_window(app, language):
    old = getattr(app, 'cad_language', None)
    app.cad_language = SimpleNamespace(language=language)
    original = design_fixture()
    dialog = ElectricalSchematicDialog(None, original.electrical, parts=original.model_dump(mode='json')['parts'])
    dialog.resize(1240, 600); dialog.show(); app.processEvents()
    try:
        for widget in (dialog.link_button, dialog.ai_button, dialog.apply_button, dialog.close_button):
            rect = widget.rect(); top = widget.mapTo(dialog, rect.topLeft()).y(); bottom = widget.mapTo(dialog, rect.bottomRight()).y()
            assert widget.isVisible() and 0 <= top <= bottom < dialog.height()
        assert ('Link CAD' if language == 'en' else 'CAD 대응') in dialog.link_button.text()
    finally:
        dialog.close(); dialog.deleteLater(); app.cad_language = old
