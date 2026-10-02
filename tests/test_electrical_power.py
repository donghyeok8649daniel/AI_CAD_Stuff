"""Explicit source enable/disable behavior without changing battery ratings."""

import pytest

from cadstudio.electrical import ElectricalWorkspace, evaluate_electrical


def _circuit(enabled=True):
    return dict(nodes=['GND','SOURCE','VCC'],components=[
        dict(id='cell',name='Measured cell',kind='battery',a='SOURCE',b='GND',
             voltage_v=5,internal_resistance_ohm=.1,closed=enabled),
        dict(id='feed',name='Feed wire',kind='wire',a='SOURCE',b='VCC',
             length_mm=250,cross_section_mm2=.5),
        dict(id='board',name='Controller',kind='mcu',a='VCC',b='GND',
             rated_voltage_v=5,rated_current_a=.1),
    ])


def _branch(result, identifier):
    return next(item for item in result.components if item.id==identifier)


def test_battery_output_toggle_changes_dc_current_and_mcu_supply_path():
    on=evaluate_electrical(_circuit(True))
    off=evaluate_electrical(_circuit(False))
    assert _branch(on,'cell').current_a>0
    assert _branch(on,'board').current_a>0
    assert _branch(on,'board').supply_connected is True
    assert _branch(on,'board').return_connected is True
    assert _branch(off,'cell').current_a==0
    assert _branch(off,'cell').voltage_drop_v is None
    assert _branch(off,'feed').current_a==0
    assert _branch(off,'board').current_a==0
    assert _branch(off,'board').supply_connected is False
    assert _branch(off,'board').return_connected is False
    assert off.source_power_w==0
    assert any('전원 인가가 꺼져' in warning for warning in off.warnings)
    assert any('전원이 없어' in warning for warning in off.warnings)


def test_off_state_survives_project_round_trip_and_leaves_voltage_rating_intact():
    workspace=ElectricalWorkspace.model_validate(_circuit(False))
    restored=ElectricalWorkspace.model_validate_json(workspace.model_dump_json())
    cell=restored.components[0]
    assert cell.closed is False
    assert cell.voltage_v==5
    assert evaluate_electrical(restored).source_power_w==0
    old=ElectricalWorkspace.model_validate(_circuit())
    assert old.components[0].closed is True


def test_open_battery_does_not_erase_an_independent_enabled_source():
    circuit=_circuit(False)
    circuit['components'].append(dict(id='backup',name='Backup source',kind='battery',
        a='SOURCE',b='GND',voltage_v=5,internal_resistance_ohm=.2,closed=True))
    result=evaluate_electrical(circuit)
    assert _branch(result,'cell').current_a==0
    assert _branch(result,'backup').current_a>0
    assert _branch(result,'board').supply_connected is True
    assert _branch(result,'board').current_a>0
