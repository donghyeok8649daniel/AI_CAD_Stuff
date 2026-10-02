"""Single-source power-path generation and honest DC loss/capacity reporting."""

from copy import deepcopy

import pytest

from cadstudio.electrical import ElectricalWorkspace, evaluate_electrical
from cadstudio.power_paths import (PowerInputRequired, PowerPathSpec, build_power_path,
                                   format_power_path_report)


def spec(**changes):
    data = dict(name='Controller supply', source_voltage_v=12,
                source_internal_resistance_ohm=.2, switch_contact_resistance_ohm=.05,
                positive_wire_length_mm=1000, positive_wire_cross_section_mm2=1,
                positive_wire_resistivity_ohm_mm2_per_m=.1,
                return_wire_length_mm=1000, return_wire_cross_section_mm2=1,
                return_wire_resistivity_ohm_mm2_per_m=.1,
                load_kind='mcu', load_voltage_v=12, load_current_a=1)
    data.update(changes)
    return data


def branch(build, key):
    return next(item for item in build.result.components if item.id == build.ids[key])


def test_missing_actual_values_cannot_generate_or_append_a_path():
    original = dict(nodes=['GND'], components=[])
    with pytest.raises(ValueError, match='source_voltage_v'):
        build_power_path(original, dict(spec(), source_voltage_v=0))
    with pytest.raises(ValueError, match='positive_wire_length_mm'):
        build_power_path(original, dict(spec(), positive_wire_length_mm=0))
    with pytest.raises(ValueError, match='load_current_a'):
        build_power_path(original, dict(spec(), load_current_a=0))
    assert original == dict(nodes=['GND'], components=[])


def test_missing_operating_values_return_actionable_typed_error():
    incomplete = spec()
    del incomplete['source_voltage_v']
    incomplete['positive_wire_length_mm'] = 0
    with pytest.raises(PowerInputRequired) as captured:
        build_power_path(None, incomplete)
    assert captured.value.missing_fields == ('source_voltage_v', 'positive_wire_length_mm')
    assert '배터리 전압(V)' in str(captured.value)
    assert '공급선 길이(mm)' in str(captured.value)


def test_generated_source_switch_feed_load_return_has_real_series_path_and_losses():
    build = build_power_path(None, spec())
    items = {key: next(c for c in build.workspace.components if c.id == identifier)
             for key, identifier in build.ids.items()}
    assert [items[key].kind for key in ('source', 'switch', 'feed', 'load', 'return')] == [
        'battery', 'switch', 'wire', 'mcu', 'wire']
    assert items['source'].a == items['switch'].a
    assert items['switch'].b == items['feed'].a
    assert items['feed'].b == items['load'].a
    assert items['load'].b == items['return'].a
    assert items['return'].b == items['source'].b == 'GND'
    expected = 12 / (12 + .2 + .05 + .1 + .1)
    report = build.report
    assert report.state == 'energized'
    assert report.current_a == pytest.approx(expected)
    assert branch(build, 'load').supply_connected is True
    assert branch(build, 'load').return_connected is True
    assert report.load_voltage_v == pytest.approx(expected * 12)
    assert report.positive_wire_drop_v == pytest.approx(expected * .1)
    assert report.return_wire_drop_v == pytest.approx(expected * .1)
    assert report.battery_internal_loss_w == pytest.approx(expected**2 * .2)
    assert report.positive_wire_loss_w == pytest.approx(expected**2 * .1)
    assert report.return_wire_loss_w == pytest.approx(expected**2 * .1)
    assert report.switch_loss_w == pytest.approx(expected**2 * .05)
    assert report.open_circuit_power_w == pytest.approx(12 * expected)
    assert report.terminal_output_w == pytest.approx((12 - expected * .2) * expected)
    assert report.balance_error_w < 1e-9


def test_off_source_or_open_switch_delivers_zero_current_without_erasing_rating():
    for change, state in (({'source_enabled': False}, 'source_off'),
                          ({'switch_closed': False}, 'switch_open')):
        build = build_power_path(None, spec(**change))
        assert build.report.state == state
        assert build.report.current_a == 0
        assert build.report.open_circuit_power_w == 0
        assert build.report.terminal_output_w == 0
        assert branch(build, 'load').current_a == 0
        assert next(c for c in build.workspace.components if c.id == build.ids['source']).voltage_v == 12
        assert evaluate_electrical(ElectricalWorkspace.model_validate_json(
            build.workspace.model_dump_json())).source_power_w == 0


def test_missing_capacity_is_unverified_and_entered_limit_is_only_an_input_check():
    unknown = build_power_path(None, spec())
    assert all(check.status == 'unverified' for check in unknown.report.capacities)
    assert format_power_path_report(unknown).count('용량 미검증') == 4
    assert format_power_path_report(unknown, 'en').count('capacity unverified') == 4
    checked = build_power_path(None, spec(source_max_current_a=.5,
                                          switch_max_current_a=2,
                                          positive_wire_max_current_a=.3,
                                          return_wire_max_current_a=2))
    assert [c.status for c in checked.report.capacities] == [
        'over_entered_limit', 'within_entered_limit', 'over_entered_limit', 'within_entered_limit']
    report = format_power_path_report(checked)
    assert 'FAIL · 배터리' in report and 'FAIL · 공급선' in report
    assert '제품 허용 범위나 제작 안전 인증은 아닙니다' in report


def test_existing_components_and_nodes_are_unchanged_and_new_identifiers_are_unique():
    old = dict(name='Existing circuit', nodes=['GND', 'OLD', 'PWR0001_SOURCE'], components=[
        dict(id='powerpath_0001_source', name='Old wire', kind='wire',
             a='OLD', b='GND', length_mm=100, cross_section_mm2=1),
    ])
    snapshot = deepcopy(old)
    first = build_power_path(old, spec(source_part_id='cell_body', load_part_id='control_board'))
    assert old == snapshot
    assert len(first.workspace.components) == len(old['components']) + 5
    assert first.workspace.components[0].model_dump()['id'] == old['components'][0]['id']
    assert first.ids['source'].startswith('powerpath_0002_')
    assert set(old['nodes']).issubset(set(first.workspace.nodes))
    assert next(c for c in first.workspace.components if c.id == first.ids['load']).part_id == 'control_board'
    restored = ElectricalWorkspace.model_validate_json(first.workspace.model_dump_json())
    second = build_power_path(restored, spec(name='Second path'))
    assert len(second.workspace.components) == len(old['components']) + 10
    assert set(first.ids.values()).isdisjoint(second.ids.values())
    assert [c.model_dump() for c in second.workspace.components[:6]] == [
        c.model_dump() for c in restored.components]


def test_motor_startup_is_distinct_input_scenario_and_not_mcu_firmware():
    build = build_power_path(None, spec(load_kind='motor', load_startup_current_a=3,
                                        source_max_current_a=1.5))
    assert build.result.startup is not None
    running = branch(build, 'load').current_a
    startup = next(b.current_a for b in build.result.startup.components if b.id == build.ids['load'])
    assert startup > running
    assert build.report.capacities[0].status == 'within_entered_limit'
    assert build.report.startup_capacities[0].status == 'over_entered_limit'
    assert 'FAIL · 기동 배터리' in format_power_path_report(build)
    with pytest.raises(ValueError, match='기동 전류'):
        PowerPathSpec.model_validate(spec(load_kind='mcu', load_startup_current_a=3))


def test_unrelated_existing_motor_startup_does_not_label_new_mcu_as_starting():
    motor = build_power_path(None, spec(load_kind='motor', load_startup_current_a=3))
    mcu = build_power_path(motor.workspace, spec(name='Control supply'))
    assert mcu.result.startup is not None  # Solver evaluates the entire circuit.
    assert mcu.report.startup_current_a is None
    assert mcu.report.startup_capacities == ()
    assert '기동' not in format_power_path_report(mcu)


def test_exact_wire_sku_uses_source_dcr_without_inventing_harness_ampacity():
    from cadstudio.mechanical_catalog import get_catalog_entry

    entry = get_catalog_entry('belden_9918')
    assert entry is not None and entry.wire_spec is not None
    build = build_power_path(None, spec(positive_wire_catalog_id=entry.catalog_id,
                                        return_wire_catalog_id=entry.catalog_id,
                                        positive_wire_length_mm=304.8,
                                        return_wire_length_mm=609.6,
                                        positive_wire_cross_section_mm2=.75,
                                        return_wire_cross_section_mm2=.75))
    feed = next(c for c in build.workspace.components if c.id == build.ids['feed'])
    ret = next(c for c in build.workspace.components if c.id == build.ids['return'])
    assert feed.catalog_id == ret.catalog_id == 'belden_9918'
    assert feed.source_url == ret.source_url == entry.source_url
    assert branch(build, 'feed').resistance_ohm == pytest.approx(entry.wire_spec.dcr_ohm_per_1000ft / 1000)
    assert branch(build, 'return').resistance_ohm == pytest.approx(2 * entry.wire_spec.dcr_ohm_per_1000ft / 1000)
    assert feed.max_current_a is None and ret.max_current_a is None
    assert build.report.capacities[2].status == build.report.capacities[3].status == 'unverified'
    with pytest.raises(ValueError, match='정확한 전선 SKU'):
        build_power_path(None, spec(positive_wire_catalog_id='nonexistent'))
