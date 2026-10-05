"""User interactions in the integrated component-and-pin circuit canvas."""
from copy import deepcopy
import sys
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QGraphicsItem, QMessageBox, QPushButton

from cadstudio.electrical import ElectricalWorkspace, evaluate_electrical
from cadstudio.native.electrical_dialog import ComponentDialog, ElectricalDialog
from cadstudio.native.electrical_schematic import ElectricalSchematicDialog, NET_ROLE


@pytest.fixture(scope='module')
def app():
    instance=QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    yield instance
    instance.processEvents()


def circuit():
    return ElectricalWorkspace.model_validate(dict(name='Component circuit',
        nodes=['GND','BAT','SUPPLY','SIG'],components=[
            dict(id='source',name='Battery',kind='battery',a='BAT',b='GND',voltage_v=5),
            dict(id='switch',name='Power switch',kind='switch',a='BAT',b='SUPPLY',contact_resistance_ohm=.01),
            dict(id='pi',name='Raspberry controller',kind='mcu',catalog_id='rpi4b',a='SUPPLY',b='GND',
                 rated_voltage_v=5,rated_current_a=.2),
            dict(id='driver',name='Actuator driver',kind='load',catalog_id='pololu_2130',a='SUPPLY',b='GND',
                 analysis_enabled=False),
            dict(id='motor',name='Actuator',kind='motor',a='SUPPLY',b='GND',rated_voltage_v=5,rated_current_a=.1),
            dict(id='pull',name='Pull-down resistor',kind='resistor',a='SIG',b='GND',resistance_ohm=1000),
        ]))


def show(app,dialog):
    dialog.resize(1280,850);dialog.show();app.processEvents();dialog.fit_scene();app.processEvents()


def click_port(app,dialog,identifier,key):
    point=dialog.view.mapFromScene(dialog.component_items[identifier].port_scene_position(key))
    QTest.mouseClick(dialog.view.viewport(),Qt.MouseButton.LeftButton,pos=point)
    app.processEvents()


def wait_ui(app,predicate):
    end=time.monotonic()+3
    while not predicate():
        QTest.qWait(10);app.processEvents()
        assert time.monotonic()<end,'Circuit redraw did not settle'


def test_default_circuit_has_compact_boards_and_every_electronic_component(app):
    original=circuit();dialog=ElectricalSchematicDialog(None,original,view_mode='symbols')
    try:
        assert set(dialog.component_items)=={'source','switch','pi','driver','motor','pull'}
        assert dialog.pin_panel.isHidden()
        assert {dialog.kind_combo.itemData(index) for index in range(dialog.kind_combo.count())}=={
            'mcu','battery','motor','load','resistor','switch','wire'}
        board=dialog.component_items['pi']
        assert board.board.model=='Raspberry Pi 4 Model B'
        assert board.compact and len(board.ports)<=10
        assert 'pin:GPIO17' in board.all_ports
        assert board.all_ports['pin:3V3_1'].node is None
        assert 'pin:3V3_1' not in board.ports
        assert set(dialog.component_items['driver'].ports)>={'a','b','port:AIN1'}
        assert set(dialog.component_items['driver'].all_ports)>={'port:AIN1','port:BIN1'}
        assert not dialog.workspace_changed
        assert original.model_dump()==circuit().model_dump()
    finally:dialog.reject()


def test_main_circuit_view_inspects_pins_and_requests_editor_without_mutating_input(app):
    original=circuit();before=original.model_dump()
    panel=ElectricalSchematicDialog(None,original,editable=False,view_mode='symbols')
    requested=[];focused=[]
    panel.editRequested.connect(lambda:requested.append(True))
    panel.focusRequested.connect(lambda:focused.append(True))
    try:
        show(app,panel)
        assert panel.add_button.isHidden() and panel.wire_button.isHidden() and panel.apply_button.isHidden()
        assert all(not item.flags()&QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                   for item in panel.component_items.values())
        panel.component_items['pi'].setSelected(True);panel.expand_selected();panel.fit_scene()
        assert not panel.workspace_changed
        assert len([port for port in panel.component_items['pi'].ports.values() if port.physical])==40
        panel.edit_button.click()
        assert requested==[True] and original.model_dump()==before
        focus=next(item for item in panel.findChildren(QPushButton)
                   if item.text().startswith(('회로도 크게 보기','Focus circuit')))
        focus.click();assert focused==[True] and original.model_dump()==before
        panel.accept();assert panel.accepted_workspace is None
    finally:panel.reject()


def test_actual_mouse_drag_saves_arrangement_without_rewiring_and_cancel_discards(app):
    original=circuit();before=original.model_dump();calculation=evaluate_electrical(original)
    dialog=ElectricalSchematicDialog(None,original,calculation,view_mode='symbols')
    try:
        show(app,dialog)
        item=dialog.component_items['motor'];start=item.pos()
        point=dialog.view.mapFromScene(item.mapToScene(item.body_rect.center()))
        QTest.mousePress(dialog.view.viewport(),Qt.MouseButton.LeftButton,pos=point)
        for offset in (QPoint(18,8),QPoint(36,16),QPoint(54,24)):
            QTest.mouseMove(dialog.view.viewport(),point+offset,delay=15)
        QTest.mouseRelease(dialog.view.viewport(),Qt.MouseButton.LeftButton,pos=point+QPoint(54,24))
        wait_ui(app,lambda:dialog.endpoint_coordinates[('motor','a')]==item.port_scene_position('a'))
        assert (item.pos()-start).manhattanLength()>5
        position=dialog.workspace.schematic_positions['motor']
        assert (position.x,position.y)==(item.pos().x(),item.pos().y())
        assert dialog.endpoint_coordinates[('motor','a')]==item.port_scene_position('a')
        assert dialog.workspace.components==original.components and dialog.workspace.nodes==original.nodes
        assert evaluate_electrical(dialog.workspace).model_dump()==calculation.model_dump()
        assert dialog.workspace_changed and dialog.apply_button.isEnabled()
        dialog.reject()
        assert dialog.accepted_workspace is None and original.model_dump()==before
    finally:dialog.reject()


def test_redrawing_selected_symbols_and_closing_pending_router_never_calls_deleted_items(app,monkeypatch):
    errors=[];monkeypatch.setattr(sys,'excepthook',lambda kind,value,traceback:errors.append(value))
    original=circuit();before=original.model_dump();dialog=ElectricalSchematicDialog(None,original,view_mode='symbols')
    show(app,dialog)
    for _ in range(3):
        dialog.component_items['pi'].setSelected(True)
        dialog._adopt(dialog.workspace)
        app.processEvents()
    assert not errors
    dialog.component_items['motor'].setPos(QPointF(1400,420))
    assert dialog.route_timer.isActive()
    dialog.reject();assert not dialog.route_timer.isActive()
    dialog.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    QTest.qWait(150);app.processEvents()
    assert not errors and original.model_dump()==before


def test_actual_port_clicks_connect_gpio_then_escape_cancels_pending_wire(app):
    original=circuit();before=original.model_dump();dialog=ElectricalSchematicDialog(None,original,view_mode='symbols')
    try:
        show(app,dialog)
        board=dialog.component_items['pi'];board.setSelected(True);dialog.expand_selected();dialog.fit_scene()
        dialog.wire_button.click();assert dialog.wire_button.isChecked()
        click_port(app,dialog,'pi','pin:GPIO17')
        assert dialog.pending_terminal==('pi','pin:GPIO17')
        click_port(app,dialog,'pull','a')
        assert dialog.pending_terminal is None
        pi=next(component for component in dialog.workspace.components if component.id=='pi')
        assert pi.signal_pins['GPIO17']=='SIG'
        assert dialog.branch_layout['pi']['signals']['GPIO17']['node']=='SIG'
        assert all(segment.data(NET_ROLE)=='SIG' for segment in dialog.net_segments['SIG'])
        assert original.model_dump()==before
        click_port(app,dialog,'motor','a');assert dialog.pending_terminal==('motor','a')
        QTest.keyClick(dialog.view,Qt.Key.Key_Escape);app.processEvents()
        assert dialog.pending_terminal is None
        dialog.reject();assert dialog.accepted_workspace is None
    finally:dialog.reject()


def test_physical_power_reference_cannot_become_a_fake_gpio_connection(app):
    original=circuit();dialog=ElectricalSchematicDialog(None,original,view_mode='symbols')
    try:
        show(app,dialog);dialog.component_items['pi'].setSelected(True);dialog.expand_selected();dialog.fit_scene()
        before=dialog.workspace.model_dump();dialog.wire_button.click()
        click_port(app,dialog,'pi','pin:3V3_1')
        assert dialog.pending_terminal is None
        assert 'DC' in dialog.status.text()
        assert dialog.workspace.model_dump()==before and not dialog.workspace_changed
    finally:dialog.reject()


def test_declining_reassignment_keeps_shared_old_net_and_every_other_terminal(app,monkeypatch):
    dialog=ElectricalSchematicDialog(None,circuit(),view_mode='symbols')
    try:
        show(app,dialog);before=dialog.workspace.model_dump()
        monkeypatch.setattr(QMessageBox,'question',lambda *_args:QMessageBox.StandardButton.No)
        dialog.wire_button.click();click_port(app,dialog,'motor','a');click_port(app,dialog,'pull','a')
        assert dialog.workspace.model_dump()==before
        assert not dialog.workspace_changed and not dialog.apply_button.isEnabled()
    finally:dialog.reject()


def test_add_component_modal_is_transactional_and_uses_selected_symbol_kind(app,monkeypatch):
    original=circuit();before=original.model_dump();dialog=ElectricalSchematicDialog(None,original,view_mode='symbols')
    def fill(child):
        assert child.kind.currentData()=='resistor'
        child.name.setText('Added resistor');child.a.setText('NEW_INPUT');child.b.setText('GND')
        child.inputs['resistance_ohm'].setValue(2200);child.accept()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(ComponentDialog,'exec',fill)
    try:
        dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData('resistor'));dialog.add_button.click()
        added=next(component for component in dialog.workspace.components if component.name=='Added resistor')
        assert added.kind=='resistor' and added.resistance_ohm==2200
        assert added.id in dialog.component_items and 'NEW_INPUT' in dialog.workspace.nodes
        assert original.model_dump()==before and dialog.apply_button.isEnabled()
        dialog.reject();assert dialog.accepted_workspace is None
    finally:dialog.reject()


def test_saved_component_placement_round_trips_with_exact_cad_undo_history(app,tmp_path):
    from cadstudio.catalog import preset
    from cadstudio.models import Design
    from cadstudio.native.document import Document,Journal,read_project
    original=circuit();dialog=ElectricalSchematicDialog(None,original,view_mode='symbols')
    try:
        dialog.component_items['source'].setPos(QPointF(-55,130))
        dialog.component_items['motor'].setPos(QPointF(1120,330))
        dialog.accept();assert dialog.accepted_workspace is not None
        document=Document();base=preset('cylinder').model_dump();base['electrical']=original.model_dump()
        document.commit(Design.model_validate(base),'Initial circuit');base_id=document.journal.data['cursor']
        changed=deepcopy(base);changed['electrical']=dialog.accepted_workspace.model_dump()
        document.commit(Design.model_validate(changed),'Arrange circuit');changed_id=document.journal.data['cursor']
        target=tmp_path/'arranged.cad.json';document.write(target);loaded=read_project(target)
        assert loaded.design.model_dump()==changed
        journal=Journal(data=loaded.history.model_dump())
        assert journal.at(base_id)==base and journal.at(changed_id)==changed
        reopened=ElectricalSchematicDialog(None,loaded.design.electrical,view_mode='symbols')
        try:
            assert reopened.component_items['source'].pos()==QPointF(-55,130)
            assert reopened.component_items['motor'].pos()==QPointF(1120,330)
            assert not reopened.workspace_changed
        finally:reopened.reject()
    finally:dialog.reject()


def test_electrical_editor_preserves_layout_across_component_edits_and_schematic_accept(app,monkeypatch):
    original=circuit().model_dump();original['schematic_positions']={'motor':dict(x=1100,y=200)}
    design=dict(parts=[],electrical=deepcopy(original));editor=ElectricalDialog(None,design)
    try:
        assert editor.candidate().model_dump()['schematic_positions']==original['schematic_positions']
        def save(child):
            child.component_items['motor'].setPos(QPointF(1000,160));child.accept()
            return QDialog.DialogCode.Accepted
        monkeypatch.setattr(ElectricalSchematicDialog,'exec',save)
        editor.schematic_button.click()
        assert editor.candidate().model_dump()['schematic_positions']['motor']==dict(x=1000,y=160)
        assert design['electrical']==original
    finally:editor.reject()


def test_default_physical_board_has_real_forty_pin_header_and_explicit_supply_ports(app):
    from cadstudio.native.physical_board_symbols import PhysicalComponentItem
    original=circuit();dialog=ElectricalSchematicDialog(None,original)
    try:
        assert dialog.view_mode=='physical' and dialog.mode_picker.currentData()=='physical'
        item=dialog.component_items['pi'];assert isinstance(item,PhysicalComponentItem)
        assert len([port for port in item.ports.values() if port.physical])==40
        assert item.ports['supply:5V_2'].node is None and item.ports['supply:5V_2'].connectable
        assert item.ports['supply:GND_6'].node is None and item.ports['supply:GND_6'].connectable
        assert 'supply:GPIO17' not in item.ports and item.ports['pin:GPIO17'].kind=='signal'
        left=[item.pin_positions[('supply:' if pin.kind in ('power','ground') else 'pin:')+pin.key]
              for pin in item.board.pins if pin.side=='left']
        right=[item.pin_positions[('supply:' if pin.kind in ('power','ground') else 'pin:')+pin.key]
               for pin in item.board.pins if pin.side=='right']
        assert len(left)==len(right)==20
        assert len({point.x() for point in left})==len({point.x() for point in right})==1
        assert left[0].x()<right[0].x() and len({point.y() for point in left})==20
        assert original.model_dump()==dialog.workspace.model_dump() and not dialog.workspace_changed
    finally:dialog.reject()


def test_actual_physical_power_pad_wiring_warns_mismatch_and_never_fabricates_dc_load(app):
    original=circuit();before=original.model_dump();dialog=ElectricalSchematicDialog(None,original)
    try:
        show(app,dialog);dialog.wire_button.click()
        click_port(app,dialog,'pi','supply:5V_2');click_port(app,dialog,'source','a')
        wait_ui(app,lambda:bool(next(component for component in dialog.workspace.components if component.id=='pi').board_supply_pins))
        pi=next(component for component in dialog.workspace.components if component.id=='pi')
        assert pi.board_supply_pins=={'5V_2':'BAT'} and (pi.a,pi.b)==('SUPPLY','GND')
        assert not dialog.supply_warnings.text()
        assert dialog.connect_terminals('pi','supply:3V3_1','source','a')
        assert '3.3 V' in dialog.supply_warnings.text() and '5 V' in dialog.supply_warnings.text()
        dialog.wire_button.click();click_port(app,dialog,'pi','supply:3V3_1')
        assert dialog.selected_terminal==('pi','supply:3V3_1') and dialog.disconnect_button.isEnabled()
        QTest.mouseClick(dialog.disconnect_button,Qt.MouseButton.LeftButton);app.processEvents()
        pi=next(component for component in dialog.workspace.components if component.id=='pi')
        assert pi.board_supply_pins=={'5V_2':'BAT'} and not dialog.supply_warnings.text()
        assert dialog.pending_terminal is None and not dialog.disconnect_button.isEnabled()
        assert original.model_dump()==before
    finally:dialog.reject()


def test_physical_view_and_symbol_view_switch_keep_saved_mapping_and_layout_exact(app):
    original=circuit();dialog=ElectricalSchematicDialog(None,original)
    try:
        assert dialog.connect_terminals('pi','supply:5V_2','source','a')
        dialog.component_items['pi'].setPos(QPointF(600,90));before=dialog.workspace.model_dump()
        dialog.mode_picker.setCurrentIndex(dialog.mode_picker.findData('symbols'))
        assert dialog.view_mode=='symbols' and dialog.workspace.model_dump()==before
        dialog.mode_picker.setCurrentIndex(dialog.mode_picker.findData('physical'))
        assert dialog.component_items['pi'].ports['supply:5V_2'].node=='BAT'
        assert dialog.component_items['pi'].pos()==QPointF(600,90) and dialog.workspace.model_dump()==before
    finally:dialog.reject()
