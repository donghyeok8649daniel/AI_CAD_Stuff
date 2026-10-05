"""Ordinary board editors preserve explicit physical supplies or confirm removal."""
import pytest
from PySide6.QtWidgets import QApplication

from cadstudio.board_supply import assign_board_supply_node
from cadstudio.electrical import ElectricalWorkspace
from cadstudio.native.electrical_dialog import ComponentDialog,ElectricalDialog
from cadstudio.native.mcu_pin_dialog import McuBoardDialog


@pytest.fixture(scope='module')
def app():
    instance=QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    yield instance


def circuit():
    workspace=ElectricalWorkspace.model_validate(dict(nodes=['GND','ABSTRACT'],components=[
        dict(id='pi',name='Pi board',kind='mcu',catalog_id='rpi4b',a='ABSTRACT',b='GND',analysis_enabled=False)]))
    return assign_board_supply_node(workspace,'pi','5V_2','POWER')


def test_component_name_edit_and_parent_editor_keep_physical_supply_metadata(app):
    workspace=circuit();component=workspace.components[0];before=workspace.model_dump()
    dialog=ComponentDialog(None,[],component.model_dump())
    try:
        dialog.name.setText('Renamed board');candidate=dialog.candidate()
        assert candidate['board_supply_pins']=={'5V_2':'POWER'} and candidate['supply_pinout_catalog_id']=='rpi4b'
    finally:dialog.reject()
    editor=ElectricalDialog(None,dict(parts=[],electrical=before))
    try:
        assert editor.candidate().model_dump()['components'][0]['board_supply_pins']=={'5V_2':'POWER'}
        assert workspace.model_dump()==before
    finally:editor.reject()


def test_board_model_modal_requires_consent_and_removes_only_supply_bindings_for_changed_model(app):
    workspace=circuit();before=workspace.model_dump()
    dialog=McuBoardDialog(None,workspace,[],workspace.components[0])
    try:
        assert dialog.candidate().board_supply_pins=={'5V_2':'POWER'}
        dialog.model_combo.setCurrentIndex(dialog.model_combo.findData('arduino_uno_r3'))
        assert dialog.assignments_to_drop()=={'supply:5V_2':'POWER'}
        with pytest.raises(ValueError,match='확인'):dialog.candidate()
        dialog.dropped_confirmed=True
        candidate=dialog.candidate()
        assert candidate.board_supply_pins=={} and candidate.supply_pinout_catalog_id==''
        assert workspace.model_dump()==before
    finally:dialog.reject()
