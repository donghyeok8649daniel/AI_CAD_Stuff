"""Averaged motor dynamics must validate wiring and close a real feedback loop."""

from copy import deepcopy
from math import floor, pi
from threading import Event

import pytest
from pydantic import ValidationError

from cadstudio.drive_simulation import (DriveSimulationSpec, MAX_TRACE_POINTS,
    preflight_drive, simulate_drive, synthetic_drive_demo)
from cadstudio.models import Design


def changed(raw, **values):
    return DriveSimulationSpec.model_validate({**raw.model_dump(), **values})


def modify(design, identifier, **values):
    raw = design.model_dump()
    component = next(item for item in raw['electrical']['components'] if item['id'] == identifier)
    component.update(values)
    for node in (component['a'], component['b'], *component.get('terminal_pins', {}).values(),
                 *component.get('signal_pins', {}).values()):
        if node not in raw['electrical']['nodes']:
            raw['electrical']['nodes'].append(node)
    return Design.model_validate(raw)


def bldc_fixture():
    design, spec = synthetic_drive_demo()
    design = modify(design, 'controller', catalog_id='st_b_g431b_esc1',
        product_pinout_catalog_id='st_b_g431b_esc1',
        terminal_pins=dict(BAT_POS='BAT', BAT_NEG='GND', MOTOR_U='PHASE_U', MOTOR_V='PHASE_V', MOTOR_W='PHASE_W',
            SENSOR_A_H1='SENSE_A', SENSOR_B_H2='SENSE_B', SENSOR_5V='ENCODER_SUPPLY', SENSOR_GND='GND'))
    design = modify(design, 'motor', terminal_pins=dict(MOTOR_U='PHASE_U', MOTOR_V='PHASE_V', MOTOR_W='PHASE_W'))
    design = modify(design, 'encoder', a='ENCODER_SUPPLY')
    return design, changed(spec, motor_type='bldc_average', controller_type='three_phase_esc', voltage_limit_fraction=.95)


def test_virtual_fixture_converges_with_explicit_measured_feedback_and_no_mutation():
    design, spec = synthetic_drive_demo(); before = deepcopy(design.model_dump())
    result = simulate_drive(design, spec)
    assert design.model_dump() == before
    assert 'VIRTUAL' in design.name and all('VIRTUAL' in component.name for component in design.electrical.components)
    assert result.status == 'converged' and result.summary.convergence
    assert result.summary.final_speed_rpm == pytest.approx(600, abs=2)
    assert result.summary.mean_tail_error_rpm < 2
    assert not result.faults and all(result.connections.values())
    assert 1 < len(result.points) <= MAX_TRACE_POINTS
    assert result.summary.peak_current_a <= spec.current_limit_a
    assert result.summary.min_bus_voltage_v < 12
    assert result.summary.steps == 800 and result.summary.elapsed_s == 4
    assert any('No MCU code execution' in item for item in result.assumptions)


def test_drive_simulation_is_bitwise_deterministic_and_encoder_counts_are_quantized():
    design, spec = synthetic_drive_demo()
    first = simulate_drive(design, spec); second = simulate_drive(design, spec)
    assert first.model_dump() == second.model_dump()
    previous = first.points[0]
    for point in first.points[1:]:
        assert point.encoder_counts == floor(point.angle_rad * spec.encoder_ticks_per_rev / (2*pi))
        measured_rpm = (point.encoder_counts - previous.encoder_counts) * 60 / (spec.encoder_ticks_per_rev * (point.time_s - previous.time_s))
        assert point.encoder_speed_rpm == pytest.approx(measured_rpm)
        assert abs(point.duty_cycle) <= 1
        assert abs(point.current_a) <= spec.current_limit_a
        previous = point


def test_insufficient_torque_and_current_limit_cannot_claim_target_reached():
    design, spec = synthetic_drive_demo()
    result = simulate_drive(design, changed(spec, current_limit_a=.2, overspeed_rpm=100000))
    assert result.status == 'not_converged' and not result.summary.convergence
    assert result.summary.current_limited_fraction > .9
    assert result.summary.peak_current_a <= .2
    assert result.summary.final_speed_rpm < 0  # Resisting load back-drives this underpowered motor.
    assert any('Target not reached' in item for item in result.warnings)
    assert any('Ideal current limit' in item for item in result.warnings)


def test_voltage_limited_target_is_reported_without_integral_windup_success():
    design, spec = synthetic_drive_demo()
    result = simulate_drive(design, changed(spec, target_rpm=3000, overspeed_rpm=10000,
        duration_s=8, proportional_gain_v_per_rad_s=.5, integral_gain_v_per_rad=10))
    assert result.status == 'not_converged' and not result.summary.convergence
    assert result.summary.voltage_limited_fraction > .9
    assert result.summary.final_speed_rpm < 1200
    assert all(abs(point.current_a) <= spec.current_limit_a for point in result.points)


@pytest.mark.parametrize('fault', ['flag', 'wire', 'same_net', 'missing_power'])
def test_encoder_disconnection_and_incorrect_channels_block_output(fault):
    design, spec = synthetic_drive_demo()
    if fault == 'flag':
        spec = changed(spec, encoder_connected=False)
    elif fault == 'wire':
        design = modify(design, 'encoder', terminal_pins=dict(ENCODER_A='UNPLUGGED', ENCODER_B='SENSE_B'))
    elif fault == 'same_net':
        design = modify(design, 'encoder', terminal_pins=dict(ENCODER_A='SENSE_A', ENCODER_B='SENSE_A'))
    else:
        design = modify(design, 'encoder', a='UNPOWERED')
    result = simulate_drive(design, spec)
    assert result.status == 'blocked' and result.summary.steps == 0
    assert result.points[0].current_a == 0 and not result.summary.convergence
    assert any(item.startswith('encoder_') for item in result.faults)


@pytest.mark.parametrize('what', ['enable', 'source'])
def test_disabled_drive_or_battery_has_zero_output(what):
    design, spec = synthetic_drive_demo()
    if what == 'enable':
        spec = changed(spec, enabled=False)
    else:
        design = modify(design, 'source', closed=False)
    result = simulate_drive(design, spec)
    assert result.status == 'disabled' and result.summary.steps == 0
    assert result.summary.peak_current_a == result.summary.final_speed_rpm == 0


def test_negative_encoder_feedback_polarity_trips_instead_of_claiming_closed_loop_success():
    design, spec = synthetic_drive_demo()
    result = simulate_drive(design, changed(spec, encoder_polarity=-1))
    assert result.status == 'fault' and not result.summary.convergence
    assert any(item.startswith('feedback_polarity_fault:') for item in result.faults)
    assert result.summary.elapsed_s < spec.duration_s
    assert result.points[-1].speed_rpm > 0 and result.points[-1].encoder_speed_rpm < 0


def test_speed_cutoff_stops_unstable_or_aggressive_drive():
    design, spec = synthetic_drive_demo()
    result = simulate_drive(design, changed(spec, target_rpm=600, overspeed_rpm=610,
        proportional_gain_v_per_rad_s=.5, integral_gain_v_per_rad=5))
    assert result.status == 'fault'
    assert any(item.startswith('overspeed_fault:') for item in result.faults)
    assert result.summary.elapsed_s < spec.duration_s


def test_battery_sag_tracks_load_and_voltage_collapse_is_a_fault():
    design, spec = synthetic_drive_demo()
    nominal = simulate_drive(design, spec)
    weak = simulate_drive(modify(design, 'source', internal_resistance_ohm=1000), changed(spec, duration_s=.1))
    assert weak.summary.min_bus_voltage_v < nominal.summary.min_bus_voltage_v
    assert weak.status == 'fault'
    assert any(item.startswith('source_voltage_collapse:') for item in weak.faults)


def test_preflight_requires_real_registered_cad_ids_and_preserves_unrelated_design():
    design, spec = synthetic_drive_demo()
    missing = simulate_drive(design, changed(spec, motor_id='not_registered'))
    unregistered = simulate_drive(modify(design, 'motor', part_registration=False), spec)
    assert missing.status == unregistered.status == 'blocked'
    assert any(item.startswith('unregistered_motor:') for item in missing.faults)
    before = deepcopy(design.model_dump())
    simulate_drive(design, spec)
    assert design.model_dump() == before


@pytest.mark.parametrize('what', ['driver_input', 'motor_output', 'motor_bypass'])
def test_unpowered_disconnected_or_bypassed_driver_cannot_claim_motor_operation(what):
    design, spec = synthetic_drive_demo()
    if what == 'driver_input':
        design = modify(design, 'controller', a='UNPOWERED')
    elif what == 'motor_output':
        design = modify(design, 'controller', terminal_pins=dict(IN_A='SENSE_A', IN_B='SENSE_B'))
    else:
        design = modify(design, 'motor', a='BAT')
        design = modify(design, 'controller', terminal_pins=dict(OUT_A='BAT', OUT_B='MRETURN', IN_A='SENSE_A', IN_B='SENSE_B'))
    result = simulate_drive(design, spec)
    assert result.status == 'blocked' and result.summary.steps == 0


def test_documented_b_g431_only_accepts_explicit_three_phase_averaged_model():
    design, spec = bldc_fixture()
    result = simulate_drive(design, spec)
    assert result.status == 'converged'
    assert result.motor_type == 'bldc_average'
    assert any('phase-resolved' in item for item in result.assumptions)
    dc = simulate_drive(design, changed(spec, motor_type='dc', controller_type='dc_driver'))
    assert dc.status == 'blocked'
    assert any(item.startswith('incompatible_motor_driver:') for item in dc.faults)


@pytest.mark.parametrize('change', ['missing_phase', 'shorted_phases', 'missing_battery_pad', 'swapped_phase'])
def test_b_g431_requires_all_three_distinct_phase_connections_and_explicit_battery_pads(change):
    design, spec = bldc_fixture()
    controller = next(item for item in design.electrical.components if item.id == 'controller')
    mapping = deepcopy(controller.terminal_pins)
    if change == 'missing_phase':
        mapping.pop('MOTOR_W')
    elif change == 'shorted_phases':
        mapping['MOTOR_W'] = mapping['MOTOR_V']
    elif change == 'missing_battery_pad':
        mapping.pop('BAT_POS')
    else:
        mapping['MOTOR_V'], mapping['MOTOR_W'] = mapping['MOTOR_W'], mapping['MOTOR_V']
    result = simulate_drive(modify(design, 'controller', terminal_pins=mapping), spec)
    assert result.status == 'blocked'
    assert result.summary.steps == 0 and not result.summary.convergence


def test_integrated_pololu_encoder_uses_separate_encoder_supply_and_actual_stable_motor_keys():
    design, spec = synthetic_drive_demo()
    design = modify(design, 'motor', catalog_id='pololu_4755', product_pinout_catalog_id='pololu_4755',
        terminal_pins=dict(MOTOR_RED='MPLUS', MOTOR_BLACK='MRETURN', ENCODER_VCC='BAT', ENCODER_GND='GND',
                           ENCODER_A='SENSE_A', ENCODER_B='SENSE_B'))
    spec = changed(spec, encoder_id='motor', encoder_ticks_per_rev=64)
    check = preflight_drive(design, spec)
    assert not check.faults and all(check.connections.values())
    broken = deepcopy(next(item for item in design.electrical.components if item.id == 'motor').terminal_pins)
    broken.pop('ENCODER_VCC')
    result = simulate_drive(modify(design, 'motor', terminal_pins=broken), spec)
    assert result.status == 'blocked'
    assert any(item.startswith('encoder_power_disconnected:') for item in result.faults)


def test_known_encoder_cannot_be_registered_as_a_motor_or_controller_for_simulation():
    design, spec = synthetic_drive_demo()
    design = modify(design, 'encoder', catalog_id='omron_e6b2_cwz6c_1000',
        product_pinout_catalog_id='omron_e6b2_cwz6c_1000', terminal_pins=dict(ENCODER_VCC='BAT', ENCODER_GND='GND',
            ENCODER_A='SENSE_A', ENCODER_B='SENSE_B'))
    check = preflight_drive(design, changed(spec, controller_id='encoder'))
    assert any(item.startswith('unsupported_controller_product:') for item in check.faults)


def test_known_mcu_does_not_implicitly_become_a_power_driver():
    design, spec = synthetic_drive_demo()
    design = modify(design, 'controller', kind='mcu', catalog_id='rpi4b', pinout_catalog_id='rpi4b',
        terminal_pins={}, signal_pins=dict(GPIO17='SENSE_A', GPIO18='SENSE_B'))
    check = preflight_drive(design, spec)
    assert any(item.startswith('unsupported_driver_product:') for item in check.faults)


def test_separate_mcu_and_driver_require_a_saved_command_connection():
    design, spec = synthetic_drive_demo(); raw = design.model_dump()
    raw['parts'].append(dict(id='bridge', name='VIRTUAL separate H-bridge',
                            geometry=dict(kind='plate', length=10, width=10, thickness=2, hole_count=0)))
    raw['electrical']['components'].append(dict(id='bridge', part_id='bridge', part_registration=True,
        name='VIRTUAL H-bridge', kind='load', a='BAT', b='GND', analysis_enabled=False,
        terminal_pins=dict(OUT_A='MPLUS', OUT_B='MRETURN', CMD='CONTROL')))
    raw['electrical']['nodes'].append('CONTROL')
    design = Design.model_validate(raw)
    design = modify(design, 'controller', terminal_pins=dict(IN_A='SENSE_A', IN_B='SENSE_B', PWM='CONTROL'))
    spec = changed(spec, driver_id='bridge')
    assert not preflight_drive(design, spec).faults
    disconnected = modify(design, 'controller', terminal_pins=dict(IN_A='SENSE_A', IN_B='SENSE_B'))
    result = simulate_drive(disconnected, spec)
    assert result.status == 'blocked'
    assert any(item.startswith('driver_command_disconnected:') for item in result.faults)


def test_pre_cancelled_simulation_returns_without_starting_or_changing_design():
    design, spec = synthetic_drive_demo(); event = Event(); event.set()
    result = simulate_drive(design, spec, event)
    assert result.status == 'cancelled' and result.summary.steps == 0


def test_cancellation_also_interrupts_a_tick_with_many_stable_microsteps():
    class CancelAfterChecks:
        count = 0
        def is_set(self):
            self.count += 1
            return self.count >= 4
    design, spec = synthetic_drive_demo()
    result = simulate_drive(design, changed(spec, inductance_h=.00001, duration_s=.005), CancelAfterChecks())
    assert result.status == 'cancelled' and result.summary.elapsed_s < .005


def test_too_fast_time_constants_are_blocked_before_an_unbounded_integration():
    design, spec = synthetic_drive_demo()
    result = simulate_drive(design, changed(spec, inductance_h=1e-12))
    assert result.status == 'blocked' and result.summary.steps == 0
    assert any(item.startswith('integration_budget:') for item in result.faults)


def test_trace_size_is_bounded_for_a_long_but_valid_model():
    design, spec = synthetic_drive_demo()
    result = simulate_drive(design, changed(spec, duration_s=20))
    assert len(result.points) <= MAX_TRACE_POINTS
    assert result.points[-1].time_s == 20
    assert result.status == 'converged'


@pytest.mark.parametrize('field,value', [
    ('resistance_ohm', 0), ('inductance_h', 0), ('inertia_kg_m2', 0),
    ('back_emf_v_per_rad_s', float('nan')), ('load_torque_nm', -1),
    ('dt_s', 1), ('duration_s', 1000), ('encoder_ticks_per_rev', 0),
    ('current_limit_a', float('inf')), ('voltage_limit_fraction', 1.1),
    ('overspeed_rpm', 500), ('encoder_polarity', 0),
])
def test_unphysical_nonfinite_or_unbounded_input_is_rejected(field, value):
    _, spec = synthetic_drive_demo()
    with pytest.raises(ValidationError):
        changed(spec, **{field: value})


def test_motor_and_controller_constants_are_required_not_guessed_from_catalog():
    _, spec = synthetic_drive_demo(); raw = spec.model_dump()
    for field in ('resistance_ohm', 'inductance_h', 'inertia_kg_m2', 'torque_constant_nm_per_a', 'back_emf_v_per_rad_s'):
        missing = deepcopy(raw); missing.pop(field)
        with pytest.raises(ValidationError):
            DriveSimulationSpec.model_validate(missing)
