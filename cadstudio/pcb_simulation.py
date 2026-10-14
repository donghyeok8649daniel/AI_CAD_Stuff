"""Bounded linear MNA for explicit DC/AC PCB netlists. No SPICE runtime.

AC source values are peak phasors. Capacitors are open at settled DC.
This solver uses logical nets, not board routing or measured hardware.
"""
from __future__ import annotations
import cmath
import math
from .pcb import PCBProject, PCBSimulationInput, pcb_digest


LIMITS = ['Logical netlist, ideal linear R/C and independent voltage sources only.',
    'AC amplitudes are peak phasors; resistor average power uses |I|²R/2.',
    'No transient, semiconductor, MCU/ADC/firmware, noise, thermal, rating or physical verification.',
    'PCB copper geometry, trace resistance and parasitics are not simulated.']


def circuit_elements(project):
    p = PCBProject.model_validate(project)
    elements = []
    excluded = []
    for c in p.components:
        if not c.fitted:
            excluded.append(c.ref);continue
        m = c.model
        if m.kind == 'unsupported':
            raise ValueError(f'{c.ref}: 시뮬레이션 모델이 없습니다. / Unsupported device model.')
        if m.kind == 'none':
            excluded.append(c.ref);continue
        pins = {pin.number:pin.net for pin in c.pins}
        a, b = pins[m.pin_a], pins[m.pin_b]
        if a is None or b is None:
            raise ValueError(f'{c.ref}: 모델 핀의 net을 먼저 지정하세요. / Unconnected model pin.')
        if a == b and m.kind == 'voltage_source':
            raise ValueError(f'{c.ref}: 전압원의 양 끝이 같은 net입니다. / Shorted voltage source.')
        elements.append((c,a,b))
    if not elements or not any(c.model.kind == 'voltage_source' for c,_,_ in elements):
        raise ValueError('회로와 명시적인 전압원 모델이 필요합니다. / Explicit source model required.')
    return p,elements,excluded


def simulate_pcb(project, inputs=None, *, backend='builtin-linear', check=None):
    if backend != 'builtin-linear':
        raise ValueError('요청한 시뮬레이션 runtime은 연결되지 않았습니다. / Requested runtime unavailable; no fallback.')
    try: import numpy as np
    except ImportError as exc: raise ValueError('NumPy runtime이 없습니다. / Missing NumPy simulation runtime.') from exc
    p,elements,excluded = circuit_elements(project)
    settings = PCBSimulationInput.model_validate(inputs or p.simulation)
    check = check or (lambda:None);check()
    used = {node for _,a,b in elements for node in (a,b)}
    if 'GND' not in used:
        raise ValueError('모델 회로에 GND가 연결되지 않았습니다. / No ground reference in simulated circuit.')
    nodes = sorted(used-{'GND'}); index={node:i for i,node in enumerate(nodes)}
    sources = [(c,a,b) for c,a,b in elements if c.model.kind == 'voltage_source']
    size=len(nodes)+len(sources)
    matrix=np.zeros((size,size),dtype=complex);rhs=np.zeros(size,dtype=complex)
    w=2*math.pi*settings.frequency_hz
    def stamp(a,b,y):
        for node,sign in ((a,1),(b,-1)):
            if node == 'GND':continue
            for other,other_sign in ((a,1),(b,-1)):
                if other != 'GND':matrix[index[node],index[other]] += y*sign*other_sign
    for c,a,b in elements:
        check();m=c.model
        if m.kind == 'resistor':stamp(a,b,1/m.resistance_ohm)
        elif m.kind == 'capacitor' and settings.analysis == 'ac':stamp(a,b,1j*w*m.capacitance_f)
    for i,(c,a,b) in enumerate(sources):
        k=len(nodes)+i
        for node,sign in ((a,1),(b,-1)):
            if node != 'GND':matrix[index[node],k] += sign;matrix[k,index[node]] += sign
        m=c.model
        rhs[k]=m.dc_voltage_v if settings.analysis=='dc' else cmath.rect(m.ac_voltage_v or 0,math.radians(m.ac_phase_deg))
    check()
    try: solution=np.linalg.solve(matrix,rhs)
    except np.linalg.LinAlgError as exc:
        raise ValueError('떠 있는 net 또는 모순된 이상 전압원으로 계산이 차단됐습니다. / Singular netlist: floating node or conflicting ideal sources.') from exc
    check()
    residual=float(np.max(np.abs(matrix@solution-rhs)))
    if not np.all(np.isfinite(solution)) or residual > 1e-8*max(1,float(np.max(np.abs(rhs)))):
        raise ValueError('수치 해를 검증하지 못했습니다. / Invalid numerical solution.')
    voltages={'GND':0j,**{node:complex(solution[i]) for node,i in index.items()}}
    source_index={c.ref:len(nodes)+i for i,(c,_,_) in enumerate(sources)}
    def scalar(v):return dict(real=float(v.real),imag=float(v.imag),magnitude=float(abs(v)),phase_deg=float(math.degrees(cmath.phase(v))))
    branches={}
    for c,a,b in elements:
        m=c.model;voltage=voltages[a]-voltages[b]
        if m.kind=='resistor': current=voltage/m.resistance_ohm
        elif m.kind=='capacitor': current=voltage*(1j*w*m.capacitance_f) if settings.analysis=='ac' else 0j
        else: current=complex(solution[source_index[c.ref]])
        power=(voltage*current.conjugate()).real*(.5 if settings.analysis=='ac' else 1)
        branches[c.ref]=dict(voltage_v=scalar(voltage),current_a=scalar(current),absorbed_power_w=float(power))
    return dict(status='calculated',backend=backend,pcb_sha256=pcb_digest(p),input=settings.model_dump(),
        node_voltages_v={key:scalar(value) for key,value in voltages.items()},branches=branches,
        max_equation_residual=residual,excluded_refs=excluded,unused_nets=sorted(set(p.nets)-used),limits=LIMITS,
        actual_hardware_verified=False)


def spice_netlist(project):
    p,elements,excluded=circuit_elements(project)
    numbers={node:str(i+1) for i,node in enumerate(sorted(set(p.nets)-{'GND'}))};numbers['GND']='0'
    lines=['* Prompt CAD PCB: ideal linear reference netlist; no device subcircuits',
        '* '+pcb_digest(p),*[f'* node {value} = {key}' for key,value in numbers.items()]]
    for i,(c,a,b) in enumerate(elements,1):
        m=c.model
        if m.kind=='resistor':line=f'R{i} {numbers[a]} {numbers[b]} {m.resistance_ohm:.12g}'
        elif m.kind=='capacitor':line=f'C{i} {numbers[a]} {numbers[b]} {m.capacitance_f:.12g}'
        else:line=f'V{i} {numbers[a]} {numbers[b]} DC {m.dc_voltage_v:.12g} AC {(m.ac_voltage_v or 0):.12g} {m.ac_phase_deg:.12g}'
        lines.extend(['* reference '+c.ref,line])
    lines.extend(['.op','.end'])
    return '\n'.join(lines)+'\n'
