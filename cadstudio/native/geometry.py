"""Analytic sketch construction and editing used by the native canvas."""
from copy import deepcopy
import math
from uuid import uuid4

def uid():return uuid4().hex
def pt(x,y):return dict(x=float(x),y=float(y))
def add(a,b):return pt(a['x']+b['x'],a['y']+b['y'])
def sub(a,b):return pt(a['x']-b['x'],a['y']-b['y'])
def mul(a,k):return pt(a['x']*k,a['y']*k)
def dot(a,b):return a['x']*b['x']+a['y']*b['y']
def cross(a,b):return a['x']*b['y']-a['y']*b['x']
def length(a):return math.hypot(a['x'],a['y'])
def dist(a,b):return length(sub(a,b))
def unit(a):return mul(a,1/max(length(a),1e-12))
def left(a):return pt(-a['y'],a['x'])
def angle(a):return math.degrees(math.atan2(a['y'],a['x']))
def norm(a):return (a+180)%360-180
def rotate(a,degrees):
    t=math.radians(degrees);return pt(a['x']*math.cos(t)-a['y']*math.sin(t),a['x']*math.sin(t)+a['y']*math.cos(t))
def entity(kind,**fields):return dict(id=uid(),construction=False,kind=kind,**deepcopy(fields))
def line(a,b):return entity('line',start=a,end=b)
def circle(c,r):return entity('circle',center=c,radius=r)
def arc(c,r,start,sweep):return entity('arc',center=c,radius=r,start_angle=norm(start),sweep=sweep)
def at(e,t):
    if e['kind']=='line':return add(e['start'],mul(sub(e['end'],e['start']),t))
    if e['kind'] in ('point','text'):return e['position']
    if e['kind']=='spline':
        from ..sketch_engine import curve
        p=curve(e,t);return pt(p[0],p[1])
    a=math.radians(e.get('start_angle',0)+t*e.get('sweep',360))
    return add(e['center'],rotate(pt(e.get('radius',e.get('radius_x',1))*math.cos(a),e.get('radius',e.get('radius_y',1))*math.sin(a)),e.get('rotation',0)))
def anchors(e):
    k=e['kind']
    if k=='line':return [('start',e['start']),('end',e['end']),('mid',at(e,.5))]
    if k=='arc':return [('start',at(e,0)),('end',at(e,1)),('center',e['center']),('mid',at(e,.5))]
    if k=='spline':return [('start',e['points'][0]),('end',e['points'][-1])]
    if k in ('circle','ellipse'):return [('center',e['center'])]+[('quadrant',at(e,i/4)) for i in range(4)]
    return [('start',e['position'])]
def closed_lines(points):return [line(p,points[(i+1)%len(points)]) for i,p in enumerate(points)]
def three_arc(a,b,c,full=False):
    v=sub(b,a);w=sub(c,a);den=2*cross(v,w)
    if abs(den)<1e-7:raise ValueError('세 점이 한 직선 위에 있습니다.')
    center=add(a,pt((length(v)**2*w['y']-length(w)**2*v['y'])/den,(v['x']*length(w)**2-w['x']*length(v)**2)/den));r=dist(center,a)
    if full:return circle(center,r)
    start=angle(sub(a,center));mid=(angle(sub(b,center))-start)%360;end=(angle(sub(c,center))-start)%360
    return arc(center,r,start,end if mid<end else end-360)

def create(tool,points,options=None):
    o=options or {};a=points[0];b=points[1] if len(points)>1 else None;c=points[2] if len(points)>2 else None;r=dist(a,b) if b else 0
    if tool=='line':return [line(a,b)]
    if tool=='point':return [entity('point',position=a)]
    if tool=='text':return [entity('text',position=a,text=o.get('text','CAD'),size=o.get('size',10),rotation=0,font=o.get('font','Malgun Gothic'))]
    if tool in ('rectangle','center-rectangle'):
        first=a if tool=='rectangle' else sub(mul(a,2),b);return closed_lines([first,pt(b['x'],first['y']),b,pt(first['x'],b['y'])])
    if tool=='rectangle-3':
        v=unit(sub(b,a));h=mul(left(v),cross(v,sub(c,b)));return closed_lines([a,b,add(b,h),add(a,h)])
    if tool=='circle':return [circle(a,r)]
    if tool=='circle-2':return [circle(mul(add(a,b),.5),r/2)]
    if tool in ('circle-3','arc-3'):return [three_arc(a,b,c,tool=='circle-3')]
    if tool=='arc-center':
        start=angle(sub(b,a));sweep=(angle(sub(c,a))-start)%360;return [arc(a,r,start,sweep-360 if o.get('clockwise') else sweep)]
    if tool=='ellipse':return [entity('ellipse',center=a,radius_x=r,radius_y=abs(cross(unit(sub(b,a)),sub(c,a))),rotation=angle(sub(b,a)))]
    if tool in ('polygon','polygon-inscribed'):
        n=max(3,min(32,int(o.get('count',6))));radius=r/math.cos(math.pi/n) if tool=='polygon-inscribed' else r;phase=angle(sub(b,a))+(180/n if tool=='polygon-inscribed' else 0)
        return closed_lines([add(a,rotate(pt(radius,0),phase+i*360/n)) for i in range(n)])
    if tool in ('slot','center-slot'):
        first=a if tool=='slot' else sub(mul(a,2),b);v=unit(sub(b,first));radius=abs(cross(v,sub(c,first)));n=mul(left(v),radius);start=angle(n)
        return [line(add(first,n),add(b,n)),arc(b,radius,start,-180),line(sub(b,n),sub(first,n)),arc(first,radius,start+180,-180)]
    if tool in ('spline-fit','spline-control'):return [entity('spline',points=points,style='fit' if tool=='spline-fit' else 'control',closed=bool(o.get('closed')))]
    raise ValueError('도구의 입력 점을 확인하세요.')

def transform(e,dx=0,dy=0,degrees=0,scale=1,center=None,axis=None):
    center=center or pt(0,0)
    def f(p):
        q=mul(sub(p,center),scale)
        if axis:
            v=unit(sub(axis['end'],axis['start']));d=sub(add(q,center),axis['start']);q=add(axis['start'],sub(mul(v,2*dot(d,v)),d));return add(q,pt(dx,dy))
        return add(add(rotate(q,degrees),center),pt(dx,dy))
    out=deepcopy(e)
    for key in ('start','end','center','position'):
        if key in e:out[key]=f(e[key])
    if 'points' in e:out['points']=[f(p) for p in e['points']]
    for key in ('radius','radius_x','radius_y','size'):
        if key in e:out[key]*=abs(scale)
    if e['kind']=='arc':
        out['start_angle']=angle(sub(f(at(e,0)),out['center']))
        if axis:out['sweep']=-out['sweep']
    if e['kind'] in ('ellipse','text'):
        if axis and e['kind']=='text':raise ValueError('텍스트에는 이동·회전·배율을 사용하세요.')
        out['rotation']=norm(2*angle(sub(axis['end'],axis['start']))-e['rotation'] if axis else e['rotation']+degrees)
    return out

def parameter(e,p):
    if e['kind']=='line':
        v=sub(e['end'],e['start']);return dot(sub(p,e['start']),v)/max(dot(v,v),1e-20)
    a=angle(sub(p,e['center']));s=e.get('start_angle',0);d=e.get('sweep',360)
    return (a-s)%360/d if d>0 else -((s-a)%360)/d
def intersections(a,b,infinite_a=False,infinite_b=False):
    if a['kind'] not in ('line','circle','arc') or b['kind'] not in ('line','circle','arc'):return []
    points=[]
    if a['kind']==b['kind']=='line':
        v=sub(a['end'],a['start']);w=sub(b['end'],b['start']);den=cross(v,w)
        if abs(den)>1e-10:points=[add(a['start'],mul(v,cross(sub(b['start'],a['start']),w)/den))]
    elif 'line' in (a['kind'],b['kind']):
        l,c=(a,b) if a['kind']=='line' else (b,a);v=sub(l['end'],l['start']);q=sub(l['start'],c['center']);aa=dot(v,v);bb=2*dot(q,v);cc=dot(q,q)-c['radius']**2;d=bb*bb-4*aa*cc
        if aa>1e-20 and d>=-1e-9:
            s=math.sqrt(max(0,d));points=[add(l['start'],mul(v,t)) for t in ((-bb-s)/(2*aa),(-bb+s)/(2*aa))]
    else:
        v=sub(b['center'],a['center']);d=length(v)
        if d>1e-9 and d<=a['radius']+b['radius']+1e-8 and d>=abs(a['radius']-b['radius'])-1e-8:
            x=(a['radius']**2-b['radius']**2+d*d)/(2*d);h=math.sqrt(max(0,a['radius']**2-x*x));mid=add(a['center'],mul(v,x/d));n=mul(left(v),h/d);points=[add(mid,n),sub(mid,n)]
    def within(e,p,inf):return inf or e['kind']=='circle' or -1e-7<=parameter(e,p)<=1+1e-7 or dist(at(e,1),p)<1e-6
    return [p for i,p in enumerate(points) if within(a,p,infinite_a) and within(b,p,infinite_b) and not any(dist(p,q)<1e-7 for q in points[:i])]
def piece(e,a,b):
    out=line(at(e,a),at(e,b)) if e['kind']=='line' else arc(e['center'],e['radius'],e.get('start_angle',0)+e.get('sweep',360)*a,e.get('sweep',360)*(b-a));out['construction']=e['construction'];return out
def trim(e,others,p):
    if e['kind'] not in ('line','circle','arc'):raise ValueError('자르기: 직선·원·원호를 선택하세요.')
    ts=sorted({round(parameter(e,q),10) for o in others if o['id']!=e['id'] and not o['construction'] for q in intersections(e,o) if 1e-7<parameter(e,q)<1-1e-7});t=parameter(e,p)
    if e['kind']=='circle':
        if len(ts)<2:raise ValueError('원을 자르려면 두 곳 이상의 교점이 필요합니다.')
        upper=next((x for x in ts if x>t),ts[0]+1);lower=next((x for x in reversed(ts) if x<t),ts[-1]-1);return [piece(e,upper,lower+1)]
    if not ts:raise ValueError('교차하는 경계가 없습니다.')
    lo=next((x for x in reversed(ts) if x<t),0);hi=next((x for x in ts if x>t),1)
    return ([piece(e,0,lo)] if lo>1e-7 else [])+([piece(e,hi,1)] if hi<1-1e-7 else [])
def split(e,p):
    if e['kind'] not in ('line','arc'):raise ValueError('분할: 직선 또는 원호를 선택하세요.')
    t=parameter(e,p)
    if not .001<t<.999:raise ValueError('끝점 사이를 클릭하세요.')
    return [piece(e,0,t),piece(e,t,1)]
def extend(e,others,p):
    if e['kind']!='line':raise ValueError('연장: 직선을 선택하세요.')
    end=dist(p,e['start'])>dist(p,e['end']);ts=sorted([parameter(e,q) for o in others if o['id']!=e['id'] for q in intersections(e,o,True) if (parameter(e,q)>1+1e-7 if end else parameter(e,q)<-1e-7)],reverse=not end)
    if not ts:raise ValueError('연장 방향에 경계가 없습니다.')
    return [piece(e,0 if end else ts[0],ts[0] if end else 1)]
def offset(entities,d):
    out=[]
    for e in entities:
        if e['kind']=='line':
            n=mul(left(unit(sub(e['end'],e['start']))),d);v=line(add(e['start'],n),add(e['end'],n));v['construction']=e['construction'];out.append(v)
        elif e['kind'] in ('circle','arc'):
            if e['radius']+d<=.01:raise ValueError('간격이 반지름보다 큽니다.')
            v=deepcopy(e);v.update(id=uid(),radius=e['radius']+d);out.append(v)
        else:raise ValueError('간격띄우기: 직선·원·원호를 선택하세요.')
    for i,a in enumerate(entities):
        for j,b in enumerate(entities[i+1:],i+1):
            if a['kind']==b['kind']=='line':
                hits=intersections(out[i],out[j],True,True)
                if hits:
                    for x in ('start','end'):
                        for y in ('start','end'):
                            if dist(a[x],b[y])<1e-5:out[i][x]=deepcopy(hits[0]);out[j][y]=deepcopy(hits[0])
    return out
def corner(a,b,d,fillet):
    if a['kind']!='line' or b['kind']!='line':raise ValueError('두 직선을 선택하세요.')
    hits=intersections(a,b,True,True)
    if not hits or d<=0:raise ValueError('평행선이거나 유효하지 않은 크기입니다.')
    v=hits[0];pa=max((a['start'],a['end']),key=lambda p:dist(p,v));pb=max((b['start'],b['end']),key=lambda p:dist(p,v));u=unit(sub(pa,v));w=unit(sub(pb,v));theta=math.acos(max(-1,min(1,dot(u,w))))
    if theta<.001 or math.pi-theta<.001:raise ValueError('모서리 각도가 너무 작습니다.')
    cut=d/math.tan(theta/2) if fillet else d
    if cut>=min(dist(pa,v),dist(pb,v)):raise ValueError('모서리 크기가 선보다 큽니다.')
    x=add(v,mul(u,cut));y=add(v,mul(w,cut));l1=line(pa,x);l2=line(y,pb);l1['id']=a['id'];l2['id']=b['id']
    if not fillet:return [l1,line(x,y),l2]
    c=add(v,mul(unit(add(u,w)),d/math.sin(theta/2)));s=angle(sub(x,c));return [l1,arc(c,d,s,norm(angle(sub(y,c))-s)),l2]
def to_entities(sketch):
    g=deepcopy(sketch)
    if g.get('sketch_mode')=='entities':return g
    g.update(sketch_mode='entities',entities=closed_lines(g['points']),entity_constraints=[],profiles=[])
    ids=[e['id'] for e in g['entities']]
    def constraint(kind,a,b='',**fields):g['entity_constraints'].append(dict(id=uid(),kind=kind,a=a,b=b,**fields))
    for i,id in enumerate(ids):constraint('coincident',id,ids[(i+1)%len(ids)],a_point='end',b_point='start')
    for c in g.get('constraints',[]):
        if c['kind']=='angle':
            helper=line(g['points'][c['a']],g['points'][c['b']]);helper['construction']=True;g['entities'].append(helper);constraint('coincident',helper['id'],ids[c['a']]);constraint('coincident',helper['id'],ids[c['b']],a_point='end');constraint('angle',helper['id'],value=c['value'])
        else:constraint(c['kind'],ids[c['a']],'' if c['kind']=='fixed' else ids[c['b']],value=c['value'],x=c['x'],y=c['y'])
    g['entities'] += [circle(pt(h['x'],h['y']),h['diameter']/2) for h in g.get('holes',[])]
    g.update(constraints=[],holes=[]);return g
