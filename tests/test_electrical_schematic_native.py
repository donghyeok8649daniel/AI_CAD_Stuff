"""Real Qt electrical schematic and explicit battery-output controls."""

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from cadstudio.electrical import ElectricalComponent, ElectricalWorkspace, evaluate_electrical
from cadstudio.mcu_connections import connection_endpoints
from cadstudio.native.electrical_dialog import ComponentDialog, ElectricalDialog
from cadstudio.native.electrical_schematic import ElectricalSchematicDialog


@pytest.fixture(scope='module')
def app():
    qt=QApplication.instance() or QApplication([])
    qt.setQuitOnLastWindowClosed(False)
    yield qt
    qt.processEvents()


def circuit(*, battery_on=True, feed_connected=True):
    return dict(name='Supply and MCU',nodes=['GND','SUPPLY','VCC','SIG','REMOTE'],components=[
        dict(id='cell',name='Test cell',kind='battery',a='SUPPLY',b='GND',
             voltage_v=5,internal_resistance_ohm=.1,closed=battery_on),
        dict(id='feed',name='Power lead',kind='wire',a='SUPPLY',b='VCC',
             length_mm=250,cross_section_mm2=.5,closed=feed_connected),
        dict(id='board',name='Controller',kind='mcu',a='VCC',b='GND',
             rated_voltage_v=5,rated_current_a=.1,signal_pins={'GPIO1':'SIG'}),
        dict(id='signal',name='Signal lead',kind='wire',a='SIG',b='REMOTE',
             length_mm=100,cross_section_mm2=.5),
        dict(id='pull',name='Pull resistor',kind='resistor',a='REMOTE',b='GND',resistance_ohm=1000),
    ])


def test_logical_component_edit_is_queued_until_graphics_emitter_returns(app, monkeypatch):
    import shiboken6
    calls=[]
    def replace(self, identifier):
        calls.append(identifier)
        self._adopt(self.workspace.model_copy(deep=True))
    monkeypatch.setattr(ElectricalSchematicDialog,'edit_component',replace)
    dialog=ElectricalSchematicDialog(None,ElectricalWorkspace.model_validate(circuit()),view_mode='symbols')
    try:
        source=dialog.component_items['cell']
        source.activated.emit('cell')
        assert not calls and shiboken6.isValid(source)
        app.processEvents()
        assert calls==['cell'] and not shiboken6.isValid(source)
        assert shiboken6.isValid(dialog.component_items['cell'])
    finally:
        dialog.reject()


def test_new_battery_requires_entered_voltage_and_toggle_preserves_rating(app):
    form=ComponentDialog(None,[])
    try:
        assert form.kind.currentData()=='battery'
        assert form.inputs['voltage_v'].value()==0
        assert form.power_enabled.isChecked()
        with pytest.raises(ValueError,match='배터리'):
            ElectricalComponent.model_validate(form.candidate())
        form.inputs['voltage_v'].setValue(5)
        form.power_enabled.setChecked(False)
        candidate=form.candidate()
        assert candidate['closed'] is False
        assert candidate['voltage_v']==5
        assert candidate['a']=='VPLUS' and candidate['b']=='GND'
        assert ElectricalComponent.model_validate(candidate).closed is False
    finally:
        form.reject()


def test_main_editor_switches_selected_battery_without_erasing_voltage(app):
    dialog=ElectricalDialog(None,dict(parts=[],electrical=circuit()))
    try:
        dialog.table.selectRow(0)
        assert dialog.power_button.isEnabled()
        assert '전원 차단' in dialog.power_button.text()
        assert 'POWER ON' in dialog.report.toPlainText()
        dialog.power_button.click()
        assert dialog.components[0]['closed'] is False
        assert dialog.components[0]['voltage_v']==5
        assert '전원 OFF' in dialog.table.item(0,5).text()
        report=dialog.report.toPlainText()
        assert 'POWER OFF · Test cell' in report
        assert 'FAIL · Controller: VCC' in report
        assert evaluate_electrical(dialog.candidate()).source_power_w==0
        dialog.power_button.click()
        assert dialog.components[0]['closed'] is True
        assert 'POWER ON · Test cell' in dialog.report.toPlainText()
        assert evaluate_electrical(dialog.candidate()).source_power_w>0
    finally:
        dialog.reject()


def test_separate_schematic_uses_real_nodes_endpoints_and_signal_pins(app):
    workspace=ElectricalWorkspace.model_validate(circuit())
    result=evaluate_electrical(workspace)
    schematic=ElectricalSchematicDialog(None,workspace,result,view_mode='symbols')
    try:
        assert set(schematic.node_positions)==set(workspace.nodes)
        assert set(schematic.branch_layout)=={part.id for part in workspace.components}
        assert set(schematic.component_items)=={part.id for part in workspace.components}
        for component in workspace.components:
            branch=schematic.branch_layout[component.id]
            assert branch['a']==component.a and branch['b']==component.b
            assert (component.id,'a') in schematic.endpoint_coordinates
            assert (component.id,'b') in schematic.endpoint_coordinates
            assert branch['a_x']==schematic.endpoint_coordinates[(component.id,'a')].x()
            assert branch['b_x']==schematic.endpoint_coordinates[(component.id,'b')].x()
        assert schematic.branch_layout['feed']['active'] is True
        signal=schematic.branch_layout['board']['signals']['GPIO1']
        assert signal['node']=='SIG'
        point=schematic.endpoint_coordinates[('board','pin:GPIO1')]
        assert (signal['origin_x'],signal['origin_y'])==(point.x(),point.y())
        assert signal['connected'] is True
        # Conductors terminate on the actual drawn component pads. The old
        # node-bus table could pass net-name tests while showing no board wiring.
        by_node={}
        for endpoint in connection_endpoints(workspace):
            if endpoint.node is not None:
                by_node.setdefault(endpoint.node,[]).append(endpoint)
        for node,endpoints in by_node.items():
            if len(endpoints)<2:continue
            assert schematic.net_segments[node]
            for endpoint in endpoints:
                point=schematic.endpoint_coordinates[(endpoint.component_id,endpoint.terminal)]
                assert any(_on_line(point,item.line()) for item in schematic.net_segments[node])
        assert workspace.model_dump()==ElectricalWorkspace.model_validate(circuit()).model_dump()
        before=schematic.view.transform().m11()
        schematic.view.scale(1.25,1.25)
        assert schematic.view.transform().m11()==pytest.approx(before*1.25)
        schematic.fit_scene()
    finally:
        schematic.reject()


def _on_line(point,line):
    epsilon=1e-5
    return ((abs(line.y1()-line.y2())<epsilon and abs(point.y()-line.y1())<epsilon
             and min(line.x1(),line.x2())-epsilon<=point.x()<=max(line.x1(),line.x2())+epsilon)
            or (abs(line.x1()-line.x2())<epsilon and abs(point.x()-line.x1())<epsilon
                and min(line.y1(),line.y2())-epsilon<=point.y()<=max(line.y1(),line.y2())+epsilon))


def test_schematic_marks_open_power_and_wire_without_fake_voltage(app):
    workspace=ElectricalWorkspace.model_validate(circuit(battery_on=False,feed_connected=False))
    result=evaluate_electrical(workspace)
    schematic=ElectricalSchematicDialog(None,workspace,result,view_mode='symbols')
    try:
        assert schematic.branch_layout['cell']['active'] is False
        assert schematic.branch_layout['feed']['active'] is False
        assert schematic.branch_layout['cell']['a']=='SUPPLY'
        cell=next(part for part in result.components if part.id=='cell')
        assert cell.current_a==0 and cell.voltage_drop_v is None
        text=' '.join(item.toPlainText() for item in schematic.scene.items() if hasattr(item,'toPlainText'))
        assert 'OFF · 0 A' in text and '단선 · 0 A' in text
    finally:
        schematic.reject()


def test_main_editor_opens_an_independent_schematic_window(app,monkeypatch):
    seen=[]

    def inspect(self):
        seen.append((self.workspace.name,set(self.node_positions),self.result.source_power_w))
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(ElectricalSchematicDialog,'exec',inspect)
    dialog=ElectricalDialog(None,dict(parts=[],electrical=circuit()))
    try:
        dialog.schematic_button.click()
        assert len(seen)==1
        assert seen[0][:2]==('Supply and MCU',{'GND','SUPPLY','VCC','SIG','REMOTE'})
        assert seen[0][2]>0
        assert dialog.components[0]['closed'] is True
    finally:
        dialog.reject()
