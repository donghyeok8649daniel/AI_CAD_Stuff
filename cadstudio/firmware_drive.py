"""Explicit CAD-only velocity plant and ARM mailbox-to-joint contract.

The declaration uses a synthetic screw-axis encoder and velocity servo. It
does not substitute for the rig's linear sensor scale or a Maxon/ESCON FOC model.
"""
from __future__ import annotations
import hashlib,json,math
from pydantic import BaseModel,ConfigDict,Field,model_validator
from typing import Literal

MOTOR_SCENARIOS=('motor_drive','motor_stop','motor_guard','motor_limit')


class VirtualDriveSpec(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    profile:Literal['cad_synthetic_velocity_servo_v1']
    virtual_only:Literal[True]
    geometry_sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    clearance_receipt_sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    clearance_basis:Literal['discrete_exact_solid_poses_not_continuous_sweep']
    motor_part_id:str=Field(min_length=1,max_length=40)
    driver_component_id:str=Field(min_length=1,max_length=40)
    mate_id:str=Field(min_length=1,max_length=40)
    screw_lead_mm_per_rev:float=Field(gt=0,le=100)
    declared_gear_ratio:float=Field(gt=0,le=10000)
    feedback_basis:Literal['synthetic_counter_injection_not_physical_linear_encoder_scale']
    input_basis:Literal['virtual_fault_bits_PC0_stop_PC1_upper_PC2_lower_PC3_guard_not_physical_polarity']
    synthetic_counts_per_screw_rev:int=Field(ge=1,le=1000000)
    velocity_time_constant_s:float=Field(gt=0,le=10)
    max_displacement_mm:float=Field(gt=0,le=5)
    duration_s:float=Field(gt=0.01,le=2)
    sample_step_s:float=Field(ge=0.001,le=0.01)
    stop_time_s:float=Field(gt=0,le=2)
    @model_validator(mode='after')
    def bounded(self):
        if self.duration_s/self.sample_step_s>2000 or abs(round(self.duration_s/self.sample_step_s)-self.duration_s/self.sample_step_s)>1e-8:
            raise ValueError('Virtual drive requires at most 2000 whole sampling steps.')
        if self.stop_time_s>=self.duration_s:raise ValueError('Stop input must precede the end of the scenario.')
        return self


def geometry_fingerprint(design):
    from .models import Design
    raw=Design.model_validate(design).model_dump(mode='json')
    mechanical={key:raw.get(key) for key in ('parts','assets','mates','motion_links','loops','joint_frames','parameters','dimension_bindings')}
    return hashlib.sha256(json.dumps(mechanical,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def validate_drive(design,image):
    from .models import Design
    design=Design.model_validate(design)
    spec=image.virtual_drive
    if spec is None or geometry_fingerprint(design)!=spec.geometry_sha256:raise ValueError('Virtual drive geometry/clearance binding is missing or stale.')
    parts={p.id for p in design.parts};components={c.id:c for c in design.electrical.components}
    if spec.motor_part_id not in parts or spec.driver_component_id not in components:raise ValueError('Virtual motor/driver binding is missing.')
    if len([c for c in components.values() if c.part_id==spec.motor_part_id and c.kind=='motor'])!=1:raise ValueError('Virtual motor must match one registered motor component.')
    if components[spec.driver_component_id].kind!='load' or components[spec.driver_component_id].part_id not in parts:raise ValueError('Virtual driver has no compatible CAD body.')
    from .assembly_motion import motion_controls
    controls=motion_controls(design.model_dump(mode='json'),spec.mate_id)
    if 'rz' not in controls or 'driven_by' in controls['rz']:raise ValueError('Drive must target an independent rotary joint.')
    links=[l for l in design.motion_links if l.driver==spec.mate_id and l.driver_axis=='rz' and l.driven_axis=='z']
    if len(links)!=1 or not math.isclose(links[0].ratio*360,spec.screw_lead_mm_per_rev,rel_tol=1e-12):raise ValueError('Screw lead and CAD motion link disagree.')
    if spec.max_displacement_mm*360/spec.screw_lead_mm_per_rev>min(abs(v) for v in controls['rz']['limits']):raise ValueError('Virtual displacement exceeds the rotary joint range.')
    return spec


def drive_commands(spec,address,scenario):
    """Trusted instrumentation only; uploaded ARM code is never host Python."""
    initialize=["import math", "virtual_trace = []", "virtual_position = 0.0", "virtual_speed = 0.0", "virtual_previous_seq = -1",
                "virtual_faults = []", "virtual_bus = self.Machine['sysbus']", "virtual_gpio = self.Machine['sysbus.gpioc']"]
    commands=['cpu LogFunctionNames true "HardFault_Handler BusFault_Handler UsageFault_Handler MemManage_Handler" true',
              'python """\n'+'\n'.join(initialize)+'\n"""']
    dt=spec.sample_step_s;alpha=math.exp(-dt/spec.velocity_time_constant_s)
    for index in range(round(spec.duration_s/dt)):
        t=index*dt
        injection_time=spec.stop_time_s/2 if scenario=='motor_limit' else spec.stop_time_s
        mask=(1 if scenario=='motor_stop' else 8 if scenario=='motor_guard' else 2 if scenario=='motor_limit' else 0) if t>=injection_time else 0
        inject=[f"virtual_counter = int(round(virtual_position*{spec.synthetic_counts_per_screw_rev}/{spec.screw_lead_mm_per_rev})) & 65535",
                'virtual_bus.WriteDoubleWord(1073818660, virtual_counter)'] # TIM1 CNT
        inject += [f'virtual_gpio.OnGPIO({pin}, {bool(mask&(1<<pin))})' for pin in range(4)]
        commands += ['python """\n'+'\n'.join(inject)+'\n"""',f'emulation RunFor "{dt:.9f}"']
        sample=[f"packet = [int(virtual_bus.ReadDoubleWord({address}+4*i)) for i in range(9)]",
                "command = packet[4] if packet[4] < 2147483648 else packet[4]-4294967296",
                "feedback_um = packet[5] if packet[5] < 2147483648 else packet[5]-4294967296",
                "target_um = packet[8] if packet[8] < 2147483648 else packet[8]-4294967296",
                "if packet[0] != 1128350769 or packet[1] <= virtual_previous_seq or packet[3] not in (0,1) or abs(command)>2000:",
                "    virtual_faults.append('Invalid/nonadvancing virtual firmware mailbox')",
                "virtual_previous_seq = packet[1]", "requested_speed = command/1000.0 if packet[3] else 0.0",
                "if int(virtual_bus.ReadDoubleWord(1207960596)) & 4099: virtual_faults.append('Physical drive GPIO output became HIGH')",
                f"virtual_position += requested_speed*{dt!r} + (virtual_speed-requested_speed)*{spec.velocity_time_constant_s!r}*(1.0-{alpha!r})",
                f"virtual_speed = requested_speed + (virtual_speed-requested_speed)*{alpha!r}",
                f"if abs(virtual_position)>{spec.max_displacement_mm!r}: virtual_faults.append('Virtual motion exceeded declared clearance envelope')",
                f"virtual_trace.append(dict(time_s={(index+1)*dt!r}, position_mm=virtual_position, speed_mm_s=virtual_speed, command_mm_s=requested_speed, firmware_feedback_um=feedback_um, firmware_target_um=target_um, firmware_sequence=packet[1], firmware_elapsed_ms=packet[2], virtual_enable=packet[3], synthetic_counter=virtual_counter, input_mask={mask}, firmware_input_mask=packet[7], screw_angle_deg=virtual_position*360/{spec.screw_lead_mm_per_rev!r}, motor_angle_deg=virtual_position*360/{spec.screw_lead_mm_per_rev!r}*{spec.declared_gear_ratio!r}))"]
        commands += ['python """\n'+'\n'.join(sample)+'\n"""']
    return commands


def validate_trace(state,spec,scenario):
    trace=state.get('virtual_trace',[]);errors=list(state.get('virtual_faults',[]))
    if len(trace)!=round(spec.duration_s/spec.sample_step_s):errors.append('Virtual trace is incomplete.')
    if not trace:return trace,errors
    if any(not math.isfinite(row[key]) for row in trace for key in ('time_s','position_mm','speed_mm_s','command_mm_s','screw_angle_deg','motor_angle_deg')):errors.append('Virtual trace contains nonfinite values.')
    if any(abs(row['position_mm'])>spec.max_displacement_mm for row in trace):errors.append('Virtual trace left the declared clearance envelope.')
    if any(row['input_mask']!=row['firmware_input_mask'] for row in trace):errors.append('CPU did not read the requested virtual safety input.')
    if scenario!='motor_drive' and not any(row['input_mask'] for row in trace):errors.append('Requested safety input was never injected.')
    if scenario in ('motor_stop','motor_guard') and any(row['virtual_enable'] or row['command_mm_s'] for row in trace if row['input_mask']):errors.append('Virtual stop/guard did not disable the command.')
    if scenario=='motor_limit' and any(row['command_mm_s']>0 for row in trace if row['input_mask']):errors.append('Upper virtual limit did not block positive motion.')
    if scenario=='motor_limit' and not any(row['input_mask'] and row['firmware_target_um']>row['firmware_feedback_um'] and row['command_mm_s']==0 for row in trace):errors.append('Upper virtual limit was not tested against a positive position error.')
    return trace,errors
