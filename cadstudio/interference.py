"""Exact static overlap checks and bounded, sampled joint travel checks.

Groups and visibility never change physical collision tests. Boolean operands
are reported separately: a retained union/intersection tool is a reference body.
This is discrete pose checking, not continuous swept-volume certification.
"""
from copy import deepcopy
import math

from .models import Design

VOLUME_EPS = 1e-5


def exact_collisions(design, shapes=None, check=lambda: None):
    from .kernel import KERNEL_LOCK, build, exact_bounds
    with KERNEL_LOCK:
        shapes = build(design) if shapes is None else shapes
        bounds = [exact_bounds(s) for s in shapes]
        solids = [bool(s.Solids()) for s in shapes]
        collisions = []
        for i, a in enumerate(shapes):
            for j in range(i + 1, len(shapes)):
                check()
                if not solids[i] or not solids[j]:
                    continue
                ba, bb = bounds[i], bounds[j]
                if not all(min(getattr(ba, k+'max'), getattr(bb, k+'max')) -
                           max(getattr(ba, k+'min'), getattr(bb, k+'min')) > 1e-5 for k in 'xyz'):
                    continue
                volume = a.intersect(shapes[j]).Volume()
                if not math.isfinite(volume):
                    raise ValueError('간섭 체적을 계산하지 못했습니다. 형상을 확인하세요.')
                if volume > VOLUME_EPS:
                    collisions.append(dict(a=design.parts[i].id, b=design.parts[j].id, volume=volume))
        return collisions


def pair(collision):
    return tuple(sorted((collision['a'], collision['b'])))


def physical_collisions(design, collisions):
    references = {tuple(sorted((p.id, f.tool_part_id))) for p in design.parts for f in p.features
                  if getattr(f, 'operation', None) == 'boolean' and not f.suppressed
                  and f.boolean_mode in ('union', 'intersect')}
    return [c for c in collisions if pair(c) not in references]


def describe(design, collisions):
    names = {p.id: p.name for p in design.parts}
    return '\n'.join(f"{names.get(c['a'], c['a'])} [{c['a']}] ↔ {names.get(c['b'], c['b'])} [{c['b']}] · {c['volume']:.4g} mm³" for c in collisions[:8])


def assess(design, baseline=None, *, collisions=None, baseline_collisions=None, check=lambda: None):
    design = Design.model_validate(design)
    collisions = exact_collisions(design, check=check) if collisions is None else collisions
    physical = physical_collisions(design, collisions)
    old = {}
    if baseline is not None:
        baseline = Design.model_validate(baseline).model_copy(deep=True)
        before = exact_collisions(baseline, check=check) if baseline_collisions is None else baseline_collisions
        old = {pair(c): c['volume'] for c in physical_collisions(baseline, before)}
    blocked = [c for c in physical if c['volume'] > old.get(pair(c), 0) + max(VOLUME_EPS, old.get(pair(c), 0)*1e-7)]
    return dict(blocked=blocked, existing=[c for c in physical if c not in blocked],
                references=[c for c in collisions if c not in physical])


def require_clear(design, baseline=None, *, collisions=None, check=lambda: None):
    report = assess(design, baseline, collisions=collisions, check=check)
    if report['blocked']:
        raise ValueError('새로 생기거나 증가한 부품 간섭으로 적용을 중단했습니다.\n' + describe(design, report['blocked']) +
                         '\n원래 요청의 치수를 유지하며 배치·구멍·조립 여유를 수정하세요. 부품 삭제나 그룹화로 간섭을 숨기지 마세요.')
    return report


def motion_changes(before, after):
    """Recognize pure joint motion, including propagated linked/passive poses."""
    from .assembly_motion import JOINT_AXES
    if before is None:
        return {}
    a = Design.model_validate(before).model_dump(); b = Design.model_validate(after).model_dump()
    passive = {j for loop in a['loops'] for j in loop['passive_joints']}
    driven = {(link['driven'], link['driven_axis']) for link in a.get('motion_links',[])}
    old = {m['id']: m for m in a['mates']}; changes = {}
    if set(old) != {m['id'] for m in b['mates']}:
        return {}
    for m in b['mates']:
        for axis in JOINT_AXES[m['kind']]:
            value = m[axis]; start = old[m['id']][axis]
            if abs(value-start) > 1e-9 and m['id'] not in passive and (m['id'], axis) not in driven:
                changes[(m['id'], axis)] = (start, value)
            m[axis] = start
    for raw in (a, b):
        for part in raw['parts']:
            part.pop('transform')
    return changes if a == b else {}


def check_joint_travel(before, after, *, check=lambda: None, max_samples=1440):
    """Check interpolated independent coordinates; never skip a colliding start.

    A last-clear sample is a useful stop suggestion, not a certified hard stop.
    Limits are recomputed after edits; there is no stale cached safety range.
    """
    from .kernel import KERNEL_LOCK, build, local_shape_session
    from .assembly_motion import set_joint_motion
    with KERNEL_LOCK, local_shape_session():
        before = Design.model_validate(before).model_copy(deep=True)
        after = Design.model_validate(after).model_copy(deep=True)
        changes = motion_changes(before, after)
        if not changes:
            return None
        build(before); build(after)
        a_mates = {m.id: m for m in before.mates}
        # Include linked ratios and passive motion in the sample budget.
        steps = max(1, math.ceil(max(abs(getattr(m,k)-getattr(a_mates[m.id],k))/(2 if k.startswith('r') else .5)
                                    for m in after.mates for k in ('x','y','z','rx','ry','rz'))))
        if steps > max_samples:
            raise ValueError('관절 이동이 너무 커서 간섭 검사를 완료할 수 없습니다. 이동을 나누어 적용하세요.')
        moved = {p.id for p, q in zip(before.parts, after.parts) if p.transform != q.transform}
        # Entire revolutions can finish at the same pose: include all descendants
        # of changed joints, even when endpoint transforms compare equal.
        moved.update(m.child for m in after.mates if m.id in {k[0] for k in changes})
        while True:
            extended = moved | {m.child for m in after.mates if m.parent in moved}
            if extended == moved: break
            moved = extended
        raw = before.model_dump(); last_clear = None
        for i in range(steps+1):
            check(); t = i/steps; pose = deepcopy(raw)
            for mid in {mid for mid, axis in changes}:
                set_joint_motion(pose, mid, {axis: start+(end-start)*t for (j,axis),(start,end) in changes.items() if j==mid})
            current = Design.model_validate(pose)
            hits = [c for c in physical_collisions(current, exact_collisions(current, check=check))
                    if c['a'] in moved or c['b'] in moved]
            values = [dict(mate_id=mid, axis=axis, value=start+(end-start)*t)
                      for (mid,axis),(start,end) in sorted(changes.items())]
            if hits:
                return dict(blocked=hits, fraction=t, values=values, last_clear=last_clear, samples=i+1,
                            step_degrees=2, step_mm=.5)
            last_clear = values
        return dict(blocked=[], samples=steps+1, last_clear=last_clear, step_degrees=2, step_mm=.5)


def survey_joint_drive(design, mate_id, axis, *, check=lambda: None, max_samples=1440):
    """Probe both sides of one independent joint's configured travel.

    This is a read-only, sampled exact-solid check. It gives the operator the
    last clear *sample* before a collision in each direction; it must not be
    used as a certified mechanical stop or silently rewrite joint limits.
    The same linked joints and loop closures as ordinary motion are evaluated.
    """
    from .assembly_motion import motion_controls, set_joint_motion

    original = Design.model_validate(design).model_copy(deep=True)
    controls = motion_controls(original.model_dump(), mate_id)
    if axis not in controls:
        raise ValueError('관절의 운동 축을 선택하세요.')
    control = controls[axis]
    if 'driven_by' in control:
        raise ValueError(f'{mate_id}.{axis}는 {control["driven_by"]}가 구동합니다. 구동 관절을 선택하세요.')
    current = control['value']
    lower, upper = control['limits']
    directions = {}
    for direction, target in (('negative', lower), ('positive', upper)):
        check()
        if abs(target-current) <= 1e-9:
            directions[direction] = dict(requested=target, safe=current, blocked=False,
                                         first_hit=None, collisions=[], samples=0)
            continue
        raw = original.model_dump()
        set_joint_motion(raw, mate_id, {axis: target})
        travel = check_joint_travel(original, Design.model_validate(raw), check=check,
                                    max_samples=max_samples)
        if travel is None:
            raise ValueError('관절 구동 범위를 검사하지 못했습니다.')
        blocked = bool(travel['blocked'])
        # check_joint_travel checks the initial pose too. A collision at the
        # start has no last-clear sample, so report the current coordinate.
        last = travel['last_clear']
        safe = current if last is None else next(v['value'] for v in last
                                                if v['mate_id'] == mate_id and v['axis'] == axis)
        first = (next(v['value'] for v in travel['values']
                      if v['mate_id'] == mate_id and v['axis'] == axis)
                 if blocked else None)
        directions[direction] = dict(requested=target, safe=safe if blocked else target,
                                     blocked=blocked, first_hit=first,
                                     collisions=travel['blocked'], samples=travel['samples'])
    return dict(mate_id=mate_id, axis=axis, unit=control['unit'], current=current,
                negative=directions['negative'], positive=directions['positive'],
                samples=sum(row['samples'] for row in directions.values()),
                step_degrees=2, step_mm=.5)


def travel_message(design, travel):
    if not travel or not travel['blocked']:
        return ''
    text = '관절 구동 중 간섭 · 이 동작은 적용할 수 없습니다.\n' + describe(design, travel['blocked'])
    text += '\n간섭 발견 자세: ' + ', '.join(f"{v['mate_id']}.{v['axis'].upper()} {v['value']:.4g} {'°' if v['axis'].startswith('r') else 'mm'}" for v in travel['values'])
    if travel['last_clear'] is None:
        return text + '\n시작 자세부터 간섭합니다. 장착 위치·구멍·공차를 먼저 수정하세요.'
    return text + '\n마지막으로 간섭 없이 확인한 자세: ' + ', '.join(
        f"{v['mate_id']}.{v['axis'].upper()} {v['value']:.4g} {'°' if v['axis'].startswith('r') else 'mm'}" for v in travel['last_clear'])


def validate_candidate(design, baseline=None, *, collisions=None, check=lambda: None):
    report = require_clear(design, baseline, collisions=collisions, check=check)
    if baseline is not None:
        travel = check_joint_travel(baseline, design, check=check)
        if travel and travel['blocked']:
            raise ValueError(travel_message(design, travel))
    return report
