"""Voltage-input companion to the unchanged mean DC motor/PI engine.

Same R/L/Kt/Ke/J/b plant equations; no PI, firmware, physical timing, switching,
coasting, protection or thermal simulation. All numbers are declared scenarios.
"""
from math import ceil,floor,isfinite,pi,sqrt
from .drive_simulation import MAX_INTEGRATION_STEPS

RPM_PER_RAD_S=60/(2*pi)


def derivative(state,voltage,values):
    current,omega,angle=state
    return ((voltage-values['resistance_ohm']*current-values['back_emf_v_per_rad_s']*omega)/values['inductance_h'],
            (values['torque_constant_nm_per_a']*current-values['load_torque_nm']-values['viscous_friction_nm_per_rad_s']*omega)/values['inertia_kg_m2'],omega)


def state_matrix(values):
    return [[-values['resistance_ohm']/values['inductance_h'],-values['back_emf_v_per_rad_s']/values['inductance_h'],0.],
            [values['torque_constant_nm_per_a']/values['inertia_kg_m2'],-values['viscous_friction_nm_per_rad_s']/values['inertia_kg_m2'],0.],
            [0.,1.,0.]]


def voltage_response(record,segments,*,cancel_event=None):
    """Strict contiguous V(t) intervals on declared virtual seconds only.

    record is the validated parameter record supplied by the adapter. No hard
    current clipping: if numerical limits fail, return no computed waveform.
    """
    values={key:row.value for key,row in record.values.items()}
    if not segments:raise ValueError('missing_voltage_intervals')
    prior=0.
    for row in segments:
        if set(row)!= {'start_s','end_s','voltage_v'}:raise ValueError('invalid_voltage_interval_schema')
        if any(isinstance(n,bool) or not isinstance(n,(int,float)) or not isfinite(n) for n in row.values()):raise ValueError('nonfinite_voltage_interval')
        if row['start_s']!=prior or row['end_s']<=prior or abs(row['voltage_v'])>values['supply_voltage_v']:raise ValueError('invalid_voltage_interval_time_or_scale')
        prior=row['end_s']
    if prior!=record.duration_s:raise ValueError('voltage_duration_mismatch')
    rate=values['resistance_ohm']/values['inductance_h']+values['viscous_friction_nm_per_rad_s']/values['inertia_kg_m2']+2*sqrt(values['torque_constant_nm_per_a']*values['back_emf_v_per_rad_s']/(values['inertia_kg_m2']*values['inductance_h']))
    hmax=min(record.integration_step_s,.15/max(rate,1.))
    samples=ceil(prior/record.sample_interval_s)
    if not isfinite(rate) or samples>2000 or sum(ceil((s['end_s']-s['start_s'])/hmax) for s in segments)+samples>MAX_INTEGRATION_STEPS:raise ValueError('integration_budget_exceeded')
    times=sorted({0.,prior,*[min(prior,index*record.sample_interval_s) for index in range(1,samples)],*[s['end_s'] for s in segments]})
    state=tuple(record.initial_state[key].value for key in ('current_a','omega_rad_s','angle_rad'))
    output=[];steps=0;index=0
    def point(t,u):
        return {'virtual_time_s':t,'scenario_current_a':state[0],'scenario_rpm':state[1]*RPM_PER_RAD_S,'scenario_angle_rad':state[2],
                'mean_voltage_v':u,'scenario_encoder_counts':None if record.encoder_counts_per_rev is None else floor(state[2]*record.encoder_counts_per_rev.value/(2*pi))}
    output.append(point(0.,segments[0]['voltage_v']))
    for start,end in zip(times,times[1:]):
        while index+1<len(segments) and start>=segments[index]['end_s']:index+=1
        row=segments[index];u=row['voltage_v'];n=ceil((end-start)/hmax);h=(end-start)/n
        for substep in range(n):
            if substep%64==0 and cancel_event is not None and cancel_event.is_set():raise ValueError('scenario_cancelled')
            k1=derivative(state,u,values)
            k2=derivative(tuple(x+h*k/2 for x,k in zip(state,k1)),u,values)
            k3=derivative(tuple(x+h*k/2 for x,k in zip(state,k2)),u,values)
            k4=derivative(tuple(x+h*k for x,k in zip(state,k3)),u,values)
            state=tuple(x+h*(a+2*b+2*c+d)/6 for x,a,b,c,d in zip(state,k1,k2,k3,k4));steps+=1
            if not all(isfinite(x) for x in state):raise ValueError('nonfinite_motor_state')
            if steps>MAX_INTEGRATION_STEPS:raise ValueError('integration_budget_exceeded')
        output.append(point(end,u))
    return {'scope':'declared virtual mean DC scenario; not a physical measurement','points':output,'integration_steps':steps,
            'method':'bounded RK4; same mean plant equations as unchanged drive_simulation.py','actual_rpm':None,'actual_current_a':None,
            'physical_clock_verified':False,'actual_motion_qualified':False,'encoder_feedback_to_code':False}
