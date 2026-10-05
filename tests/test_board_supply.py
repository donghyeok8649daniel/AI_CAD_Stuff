"""Physical supply pads are explicit, typed, and independent of DC operating data."""
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from cadstudio.board_supply import assign_board_supply_node,disconnect_board_supply_pin,board_supply_warnings
from cadstudio.circuit_connections import connect_schematic_terminals,disconnect_schematic_terminal
from cadstudio.electrical import ElectricalComponent,ElectricalWorkspace,evaluate_electrical
from cadstudio.mcu_connections import change_mcu_model,connection_endpoints


def circuit():
    return ElectricalWorkspace.model_validate(dict(nodes=['GND','POWER','ABSTRACT_LOAD','LEGACY'],components=[
        dict(id='battery',name='Five volt source',kind='battery',a='POWER',b='GND',voltage_v=5),
        dict(id='pi',name='Pi4',kind='mcu',catalog_id='rpi4b',a='ABSTRACT_LOAD',b='GND',analysis_enabled=False,
             signal_pins={'3V3_1':'LEGACY'}),
    ]))


def board(workspace):return next(component for component in workspace.components if component.id=='pi')


def test_absent_supply_defaults_stay_absent_through_old_project_serialization():
    original=circuit();component=board(original)
    for data in (component.model_dump(),json.loads(component.model_dump_json()),component.model_copy(deep=True).model_dump()):
        assert 'board_supply_pins' not in data and 'supply_pinout_catalog_id' not in data
    explicit=component.model_dump();explicit.update(board_supply_pins={},supply_pinout_catalog_id='')
    assert ElectricalComponent.model_validate(explicit).model_dump()==explicit


def test_explicit_physical_five_volt_and_ground_leave_abstract_load_and_legacy_signal_unchanged():
    original=circuit();before=original.model_dump()
    powered=connect_schematic_terminals(original,'pi','supply:5V_2','battery','a')
    powered=connect_schematic_terminals(powered,'pi','supply:GND_6','battery','b')
    assert board(powered).board_supply_pins=={'5V_2':'POWER','GND_6':'GND'}
    assert board(powered).supply_pinout_catalog_id=='rpi4b'
    assert (board(powered).a,board(powered).b)==('ABSTRACT_LOAD','GND')
    assert board(powered).signal_pins=={'3V3_1':'LEGACY'}
    assert original.model_dump()==before
    assert evaluate_electrical(powered).model_dump()==evaluate_electrical(original).model_dump()
    assert board_supply_warnings(powered,evaluate_electrical(powered))==()


@pytest.mark.parametrize('key',['GPIO17','RESET','GPIO0','missing','5V','../5V_2'])
def test_only_manufacturer_known_power_and_ground_pads_can_be_bound(key):
    original=circuit();before=original.model_dump()
    with pytest.raises(ValueError):assign_board_supply_node(original,'pi',key,'POWER')
    assert original.model_dump()==before


@pytest.mark.parametrize('catalog',['','unknown','arduino_uno_r3'])
def test_supply_provenance_must_match_exact_known_board(catalog):
    data=board(circuit()).model_dump();data.update(board_supply_pins={'5V_2':'POWER'},supply_pinout_catalog_id=catalog)
    with pytest.raises(ValidationError):ElectricalComponent.model_validate(data)


def test_workspace_rejects_unregistered_supply_net_and_non_mcu_supply_metadata():
    raw=circuit().model_dump();raw['components'][1].update(board_supply_pins={'5V_2':'MISSING'},supply_pinout_catalog_id='rpi4b')
    with pytest.raises(ValidationError):ElectricalWorkspace.model_validate(raw)
    raw['components'][1].update(kind='load',signal_pins={})
    with pytest.raises(ValidationError):ElectricalWorkspace.model_validate(raw)


def test_same_rail_aliases_are_consistent_but_never_automatically_added():
    powered=assign_board_supply_node(circuit(),'pi','5V_2','POWER')
    assert board(powered).board_supply_pins=={'5V_2':'POWER'}
    raw=powered.model_dump();raw['components'][1]['board_supply_pins']['5V_4']='GND'
    with pytest.raises(ValidationError,match='레일'):ElectricalWorkspace.model_validate(raw)
    both=assign_board_supply_node(powered,'pi','5V_4','POWER')
    moved=assign_board_supply_node(both,'pi','5V_2','NEW_POWER')
    assert board(moved).board_supply_pins=={'5V_2':'NEW_POWER','5V_4':'NEW_POWER'}
    assert '3V3_1' not in board(moved).board_supply_pins
    assert board(moved).signal_pins=={'3V3_1':'LEGACY'}


def test_multiple_explicit_ground_pads_cannot_assign_two_different_potentials():
    raw=circuit().model_dump();raw['components'][1].update(
        board_supply_pins={'GND_6':'GND','GND_9':'POWER'},supply_pinout_catalog_id='rpi4b')
    with pytest.raises(ValidationError,match='GND'):ElectricalWorkspace.model_validate(raw)


def test_disconnect_removes_only_selected_physical_wire_and_preserves_other_endpoints():
    powered=assign_board_supply_node(circuit(),'pi','5V_2','POWER')
    powered=assign_board_supply_node(powered,'pi','GND_6','GND')
    unplugged=disconnect_schematic_terminal(powered,'pi','supply:5V_2')
    assert board(unplugged).board_supply_pins=={'GND_6':'GND'}
    assert board(powered).board_supply_pins=={'5V_2':'POWER','GND_6':'GND'}
    assert board(unplugged).signal_pins==board(powered).signal_pins
    assert unplugged.nodes==powered.nodes and board(unplugged).a==board(powered).a
    assert disconnect_board_supply_pin(unplugged,'pi','5V_2').model_dump()==unplugged.model_dump()


def test_physical_pads_exist_as_unassigned_endpoints_without_inferred_power_connections():
    original=circuit();endpoints=connection_endpoints(original)
    pad=next(endpoint for endpoint in endpoints if endpoint.component_id=='pi' and endpoint.terminal=='supply:5V_2')
    assert pad.node is None and pad.pin_kind=='power'
    assert not any(endpoint.terminal=='supply:GPIO17' for endpoint in endpoints)
    assert not any(endpoint.terminal=='pin:3V3_1' and endpoint.node=='LEGACY' for endpoint in endpoints)


def test_model_change_requires_explicit_drop_consent_for_physical_supply_connections():
    original=assign_board_supply_node(circuit(),'pi','5V_2','POWER');before=original.model_dump()
    with pytest.raises(ValueError,match='명시적으로'):change_mcu_model(original,'pi','arduino_uno_r3')
    changed,dropped=change_mcu_model(original,'pi','arduino_uno_r3',allow_drop=True)
    assert dropped['supply:5V_2']=='POWER' and dropped['3V3_1']=='LEGACY'
    assert board(changed).board_supply_pins=={} and board(changed).supply_pinout_catalog_id==''
    assert original.model_dump()==before and changed.nodes==original.nodes


def test_registered_cad_board_model_change_requires_supply_disconnection_consent():
    from cadstudio.catalog import preset
    from cadstudio.electrical_registration import register_part
    from cadstudio.models import Design
    design=preset('cylinder');part_id=design.parts[0].id
    registered=register_part(design,part_id,dict(catalog_id='rpi4b'))
    identifier=registered.electrical.components[0].id
    raw=registered.model_dump();raw['electrical']=assign_board_supply_node(registered.electrical,identifier,'5V_2','POWER').model_dump()
    connected=Design.model_validate(raw);before=connected.model_dump()
    with pytest.raises(ValueError,match='명시적으로'):
        register_part(connected,part_id,dict(catalog_id='arduino_uno_r3'))
    changed=register_part(connected,part_id,dict(catalog_id='arduino_uno_r3',allow_drop_connections=True))
    assert changed.electrical.components[0].board_supply_pins=={}
    assert connected.model_dump()==before and changed.parts==connected.parts


def test_voltage_warnings_use_actual_supply_pin_rails_not_board_gpio_logic_voltage():
    original=circuit();wrong=assign_board_supply_node(original,'pi','3V3_1','POWER')
    wrong=assign_board_supply_node(wrong,'pi','GND_6','POWER')
    warnings=board_supply_warnings(wrong,evaluate_electrical(wrong))
    assert len(warnings)==2 and any('3.3 V' in warning and '5 V' in warning for warning in warnings)
    assert any('GND 핀' in warning for warning in warnings)
    correct=assign_board_supply_node(original,'pi','5V_2','POWER')
    assert board_supply_warnings(correct,evaluate_electrical(correct),'en')==()
    assert evaluate_electrical(correct).model_dump()==evaluate_electrical(original).model_dump()


def test_supply_warning_without_dc_result_is_empty_not_a_fabricated_nominal_voltage():
    powered=assign_board_supply_node(circuit(),'pi','3V3_1','POWER')
    assert board_supply_warnings(powered,None)==()


def test_explicit_supply_add_disconnect_undo_and_reopen_preserve_exact_history(tmp_path):
    from cadstudio.catalog import preset
    from cadstudio.models import Design
    from cadstudio.native.document import Document,Journal,read_project
    base=preset('cylinder').model_dump();base['electrical']=circuit().model_dump()
    document=Document();document.commit(Design.model_validate(base),'Legacy circuit');first=document.journal.data['cursor']
    powered=deepcopy(base);powered['electrical']=assign_board_supply_node(circuit(),'pi','5V_2','POWER').model_dump()
    document.commit(Design.model_validate(powered),'Wire physical board supply');second=document.journal.data['cursor']
    unplugged=deepcopy(powered);unplugged['electrical']=disconnect_board_supply_pin(ElectricalWorkspace.model_validate(powered['electrical']),'pi','5V_2').model_dump()
    document.commit(Design.model_validate(unplugged),'Unplug physical supply');third=document.journal.data['cursor']
    path=tmp_path/'physical-supply.cad.json';document.write(path);loaded=read_project(path)
    assert loaded.model_dump()==document.project().model_dump()
    journal=Journal(data=loaded.history.model_dump())
    assert journal.at(first)==base and journal.at(second)==powered and journal.at(third)==unplugged
    assert 'board_supply_pins' not in journal.at(first)['electrical']['components'][1]
