"""Passive storage elements and actuator DC estimates keep their real scope."""

from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from cadstudio.electrical import ElectricalComponent, ElectricalWorkspace, evaluate_electrical
from cadstudio.electrical_registration import register_part, registration_for_part, register_terminal_node
from cadstudio.mcu_connections import topology_warnings
from cadstudio.models import Design, DraftRequest, Part
from cadstudio.native.cad_electrical_tools import feature_context
from cadstudio.native.cad_schema import plan_schema
from cadstudio.native.cad_tools import execute_plan
from cadstudio.native.document import Document, read_project
from cadstudio.power_paths import build_power_path


NEW_DEFAULTS = dict(capacitance_f=0, inductance_h=0, winding_resistance_ohm=0,
                    capacitor_polarized=False)


def component(kind, **values):
    return dict(id='device', name='Device', kind=kind, a='BAT', b='GND', **values)


def supply(voltage=12):
    return dict(id='source', name='DC source', kind='battery', a='BAT', b='GND', voltage_v=voltage)


def branch(result, identifier='device'):
    return next(item for item in result.components if item.id == identifier)


def bodies():
    return Design(parts=[Part(id=key, name=key, color='#123456', transform=dict(x=index * 100),
                             geometry=dict(kind='plate', length=10, width=10, thickness=2, hole_count=0))
                         for index, key in enumerate(('capacitor', 'coil', 'drive'))])


def test_capacitor_is_dc_open_and_does_not_change_a_parallel_resistor_load():
    workspace = dict(nodes=['GND', 'BAT'], components=[supply(),
        dict(id='load', name='100 ohms', kind='resistor', a='BAT', b='GND', resistance_ohm=100),
        component('capacitor', capacitance_f=470e-6, rated_voltage_v=25, capacitor_polarized=True)])
    old = deepcopy(workspace)
    result = evaluate_electrical(workspace)
    assert workspace == old
    assert branch(result, 'source').current_a == pytest.approx(.12)
    assert branch(result).current_a == branch(result).power_w == 0
    assert branch(result).voltage_drop_v == pytest.approx(12)
    assert branch(result).resistance_ohm is None
    assert result.source_power_w == pytest.approx(result.absorbed_power_w)
    assert any('정상상태 DC' in item and 'ESR' in item for item in result.warnings)


def test_series_capacitor_blocks_dc_without_a_false_return_path():
    result = evaluate_electrical(dict(nodes=['GND', 'BAT', 'LOAD'], components=[supply(),
        {**component('capacitor', capacitance_f=1e-6, rated_voltage_v=25), 'b': 'LOAD'},
        dict(id='load', name='Load', kind='resistor', a='LOAD', b='GND', resistance_ohm=100)]))
    assert branch(result, 'source').current_a == branch(result, 'load').current_a == 0
    assert result.node_voltages_v['LOAD'] == 0
    assert branch(result).voltage_drop_v == pytest.approx(12)


@pytest.mark.parametrize('with_source', [False, True])
def test_capacitor_with_a_floating_terminal_does_not_invent_a_voltage(with_source):
    cap = {**component('capacitor', capacitance_f=100e-9), 'b': 'FLOAT'}
    result = evaluate_electrical(dict(nodes=['GND', 'BAT', 'FLOAT'], components=[
        *([supply()] if with_source else []), cap]))
    assert branch(result).voltage_drop_v is None and branch(result).current_a == 0
    assert 'FLOAT' not in result.node_voltages_v
    assert any('전압 차가 미정' in item for item in result.warnings)


def test_capacitor_on_a_floating_powered_island_has_relative_drop_only():
    result = evaluate_electrical(dict(nodes=['GND', 'BAT', 'RETURN'], components=[
        {**supply(), 'b': 'RETURN'},
        {**component('capacitor', capacitance_f=1e-6, rated_voltage_v=25), 'b': 'RETURN'}]))
    assert result.node_voltages_v == {'GND': 0}
    assert branch(result).voltage_drop_v == pytest.approx(12)
    assert branch(result).current_a == 0


def test_polarized_capacitor_reverse_and_overvoltage_are_both_reported():
    result = evaluate_electrical(dict(nodes=['GND', 'BAT'], components=[supply(),
        {**component('capacitor', capacitance_f=220e-6, rated_voltage_v=10,
                     capacitor_polarized=True), 'a': 'GND', 'b': 'BAT'}]))
    assert branch(result).voltage_drop_v == pytest.approx(-12)
    assert any('극성' in item and '반대' in item for item in result.warnings)
    assert any('전압 정격' in item and '초과' in item for item in result.warnings)


def test_coil_uses_winding_resistance_and_checks_entered_current_limit():
    result = evaluate_electrical(dict(nodes=['GND', 'BAT'], components=[supply(),
        component('inductor', inductance_h=.01, winding_resistance_ohm=24, max_current_a=.4)]))
    coil = branch(result)
    assert coil.current_a == pytest.approx(.5) and coil.power_w == pytest.approx(6)
    assert coil.resistance_ohm == 24
    assert result.source_power_w == pytest.approx(result.absorbed_power_w)
    assert any('권선 저항' in item and '역기전력' in item for item in result.warnings)
    assert any('최대' in item and '초과' in item for item in result.warnings)


def test_choke_in_mcu_power_path_preserves_supply_continuity_and_voltage_drop():
    result = evaluate_electrical(dict(nodes=['GND', 'BAT', 'VCC'], components=[supply(5),
        {**component('inductor', inductance_h=1e-3, winding_resistance_ohm=1), 'b': 'VCC'},
        dict(id='board', name='Board', kind='mcu', a='VCC', b='GND',
             rated_voltage_v=5, rated_current_a=.1)]))
    board = branch(result, 'board')
    assert board.supply_connected is board.return_connected is True
    assert board.current_a == pytest.approx(5 / 51)
    assert board.voltage_drop_v == pytest.approx(250 / 51)
    assert branch(result).voltage_drop_v == pytest.approx(5 / 51)


def test_actuator_has_explicit_running_and_separate_starting_estimates():
    result = evaluate_electrical(dict(nodes=['GND', 'BAT'], components=[
        {**supply(), 'internal_resistance_ohm': .2},
        component('actuator', rated_voltage_v=12, rated_current_a=1, startup_current_a=4)]))
    assert branch(result).current_a == pytest.approx(12 / 12.2)
    assert result.startup is not None
    assert branch(result.startup).current_a == pytest.approx(12 / 3.2)
    assert any('액추에이터' in item and '힘·속도·스트로크' in item for item in result.warnings)


def test_actuator_power_path_exposes_its_starting_report_and_capacity_check():
    made = build_power_path(None, dict(source_voltage_v=12, source_max_current_a=2,
        positive_wire_length_mm=100, positive_wire_cross_section_mm2=1,
        return_wire_length_mm=100, return_wire_cross_section_mm2=1,
        load_kind='actuator', load_voltage_v=12, load_current_a=1, load_startup_current_a=4))
    assert made.report.startup_current_a > 3.9
    assert made.report.current_a < 1
    assert made.report.startup_capacities[0].status == 'over_entered_limit'
    assert branch(made.result, made.ids['load']).kind == 'actuator'


@pytest.mark.parametrize('kind,fields', [
    ('capacitor', {}), ('capacitor', dict(capacitance_f=-1)),
    ('capacitor', dict(capacitance_f=float('nan'))),
    ('inductor', dict(inductance_h=.01)),
    ('inductor', dict(winding_resistance_ohm=1)),
    ('inductor', dict(inductance_h=.01, winding_resistance_ohm=0)),
    ('inductor', dict(inductance_h=.01, winding_resistance_ohm=float('inf'))),
    ('actuator', dict(rated_voltage_v=12)),
    ('resistor', dict(resistance_ohm=10, capacitance_f=1e-6)),
    ('resistor', dict(resistance_ohm=10, inductance_h=.01)),
    ('resistor', dict(resistance_ohm=10, winding_resistance_ohm=1)),
    ('resistor', dict(resistance_ohm=10, capacitor_polarized=True)),
    ('capacitor', dict(capacitance_f=1e-6, startup_current_a=1)),
])
def test_missing_invalid_or_wrong_kind_ratings_are_not_silently_guessed(kind, fields):
    with pytest.raises(ValidationError):
        ElectricalComponent.model_validate(component(kind, **fields))


@pytest.mark.parametrize('kind', ['capacitor', 'inductor', 'actuator'])
def test_pending_registration_can_be_created_without_invented_ratings(kind):
    old = bodies(); before = old.model_dump()
    identifier = {'capacitor': 'capacitor', 'inductor': 'coil', 'actuator': 'drive'}[kind]
    made = register_part(old, identifier, dict(kind=kind))
    model = registration_for_part(made, identifier)
    assert old.model_dump() == before and model.analysis_enabled is False
    assert model.capacitance_f == model.inductance_h == model.winding_resistance_ohm == 0
    assert model.rated_current_a == model.rated_voltage_v == 0
    for original, changed in zip(old.parts, made.parts):
        assert changed.geometry == original.geometry and changed.color == original.color
    assert branch(evaluate_electrical(made.electrical), model.id).voltage_drop_v is None


def test_passive_features_and_actuator_ports_survive_history_save_undo_redo(tmp_path):
    original = bodies(); doc = Document(); doc.commit(original, 'Original bodies')
    made = register_part(original, 'capacitor', dict(kind='capacitor', capacitance_f=470e-6,
        capacitor_polarized=True, rated_voltage_v=25, analysis_enabled=True))
    made = register_part(made, 'coil', dict(kind='inductor', inductance_h=.01,
        winding_resistance_ohm=10, analysis_enabled=True))
    made = register_part(made, 'drive', dict(kind='actuator', rated_voltage_v=12,
        rated_current_a=1, terminal_pins=dict(ENABLE='CONTROL'), analysis_enabled=True))
    doc.commit(made, 'Electrical features')
    expected = doc.project().model_dump(); path = tmp_path / 'passives.cad.json'
    doc.write(path); reopened = read_project(path)
    assert reopened.model_dump() == expected
    doc.load(reopened)
    first, last = doc.journal.path()[0]['id'], doc.journal.path()[-1]['id']
    doc.commit(doc.journal.at(first), 'Restore original', cursor=first)
    assert doc.design == original.model_dump()
    doc.commit(doc.journal.at(last), 'Restore electrical features', cursor=last)
    assert doc.design == made.model_dump()
    updated = register_terminal_node(made, 'drive', 'FEEDBACK', 'SENSE')
    assert registration_for_part(updated, 'drive').terminal_pins == dict(ENABLE='CONTROL', FEEDBACK='SENSE')


def test_legacy_component_omits_new_defaults_and_explicit_defaults_are_preserved():
    old = ElectricalComponent.model_validate(component('resistor', resistance_ohm=10))
    encoded = old.model_dump()
    assert not NEW_DEFAULTS.keys() & encoded.keys()
    assert ElectricalComponent.model_validate(encoded).model_dump() == encoded
    explicit = ElectricalComponent.model_validate({**encoded, **NEW_DEFAULTS})
    assert {key: explicit.model_dump()[key] for key in NEW_DEFAULTS} == NEW_DEFAULTS
    cap = ElectricalComponent.model_validate(component('capacitor', capacitance_f=1e-6))
    assert json.loads(cap.model_dump_json())['capacitance_f'] == 1e-6


@pytest.mark.parametrize('kind', ['actuator', 'inductor'])
def test_direct_gpio_to_actuator_or_coil_warns_in_both_languages(kind):
    workspace = dict(nodes=['GND', 'BAT', 'CONTROL'], components=[
        dict(id='board', name='MCU', kind='mcu', a='BAT', b='GND', analysis_enabled=False,
             signal_pins=dict(GPIO1='CONTROL')),
        {**component(kind, analysis_enabled=False), 'a': 'CONTROL'}])
    assert any('전력 단자' in item for item in topology_warnings(workspace))
    assert any('power terminal' in item for item in topology_warnings(workspace, 'en'))


def test_ai_registration_schema_and_execution_accept_si_passive_values_without_geometry_edits():
    schema = plan_schema(['electrical_register'], existing_parts=['capacitor', 'coil', 'drive'])
    args = schema['properties']['actions']['items']['anyOf'][0]['properties']['args']['properties']
    assert {'capacitor', 'inductor', 'actuator'} <= set(args['kind']['anyOf'][0]['enum'])
    assert {'capacitance_f', 'inductance_h', 'winding_resistance_ohm', 'capacitor_polarized'} <= set(args)
    original = bodies(); before = original.model_dump()
    sequence = [dict(tool='electrical_register', target='capacitor', args=dict(kind='capacitor', capacitance_f=1e-6)),
                dict(tool='electrical_register', target='coil', args=dict(kind='inductor', inductance_h=.001,
                     winding_resistance_ohm=2)),
                dict(tool='electrical_register', target='drive', args=dict(kind='actuator'))]
    reply = execute_plan(json.dumps(dict(summary='Register passive parts', actions=sequence)),
                         DraftRequest(prompt='기존 부품 전장으로 등록', current=original))
    assert original.model_dump() == before
    assert len(reply.design.parts) == 3 and len(reply.design.electrical.components) == 3
    for source, changed in zip(original.parts, reply.design.parts):
        assert source.geometry == changed.geometry and source.transform == changed.transform
    context = {item['part_id']: item for item in feature_context(reply.design)}
    assert context['capacitor']['capacitance_f'] == 1e-6
    assert context['coil']['inductance_h'] == .001
    assert context['coil']['winding_resistance_ohm'] == 2
    assert all(not item['analysis_enabled'] for item in context.values())
