import pytest
from PySide6.QtCore import QCoreApplication,QEvent,QTimer,Qt
from PySide6.QtWidgets import QApplication,QDialog
from PySide6.QtTest import QTest
from cadstudio.native.electrical_schematic import ElectricalSchematicDialog
from cadstudio.native.wire_connection_dialog import WireConnectionDialog
from cadstudio.electrical import ElectricalWorkspace
from cadstudio.circuit_connections import add_schematic_wire


@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])


def circuit():return ElectricalWorkspace.model_validate(dict(nodes=['GND','BAT','LOAD'],components=[
    dict(id='source',name='Battery',kind='battery',a='BAT',b='GND',voltage_v=5),
    dict(id='load',name='Load',kind='load',a='LOAD',b='GND',rated_voltage_v=5,rated_current_a=.1)]))


def close(dialog,app):
    dialog.reject();dialog.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()


def test_wire_dialog_requires_user_dimensions_and_selects_actual_endpoints(app):
    dialog=WireConnectionDialog(None,circuit(),selected_terminal=('source','a'))
    try:
        assert dialog.length.value()==dialog.area.value()==0
        dialog.accept();assert dialog.checked is None and dialog.status.text()
        dialog.target.setCurrentIndex(dialog.target.findData('load|a'))
        dialog.length.setValue(200);dialog.area.setValue(.5);dialog.name.setText('User lead');dialog.accept()
        assert dialog.checked.components[-1].name=='User lead' and dialog.checked.components[-1].a=='BAT'
        assert dialog.checked.components[-1].b=='LOAD'
    finally:close(dialog,app)


@pytest.mark.parametrize('mode',['physical','symbols'])
def test_visible_wire_add_delete_controls_make_saved_branch_with_safe_scene_rebuild(app,mode):
    original=circuit();dialog=ElectricalSchematicDialog(None,original,view_mode=mode);errors=[]
    try:
        dialog.show();app.processEvents()
        assert dialog.add_wire_button.isVisible() and not dialog.delete_wire_button.isEnabled()
        def fill():
            child=QApplication.activeModalWidget()
            try:
                assert isinstance(child,WireConnectionDialog)
                child.source.setCurrentIndex(child.source.findData('source|a'))
                child.target.setCurrentIndex(child.target.findData('load|a'))
                child.length.setValue(150);child.area.setValue(.5);child.name.setText('Selected lead');child.accept()
            except Exception as exc:errors.append(exc);child.reject()
        QTimer.singleShot(20,fill);dialog.add_wire_button.click();app.processEvents();assert not errors
        wire=dialog.workspace.components[-1];assert wire.kind=='wire' and dialog._selected_id()==wire.id
        if mode=='physical':
            assert wire.id in dialog.wire_paths
            item=dialog.wire_paths[wire.id]
            assert item.pen().color().name()=='#297dc2'
            dialog.scene.clearSelection()
            path=item.path();element=path.elementAt(path.elementCount()-1);previous=path.elementAt(path.elementCount()-2)
            from PySide6.QtCore import QPointF
            point=dialog.view.mapFromScene(QPointF((element.x+previous.x)/2,(element.y+previous.y)/2))
            QTest.mouseClick(dialog.view.viewport(),Qt.MouseButton.LeftButton,pos=point);app.processEvents()
            assert dialog._selected_id()==wire.id
        assert dialog.delete_wire_button.isEnabled() and dialog.apply_button.isEnabled()
        dialog.accept();assert dialog.accepted_workspace.components[-1].id==wire.id
        QTest.keyClick(dialog.view,Qt.Key.Key_Delete);app.processEvents()
        assert {item.id for item in dialog.workspace.components}=={'source','load'}
        assert dialog.workspace.nodes==original.nodes and original==circuit()
        assert not dialog.delete_wire_button.isEnabled()
    finally:close(dialog,app)


def test_readonly_main_wire_controls_request_direct_action_with_selected_context(app):
    dialog=ElectricalSchematicDialog(None,circuit(),editable=False);requests=[]
    dialog.wireActionRequested.connect(lambda action,context:requests.append((action,context)))
    try:
        dialog.selected_terminal=('source','a')
        dialog.add_wire_button.click();assert requests==[('add',('source','a'))]
        assert dialog.workspace==circuit()
    finally:close(dialog,app)


def test_exact_wire_endpoints_follow_movement_and_open_wire_is_dashed(app):
    wired=add_schematic_wire(circuit(),'source','a','load','a',name='Colored lead',length_mm=100,cross_section_mm2=.5,wire_color='#25A55F')
    wired.components[-1].closed=False
    dialog=ElectricalSchematicDialog(None,wired)
    try:
        from PySide6.QtCore import QPointF
        dialog.show();app.processEvents();wire=wired.components[-1]
        item=dialog.wire_paths[wire.id]
        assert item.pen().style()==Qt.PenStyle.DashLine and item.pen().color().name()=='#25a55f'
        for reference in wire.wire_endpoints:
            anchor=dialog.component_items[reference.component_id].port_scene_position(reference.terminal)
            assert item.shape().contains(anchor)
        dialog.component_items['load'].setPos(QPointF(1450,250));dialog._route()
        assert dialog.wire_paths[wire.id].shape().contains(dialog.component_items['load'].port_scene_position('a'))
    finally:close(dialog,app)


def test_changed_terminal_mapping_never_draws_a_false_endpoint_wire(app):
    wired=add_schematic_wire(circuit(),'source','a','load','a',name='Lead',length_mm=100,cross_section_mm2=.5)
    wired.components[1].a='BAT'
    dialog=ElectricalSchematicDialog(None,wired)
    try:
        assert wired.components[-1].id not in dialog.wire_paths
        assert dialog.component_items[wired.components[-1].id].isVisible()
    finally:close(dialog,app)


@pytest.mark.parametrize('reference',['chain','self','cycle'])
def test_wire_references_to_wire_bodies_preserve_safe_symbol_fallback(app,reference):
    wired=add_schematic_wire(circuit(),'source','a','load','a',name='First lead',length_mm=100,cross_section_mm2=.5)
    first=wired.components[-1]
    if reference=='chain':
        wired.components.append(wired.components[1].model_copy(update={'id':'other_load','name':'Other load'}))
        wired=add_schematic_wire(wired,first.id,'a','other_load','a',name='Branch lead',length_mm=100,cross_section_mm2=.5)
        fallback=wired.components[-1].id
    else:
        raw=wired.model_dump();row=raw['components'][-1]
        row['wire_endpoints']=[dict(component_id=first.id,terminal='a'),dict(component_id=first.id,terminal='b')]
        if reference=='cycle':
            peer={**row,'id':'WIRE_PEER','name':'Referenced lead'}
            peer['wire_endpoints']=[dict(component_id=first.id,terminal='a'),dict(component_id=first.id,terminal='b')]
            row['wire_endpoints']=[dict(component_id='WIRE_PEER',terminal='a'),dict(component_id='WIRE_PEER',terminal='b')]
            raw['components'].append(peer)
        wired=ElectricalWorkspace.model_validate(raw);fallback=first.id
    original=wired.model_dump();dialog=ElectricalSchematicDialog(None,wired)
    try:
        dialog.show();app.processEvents();dialog.fit_scene()
        assert fallback not in dialog.wire_paths and dialog.component_items[fallback].isVisible()
        assert dialog.workspace.model_dump()==original
        dialog.component_items[fallback].setSelected(True);dialog.delete_wire_button.click();app.processEvents()
        assert fallback not in dialog.component_items and not dialog.delete_wire_button.isEnabled()
    finally:close(dialog,app)
