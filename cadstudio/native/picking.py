"""Screen-distance picking with exact curve projection for sketch inference."""
import math
from . import geometry as G


def nearest_curve(entity, p, samples):
    kind = entity['kind']
    if kind == 'line':
        a, b = entity['start'], entity['end']
        v = G.sub(b, a)
        t = max(0, min(1, G.dot(G.sub(p, a), v) / max(G.dot(v, v), 1e-20)))
        return G.add(a, G.mul(v, t))
    if kind in ('circle', 'arc'):
        angle = G.angle(G.sub(p, entity['center']))
        if kind == 'arc':
            start, sweep = entity['start_angle'], entity['sweep']
            delta = (angle-start) % 360 if sweep > 0 else (start-angle) % 360
            if delta > abs(sweep):
                return min((G.at(entity, 0), G.at(entity, 1)), key=lambda q: G.dist(p, q))
        return G.add(entity['center'], G.rotate(G.pt(entity['radius'], 0), angle))
    if kind in ('ellipse', 'spline'):
        # Refine the closest sampled parameter on the analytic curve, not the
        # painted polyline. Consequently a snapped point is truly on the curve.
        from scipy.optimize import minimize_scalar
        count = 64
        i = min(range(count+1), key=lambda j: G.dist(p, G.at(entity, j/count)))
        lo, hi = max(0, (i-1)/count), min(1, (i+1)/count)
        result = minimize_scalar(lambda t: G.dist(p, G.at(entity, t))**2,
                                 bounds=(lo, hi), method='bounded', options={'xatol': 1e-12})
        return min((G.at(entity, result.x), G.at(entity, lo), G.at(entity, hi)), key=lambda q: G.dist(p, q))
    return None


def infer(p, entities, samples, candidates, tolerance):
    """Prefer semantic points before a nearest point on a curve."""
    close = [s for s in candidates if G.dist(p, s['p']) <= tolerance]
    if close:
        best = min(close, key=lambda s: (G.dist(p, s['p']), s['type'] != '교점'))
        return dict(best)
    best, distance = None, tolerance
    for e in entities:
        # Cheap bounding rejection before analytic projection of splines.
        rows = samples.get(e['id'], [])
        pts = [q for row in rows for q in row]
        if not pts: continue
        if not (min(q['x'] for q in pts)-tolerance <= p['x'] <= max(q['x'] for q in pts)+tolerance
                and min(q['y'] for q in pts)-tolerance <= p['y'] <= max(q['y'] for q in pts)+tolerance): continue
        q = nearest_curve(e, p, rows)
        if q is not None and G.dist(p, q) < distance:
            distance = G.dist(p, q)
            best = dict(p=q, type='곡선 위' if e['kind'] != 'line' else '선 위', ids=[e['id']])
    return best
