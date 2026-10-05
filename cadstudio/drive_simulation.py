"""Bounded averaged motor drive, quantized encoder and PI speed feedback.

This solves a user-parameterized electromechanical plant, not GPIO instructions,
firmware, FOC, phase commutation, PWM switching, thermal limits or certification.
The BLDC mode is one effective torque/current axis with user-specified voltage
normalization; its R/L/kt/ke are not automatically derived from phase ratings.

Primary equation and control references:
https://www.mathworks.com/help/simscape-electrical/ref/dcmotor.html
https://www.mathworks.com/help/simulink/slref/anti-windup-control-using-a-pid-controller.html
Known B-G431 driver capability (three-phase BLDC/PMSM, not a brushed DC bridge):
https://www.st.com/en/evaluation-tools/b-g431b-esc1.html
"""

from __future__ import annotations

from collections import defaultdict, deque
from math import ceil, floor, isfinite, pi, sqrt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .electrical import ElectricalComponent
from .models import Design


MAX_INTEGRATION_STEPS = 500_000
MAX_TRACE_POINTS = 2001
_RPM_PER_RAD_S = 60 / (2 * pi)


class _Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class DriveSimulationSpec(_Model):
    source_id: str = Field(min_length=1, max_length=40)
    motor_id: str = Field(min_length=1, max_length=40)
    encoder_id: str = Field(min_length=1, max_length=40)
    controller_id: str = Field(min_length=1, max_length=40)
    # Empty means an explicitly declared combined controller / driver. A
    # separate driver's control inputs must be wired to this controller.
    driver_id: str = Field(default='', max_length=40)
    motor_type: Literal['dc', 'bldc_average']
    controller_type: Literal['dc_driver', 'three_phase_esc']
    encoder_interface: Literal['quadrature', 'sampled_angle']
    resistance_ohm: float = Field(gt=0, le=10000)
    inductance_h: float = Field(gt=0, le=1000)
    torque_constant_nm_per_a: float = Field(gt=0, le=10000)
    back_emf_v_per_rad_s: float = Field(gt=0, le=10000)
    inertia_kg_m2: float = Field(gt=0, le=10000)
    viscous_friction_nm_per_rad_s: float = Field(ge=0, le=10000)
    load_torque_nm: float = Field(ge=0, le=100000)
    # Effective decoded counts per revolution of the modeled shaft. This is
    # not automatically PPR, and gearing must be reflected explicitly.
    encoder_ticks_per_rev: int = Field(ge=1, le=1_000_000)
    target_rpm: float = Field(ge=0, le=200000)
    duration_s: float = Field(gt=0, le=120)
    current_limit_a: float = Field(gt=0, le=10000)
    proportional_gain_v_per_rad_s: float = Field(ge=0, le=10000)
    integral_gain_v_per_rad: float = Field(ge=0, le=10000)
    # Explicit effective-axis modulation assumption, never a guessed dq/line
    # voltage conversion for a three-phase product.
    voltage_limit_fraction: float = Field(gt=0, le=1)
    overspeed_rpm: float = Field(gt=0, le=1_000_000)
    dt_s: float = Field(default=.005, ge=.0001, le=.02)
    enabled: bool = True
    encoder_connected: bool = True
    encoder_polarity: Literal[-1, 1] = 1

    @model_validator(mode='after')
    def bounds(self):
        if self.overspeed_rpm <= self.target_rpm:
            raise ValueError('Overspeed cutoff must exceed the requested speed.')
        if self.proportional_gain_v_per_rad_s == self.integral_gain_v_per_rad == 0:
            raise ValueError('Enter at least one positive PI gain.')
        if self.controller_type == 'dc_driver' and self.motor_type != 'dc':
            raise ValueError('A brushed DC bridge is not a three-phase BLDC controller.')
        if self.controller_type == 'three_phase_esc' and self.motor_type != 'bldc_average':
            raise ValueError('A three-phase ESC requires the explicitly averaged BLDC model.')
        return self


class DriveTracePoint(_Model):
    time_s: float
    speed_rpm: float
    encoder_speed_rpm: float
    current_a: float
    bus_voltage_v: float
    angle_rad: float
    error_rpm: float
    duty_cycle: float
    encoder_counts: int


class DriveSimulationSummary(_Model):
    final_speed_rpm: float
    final_error_rpm: float
    mean_tail_error_rpm: float
    peak_current_a: float
    min_bus_voltage_v: float
    peak_speed_rpm: float
    convergence: bool
    current_limited_fraction: float
    voltage_limited_fraction: float
    elapsed_s: float
    steps: int
    encoder_counts: int


class DriveSimulationResult(_Model):
    status: Literal['blocked', 'disabled', 'cancelled', 'converged', 'not_converged', 'fault']
    motor_type: Literal['dc', 'bldc_average']
    points: list[DriveTracePoint]
    summary: DriveSimulationSummary
    faults: list[str]
    warnings: list[str]
    connections: dict[str, bool]
    assumptions: list[str]


class DrivePreflight(_Model):
    faults: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    connections: dict[str, bool] = Field(default_factory=dict)


def _reachable(node, graph):
    seen = {node}; queue = deque([node])
    while queue:
        for other in graph[queue.popleft()]:
            if other not in seen:
                seen.add(other); queue.append(other)
    return seen


def _roles(component):
    from .electrical_catalog import catalog_functions
    return set(catalog_functions(component.catalog_id))


def _power_pair(component):
    """Prefer documented input pads; legacy A/B remain explicitly abstract."""
    if component.catalog_id == 'st_b_g431b_esc1':
        return component.terminal_pins.get('BAT_POS'), component.terminal_pins.get('BAT_NEG')
    if component.catalog_id == 'pololu_2130':
        return component.terminal_pins.get('VIN'), component.terminal_pins.get('GND')
    return component.a, component.b


def _signal_nodes(component):
    from .product_diagrams import product_diagram
    product = product_diagram(component.catalog_id)
    if product:
        return {port.key: component.terminal_pins[port.key] for port in product.terminals
                if port.kind == 'signal' and port.key in component.terminal_pins}
    return {**component.signal_pins, **component.terminal_pins}


def _encoder_supply(component):
    from .product_diagrams import product_diagram
    product = product_diagram(component.catalog_id)
    if component.catalog_id == 'pololu_4755':
        return ([component.terminal_pins['ENCODER_VCC']] if 'ENCODER_VCC' in component.terminal_pins else [],
                [component.terminal_pins['ENCODER_GND']] if 'ENCODER_GND' in component.terminal_pins else [])
    if product:
        positives = [component.terminal_pins[port.key] for port in product.terminals
                     if port.kind == 'power' and port.key in component.terminal_pins
                     and not port.key.startswith('MOTOR_')]
        negatives = [component.terminal_pins[port.key] for port in product.terminals
                     if port.kind == 'ground' and port.key in component.terminal_pins]
        return positives, negatives
    return [component.a], [component.b]


def _motor_inputs(component, mode):
    if mode == 'bldc_average':
        return [component.terminal_pins.get(key) for key in ('MOTOR_U', 'MOTOR_V', 'MOTOR_W')]
    if component.catalog_id == 'pololu_4755':
        return [component.terminal_pins.get(key) for key in ('MOTOR_RED', 'MOTOR_BLACK')]
    return [component.a, component.b]


def _driver_outputs(component, mode):
    if mode == 'bldc_average':
        return [component.terminal_pins.get(key) for key in ('MOTOR_U', 'MOTOR_V', 'MOTOR_W')]
    if component.catalog_id == 'pololu_2130':
        return [component.terminal_pins.get(key) for key in ('AOUT1', 'AOUT2')]
    return [component.terminal_pins.get(key) for key in ('OUT_A', 'OUT_B')]


def preflight_drive(raw: Design | dict, raw_spec: DriveSimulationSpec | dict) -> DrivePreflight:
    """Check saved device identity and explicit nets, not firmware correctness."""
    design = Design.model_validate(raw.model_dump() if isinstance(raw, Design) else raw)
    spec = DriveSimulationSpec.model_validate(raw_spec)
    check = DrivePreflight()
    if design.electrical is None:
        check.faults.append('missing_circuit: Register and wire the electrical CAD parts first.')
        return check
    workspace = design.electrical
    by_id = {component.id: component for component in workspace.components}
    requested = dict(source=spec.source_id, motor=spec.motor_id, encoder=spec.encoder_id,
                     controller=spec.controller_id, driver=spec.driver_id or spec.controller_id)
    selected = {}
    parts = {part.id for part in design.parts}
    for role, identifier in requested.items():
        component = by_id.get(identifier)
        if component is None or not component.part_registration or component.part_id not in parts:
            check.faults.append(f'unregistered_{role}: Select an electrical feature attached to an existing CAD body.')
        else:
            selected[role] = component
    if check.faults:
        return check
    source, motor, encoder, controller, driver = (selected[role] for role in requested)
    expected = dict(source={'battery'}, motor={'motor'}, encoder={'load', 'motor', 'mcu'},
                    controller={'mcu', 'load'}, driver={'mcu', 'load'})
    for role, component in selected.items():
        if component.kind not in expected[role]:
            check.faults.append(f'wrong_{role}_kind: The selected component is not suitable for this role.')
        functions = _roles(component)
        expected_function = 'motor_driver' if role == 'driver' else role
        if role != 'source' and functions and expected_function not in functions:
            check.faults.append(f'unsupported_{role}_product: This catalog product is not a documented {role}.')
    if source.id in {motor.id, encoder.id, controller.id, driver.id} or motor.id in {controller.id, driver.id}:
        check.faults.append('duplicate_drive_roles: Power, motor and controller must be separate devices.')
    if motor.id == encoder.id and not {'motor', 'encoder'} <= _roles(motor):
        check.faults.append('unverified_integrated_encoder: Use a documented motor with an integrated encoder or select a separate encoder.')
    if controller.id == encoder.id:
        check.faults.append('duplicate_encoder_controller: The feedback sensor must be a separate device.')
    if source.voltage_v <= 0:
        check.faults.append('source_voltage_missing: Enter the selected source voltage.')
    if not source.closed:
        check.faults.append('source_disabled: Battery output is switched off.')
    if not source.analysis_enabled:
        check.faults.append('source_unverified: Enable the entered battery voltage and resistance for this study.')
    if driver.catalog_id == 'st_b_g431b_esc1' and spec.motor_type != 'bldc_average':
        check.faults.append('incompatible_motor_driver: B-G431B-ESC1 is a three-phase BLDC/PMSM ESC, not a brushed DC bridge.')
    if driver.catalog_id == 'pololu_2130' and spec.motor_type != 'dc':
        check.faults.append('incompatible_motor_driver: DRV8833 is a brushed DC H-bridge, not a BLDC commutator.')
    if motor.catalog_id == 'pololu_4755' and spec.motor_type != 'dc':
        check.faults.append('incompatible_motor_type: This exact Pololu product is a brushed DC gearmotor.')
    if encoder.catalog_id == 'ams_as5600_asot' and spec.encoder_interface != 'sampled_angle':
        check.faults.append('incompatible_encoder_interface: AS5600 provides absolute angle output, not quadrature A/B.')
    if (encoder.catalog_id.startswith('omron_') or encoder.catalog_id == 'pololu_4755') and spec.encoder_interface != 'quadrature':
        check.faults.append('incompatible_encoder_interface: This encoder requires its quadrature A/B count definition.')
    if motor.catalog_id == 'pololu_4755':
        check.warnings.append('Pololu #4755 has 64 decoded edges per MOTOR-shaft revolution and a 102.083:1 gearbox; model its output shaft only after explicitly reflecting counts, kt/ke, inertia and load consistently.')
    for role in ('motor', 'encoder', 'controller', 'driver'):
        if not _roles(selected[role]) or (role not in _roles(selected[role]) and not (role == 'driver' and 'motor_driver' in _roles(selected[role]))):
            check.warnings.append(f'{role}: Manual functional role; product capability and signal levels are not verified by this model.')
    power_graph = defaultdict(set); signal_graph = defaultdict(set)
    for component in workspace.components:
        if component.kind in ('wire', 'switch') and component.closed:
            for graph in (power_graph, signal_graph):
                graph[component.a].add(component.b); graph[component.b].add(component.a)
        elif component.analysis_enabled and component.kind in ('resistor', 'inductor'):
            power_graph[component.a].add(component.b); power_graph[component.b].add(component.a)
    def joined(a, b, graph=power_graph):
        return a is not None and b is not None and b in _reachable(a, graph)
    def store(label, value, explanation):
        check.connections[label] = bool(value)
        if not value:
            check.faults.append(label + ': ' + explanation)
    driver_plus, driver_minus = _power_pair(driver)
    store('source_power_disconnected', joined(source.a, driver_plus) and joined(source.b, driver_minus),
          'Wire source + and return to the selected driver input; no implicit power rails are assumed.')
    if controller.id != driver.id:
        ctrl_plus, ctrl_minus = _power_pair(controller)
        # A separately named regulator/BEC output may supply the controller.
        outputs = [source.a, *[node for key, node in driver.terminal_pins.items() if key in ('SENSOR_5V', 'J3_BEC_5V', 'VCC')]]
        store('controller_power_disconnected', any(joined(node, ctrl_plus) for node in outputs) and joined(source.b, ctrl_minus),
              'Wire the controller supply and common return explicitly.')
        ctrl_signals, drv_signals = _signal_nodes(controller), _signal_nodes(driver)
        store('driver_command_disconnected', any(joined(a, b, signal_graph) for a in ctrl_signals.values() for b in drv_signals.values()),
              'Connect a declared MCU control signal to the separate driver command input.')
    outs, inputs = _driver_outputs(driver, spec.motor_type), _motor_inputs(motor, spec.motor_type)
    store('motor_output_disconnected', len(outs) == len(inputs) and all(joined(a, b) for a, b in zip(outs, inputs)),
          'Connect DC OUT_A/OUT_B (DRV8833 channel A) or distinct MOTOR_U/V/W driver and motor terminals.')
    if any(node is not None and joined(source.a, node) for node in outs):
        check.faults.append('motor_bypasses_driver: A motor output is directly connected to the source positive rail.')
    if len({node for node in outs if node is not None}) != len(outs):
        check.faults.append('motor_outputs_shorted: Driver motor outputs must be distinct nets.')
    signal_nodes = _signal_nodes(encoder)
    ctrl_signals = _signal_nodes(controller)
    if spec.encoder_interface == 'quadrature':
        groups = ({'ENCODER_A', 'A'}, {'ENCODER_B', 'B'})
        channels = [next((node for key, node in signal_nodes.items() if key in keys), None) for keys in groups]
        # A typed catalog may use the exact ENCODER_A / B keys. Manual ports
        # must name their channels; two arbitrary nets are not an encoder.
    else:
        channels = [signal_nodes.get('OUT')]
        if channels[0] is None and 'SDA' in signal_nodes and 'SCL' in signal_nodes:
            channels = [signal_nodes['SDA'], signal_nodes['SCL']]
    feedback = all(node is not None and any(joined(node, other, signal_graph) for other in ctrl_signals.values()) for node in channels)
    feedback = feedback and len(set(channels)) == len(channels)
    store('encoder_feedback_disconnected', feedback and spec.encoder_connected,
          'Wire distinct encoder A/B channels or the declared angle output/I2C pair to controller signal inputs.')
    encoder_plus, encoder_minus = _encoder_supply(encoder)
    supply_outputs = [source.a, *[node for item in (controller, driver) for key, node in item.terminal_pins.items()
                                 if key in ('SENSOR_5V', 'J3_BEC_5V', 'VCC')]]
    supply_outputs.extend(node for item in (controller, driver) for node in item.board_supply_pins.values()
                          if node != source.b)
    store('encoder_power_disconnected', any(joined(node, rail) for node in encoder_plus for rail in supply_outputs)
          and any(joined(node, source.b) for node in encoder_minus),
          'Connect the encoder supply and common return; a feedback wire alone does not power a sensor.')
    if encoder.catalog_id == 'ams_as5600_asot' and source.voltage_v > 5.5 and any(joined(source.a, node) for node in encoder_plus):
        check.faults.append('encoder_supply_overvoltage: AS5600 must not be powered directly from this source voltage.')
    check.warnings.extend([
        'Continuity only: pin voltage compatibility, output circuits, pull-ups, actual firmware and protection must be checked separately.',
        'The dynamic model includes battery internal resistance and entered motor resistance, but not cable/driver/converter losses.',
        'Encoder counts refer to the modeled shaft. Enter decoded counts per revolution and reflect gearbox ratio and load inertia explicitly.',
    ])
    return check


def _empty_result(spec, status, check, voltage):
    point = DriveTracePoint(time_s=0, speed_rpm=0, encoder_speed_rpm=0, current_a=0,
                           bus_voltage_v=voltage, angle_rad=0, error_rpm=spec.target_rpm,
                           duty_cycle=0, encoder_counts=0)
    return DriveSimulationResult(status=status, motor_type=spec.motor_type, points=[point],
        summary=DriveSimulationSummary(final_speed_rpm=0, final_error_rpm=spec.target_rpm,
            mean_tail_error_rpm=spec.target_rpm, peak_current_a=0, min_bus_voltage_v=voltage,
            peak_speed_rpm=0, convergence=False, current_limited_fraction=0,
            voltage_limited_fraction=0, elapsed_s=0, steps=0, encoder_counts=0),
        faults=check.faults, warnings=check.warnings, connections=check.connections,
        assumptions=_assumptions(spec))


def _assumptions(spec):
    return [
        'User-entered constant R/L/kt/ke, inertia, friction and resisting torque; no defaults inferred from nominal current.',
        'Ideal averaged bidirectional modulation with a hard current limit and PI integral clamping; no switching or inner-loop timing.',
        'No MCU code execution, FOC, phase commutation, PWM waveform, switching loss, thermal/current certification, sensor protocol timing or battery BMS.',
        'A virtual parameter model can converge without proving a physical product works.',
        *(['BLDC average mode is one effective torque-current axis, not a phase-resolved BLDC/PMSM or dq/FOC model.'] if spec.motor_type == 'bldc_average' else []),
    ]


def simulate_drive(raw: Design | dict, raw_spec: DriveSimulationSpec | dict, cancel_event=None) -> DriveSimulationResult:
    """Return deterministic traces; cancellation is checked every controller tick."""
    design = Design.model_validate(raw.model_dump() if isinstance(raw, Design) else raw)
    spec = DriveSimulationSpec.model_validate(raw_spec)
    check = preflight_drive(design, spec)
    source = next((component for component in design.electrical.components if component.id == spec.source_id), None) if design.electrical else None
    voltage = source.voltage_v if source else 0
    if check.faults:
        disabled = all(fault.startswith('source_disabled:') for fault in check.faults)
        return _empty_result(spec, 'disabled' if disabled else 'blocked', check, voltage)
    if not spec.enabled:
        check.faults.append('drive_disabled: Drive enable is off; motor output is zero.')
        return _empty_result(spec, 'disabled', check, voltage)
    if cancel_event is not None and cancel_event.is_set():
        return _empty_result(spec, 'cancelled', check, voltage)
    # Conservative RK4 microsteps resolve resistance, damping and coupled
    # electromechanical frequency. The model never silently takes an unstable
    # large step or starts an unbounded integration workload.
    rate = ((spec.resistance_ohm + source.internal_resistance_ohm) / spec.inductance_h
            + spec.viscous_friction_nm_per_rad_s / spec.inertia_kg_m2
            + 2 * sqrt(spec.torque_constant_nm_per_a * spec.back_emf_v_per_rad_s
                       / (spec.inertia_kg_m2 * spec.inductance_h)))
    safe_h = .15 / max(rate, 1)
    controller_steps = ceil(spec.duration_s / spec.dt_s)
    microsteps = max(1, ceil(spec.dt_s / safe_h))
    if not isfinite(rate) or controller_steps * microsteps > MAX_INTEGRATION_STEPS:
        check.faults.append('integration_budget: These time constants require too many stable steps. Shorten the duration or enter a suitable model.')
        return _empty_result(spec, 'blocked', check, voltage)
    stride = max(1, ceil(controller_steps / (MAX_TRACE_POINTS - 1)))
    points = []; tail_errors = deque(maxlen=max(1, ceil(controller_steps / 5)))
    current = omega = angle = integral = measured = 0.0
    count = previous_count = 0
    elapsed = peak_current = peak_speed = 0.0; min_bus = voltage
    limited_i = limited_v = executed = 0
    status = 'not_converged'; faults = []
    reference = spec.target_rpm / _RPM_PER_RAD_S
    def bus_voltage(state_i, duty):
        # Ideal averaged conversion: source current = effective voltage duty
        # times motor-axis current. Negative power represents regeneration;
        # this simple source model does not validate battery charge acceptance.
        return max(0.0, voltage - source.internal_resistance_ohm * duty * spec.voltage_limit_fraction * state_i)
    def derivative(state, requested_voltage):
        state_i, state_w, state_a = state
        # Duty is a normalized averaged voltage, not the board's gate PWM.
        duty = max(-1., min(1., requested_voltage / (max(voltage, 1e-12) * spec.voltage_limit_fraction)))
        bus = bus_voltage(state_i, duty)
        applied = duty * bus * spec.voltage_limit_fraction
        di = (applied - spec.resistance_ohm * state_i - spec.back_emf_v_per_rad_s * state_w) / spec.inductance_h
        if ((state_i >= spec.current_limit_a and di > 0)
                or (state_i <= -spec.current_limit_a and di < 0)):
            di = 0.0
        dw = (spec.torque_constant_nm_per_a * state_i - spec.load_torque_nm
              - spec.viscous_friction_nm_per_rad_s * state_w) / spec.inertia_kg_m2
        return di, dw, state_w
    def point(time, duty, bus):
        return DriveTracePoint(time_s=time, speed_rpm=omega * _RPM_PER_RAD_S,
            encoder_speed_rpm=measured * _RPM_PER_RAD_S, current_a=current, bus_voltage_v=bus,
            angle_rad=angle, error_rpm=spec.target_rpm - measured * _RPM_PER_RAD_S,
            duty_cycle=duty, encoder_counts=count)
    points.append(point(0, 0, voltage))
    for tick in range(controller_steps):
        if cancel_event is not None and cancel_event.is_set():
            status = 'cancelled'; break
        dt = min(spec.dt_s, spec.duration_s - elapsed)
        if dt <= 0:
            break
        error = reference - measured
        unconstrained = spec.proportional_gain_v_per_rad_s * error + integral
        bus = bus_voltage(current, max(-1., min(1., unconstrained / (voltage * spec.voltage_limit_fraction))))
        available = bus * spec.voltage_limit_fraction
        command = max(-available, min(available, unconstrained))
        current_saturated = abs(current) >= spec.current_limit_a * .999 and command * current > 0
        voltage_saturated = abs(unconstrained) > available + 1e-9
        # Conditional integration: do not accumulate an error that pushes an
        # already saturated actuator farther into its voltage/current limit.
        if not ((voltage_saturated or current_saturated) and error * unconstrained > 0):
            integral += spec.integral_gain_v_per_rad * error * dt
            integral = max(-voltage, min(voltage, integral))
        n = max(1, ceil(dt / safe_h)); h = dt / n
        reached_limit = current_saturated
        for substep in range(n):
            if substep % 64 == 0 and cancel_event is not None and cancel_event.is_set():
                elapsed += substep * h
                status = 'cancelled'; break
            state = current, omega, angle
            k1 = derivative(state, command)
            k2 = derivative(tuple(value + h * slope / 2 for value, slope in zip(state, k1)), command)
            k3 = derivative(tuple(value + h * slope / 2 for value, slope in zip(state, k2)), command)
            k4 = derivative(tuple(value + h * slope for value, slope in zip(state, k3)), command)
            next_state = tuple(value + h * (a + 2*b + 2*c + d) / 6 for value, a, b, c, d in zip(state, k1, k2, k3, k4))
            reached_limit = reached_limit or abs(next_state[0]) >= spec.current_limit_a * .999
            current = max(-spec.current_limit_a, min(spec.current_limit_a, next_state[0]))
            omega, angle = next_state[1:]
            if not all(isfinite(value) for value in (current, omega, angle)):
                faults.append('numerical_fault: Non-finite state; no physical conclusion is available.'); status = 'fault'; break
            peak_current = max(peak_current, abs(current)); peak_speed = max(peak_speed, abs(omega * _RPM_PER_RAD_S))
        if faults or status == 'cancelled':
            break
        elapsed = min(spec.duration_s, (tick + 1) * spec.dt_s); executed += 1
        # Quantized position difference, not true velocity, closes the loop.
        count = floor(spec.encoder_polarity * angle * spec.encoder_ticks_per_rev / (2*pi))
        measured = (count - previous_count) * 2*pi / (spec.encoder_ticks_per_rev * dt)
        previous_count = count
        duty = max(-1., min(1., command / (max(voltage, 1e-12) * spec.voltage_limit_fraction)))
        bus = bus_voltage(current, duty); min_bus = min(min_bus, bus)
        limited_i += int(reached_limit); limited_v += int(voltage_saturated)
        tail_errors.append(abs(spec.target_rpm - omega * _RPM_PER_RAD_S))
        if spec.encoder_polarity == -1 and omega > 1 and measured < 0:
            faults.append('feedback_polarity_fault: Encoder direction opposes motor direction; closed-loop operation stopped.'); status = 'fault'
        if abs(omega * _RPM_PER_RAD_S) >= spec.overspeed_rpm:
            faults.append('overspeed_fault: Entered speed cutoff reached; closed-loop operation stopped.'); status = 'fault'
        if bus <= voltage * .01 and abs(current) > 1e-8:
            faults.append('source_voltage_collapse: Battery resistance and load collapsed the modeled bus voltage.'); status = 'fault'
        if (tick + 1) % stride == 0 or tick + 1 == controller_steps or faults:
            points.append(point(elapsed, duty, bus))
        if faults:
            break
    if points[-1].time_s != elapsed:
        count = floor(spec.encoder_polarity * angle * spec.encoder_ticks_per_rev / (2*pi))
        points.append(point(elapsed, 0, bus_voltage(current, 0)))
    final_error = spec.target_rpm - omega * _RPM_PER_RAD_S
    tail_error = sum(tail_errors) / len(tail_errors) if tail_errors else abs(final_error)
    tolerance = max(2., abs(spec.target_rpm) * .02)
    convergence = (status == 'not_converged' and executed == controller_steps
                   and abs(final_error) <= tolerance and tail_error <= tolerance)
    if status == 'not_converged' and convergence:
        status = 'converged'
    if status == 'not_converged':
        check.warnings.append('Target not reached within the modeled duration/tolerance. Review load, voltage/current limits, inertia, encoder counts and PI gains.')
    if limited_i:
        check.warnings.append('Ideal current limit was active. This is not a verified board protection response.')
    if min_bus < voltage * .9:
        check.warnings.append('Modeled battery sag exceeds 10% of open-circuit voltage.')
    return DriveSimulationResult(status=status, motor_type=spec.motor_type, points=points,
        summary=DriveSimulationSummary(final_speed_rpm=omega * _RPM_PER_RAD_S, final_error_rpm=final_error,
            mean_tail_error_rpm=tail_error, peak_current_a=peak_current, min_bus_voltage_v=min_bus,
            peak_speed_rpm=peak_speed, convergence=convergence,
            current_limited_fraction=limited_i / max(executed, 1), voltage_limited_fraction=limited_v / max(executed, 1),
            elapsed_s=elapsed, steps=executed, encoder_counts=count),
        faults=faults, warnings=check.warnings, connections=check.connections, assumptions=_assumptions(spec))


def synthetic_drive_demo() -> tuple[Design, DriveSimulationSpec]:
    """Explicit virtual fixture; none of these numbers are product ratings."""
    parts = [dict(id=key, name='VIRTUAL ' + key, geometry=dict(kind='plate', length=10, width=10, thickness=2, hole_count=0),
                  transform=dict(x=index*30), role='electrical') for index, key in enumerate(('source', 'motor', 'encoder', 'controller'))]
    common = dict(part_registration=True, analysis_enabled=False)
    components = [dict(id='source', part_id='source', name='VIRTUAL 12 V source', kind='battery', a='BAT', b='GND',
                       voltage_v=12, internal_resistance_ohm=.1, part_registration=True),
                  dict(id='motor', part_id='motor', name='VIRTUAL DC motor', kind='motor', a='MPLUS', b='MRETURN', **common),
                  dict(id='encoder', part_id='encoder', name='VIRTUAL quadrature encoder', kind='load', a='BAT', b='GND',
                       terminal_pins=dict(ENCODER_A='SENSE_A', ENCODER_B='SENSE_B'), **common),
                  dict(id='controller', part_id='controller', name='VIRTUAL combined MCU / H-bridge', kind='load', a='BAT', b='GND',
                       terminal_pins=dict(OUT_A='MPLUS', OUT_B='MRETURN', IN_A='SENSE_A', IN_B='SENSE_B'), **common)]
    design = Design.model_validate(dict(name='VIRTUAL drive demonstration — not product ratings', parts=parts,
        electrical=dict(nodes=['GND', 'BAT', 'MPLUS', 'MRETURN', 'SENSE_A', 'SENSE_B'], components=components)))
    spec = DriveSimulationSpec(source_id='source', motor_id='motor', encoder_id='encoder', controller_id='controller',
        motor_type='dc', controller_type='dc_driver', encoder_interface='quadrature', resistance_ohm=2,
        inductance_h=.02, torque_constant_nm_per_a=.1, back_emf_v_per_rad_s=.1, inertia_kg_m2=.002,
        viscous_friction_nm_per_rad_s=.001, load_torque_nm=.05, encoder_ticks_per_rev=4096,
        target_rpm=600, duration_s=4, current_limit_a=4, proportional_gain_v_per_rad_s=.12,
        integral_gain_v_per_rad=.6, voltage_limit_fraction=1, overspeed_rpm=1500)
    return design, spec
