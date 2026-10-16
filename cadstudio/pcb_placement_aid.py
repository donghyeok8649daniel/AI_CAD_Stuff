"""Bounded, copy-only PCB placement suggestions; never a fabrication approval.

Only component X/Y positions can change. Existing copper locks its entire nets;
any stored zone locks the whole board, because this aid does not refill copper.
The objective is a straight-line pad-net MST, not routed trace length.
"""
from copy import deepcopy
import json
import math
import re

from .pcb import PCBProject, inspect_layout, pad_positions, pcb_digest
from . import pcb_geometry as geometry

MAX_TRIALS = 2000
MAX_PADS = 128
MAX_SEGMENTS = 128
MAX_ZONE_VERTICES = 512
EPS = 1e-7


def _signature(findings):
    return {(row['code'], row['severity'], tuple(sorted(row['refs']))) for row in findings}


def _body(component):
    angle = math.radians(component.rotation_deg)
    ca, sa = math.cos(angle), math.sin(angle)
    hx, hy = component.body_width_mm / 2, component.body_height_mm / 2
    return [(component.x_mm + x * ca - y * sa, component.y_mm + x * sa + y * ca)
            for x, y in ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy))]


def _body_report(project):
    bodies = [(component.ref, _body(component)) for component in project.components]
    findings = []
    for ref, corners in bodies:
        gap = min(min(x, y, project.width_mm - x, project.height_mm - y) for x, y in corners)
        if gap + EPS < project.edge_clearance_mm:
            findings.append(dict(code='body_edge', severity='error', refs=[ref],
                gap_mm=gap, required_gap_mm=project.edge_clearance_mm))
    for index, (ref, corners) in enumerate(bodies):
        for other_ref, other in bodies[index + 1:]:
            overlap = geometry.core_overlap(corners, other)
            gap = geometry.core_distance(corners, other)
            if overlap or gap + EPS < project.clearance_mm:
                findings.append(dict(code='body_overlap' if overlap else 'body_clearance', severity='error',
                    refs=sorted([ref, other_ref]), gap_mm=gap, required_gap_mm=project.clearance_mm))
    return findings


def _ratsnest(project):
    """Deterministic Euclidean MST per declared net; no inferred copper paths."""
    pads = sorted(pad_positions(project), key=lambda pad: (pad['ref'], pad['pin']))
    length = 0.0
    edges = []
    for net in project.nets:
        points = [pad for pad in pads if pad['net'] == net]
        if len(points) < 2:
            continue
        reached = {0}
        distances = {index: (math.hypot(points[index]['x'] - points[0]['x'], points[index]['y'] - points[0]['y']), 0)
                     for index in range(1, len(points))}
        while distances:
            selected = min(distances, key=lambda index: (distances[index][0], index))
            distance, parent = distances.pop(selected)
            length += distance
            a, b = points[parent], points[selected]
            edges.append((net, (a['x'], a['y']), (b['x'], b['y'])))
            reached.add(selected)
            for index in distances:
                distance = math.hypot(points[index]['x'] - b['x'], points[index]['y'] - b['y'])
                if distance < distances[index][0] - EPS:
                    distances[index] = (distance, selected)
    crossings = 0
    for index, (net, a, b) in enumerate(edges):
        for other_net, c, d in edges[index + 1:]:
            if net != other_net and geometry.cross(a, b, c) * geometry.cross(a, b, d) < -EPS and geometry.cross(c, d, a) * geometry.cross(c, d, b) < -EPS:
                crossings += 1
    return length, crossings


def _metrics(project, layout, bodies):
    length, crossings = _ratsnest(project)
    return dict(ratsnest_wirelength_mm=length, crossing_estimate=crossings,
        body_clearance_violations=sum(row['code'] in ('body_overlap', 'body_clearance') for row in bodies),
        boundary_violations=sum(row['code'] == 'body_edge' for row in bodies),
        unrouted_net_count=None if layout is None else sum(row['code'] == 'unrouted_net' for row in layout['findings']))


def _limits(component, project):
    corners = _body(component)
    dx = max(abs(x - component.x_mm) for x, y in corners)
    dy = max(abs(y - component.y_mm) for x, y in corners)
    edge = project.edge_clearance_mm
    return (edge + dx, project.width_mm - edge - dx, edge + dy, project.height_mm - edge - dy)


def _positions(project, component):
    pads = pad_positions(project)
    own = [pad for pad in pads if pad['ref'] == component.ref and pad['net']]
    targets = [(other['x'] - (pad['x'] - component.x_mm), other['y'] - (pad['y'] - component.y_mm))
               for pad in own for other in pads if other['ref'] != component.ref and other['net'] == pad['net']]
    if not targets:
        return []
    x = sum(point[0] for point in targets) / len(targets)
    y = sum(point[1] for point in targets) / len(targets)
    low_x, high_x, low_y, high_y = _limits(component, project)
    step = max(component.body_width_mm, component.body_height_mm) + project.clearance_mm
    proposals = [(x, y), ((x + component.x_mm) / 2, (y + component.y_mm) / 2),
        (x, component.y_mm), (component.x_mm, y)]
    proposals.extend((x + dx * step, y + dy * step) for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)))
    proposals.extend((component.x_mm + dx * step, component.y_mm + dy * step) for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)))
    positions = []
    seen = set()
    for x, y in proposals:
        point = (round(max(low_x, min(high_x, x)), 6), round(max(low_y, min(high_y, y)), 6))
        if point not in seen and math.hypot(point[0] - component.x_mm, point[1] - component.y_mm) > EPS:
            seen.add(point)
            positions.append(point)
    return positions


def optimize_placement(project, *, locked_refs=(), max_trials=200):
    """Return a JSON-safe preview; input, identity, rotation, pads and copper stay intact.

    ``budget_exhausted`` may contain a strictly improved safe preview. Callers
    must inspect ``can_apply`` and require explicit preview/apply; never commit
    merely because this function returned. Unknown lock refs are input errors.
    """
    if type(max_trials) is not int or not 0 <= max_trials <= MAX_TRIALS:
        raise ValueError('max_trials must be an integer from 0 to 2000.')
    if not isinstance(locked_refs, (list, tuple, set, frozenset)) or any(not isinstance(ref, str) for ref in locked_refs):
        raise ValueError('locked_refs must be a finite collection of component references.')
    original = PCBProject.model_validate(project).model_dump(mode='json')
    base = PCBProject.model_validate(original)
    refs = {component.ref for component in base.components}
    unknown = set(locked_refs) - refs
    if unknown:
        raise ValueError('Unknown locked component reference: ' + ', '.join(sorted(unknown)))
    fixed = {}
    routed_nets = {obj.net for obj in [*base.tracks, *base.vias]}
    net_refs = {net: {component.ref for component in base.components if any(pin.net == net for pin in component.pins)} for net in base.nets}
    for component in base.components:
        reasons = []
        if component.ref in locked_refs:
            reasons.append('user_locked')
        if base.zones:
            reasons.append('existing_zones_preserved_no_refill')
        if any(pin.net in routed_nets for pin in component.pins):
            reasons.append('existing_copper_net_locked')
        if not component.fitted:
            reasons.append('not_fitted_preserved')
        mechanical = (component.footprint + ' ' + component.value).lower()
        if re.match(r'^(?:H|MH|HOLE)[0-9]', component.ref, re.I) or any(token in mechanical for token in ('mountinghole', 'mounting_hole', 'mounting hole', 'mechanical-hole', 'npth')):
            reasons.append('mechanical_hole_preserved')
        if not any(pin.net and len(net_refs[pin.net]) > 1 for pin in component.pins):
            reasons.append('no_external_net_peers')
        low_x, high_x, low_y, high_y = _limits(component, base)
        if low_x > high_x or low_y > high_y:
            reasons.append('body_does_not_fit_board')
        if reasons:
            fixed[component.ref] = reasons
    movable = sorted(refs - set(fixed))
    zone_vertices = sum(len(zone.outline) + sum(map(len, zone.holes)) + sum(len(polygon.points) + sum(map(len, polygon.holes)) for polygon in zone.filled_polygons) for zone in base.zones)
    complexity_blocked = sum(len(component.pins) for component in base.components) > MAX_PADS or sum(len(track.points) - 1 for track in base.tracks) > MAX_SEGMENTS or zone_vertices > MAX_ZONE_VERTICES
    before_bodies = _body_report(base)
    before_layout = None if complexity_blocked else inspect_layout(base)
    before = None if complexity_blocked else _metrics(base, before_layout, before_bodies)
    best = base
    best_dump = deepcopy(original)
    best_layout, best_bodies, best_metrics = before_layout, before_bodies, before
    trials = 0
    exhausted = False
    blocked_reason = 'inspection_complexity_limit' if complexity_blocked else 'all_components_fixed' if not movable else None
    if not blocked_reason:
        while True:
            pass_improved = False
            for ref in movable:
                component = next(component for component in best.components if component.ref == ref)
                for x, y in _positions(best, component):
                    if trials >= max_trials:
                        exhausted = True
                        break
                    trials += 1
                    raw = deepcopy(best_dump)
                    row = next(row for row in raw['components'] if row['ref'] == ref)
                    row['x_mm'], row['y_mm'] = x, y
                    candidate = PCBProject.model_validate(raw)
                    bodies = _body_report(candidate)
                    if any(ref in finding['refs'] for finding in bodies) or not _signature(bodies) <= _signature(best_bodies):
                        continue
                    metrics = _metrics(candidate, None, bodies)
                    if metrics['ratsnest_wirelength_mm'] >= best_metrics['ratsnest_wirelength_mm'] - EPS or metrics['crossing_estimate'] > best_metrics['crossing_estimate']:
                        continue
                    layout = inspect_layout(candidate)
                    if not _signature(layout['findings']) <= _signature(best_layout['findings']):
                        continue
                    physical = [finding for finding in layout['findings'] if finding['code'] not in ('unrouted_net', 'drill_checks_partial', 'zone_fill_missing', 'zone_fill_unverified', 'zone_contour_checks_partial', 'layer_subset')]
                    if any(finding['severity'] == 'error' and ref in finding['refs'] for finding in physical):
                        continue
                    best, best_dump = candidate, candidate.model_dump(mode='json')
                    best_layout, best_bodies = layout, bodies
                    best_metrics = _metrics(candidate, layout, bodies)
                    pass_improved = True
                    break
                if exhausted:
                    break
            if exhausted or not pass_improved:
                break
    moved = [component.ref for component, old in zip(best.components, base.components) if (component.x_mm, component.y_mm) != (old.x_mm, old.y_mm)]
    # Independently guard the preview's allowed delta: translation only.
    stripped = deepcopy(best_dump)
    for row, old in zip(stripped['components'], original['components']):
        row['x_mm'], row['y_mm'] = old['x_mm'], old['y_mm']
    assert stripped == original
    result = dict(schema_version=1, base_sha256=pcb_digest(base), candidate=best_dump,
        moved_refs=moved, fixed_refs=sorted(fixed), fixed_reasons=fixed,
        before_objective=before, after_objective=best_metrics, trials=trials, max_trials=max_trials,
        status='blocked' if blocked_reason else 'budget_exhausted' if exhausted else 'improved' if moved else 'no_change',
        blocked_reason=blocked_reason, can_apply=bool(moved), improved=bool(moved), budget_exhausted=exhausted,
        geometry_report=dict(before_layout=before_layout, after_layout=best_layout,
            before_body_findings=before_bodies, after_body_findings=best_bodies,
            no_new_findings=None if complexity_blocked else _signature(best_layout['findings']) <= _signature(before_layout['findings']) and _signature(best_bodies) <= _signature(before_bodies),
            not_checked_reason='inspection_complexity_limit' if complexity_blocked else None),
        manufacturing_qualified=False, safety_approved=False, physical_IO=False,
        limits=['Pad-net Euclidean MST and crossing counts are straight-line placement proxies, not routed length or routability proofs.',
            'Bodies use conservative rotated 2D rectangles and entered board edge/clearance rules; body projection is not a 3D mechanical model.',
            'Only the model rectangular outline is represented; no unregistered keepouts, mounting details or thermal/electrical/fabrication constraints are inferred.',
            'Existing track/via nets are locked; any stored zone locks every component. Copper, vias and zones are never removed or rerouted.',
            'No optimality, minimum-layer, manufacturing, thermal, ampacity or hardware approval. Explicit preview/apply is required.'])
    json.dumps(result, allow_nan=False)
    return result
