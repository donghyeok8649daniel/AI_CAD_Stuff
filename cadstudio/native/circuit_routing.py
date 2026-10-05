"""Bounded orthogonal circuit routing without inferred electrical junctions.

Routes join only explicitly saved net endpoints. Different nets may cross,
but never share a positive-length conductor or meet at another net's vertex.
If the bounded search cannot find a route, the caller receives its endpoint
for an explicit net-label fallback rather than a wire through a component.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from heapq import heappop, heappush
from math import isfinite

from PySide6.QtCore import QPointF, QRectF


_EPSILON = 1e-6
_CLEARANCE = 4.0
_LANE = 10.0
_MAX_AXIS = 80
_MAX_PAIR_EXPANSIONS = 6000
_MAX_TOTAL_EXPANSIONS = 60000
_MAX_CONNECTIONS = 512


@dataclass(slots=True)
class CircuitRoutes:
    segments: dict[str, list[tuple[QPointF, QPointF]]]
    unrouted: tuple[tuple[str, str, str], ...]
    junctions: dict[str, list[QPointF]] = field(default_factory=dict)


def _point(point: QPointF) -> tuple[float, float]:
    return (float(point.x()), float(point.y()))


def _on_segment(point, start, end) -> bool:
    x, y = point
    return ((abs(start[1] - end[1]) < _EPSILON and abs(y - start[1]) < _EPSILON
             and min(start[0], end[0]) - _EPSILON <= x <= max(start[0], end[0]) + _EPSILON)
            or (abs(start[0] - end[0]) < _EPSILON and abs(x - start[0]) < _EPSILON
                and min(start[1], end[1]) - _EPSILON <= y <= max(start[1], end[1]) + _EPSILON))


def _shared_segment(start, end, other_start, other_end) -> bool:
    if (abs(start[1] - end[1]) < _EPSILON and abs(other_start[1] - other_end[1]) < _EPSILON
            and abs(start[1] - other_start[1]) < _EPSILON):
        return (min(max(start[0], end[0]), max(other_start[0], other_end[0]))
                - max(min(start[0], end[0]), min(other_start[0], other_end[0]))) > _EPSILON
    if (abs(start[0] - end[0]) < _EPSILON and abs(other_start[0] - other_end[0]) < _EPSILON
            and abs(start[0] - other_start[0]) < _EPSILON):
        return (min(max(start[1], end[1]), max(other_start[1], other_end[1]))
                - max(min(start[1], end[1]), min(other_start[1], other_end[1]))) > _EPSILON
    return False


def _crosses_body(start, end, rectangles) -> bool:
    for rect in rectangles:
        if abs(start[1] - end[1]) < _EPSILON:
            if (rect.top() + _EPSILON < start[1] < rect.bottom() - _EPSILON
                    and min(max(start[0], end[0]), rect.right())
                    - max(min(start[0], end[0]), rect.left()) > _EPSILON):
                return True
        elif (rect.left() + _EPSILON < start[0] < rect.right() - _EPSILON
              and min(max(start[1], end[1]), rect.bottom())
              - max(min(start[1], end[1]), rect.top()) > _EPSILON):
            return True
    return False


def _valid_segment(start, end, rectangles, protected_points, occupied) -> bool:
    if start == end:
        return True
    if abs(start[0] - end[0]) >= _EPSILON and abs(start[1] - end[1]) >= _EPSILON:
        return False
    return (not _crosses_body(start, end, rectangles)
            and not any(_on_segment(point, start, end) for point in protected_points)
            and not any(_shared_segment(start, end, a, b) for a, b in occupied))


def _segments(points):
    return [(a, b) for a, b in zip(points, points[1:]) if a != b]


def _valid_path(points, rectangles, protected_points, occupied) -> bool:
    simplified=_simplify(points)
    return (not any(_on_segment(point,a,b) for point in simplified for a,b in occupied)
            and all(_valid_segment(a, b, rectangles, protected_points, occupied)
                    for a, b in _segments(simplified)))


def _simplify(points):
    result = []
    for point in points:
        if result and point == result[-1]:
            continue
        if len(result) > 1:
            first, middle = result[-2:]
            if (abs(first[0] - middle[0]) < _EPSILON and abs(middle[0] - point[0]) < _EPSILON
                    or abs(first[1] - middle[1]) < _EPSILON and abs(middle[1] - point[1]) < _EPSILON):
                result[-1] = point
                continue
        result.append(point)
    return result


def _axis(values, first, second):
    """Keep nearby channels and exterior detours without an unbounded grid."""
    unique = set(values) | {first, second}
    if len(unique) > _MAX_AXIS:
        low, high = sorted((first, second))
        distance = lambda value: max(low - value, value - high, 0)
        retained = sorted(unique, key=lambda value: (distance(value), min(abs(value-first), abs(value-second)), value))[:_MAX_AXIS-4]
        unique = set(retained) | {min(unique), max(unique), first, second}
    return sorted(unique)


def _path(start, end, rectangles, protected_points, occupied, budget):
    # Most wiring needs zero or one bend. The few channel detours below also
    # cover narrow gaps without moving a lead through an adjacent board.
    candidates = [[start, end], [start, (end[0], start[1]), end],
                  [start, (start[0], end[1]), end]]
    exterior_x = [min([start[0], end[0], *(r.left() for r in rectangles)], default=0) - _LANE,
                  max([start[0], end[0], *(r.right() for r in rectangles)], default=0) + _LANE]
    exterior_y = [min([start[1], end[1], *(r.top() for r in rectangles)], default=0) - _LANE,
                  max([start[1], end[1], *(r.bottom() for r in rectangles)], default=0) + _LANE]
    for coordinate in [start[0]-_LANE, start[0]+_LANE, end[0]-_LANE, end[0]+_LANE, *exterior_x]:
        candidates.append([start, (coordinate, start[1]), (coordinate, end[1]), end])
    for coordinate in [start[1]-_LANE, start[1]+_LANE, end[1]-_LANE, end[1]+_LANE, *exterior_y]:
        candidates.append([start, (start[0], coordinate), (end[0], coordinate), end])
    candidates.sort(key=lambda points: sum(abs(a[0]-b[0]) + abs(a[1]-b[1]) for a,b in _segments(points)))
    for points in candidates:
        if _valid_path(points, rectangles, protected_points, occupied):
            return _simplify(points), 0
    if budget <= 0:
        return None, 0
    xs = {start[0], end[0], *exterior_x}
    ys = {start[1], end[1], *exterior_y}
    for rect in rectangles:
        xs.update((rect.left()-_LANE, rect.right()+_LANE))
        ys.update((rect.top()-_LANE, rect.bottom()+_LANE))
    # Parallel offsets offer distinct conductors without pretending that a
    # routed wire vertex is a junction shared with a different saved net.
    for point in [start, end, *protected_points]:
        xs.update((point[0]-_LANE, point[0]+_LANE))
        ys.update((point[1]-_LANE, point[1]+_LANE))
    xs = _axis(xs, start[0], end[0]); ys = _axis(ys, start[1], end[1])
    start_index = (xs.index(start[0]), ys.index(start[1]))
    end_index = (xs.index(end[0]), ys.index(end[1]))
    frontier = [(abs(start[0]-end[0])+abs(start[1]-end[1]), 0.0, start_index)]
    scores = {start_index: 0.0}; previous = {}; checked = {}; expanded = 0
    limit = min(budget, _MAX_PAIR_EXPANSIONS)
    while frontier and expanded < limit:
        _, cost, current = heappop(frontier)
        if cost != scores.get(current):
            continue
        if current == end_index:
            points = []
            while current != start_index:
                points.append((xs[current[0]], ys[current[1]])); current = previous[current]
            points.append(start)
            simplified=_simplify(list(reversed(points)))
            return (simplified if _valid_path(simplified,rectangles,protected_points,occupied) else None), expanded
        expanded += 1
        x, y = current
        current_point = (xs[x], ys[y])
        for neighbor in ((x-1,y), (x+1,y), (x,y-1), (x,y+1)):
            nx, ny = neighbor
            if not (0 <= nx < len(xs) and 0 <= ny < len(ys)):
                continue
            edge = tuple(sorted((current, neighbor)))
            valid = checked.get(edge)
            point = (xs[nx], ys[ny])
            # Grid subdivisions may cross a foreign wire without creating a
            # junction. At that exact crossing continue straight: a bend or
            # termination would look like a T connection to the foreign net.
            if current in previous and any(_on_segment(current_point,a,b) for a,b in occupied):
                px,py=previous[current]
                old=(xs[px],ys[py])
                if ((abs(old[0]-current_point[0])<_EPSILON) !=
                        (abs(point[0]-current_point[0])<_EPSILON)):continue
            if valid is None:
                valid = _valid_segment(current_point, point, rectangles, protected_points, occupied)
                checked[edge] = valid
            if not valid:
                continue
            score = cost + abs(point[0]-current_point[0]) + abs(point[1]-current_point[1])
            if score >= scores.get(neighbor, float("inf")):
                continue
            scores[neighbor] = score; previous[neighbor] = current
            estimate = score + abs(point[0]-end[0]) + abs(point[1]-end[1])
            heappush(frontier, (estimate, score, neighbor))
    return None, expanded


def _junctions(segments):
    points = {point for start,end in segments for point in (start,end)}
    junctions = []
    for point in points:
        directions = set()
        for start,end in segments:
            if not _on_segment(point,start,end):
                continue
            for terminal in (start,end):
                if terminal == point:
                    continue
                dx,dy = terminal[0]-point[0],terminal[1]-point[1]
                directions.add((0 if abs(dx)<_EPSILON else 1 if dx>0 else -1,
                                0 if abs(dy)<_EPSILON else 1 if dy>0 else -1))
        if len(directions) >= 3:
            junctions.append(QPointF(*point))
    return junctions


def route_nets(nets, obstacles, *, reserved_points=(), reserved_segments=None) -> CircuitRoutes:
    """Route explicit nets around body rectangles within a fixed search budget.

    ``nets`` maps a saved node name to ``(component_id, terminal, QPointF,
    port_metadata)`` rows. Metadata is not interpreted or used to infer nets.
    ``obstacles`` are actual body rectangles rather than label bounding boxes.
    ``reserved_points`` are visible, unassigned pad locations; no conductor
    may pass through them and suggest a connection which was never saved.
    ``reserved_segments`` maps saved net names to existing orthogonal leads.
    Callers validate those leads (including any own-board interior exception).
    They are not added to the returned geometry, but other nets cannot share
    them or touch their endpoints. Perpendicular interior crossings stay legal.
    One-endpoint nets need only a label, so they are not reported as failures.
    """
    rectangles = [QRectF(rect).normalized().adjusted(-_CLEARANCE,-_CLEARANCE,_CLEARANCE,_CLEARANCE)
                  for rect in obstacles if rect.width()>0 and rect.height()>0]
    result = {node: [] for node in nets}; raw_segments = {node: [] for node in nets}
    endpoint_points = {node: {_point(row[2]) for row in rows} for node,rows in nets.items()}
    fixed_segments={node:[(_point(start),_point(end)) for start,end in segments if start!=end]
                    for node,segments in (reserved_segments or {}).items()}
    reserved = {_point(point) for point in reserved_points}
    unrouted = []; remaining = _MAX_TOTAL_EXPANSIONS; connections = 0
    for node, endpoints in nets.items():
        if not endpoints:
            continue
        connected = []
        protected = set().union(*(points for name,points in endpoint_points.items() if name != node))
        protected.update(reserved)
        occupied = [segment for collection in (fixed_segments,raw_segments)
                    for name,segments in collection.items() if name != node for segment in segments]
        protected.update(point for segment in occupied for point in segment)
        for component_id, terminal, scene_point, _ in endpoints:
            point = _point(scene_point)
            if not all(isfinite(value) for value in point):
                unrouted.append((node,component_id,terminal)); continue
            if point in connected:
                continue
            if not connected:
                connected.append(point); continue
            if connections >= _MAX_CONNECTIONS:
                unrouted.append((node,component_id,terminal)); continue
            connections += 1
            destination = min(connected, key=lambda other: abs(point[0]-other[0])+abs(point[1]-other[1]))
            path, explored = _path(point, destination, rectangles, protected, occupied, remaining)
            remaining -= explored
            if path is None:
                unrouted.append((node,component_id,terminal)); continue
            connected.append(point)
            for start,end in _segments(path):
                segment = tuple(sorted((start,end)))
                if segment not in raw_segments[node]:
                    raw_segments[node].append(segment)
                    result[node].append((QPointF(*start), QPointF(*end)))
        if len(endpoint_points[node]) > 1 and not result[node]:
            # If no connection could leave the first anchor, it also needs an
            # explicit fallback label; reporting only later pads would hide
            # the disconnected visual island.
            for identifier,terminal,_,_ in endpoints:
                if (node,identifier,terminal) not in unrouted:
                    unrouted.append((node,identifier,terminal))
    return CircuitRoutes(result, tuple(unrouted), {node:_junctions(segments) for node,segments in raw_segments.items()})
