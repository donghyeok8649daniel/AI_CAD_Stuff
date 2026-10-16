"""Bounded, copy-only Manhattan routing trials, never a minimum-layer proof.

Existing copper, placements, pad layer declarations and stored fills are kept.
Only the model's rectangular outline and declared copper rules are available.
New vias require a full-stack via already declared on this board as a geometry
template; no drill/process rule is guessed. Final verdicts use inspect_layout.
"""
from __future__ import annotations

import heapq
import math

from . import pcb_geometry as geom
from .pcb import (PCBProject, PCBTrack, PCBVia, copper_layers, via_layers,
                  pad_positions, track_segments, inspect_layout, pcb_digest)


class _Budget(Exception):
    pass


def _bounds(points, radius=0):
    return (min(x for x, y in points)-radius, min(y for x, y in points)-radius,
            max(x for x, y in points)+radius, max(y for x, y in points)+radius)


def _near(a, b, clearance):
    return not (a[2]+clearance < b[0] or b[2]+clearance < a[0]
                or a[3]+clearance < b[1] or b[3]+clearance < a[1])


def _via_record(project, via):
    return dict(id=via.id, net=via.net, x=via.x_mm, y=via.y_mm,
                size_x_mm=via.diameter_mm, size_y_mm=via.diameter_mm,
                shape='circle', rotation_deg=0, roundrect_rratio=.25,
                drill_mm=via.drill_mm, layers=via_layers(project, via))


class _Work:
    def __init__(self, maximum):
        self.maximum = maximum
        self.expansions = 0
        self.geometry_tests = 0

    def pop(self):
        if self.expansions >= self.maximum:
            raise _Budget('Search expansion limit reached.')
        self.expansions += 1

    def geometry(self):
        # Bound narrow-phase work as well as popped A* states. The broad phase
        # has at most the model's bounded pad/segment/via/fill object count.
        self.geometry_tests += 1
        if self.geometry_tests > self.maximum*32:
            raise _Budget('Geometric candidate-test limit reached.')


class _Scene:
    def __init__(self, project, net, width, work):
        self.project, self.net, self.width, self.work = project, net, width, work
        self.pads = pad_positions(project)
        self.segments = track_segments(project)
        self.vias = [_via_record(project, via) for via in project.vias]
        self.fills = []
        for zone in project.zones:
            for polygon in zone.filled_polygons:
                # Fractured copper is not safely modeled by the gap helper.
                # Avoid its entire declared region for other nets instead.
                region = (geom.region(polygon.points, polygon.holes)
                          if geom.is_simple_ring(polygon.points)
                          else geom.region(zone.outline, zone.holes))
                self.fills.append(dict(net=zone.net, layer=zone.layer, polygon=region,
                                       bounds=_bounds(region['points'])))
        self.obstacles = [(pad, geom.pad_bounds(pad)) for pad in self.pads+self.vias if pad['net'] != net]
        self.other_segments = [(s, _bounds([s['a'], s['b']], s['radius'])) for s in self.segments if s['net'] != net]
        self.via_template = next((v for v in project.vias
                                  if via_layers(project, v) == copper_layers(project)), None)
        self.edge_cache, self.via_cache = {}, {}

    def inside(self, bounds):
        p, c = self.project, self.project.edge_clearance_mm
        return min(bounds[0], bounds[1], p.width_mm-bounds[2], p.height_mm-bounds[3])+1e-9 >= c

    def segment_clear(self, a, b, layer):
        if a == b:
            return True
        key = (min(a, b), max(a, b), layer)
        if key in self.edge_cache:
            return self.edge_cache[key]
        segment = dict(a=a, b=b, radius=self.width/2)
        bounds, clearance = _bounds([a, b], self.width/2), self.project.clearance_mm
        valid = self.inside(bounds)
        if valid:
            for pad, box in self.obstacles:
                if layer in pad['layers'] and _near(bounds, box, clearance):
                    self.work.geometry()
                    if geom.pad_track_gap(pad, segment) < clearance-1e-9:
                        valid = False
                        break
        if valid:
            for other, box in self.other_segments:
                if layer == other['layer'] and _near(bounds, box, clearance):
                    self.work.geometry()
                    if geom.segment_distance(a, b, other['a'], other['b']) < self.width/2+other['radius']+clearance-1e-9:
                        valid = False
                        break
        if valid:
            for fill in self.fills:
                if fill['net'] != self.net and fill['layer'] == layer and _near(bounds, fill['bounds'], clearance):
                    self.work.geometry()
                    if geom.track_region_gap(segment, fill['polygon']) < clearance-1e-9:
                        valid = False
                        break
        self.edge_cache[key] = valid
        return valid

    def existing_bridge(self, point, first, second):
        for pad in self.pads+self.vias:
            if pad['net'] == self.net and first in pad['layers'] and second in pad['layers']:
                center = (pad['x'], pad['y'])
                if math.dist(point, center) < 1e-9 or geom.pad_contains(point, pad):
                    return True
        return False

    def via_clear(self, point):
        if point in self.via_cache:
            return self.via_cache[point]
        template = self.via_template
        if template is None:
            return False
        via = dict(x=point[0], y=point[1], size_x_mm=template.diameter_mm,
                   size_y_mm=template.diameter_mm, shape='circle', rotation_deg=0,
                   roundrect_rratio=.25, drill_mm=template.drill_mm)
        bounds, clearance = geom.pad_bounds(via), self.project.clearance_mm
        valid = self.inside(bounds)
        if valid:
            for other, box in self.obstacles:
                if _near(bounds, box, clearance):
                    self.work.geometry()
                    if geom.pad_gap(via, other) < clearance-1e-9:
                        valid = False
                        break
        if valid:
            for other, box in self.other_segments:
                if _near(bounds, box, clearance):
                    self.work.geometry()
                    if geom.pad_track_gap(via, other) < clearance-1e-9:
                        valid = False
                        break
        if valid:
            for fill in self.fills:
                if fill['net'] != self.net and _near(bounds, fill['bounds'], clearance):
                    self.work.geometry()
                    if geom.pad_region_gap(via, fill['polygon']) < clearance-1e-9:
                        valid = False
                        break
        self.via_cache[point] = valid
        return valid

    def axes(self, terminals):
        p = self.project
        margin = p.edge_clearance_mm+self.width/2
        xs, ys = {margin, p.width_mm-margin}, {margin, p.height_mm-margin}
        for terminal in terminals:
            xs.add(terminal['x']); ys.add(terminal['y'])
        for pad in self.pads+self.vias:
            xs.add(pad['x']); ys.add(pad['y'])
        inflation = self.width/2+p.clearance_mm
        boxes = [box for _, box in self.obstacles]+[box for _, box in self.other_segments]+[f['bounds'] for f in self.fills if f['net'] != self.net]
        for left, bottom, right, top in boxes:
            xs.update((left-inflation, right+inflation))
            ys.update((bottom-inflation, top+inflation))
        # A small additional lattice provides legal places for vias; its size
        # is independent of board dimensions and no dense grid is allocated.
        for index in range(33):
            xs.add(margin+(p.width_mm-2*margin)*index/32)
            ys.add(margin+(p.height_mm-2*margin)*index/32)
        return (sorted(x for x in xs if margin-1e-9 <= x <= p.width_mm-margin+1e-9),
                sorted(y for y in ys if margin-1e-9 <= y <= p.height_mm-margin+1e-9))


def _path(scene, start, end, layers, terminals):
    a, b = (start['x'], start['y']), (end['x'], end['y'])
    shared = [layer for layer in layers if layer in start['layers'] and layer in end['layers']]
    # Direct/L paths are checked with actual pad shapes and stored copper.
    for layer in shared:
        options = [[a, b]] if a[0] == b[0] or a[1] == b[1] else [[a, (b[0], a[1]), b], [a, (a[0], b[1]), b]]
        for points in options:
            scene.work.pop()
            points = [point for i, point in enumerate(points) if i == 0 or point != points[i-1]]
            if len(points) > 1 and all(scene.segment_clear(x, y, layer) for x, y in zip(points, points[1:])):
                return [(point[0], point[1], layer) for point in points]
    xs, ys = scene.axes(terminals)
    if a[0] not in xs or a[1] not in ys or b[0] not in xs or b[1] not in ys:
        return None
    starts = [(xs.index(a[0]), ys.index(a[1]), i) for i, layer in enumerate(layers) if layer in start['layers']]
    targets = {(xs.index(b[0]), ys.index(b[1]), i) for i, layer in enumerate(layers) if layer in end['layers']}
    if not starts or not targets:
        return None
    queue, cost, parent = [], {}, {}
    serial = 0
    def heuristic(state):
        return abs(xs[state[0]]-b[0])+abs(ys[state[1]]-b[1])
    for state in starts:
        cost[state] = 0.
        heapq.heappush(queue, (heuristic(state), serial, 0., state)); serial += 1
    while queue:
        _, _, distance, state = heapq.heappop(queue)
        if distance != cost.get(state):
            continue
        scene.work.pop()
        if state in targets:
            result = []
            while True:
                result.append((xs[state[0]], ys[state[1]], layers[state[2]]))
                if state not in parent:
                    break
                state = parent[state]
            return result[::-1]
        x, y, z = state; here = (xs[x], ys[y])
        neighbors = []
        for nx, ny in [(x-1, y), (x+1, y), (x, y-1), (x, y+1)]:
            if 0 <= nx < len(xs) and 0 <= ny < len(ys):
                point = (xs[nx], ys[ny])
                if scene.segment_clear(here, point, layers[z]):
                    neighbors.append(((nx, ny, z), math.dist(here, point)))
        for nz in range(len(layers)):
            if nz != z and (scene.existing_bridge(here, layers[z], layers[nz]) or scene.via_clear(here)):
                neighbors.append(((x, y, nz), 2.))  # Search preference, not a physical via cost.
        for neighbor, delta in neighbors:
            candidate = distance+delta
            if candidate+1e-12 < cost.get(neighbor, math.inf):
                cost[neighbor], parent[neighbor] = candidate, state
                heapq.heappush(queue, (candidate+heuristic(neighbor), serial, candidate, neighbor)); serial += 1
    return None


def _terminals(project, net, findings):
    result = [dict(id=f"{p['ref']}.{p['pin']}", x=p['x'], y=p['y'], layers=p['layers'])
              for p in pad_positions(project) if p['net'] == net]
    if not result:
        return []
    orphan_ids = {ref for f in findings if f['code'].startswith('orphan_') for ref in f['refs']}
    for track in project.tracks:
        if track.id in orphan_ids and track.net == net:
            result.append(dict(id=track.id, x=track.points[0].x_mm, y=track.points[0].y_mm, layers=[track.layer]))
    for via in project.vias:
        if via.id in orphan_ids and via.net == net:
            result.append(dict(id=via.id, x=via.x_mm, y=via.y_mm, layers=via_layers(project, via)))
    return result


def _mst(terminals):
    if not terminals:
        return []
    connected, edges = {0}, []
    remaining = set(range(1, len(terminals)))
    best = {i: (math.dist((terminals[0]['x'], terminals[0]['y']), (terminals[i]['x'], terminals[i]['y'])), 0) for i in remaining}
    while remaining:
        chosen = min(remaining, key=lambda i: (best[i][0], i))
        edges.append((terminals[best[chosen][1]], terminals[chosen]))
        remaining.remove(chosen); connected.add(chosen)
        for i in remaining:
            distance = math.dist((terminals[chosen]['x'], terminals[chosen]['y']), (terminals[i]['x'], terminals[i]['y']))
            if distance < best[i][0]:
                best[i] = distance, chosen
    return edges


def _add_path(project, net, path, scene):
    raw = project.model_dump(mode='json')
    used = {obj.id for obj in [*project.tracks, *project.vias, *project.zones]}
    def identifier(prefix):
        number = 1
        while f'{prefix}{number}' in used:
            number += 1
        value = f'{prefix}{number}'; used.add(value); return value
    tracks, vias, points, layer = [], [], [], path[0][2]
    def flush():
        nonlocal points
        simplified = []
        for point in points:
            if simplified and point == simplified[-1]:
                continue
            if len(simplified) >= 2:
                a, b = simplified[-2:]
                if abs((b[0]-a[0])*(point[1]-b[1])-(b[1]-a[1])*(point[0]-b[0])) < 1e-12:
                    simplified.pop()
            simplified.append(point)
        for offset in range(0, len(simplified)-1, 31):
            chunk = simplified[offset:offset+32]
            tracks.append(PCBTrack(id=identifier('RTE339_'), net=net, layer=layer, width_mm=scene.width,
                points=[dict(x_mm=x, y_mm=y) for x, y in chunk]).model_dump(mode='json'))
        points = []
    for x, y, new_layer in path:
        if new_layer != layer:
            flush()
            point = (x, y)
            if not scene.existing_bridge(point, layer, new_layer):
                template = scene.via_template
                if template is None:
                    raise ValueError('No declared full-stack via geometry template.')
                vias.append(PCBVia(id=identifier('VIA339_'), net=net, x_mm=x, y_mm=y,
                    diameter_mm=template.diameter_mm, drill_mm=template.drill_mm,
                    layers=['F.Cu', 'B.Cu']).model_dump(mode='json'))
            layer = new_layer
        points.append((x, y))
    flush()
    raw['tracks'].extend(tracks)
    raw.setdefault('vias', []).extend(vias)
    return PCBProject.model_validate(raw)


def _trial(project, layers, width, maximum):
    work = _Work(maximum)
    initial = inspect_layout(project)
    trial = dict(layer_count=project.layer_count,
        scope='all-supported' if layers == copper_layers(project) else 'current-layer',
        routing_layers=list(layers), status='blocked', blockers=[], new_tracks=0, new_vias=0,
        geometric_check=initial, connectivity_complete=False, expansions=0, geometry_tests=0,
        expansion_budget=maximum, warnings_preserved=True)
    current = project.model_copy(deep=True)
    errors = [f for f in initial['findings'] if f['severity'] == 'error' and f['code'] not in ('unrouted_net', 'orphan_track', 'orphan_via', 'orphan_zone')]
    if errors:
        trial['blockers'].append(dict(code='existing_geometry_errors', message='Existing copper or pads violate declared geometry rules; preserved copper is not deleted or moved.', findings=errors))
    else:
        try:
            unsettled = {f['refs'][0] for f in initial['findings'] if f['code'] == 'unrouted_net'}
            orphan_ids = {ref for f in initial['findings'] if f['code'].startswith('orphan_') for ref in f['refs']}
            unsettled.update(obj.net for obj in [*project.tracks, *project.vias, *project.zones] if obj.id in orphan_ids)
            for net in project.nets:
                if net not in unsettled:
                    continue
                terminals = _terminals(current, net, initial['findings'])
                if len(terminals) < 2:
                    trial['blockers'].append(dict(code='unanchored_copper', net=net, message='No routable pad pair anchors the unresolved copper.'))
                scene = _Scene(current, net, width, work)
                for start, end in _mst(terminals):
                    if not set(start['layers']) & set(layers) or not set(end['layers']) & set(layers):
                        trial['blockers'].append(dict(code='pad_layer_access', net=net,
                            refs=[start['id'], end['id']], routing_layers=list(layers),
                            message='A terminal has no declared copper on a permitted routing layer; pad layer access was not invented.'))
                        continue
                    path = _path(scene, start, end, layers, terminals)
                    if path is None:
                        trial['blockers'].append(dict(code='search_no_path', net=net, refs=[start['id'], end['id']],
                            message='No route was found on this bounded grid and fixed routing order; this is not an impossibility or layer-minimum proof.',
                            via_template_available=scene.via_template is not None,
                            via_policy='Only an existing declared full-stack via supplies new-via diameter/drill; otherwise new drill transitions are disabled.'))
                    else:
                        try:
                            old_via_count = len(current.vias)
                            current = _add_path(current, net, path, scene)
                            scene.vias.extend(_via_record(current, via) for via in current.vias[old_via_count:])
                        except ValueError as exc:
                            trial['blockers'].append(dict(code='candidate_model_limit', net=net, message=str(exc)))
        except _Budget as exc:
            trial['blockers'].append(dict(code='work_budget', message=str(exc)))
            trial['status'] = 'budget_exhausted'
    final = inspect_layout(current)
    findings = final['findings']
    complete = not any(f['code'] == 'unrouted_net' or f['code'].startswith('orphan_') for f in findings)
    clean = not any(f['severity'] == 'error' for f in findings)
    trial.update(geometric_check=final, connectivity_complete=complete,
                 new_tracks=len(current.tracks)-len(project.tracks), new_vias=len(current.vias)-len(project.vias),
                 expansions=work.expansions, geometry_tests=work.geometry_tests)
    if trial['status'] == 'budget_exhausted':
        # No candidate is offered from an interrupted search, even if an
        # incidental connection happened before a redundant MST edge stopped.
        pass
    elif complete and clean and final['status'] == 'geometric_checks_passed':
        trial['status'] = 'routed'
        trial['candidate'] = current.model_dump(mode='json')
    elif complete and clean:
        trial['status'] = 'partial'
        trial['qualified_candidate'] = current.model_dump(mode='json')
        trial['qualification'] = '기하 연결 후보 · 드릴/구리 채움 등 경고의 검증은 미정입니다. 제조·전기·열 적합 판정이 아닙니다.'
    elif trial['status'] != 'budget_exhausted':
        trial['status'] = 'partial' if trial['new_tracks'] or trial['new_vias'] else 'blocked'
    if not complete or not clean:
        trial['blockers'].append(dict(code='final_inspection_unresolved', message='All-pad copper connectivity and zero geometric errors are both required.', findings=findings))
    elif trial['status'] in ('routed', 'partial'):
        trial['attempt_notes'] = trial['blockers']
        trial['blockers'] = []
    return trial


def assess_routing(project, *, active_layer=None, width_mm=.25, max_expansions=12000):
    """Try current then larger supported stacks on copies with one total budget.

    active_layer restricts a single trial to that current copper layer. Otherwise
    Current 2/4/6/8L is followed by larger supported stacks if needed, never downgraded. The total expansion
    allowance is divided between potential stack trials, not multiplied per net.
    Only a warning-free complete inspect_layout verdict is a strict success.
    """
    base = PCBProject.model_validate(project).model_copy(deep=True)
    if type(width_mm) not in (int, float) or not math.isfinite(width_mm) or not .05 <= width_mm <= 10:
        raise ValueError('Track width must be finite and within the PCB model range 0.05–10 mm.')
    if type(max_expansions) is not int or not 1 <= max_expansions <= 50000:
        raise ValueError('max_expansions must be an integer from 1 to 50000.')
    if active_layer is not None and active_layer not in copper_layers(base):
        raise ValueError('Choose a copper layer active on the current board.')
    counts = [base.layer_count] if active_layer is not None else [count for count in (2,4,6,8) if count>=base.layer_count]
    complexity = dict(pads=sum(len(c.pins) for c in base.components),
        segments=sum(len(t.points)-1 for t in base.tracks), vias=len(base.vias),
        polygon_vertices=sum(len(z.outline)+sum(len(h) for h in z.holes)
            +sum(len(p.points)+sum(len(h) for h in p.holes) for p in z.filled_polygons) for z in base.zones))
    # Existing DRC has quadratic pair/contour work. Do not enter it on an
    # oversized layout and then pretend the A* expansion budget bounds it.
    limited = complexity['pads'] > 256 or complexity['segments'] > 512 or complexity['vias'] > 256 or complexity['polygon_vertices'] > 512
    trials = []
    for index, count in enumerate(counts):
        allowance = max_expansions//len(counts)+(1 if index < max_expansions % len(counts) else 0)
        raw = base.model_dump(mode='json'); raw['layer_count'] = count
        try:
            candidate = PCBProject.model_validate(raw)
        except ValueError:
            # Explicit non-endpoint via spans are not silently widened to the
            # new stack. F/B endpoint pairs already have physical-span meaning.
            finding=dict(code='candidate_stack_incompatible',severity='warning',refs=[],
                message='Preserved declared copper/via spans cannot be represented unchanged on this larger stack; no span or pad access was invented and routing was not run.')
            trials.append(dict(layer_count=count,scope='all-supported',routing_layers=copper_layers(raw),
                status='blocked',blockers=[finding],new_tracks=0,new_vias=0,
                geometric_check=dict(status='not_run_incompatible_stack',findings=[finding],checked_layers=[],manufacturing_qualified=False),
                connectivity_complete=False,expansions=0,geometry_tests=0,expansion_budget=allowance,warnings_preserved=True))
            continue
        layers = [active_layer] if active_layer else copper_layers(candidate)
        if limited:
            finding = dict(code='routing_aid_resource_scope', severity='warning', refs=[],
                message='Layout exceeds the bounded aid scope (256 pads,512 segments,256 vias,512 polygon vertices); no routing or DRC was run. This is not a layer impossibility verdict.')
            trial = dict(layer_count=count, scope='current-layer' if active_layer else 'all-supported',
                routing_layers=layers, status='budget_exhausted', blockers=[finding], new_tracks=0, new_vias=0,
                geometric_check=dict(status='not_run_resource_limit', findings=[finding], checked_layers=[], manufacturing_qualified=False),
                connectivity_complete=False, expansions=0, geometry_tests=0, expansion_budget=allowance,
                input_complexity=complexity, warnings_preserved=True)
        else:
            trial = _trial(candidate, layers, width_mm, allowance)
        trials.append(trial)
        if trial['status'] == 'routed':
            break
    strict = [t['layer_count'] for t in trials if t['status'] == 'routed']
    connected = [t['layer_count'] for t in trials if 'candidate' in t or 'qualified_candidate' in t]
    return dict(base_sha256=pcb_digest(base), trials=trials,
        minimum_successful_tested_layers=min(strict) if strict else None,
        minimum_geometrically_routed_layers=min(connected) if connected else None,
        mathematical_minimum_proven=False,
        supported_layer_candidates=[2,4,6,8],
        unsupported_layer_candidates=[],
        unsupported_layer_candidates_status='all_listed_candidates_have_geometric_models_not_fabrication_qualification',
        parameters=dict(active_layer=active_layer, width_mm=width_mm, max_expansions=max_expansions),
        total_expansions=sum(t['expansions'] for t in trials), original_modified=False,
        limits=['Heuristic Manhattan/grid search with a fixed net/MST order; failure or resource exhaustion never proves impossibility or a minimum layer count.',
                'Existing copper, zones, pad layers, placements and pricing are preserved; a larger stack is a preview, never applied here.',
                'New vias reuse only an existing explicit full-stack via geometry template; absent drill/process rules are not guessed.',
                'The model supplies a rectangular board and copper clearances, not arbitrary outlines, keepouts, signal-layer roles, fabrication stackup or drill/annular-ring rules.',
                'Stored fills and drilled contact retain all inspect_layout warnings. No manufacturing, ampacity, thermal, impedance, electrical or physical qualification.'])
