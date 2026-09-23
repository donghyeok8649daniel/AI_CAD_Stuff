"""Screen-distance picking with exact curve projection for sketch inference."""
import math
from . import geometry as G


def grid_step(scale):
    base=10**math.floor(math.log10(24/scale))
    return next(base*n for n in (1,2,5,10) if base*n*scale>=24-1e-9)


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


def infer(p, entities, samples, candidates, tolerance,grid_step=None):
    """Prefer semantic points before a nearest point on a curve."""
    close = [s for s in candidates if G.dist(p, s['p']) <= tolerance]
    if close:
        best = min(close, key=lambda s: (G.dist(p, s['p']), s['type'] != '교점'))
        return dict(best)
    if grid_step:
        grid=grid_inference(p,entities,samples,tolerance,grid_step)
        if grid:return grid
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


def grid_inference(p,entities,samples,tolerance,step):
    """Visible grid intersections. Curve hits outrank empty grid crossings."""
    from scipy.optimize import brentq
    hits=[]
    for e in entities:
        if e['kind'] not in ('line','circle','arc','ellipse','spline'):continue
        points=[q for row in samples.get(e['id'],[]) for q in row]
        if not points or any(not min(q[k] for q in points)-tolerance<=p[k]<=max(q[k] for q in points)+tolerance for k in ('x','y')):continue
        count=1 if e['kind']=='line' else 64
        for axis in ('x','y'):
            value=round(p[axis]/step)*step
            if abs(value-p[axis])>tolerance:continue
            ts=[i/count for i in range(count+1)];ys=[G.at(e,t)[axis]-value for t in ts]
            for i in range(count):
                if abs(ys[i])<1e-9 and abs(ys[i+1])<1e-9:continue # Entire segment lies on grid.
                root=ts[i] if abs(ys[i])<1e-9 else ts[i+1] if abs(ys[i+1])<1e-9 else brentq(lambda t:G.at(e,t)[axis]-value,ts[i],ts[i+1]) if ys[i]*ys[i+1]<0 else None
                if root is None:continue
                q=G.at(e,root)
                if G.dist(p,q)<=tolerance:hits.append(dict(p=q,type='격자·곡선 교점',ids=[e['id']],grid_axis=axis,grid_value=value))
    if hits:return min(hits,key=lambda h:G.dist(p,h['p']))
    q=G.pt(round(p['x']/step)*step,round(p['y']/step)*step)
    return dict(p=q,type='격자 교점',ids=[]) if G.dist(p,q)<=tolerance else None
