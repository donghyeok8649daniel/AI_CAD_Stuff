"""Small planar geometry helpers; copper contact witnesses are conservative.

Pads are exact rotated rounded rectangles (circles/ovals are special cases).
Drilled contact uses points verified inside both copper regions, so an absent
witness never licenses a physical connectivity or manufacturing assertion.
"""
import math

EPS = 1e-9


def xy(point):
    if hasattr(point, 'x_mm'):
        return point.x_mm, point.y_mm
    if isinstance(point, dict):
        return point['x_mm'], point['y_mm']
    return tuple(point)


def ring(points):
    result = [xy(point) for point in points]
    return result[:-1] if len(result) > 1 and result[0] == result[-1] else result


def edges(points):
    return list(zip(points, points[1:] + points[:1])) if len(points) > 2 else [(points[0], points[-1])]


def point_segment_distance(p, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    t = max(0, min(1, ((p[0]-a[0])*dx + (p[1]-a[1])*dy)/(dx*dx+dy*dy))) if dx or dy else 0
    return math.hypot(p[0]-a[0]-t*dx, p[1]-a[1]-t*dy)


def cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])


def segment_distance(a, b, c, d):
    if cross(a,b,c)*cross(a,b,d) <= 0 and cross(c,d,a)*cross(c,d,b) <= 0 and max(min(a[0],b[0]),min(c[0],d[0])) <= min(max(a[0],b[0]),max(c[0],d[0])) and max(min(a[1],b[1]),min(c[1],d[1])) <= min(max(a[1],b[1]),max(c[1],d[1])):
        return 0.0
    return min(point_segment_distance(a,c,d),point_segment_distance(b,c,d),point_segment_distance(c,a,b),point_segment_distance(d,a,b))


def in_ring(point, points, boundary=True):
    if any(point_segment_distance(point,a,b) <= EPS for a,b in edges(points)):
        return boundary
    x, y = point
    inside = False
    for a,b in edges(points):
        if (a[1] > y) != (b[1] > y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            inside = not inside
    return inside


def region(points, holes=()):
    return dict(points=ring(points), holes=[ring(hole) for hole in holes])


def region_contains(point, polygon):
    return in_ring(point, polygon['points']) and not any(in_ring(point,hole,boundary=False) for hole in polygon['holes'])


def region_interior_contains(point, polygon):
    return in_ring(point,polygon['points'],boundary=False) and not any(in_ring(point,hole) for hole in polygon['holes'])


def region_edges(polygon):
    return [edge for loop in [polygon['points'], *polygon['holes']] for edge in edges(loop)]


def is_simple_ring(points):
    loop = ring(points)
    if len(set(loop)) != len(loop):
        return False
    loop_edges = edges(loop)
    for i,(a,b) in enumerate(loop_edges):
        for j in range(i+1,len(loop_edges)):
            if j == i+1 or (i == 0 and j == len(loop_edges)-1):
                continue
            if segment_distance(a,b,*loop_edges[j]) <= EPS:
                return False
    return True


def validate_polygon(points, holes, allow_fractured=False):
    outer, inner = ring(points), [ring(hole) for hole in holes]
    for loop in [outer, *inner]:
        fractured = allow_fractured and loop is outer
        limit = 8192 if fractured else 4096
        if len(loop) < 3 or len(loop) > limit or len(set(loop)) < 3 or (not fractured and len(set(loop)) != len(loop)):
            raise ValueError('Polygon ring needs at least three distinct vertices within its bounded size; only stored fill contours may retain repeated vertices.')
        area = sum(a[0]*b[1]-b[0]*a[1] for a,b in edges(loop))
        if abs(area) <= EPS:
            raise ValueError('Polygon ring must have nonzero area.')
        if not fractured and not is_simple_ring(loop):
            raise ValueError('Self-intersecting declared polygon rings are unsupported.')
    for i,hole in enumerate(inner):
        if not all(in_ring(point,outer,boundary=False) for point in hole) or any(segment_distance(a,b,c,d) <= EPS for a,b in edges(hole) for c,d in edges(outer)):
            raise ValueError('Polygon holes must lie strictly within the outer ring.')
        for other in inner[:i]:
            if in_ring(hole[0],other) or in_ring(other[0],hole) or any(segment_distance(a,b,c,d) <= EPS for a,b in edges(hole) for c,d in edges(other)):
                raise ValueError('Polygon holes must be disjoint.')


def pad_core(pad):
    w, h = pad['size_x_mm'], pad['size_y_mm']
    radius = min(w,h)/2 if pad['shape'] in ('circle','oval') else min(w,h)*pad['roundrect_rratio'] if pad['shape'] == 'roundrect' else 0
    hx, hy = w/2-radius, h/2-radius
    local = [(0,0)] if hx <= EPS and hy <= EPS else [(-hx,0),(hx,0)] if hy <= EPS else [(0,-hy),(0,hy)] if hx <= EPS else [(-hx,-hy),(hx,-hy),(hx,hy),(-hx,hy)]
    angle = math.radians(pad['rotation_deg'])
    ca, sa = math.cos(angle), math.sin(angle)
    return [(pad['x']+x*ca-y*sa,pad['y']+x*sa+y*ca) for x,y in local], radius


def core_contains(point, core):
    return point_segment_distance(point,core[0],core[-1]) <= EPS if len(core) <= 2 else in_ring(point,core)


def core_distance(a, b):
    if any(core_contains(point,b) for point in a) or any(core_contains(point,a) for point in b):
        return 0.0
    return min(segment_distance(x,y,u,v) for x,y in edges(a) for u,v in edges(b))


def core_overlap(a, b):
    if len(a) < 3 or len(b) < 3:
        return False
    for start,end in [*edges(a),*edges(b)]:
        axis = (end[1]-start[1],start[0]-end[0])
        pa = [x*axis[0]+y*axis[1] for x,y in a]
        pb = [x*axis[0]+y*axis[1] for x,y in b]
        if min(max(pa),max(pb))-max(min(pa),min(pb)) <= EPS:
            return False
    return True


def pad_gap(a, b):
    ca, ra = pad_core(a)
    cb, rb = pad_core(b)
    return core_distance(ca,cb)-ra-rb


def pad_track_gap(pad, segment):
    core, radius = pad_core(pad)
    return core_distance(core,[segment['a'],segment['b']])-radius-segment['radius']


def pad_bounds(pad):
    core, radius = pad_core(pad)
    return min(x for x,y in core)-radius,min(y for x,y in core)-radius,max(x for x,y in core)+radius,max(y for x,y in core)+radius


def pad_contains(point, pad):
    core, radius = pad_core(pad)
    outer = min(point_segment_distance(point,a,b) for a,b in edges(core)) <= radius+EPS or core_contains(point,core)
    return outer and math.hypot(point[0]-pad['x'],point[1]-pad['y'])+EPS >= pad.get('drill_mm',0)/2


def pad_witnesses(pad):
    core, radius = pad_core(pad)
    points = list(core) + [(pad['x'],pad['y'])]
    # All generated points are checked against the exact region by callers.
    for x,y in core:
        points.extend((x+radius*math.cos(i*math.pi/32),y+radius*math.sin(i*math.pi/32)) for i in range(64))
    drill = pad.get('drill_mm',0)/2
    if drill:
        points.extend((pad['x']+drill*math.cos(i*math.pi/32),pad['y']+drill*math.sin(i*math.pi/32)) for i in range(64))
    return [point for point in points if pad_contains(point,pad)]


def pads_connected(a, b):
    if pad_gap(a,b) > EPS:
        return False
    if not a.get('drill_mm') and not b.get('drill_mm'):
        return True
    return any(pad_contains(point,a) and pad_contains(point,b) for point in [*pad_witnesses(a),*pad_witnesses(b)])


def pad_track_connected(pad, segment):
    if pad_track_gap(pad,segment) > EPS:
        return False
    drill = pad.get('drill_mm',0)/2
    if not drill:
        return True
    if pad['shape'] == 'circle':
        # A connected capsule crosses the annulus exactly when its nearest
        # radius is within the pad and its farthest radius reaches past the hole.
        return max(math.hypot(x-pad['x'],y-pad['y']) for x,y in (segment['a'],segment['b']))+segment['radius'] > drill+EPS
    return any(point_segment_distance(point,segment['a'],segment['b']) <= segment['radius']+EPS for point in pad_witnesses(pad))


def core_region_distance(core, polygon):
    if any(region_contains(point,polygon) for point in core) or any(core_contains(point,core) for point in polygon['points']):
        return 0.0
    return min(segment_distance(a,b,c,d) for a,b in edges(core) for c,d in region_edges(polygon))


def pad_region_gap(pad, polygon):
    core, radius = pad_core(pad)
    return core_region_distance(core,polygon)-radius


def track_region_gap(segment, polygon):
    return core_region_distance([segment['a'],segment['b']],polygon)-segment['radius']


def regions_gap(a, b):
    if any(region_contains(point,b) for point in a['points']) or any(region_contains(point,a) for point in b['points']):
        return 0.0
    return min(segment_distance(x,y,u,v) for x,y in region_edges(a) for u,v in region_edges(b))


def region_within(inner, outer):
    # Include edge interiors: vertices alone can miss a concave boundary crossing.
    for a,b in edges(inner['points']):
        if not all(region_contains((a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])),outer) for t in (0,.25,.5,.75,1)):
            return False
        for c,d in region_edges(outer):
            if cross(a,b,c)*cross(a,b,d) < -EPS and cross(c,d,a)*cross(c,d,b) < -EPS:
                return False
    # A filled polygon may surround a declared cutout only if it retains that hole.
    return all(not region_interior_contains(hole[0],inner) for hole in outer['holes'])
