"""Cached geometric inference for drawing tangent and normal sketch lines."""
import json,math
from functools import lru_cache
import numpy as np
from scipy.optimize import brentq
from . import geometry as G
from ..sketch_engine import curve


@lru_cache(maxsize=12)
def contact_candidates(serialized,x,y):
    entities=json.loads(serialized);origin=np.array([x,y]);result=[]
    for e in entities:
        if e['kind'] not in ('line','circle','arc','ellipse','spline'):continue
        for kind in ('tangent','normal'):
            if kind=='tangent' and e['kind']=='line':continue
            def function(t):
                delta=curve(e,t)-origin;v=curve(e,t,1);v=v/max(np.linalg.norm(v),1e-12)
                return float(delta[0]*v[1]-delta[1]*v[0] if kind=='tangent' else delta@v)
            count=1 if e['kind']=='line' else 64;ts=np.linspace(0,1,count+1);ys=[function(t) for t in ts]
            if max(abs(v) for v in ys)<1e-8:continue
            roots=[]
            for i in range(count):
                t=ts[i] if abs(ys[i])<1e-9 else ts[i+1] if abs(ys[i+1])<1e-9 else brentq(function,ts[i],ts[i+1],xtol=1e-12) if ys[i]*ys[i+1]<0 else None
                if t is not None and not any(abs(t-r)<1e-7 for r in roots):roots.append(t)
            for t in roots:
                q=curve(e,t)
                if np.linalg.norm(q-origin)<1e-6:continue
                result.append(dict(p=G.pt(*q),ids=[e['id']],type='접점' if kind=='tangent' else '수선의 발' if e['kind']=='line' else '법선 접점',constraint=kind,contact='end'))
    return result


def line_inference(p,start,entities,samples,tolerance,mode='auto'):
    if mode=='off' or G.dist(p,start)<tolerance*2:return None
    from .picking import nearest_curve
    candidates=[]
    allowed={'tangent','normal'} if mode=='auto' else {'normal','perpendicular'} if mode=='perpendicular' else {mode}
    for snap in contact_candidates(json.dumps(entities,sort_keys=True),start['x'],start['y']):
        if snap['constraint'] in allowed and G.dist(p,snap['p'])<=tolerance:candidates.append(snap)
    for e in entities:
        if e['kind'] not in ('line','circle','arc','ellipse','spline'):continue
        q=nearest_curve(e,start,samples.get(e['id'],[]))
        at_contact=q is not None and G.dist(q,start)<1e-6
        if e['kind']=='line':
            directions=[('parallel',G.sub(e['end'],e['start']),'평행'),('perpendicular',G.left(G.sub(e['end'],e['start'])),'수직')]
            if mode in ('normal','tangent') and at_contact:directions=[(mode,directions[mode=='normal'][1],'법선' if mode=='normal' else '접선')]
        elif at_contact:
            from ..sketch_engine import nearest_parameter
            t=nearest_parameter(e,np.array([start['x'],start['y']]))
            tangent=G.pt(*curve(e,t,1));directions=[('tangent',tangent,'접선'),('normal',G.left(tangent),'법선')]
        else:continue
        for kind,v,name in directions:
            if mode!='auto' and kind not in allowed:continue
            v=G.unit(v);distance=G.dot(G.sub(p,start),v);target=G.add(start,G.mul(v,distance))
            if abs(distance)<2*tolerance or G.dist(p,target)>min(tolerance,abs(distance)*math.sin(math.radians(4))):continue
            candidates.append(dict(p=target,ids=[e['id']],type=name+' 방향',constraint=kind,contact='start' if at_contact else 'end',guide=[start,target]))
    return min(candidates,key=lambda s:G.dist(p,s['p'])) if candidates else None
