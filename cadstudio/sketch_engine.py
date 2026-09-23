"""Analytic 2D curves, numerical constraints and OCCT planar profile extraction."""
from copy import deepcopy
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import numpy as np
from scipy.interpolate import BSpline, make_interp_spline
from scipy.optimize import least_squares, minimize_scalar


def parameter_paths(e):
    kind=e['kind'];paths=[]
    def point(key):paths.extend([(key,'x'),(key,'y')])
    if kind=='line':point('start');point('end')
    elif kind in {'circle','arc','ellipse'}:
        point('center')
        paths.extend([(key,) for key in ({'circle':['radius'],'arc':['radius','start_angle','sweep'],'ellipse':['radius_x','radius_y','rotation']}[kind])])
    elif kind=='spline':paths=[('points',i,k) for i in range(len(e['points'])) for k in ['x','y']]
    else:
        point('position')
        if kind=='text':paths.extend([('size',),('rotation',)])
    return paths


def values(e):
    result=[]
    for path in parameter_paths(e):
        v=e
        for key in path:v=v[key]
        result.append(float(v))
    return result


@lru_cache(maxsize=256)
def spline_curve(coordinates,style,closed):
    pts=np.array(coordinates,dtype=float).reshape((-1,2));n=len(pts);degree=min(3,n-1)
    if np.min(np.linalg.norm(np.diff(pts,axis=0),axis=1))<1e-7:raise ValueError('스플라인의 연속 점이 중복됩니다.')
    if style=='control':
        if closed:
            return BSpline(np.arange(-degree,n+degree+1)/n,np.vstack([pts,pts[:degree]]),degree)
        knots=np.r_[np.zeros(degree+1),np.linspace(0,1,n-degree+1)[1:-1],np.ones(degree+1)]
        return BSpline(knots,pts,degree)
    if closed:pts=np.vstack([pts,pts[0]])
    distances=np.r_[0,np.cumsum(np.linalg.norm(np.diff(pts,axis=0),axis=1))];distances/=distances[-1]
    return make_interp_spline(distances,pts,k=degree,bc_type='periodic' if closed else None)


def xy(p):return np.array([p['x'],p['y']],dtype=float)
def spline(e):return spline_curve(tuple(v for p in e['points'] for v in [p['x'],p['y']]),e['style'],e['closed'])
def rotation(degrees):
    t=math.radians(degrees);return np.array([[math.cos(t),-math.sin(t)],[math.sin(t),math.cos(t)]])


def curve(e,u=0,derivative=0):
    kind=e['kind']
    if kind=='line':return xy(e['start'])+(xy(e['end'])-xy(e['start']))*u if not derivative else xy(e['end'])-xy(e['start']) if derivative==1 else np.zeros(2)
    if kind=='spline':return spline(e)(u,nu=derivative)
    if kind in {'point','text'}:return xy(e['position']) if not derivative else np.zeros(2)
    start=math.radians(e.get('start_angle',0));sweep=math.radians(e.get('sweep',360));t=start+u*sweep
    rx=e.get('radius',e.get('radius_x'));ry=e.get('radius',e.get('radius_y'));r=rotation(e.get('rotation',0))
    if derivative==0:return xy(e['center'])+r@np.array([rx*math.cos(t),ry*math.sin(t)])
    if derivative==1:return r@np.array([-rx*math.sin(t),ry*math.cos(t)])*sweep
    return r@np.array([-rx*math.cos(t),-ry*math.sin(t)])*sweep*sweep


def point(e,anchor):
    if anchor in {'center','all'}:
        if 'center' in e:return xy(e['center'])
        if 'position' in e:return xy(e['position'])
        return curve(e,.5)
    return curve(e,1 if anchor=='end' else .5 if anchor=='mid' else 0)


def line_vector(e):
    if e['kind']!='line':raise ValueError('이 구속은 직선 요소를 선택해야 합니다.')
    v=xy(e['end'])-xy(e['start']);return v/max(np.linalg.norm(v),1e-9)
def cross(a,b):return float(a[0]*b[1]-a[1]*b[0])
def radius(e):
    if e['kind'] not in {'circle','arc'}:raise ValueError('반지름·접선 구속은 원 또는 원호를 선택하세요.')
    return e['radius']


def constraint_residual(c,entities):
    a=entities[c.a];b=entities.get(c.b);axis=entities.get(c.c);kind=c.kind
    pa=point(a,c.a_point);pb=point(b,c.b_point) if b else None
    if kind=='fixed':
        if c.a_point=='all':
            current=values(a)
            if len(c.reference)!=len(current):raise ValueError('형상 전체 고정에는 고정 당시의 좌표·치수가 필요합니다.')
            return np.array(current)-np.array(c.reference)
        return pa-np.array([c.x,c.y])
    if kind in {'horizontal','vertical'}:
        if b is None and a['kind']!='line':raise ValueError('수평·수직 구속은 직선이나 두 점을 선택하세요.')
        delta=pb-pa if b else curve(a,1)-curve(a,0)
        return [delta[1] if kind=='horizontal' else delta[0]]
    if kind in {'radius','diameter'}:
        if c.value<=0:raise ValueError('반지름·직경은 양수여야 합니다.')
        return [radius(a)*(2 if kind=='diameter' else 1)-c.value]
    if kind=='angle':
        va=line_vector(a);vb=line_vector(b) if b else np.array([1.,0.]);target=rotation(c.value)@vb
        return [cross(target,va)*20,min(0,float(va@target))*20]
    if b is None:raise ValueError('이 구속에는 두 번째 요소가 필요합니다.')
    delta=pb-pa
    if kind=='coincident':return delta
    if kind=='distance':
        if c.value<0:raise ValueError('거리는 음수일 수 없습니다.')
        return [np.linalg.norm(delta)-c.value]
    if kind in {'dx','dy'}:return [delta[0 if kind=='dx' else 1]-c.value]
    if kind=='parallel':return [cross(line_vector(a),line_vector(b))*20]
    if kind=='perpendicular':return [float(line_vector(a)@line_vector(b))*20]
    if kind=='collinear':return [cross(line_vector(a),line_vector(b))*20,cross(line_vector(a),xy(b['start'])-xy(a['start']))]
    if kind=='concentric':
        if 'center' not in a or 'center' not in b:raise ValueError('동심 구속은 원·호·타원에 적용합니다.')
        return xy(a['center'])-xy(b['center'])
    if kind=='equal':
        if a['kind']==b['kind']=='line':return [np.linalg.norm(curve(a,1)-curve(a,0))-np.linalg.norm(curve(b,1)-curve(b,0))]
        if a['kind']==b['kind']=='ellipse':return [a['radius_x']-b['radius_x'],a['radius_y']-b['radius_y']]
        return [radius(a)-radius(b)]
    if kind=='midpoint':return pa-curve(b,.5)
    if kind=='symmetry':
        if axis is None:raise ValueError('대칭 구속에는 기준 직선 C가 필요합니다.')
        direction=line_vector(axis)
        return [cross(direction,(pa+pb)/2-xy(axis['start'])),float((pb-pa)@direction)]
    if kind=='point_on':
        if b['kind']=='line':return [cross(line_vector(b),pa-xy(b['start']))]
        if b['kind'] in {'circle','arc'}:return [np.linalg.norm(pa-xy(b['center']))-radius(b)]
        if b['kind']=='ellipse':
            local=rotation(-b['rotation'])@(pa-xy(b['center']))
            return [(math.hypot(local[0]/b['radius_x'],local[1]/b['radius_y'])-1)*min(b['radius_x'],b['radius_y'])]
        if b['kind']=='spline':
            samples=np.linspace(0,1,33);i=int(np.argmin([np.linalg.norm(curve(b,u)-pa) for u in samples]))
            nearest=minimize_scalar(lambda u:float(np.sum((curve(b,u)-pa)**2)),bounds=(samples[max(0,i-1)],samples[min(32,i+1)]),method='bounded',options={'xatol':1e-12})
            tangent=curve(b,nearest.x,1);delta=pa-curve(b,nearest.x)
            return [cross(tangent/max(np.linalg.norm(tangent),1e-9),delta)]
        raise ValueError('점-곡선 구속에는 곡선 요소가 필요합니다.')
    if kind=='tangent':
        if a['kind']=='line' and b['kind'] in {'circle','arc'}:return [abs(cross(line_vector(a),xy(b['center'])-xy(a['start'])))-radius(b)]
        if b['kind']=='line' and a['kind'] in {'circle','arc'}:return [abs(cross(line_vector(b),xy(a['center'])-xy(b['start'])))-radius(a)]
        if a['kind'] in {'circle','arc'} and b['kind'] in {'circle','arc'}:
            target=radius(a)+radius(b) if c.mode=='external' else abs(radius(a)-radius(b))
            return [np.linalg.norm(xy(a['center'])-xy(b['center']))-target]
    if kind in {'tangent','curvature'}:
        ua=1 if c.a_point=='end' else 0;ub=1 if c.b_point=='end' else 0
        ta,tb=curve(a,ua,1),curve(b,ub,1);la,lb=max(np.linalg.norm(ta),1e-9),max(np.linalg.norm(tb),1e-9)
        result=[*(curve(a,ua)-curve(b,ub)),cross(ta/la,tb/lb)*20]
        if kind=='curvature':
            ka=cross(ta,curve(a,ua,2))/la**3;kb=cross(tb,curve(b,ub,2))/lb**3
            result.append((ka-kb)*100)
        return result
    raise ValueError('지원하지 않는 스케치 구속입니다.')


def _solve_entities(entities,constraints):
    raw=[e.model_dump() for e in entities];ids=[e['id'] for e in raw]
    if len(set(ids))!=len(ids):raise ValueError('스케치 요소 ID가 중복됩니다.')
    if len({c.id for c in constraints})!=len(constraints):raise ValueError('스케치 구속 ID가 중복됩니다.')
    for c in constraints:
        if c.a not in ids or (c.b and c.b not in ids) or (c.c and c.c not in ids):raise ValueError('스케치 구속이 삭제된 요소를 참조합니다.')
    mapping=[];original=[];lower=[];upper=[]
    for i,e in enumerate(raw):
        for path,value in zip(parameter_paths(e),values(e)):
            mapping.append((i,path));original.append(value)
            key=path[-1]
            lo,hi=(.01,2000) if key in {'radius','radius_x','radius_y','size'} else (-359.99,359.99) if key=='sweep' else (-360,360) if key in {'rotation','start_angle'} else (-1000,1000)
            lower.append(lo);upper.append(hi)
    if len(original)>600:raise ValueError('스케치가 너무 복잡합니다. 스케치를 나누어 600개 이하의 좌표·치수 변수로 구성하세요.')
    def unpack(vector):
        data=deepcopy(raw)
        for (i,path),value in zip(mapping,vector):
            item=data[i]
            for key in path[:-1]:item=item[key]
            item[path[-1]]=float(value)
        return data
    def residual(vector):
        data={e['id']:e for e in unpack(vector)}
        return np.array([v for c in constraints for v in constraint_residual(c,data)],dtype=float)
    maximum=0;rank=0;solved=np.array(original);null=np.eye(len(original))
    if constraints:
        origin=np.array(original)
        result=least_squares(lambda v:np.r_[residual(v),(v-origin)*1e-7],origin,bounds=(lower,upper),max_nfev=200,ftol=1e-10,xtol=1e-10,gtol=1e-10)
        errors=residual(result.x);maximum=float(np.max(np.abs(errors))) if len(errors) else 0
        if maximum>1e-4:raise ValueError(f'스케치 구속이 충돌하거나 해를 찾지 못했습니다 (잔차 {maximum:.4g}).')
        _,singular,vt=np.linalg.svd(result.jac[:len(errors)],full_matrices=True)
        rank=int(np.count_nonzero(singular>1e-6));null=vt[rank:].T;solved=result.x
    updated=unpack(solved)
    for e in updated:
        if e['kind']=='line' and np.linalg.norm(xy(e['end'])-xy(e['start']))<1e-5:raise ValueError('길이가 0인 선은 만들 수 없습니다.')
        if e['kind']=='arc' and abs(e['sweep'])<.001:raise ValueError('원호의 각도가 너무 작습니다.')
        if e['kind']=='spline':spline(e)
    mobility={}
    for i,e in enumerate(raw):
        rows=[j for j,(entity,_) in enumerate(mapping) if entity==i]
        block=null[rows,:]
        mobility[e['id']]=int(np.linalg.matrix_rank(block,tol=1e-6)) if block.size else 0
    return [type(old).model_validate(data) for old,data in zip(entities,updated)],{'dof':max(0,len(original)-rank),'rank':rank,'max_error':maximum,'constraints':len(constraints),'entities':len(entities),'entity_dof':mobility}


@lru_cache(maxsize=128)
def _solve_cached(serialized):
    from pydantic import TypeAdapter
    from .models import SketchEntity,EntityConstraint
    e,c=json.loads(serialized)
    entities,status=_solve_entities(TypeAdapter(list[SketchEntity]).validate_python(e),[EntityConstraint.model_validate(item) for item in c])
    return entities,status


def solve_entities(entities,constraints):
    solved,status=_solve_cached(json.dumps([[e.model_dump() for e in entities],[c.model_dump() for c in constraints]],sort_keys=True))
    return [e.model_copy(deep=True) for e in solved],deepcopy(status)


def edges_for_entity(e):
    import cadquery as cq
    def vector(p):return cq.Vector(float(p[0]),float(p[1]),0)
    kind=e['kind']
    if kind=='point':return []
    if kind=='line':return [cq.Edge.makeLine(vector(xy(e['start'])),vector(xy(e['end'])))]
    if kind=='circle':return [cq.Edge.makeCircle(e['radius'],vector(xy(e['center'])))]
    if kind=='arc':return [cq.Edge.makeThreePointArc(vector(curve(e,0)),vector(curve(e,.5)),vector(curve(e,1)))]
    if kind=='ellipse':
        a=math.radians(e['rotation']);return [cq.Edge.makeEllipse(e['radius_x'],e['radius_y'],vector(xy(e['center'])),(0,0,1),(math.cos(a),math.sin(a),0))]
    if kind=='text':
        path=Path(os.getenv('WINDIR','C:/Windows'))/'Fonts'/('arial.ttf' if e['font']=='Arial' else 'malgun.ttf')
        if not path.exists():raise ValueError('선택한 글꼴이 설치되어 있지 않습니다.')
        shape=cq.Workplane('XY').text(e['text'],e['size'],.1,fontPath=str(path),halign='left',valign='bottom',combine=False).val()
        shape=shape.rotate((0,0,0),(0,0,1),e['rotation']).translate((*xy(e['position']),0))
        return [edge for face in shape.Faces() if face.geomType()=='PLANE' and face.normalAt().z<-.999 for edge in face.Edges()]
    from OCP.Geom import Geom_BSplineCurve
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.TColStd import TColStd_Array1OfReal,TColStd_Array1OfInteger
    from OCP.gp import gp_Pnt
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    b=spline(e);poles=TColgp_Array1OfPnt(1,len(b.c))
    for i,p in enumerate(b.c,1):poles.SetValue(i,gp_Pnt(float(p[0]),float(p[1]),0))
    unique,mults=np.unique(b.t,return_counts=True);knots=TColStd_Array1OfReal(1,len(unique));multiplicities=TColStd_Array1OfInteger(1,len(unique))
    for i,(u,m) in enumerate(zip(unique,mults),1):knots.SetValue(i,float(u));multiplicities.SetValue(i,int(m))
    native=Geom_BSplineCurve(poles,knots,multiplicities,b.k,False)
    return [cq.Edge(BRepBuilderAPI_MakeEdge(native,0.,1.).Edge())]


@lru_cache(maxsize=24)
def _regions_cached(serialized):
    import cadquery as cq
    raw=json.loads(serialized);edges=[edge for e in raw if not e['construction'] for edge in edges_for_entity(e)]
    if not edges:return []
    if len(edges)>1600:raise ValueError('스케치 곡선이 너무 많습니다. 텍스트나 패턴을 나누세요.')
    bounds=cq.Compound.makeCompound(edges).BoundingBox();extent=max(abs(v) for v in [bounds.xmin,bounds.xmax,bounds.ymin,bounds.ymax])+20
    background=cq.Face.makePlane(extent*2,extent*2)
    split=background.split(*edges)
    faces=[]
    for face in split.Faces():
        if any(abs(v.Center().x)>extent-1e-4 or abs(v.Center().y)>extent-1e-4 for v in face.Vertices()):continue
        if face.Area()>.0001 and face.isValid():faces.append(face)
    return sorted(faces,key=lambda f:(-round(f.Area(),7),round(f.Center().x,7),round(f.Center().y,7)))


def profile_regions(g):return _regions_cached(json.dumps([e.model_dump() for e in g.entities],sort_keys=True))


def extrude_regions(g,plane=None,direction=1):
    import cadquery as cq
    faces=profile_regions(g);selected=g.profiles or [0]
    if not faces:raise ValueError('닫힌 스케치 영역이 없습니다. 끝점을 일치시키고 영역을 선택하세요.')
    if len(set(selected))!=len(selected) or any(i>=len(faces) for i in selected):raise ValueError('선택한 스케치 영역이 변경되었습니다. 영역을 다시 선택하세요.')
    solids=[cq.Solid.extrudeLinear(faces[i].outerWire(),faces[i].innerWires(),(0,0,g.thickness*direction)) for i in selected]
    shape=solids[0].fuse(*solids[1:]).clean() if len(solids)>1 else solids[0]
    return shape.moved(cq.Location(plane)) if plane else shape


def sketch_status(g):
    if g.sketch_mode=='entities':return solve_entities(g.entities,g.entity_constraints)[1]
    from .constraints import solve_sketch
    return solve_sketch(g.points,g.constraints)[1]


def sketch_preview(g):
    import cadquery as cq
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    entities=[];edge_sets=[]
    for model in g.entities:
        e=model.model_dump();lines=[]
        edges=edges_for_entity(e);edge_sets.append((e,edges))
        for edge in edges:
            samples,_=edge.sample(65)
            if edge.IsClosed() and samples:samples.append(samples[0])
            lines.append([[v.x,v.y] for v in samples])
        entities.append({'id':e['id'],'lines':lines})
    regions=[]
    for i,face in enumerate(profile_regions(g)):
        outlines=[]
        for wire in [face.outerWire(),*face.innerWires()]:
            pts,_=wire.sample(max(80,len(wire.Edges())*12));outlines.append([[p.x,p.y] for p in pts])
        # Associate exact entity edges with region boundaries, including edges
        # split by intersections. This enables line-to-profile selection.
        boundary=cq.Compound.makeCompound(face.Edges());members=[]
        for e,edges in edge_sets:
            if e['construction']:continue
            if any(boundary.distance(cq.Vertex.makeVertex(*edge.positionAt(t).toTuple()))<1e-5 for edge in edges for t in (.25,.5,.75)):members.append(e['id'])
        regions.append({'index':i,'area':face.Area(),'outline':outlines,'entity_ids':members})
    intersections=[]
    for i,(a,ea) in enumerate(edge_sets):
        if a['kind'] in {'point','text'}:continue
        for b,eb in edge_sets[i+1:]:
            if b['kind'] in {'point','text'}:continue
            for x in ea:
                bx=x.BoundingBox()
                for y in eb:
                    by=y.BoundingBox()
                    if any(min(getattr(bx,k+'max'),getattr(by,k+'max'))<max(getattr(bx,k+'min'),getattr(by,k+'min'))-1e-7 for k in 'xy'):continue
                    section=cq.Shape(BRepAlgoAPI_Section(x.wrapped,y.wrapped).Shape())
                    for v in section.Vertices():
                        p=v.Center();intersections.append({'x':p.x,'y':p.y,'a':a['id'],'b':b['id']})
    return {'entities':entities,'regions':regions,'intersections':intersections}


def projected_face(face,plane):
    result=[];unsupported=0
    def point(p):
        v=plane.toLocalCoords(p);return {'x':v.x,'y':v.y}
    for i,edge in enumerate(face.Edges()):
        common={'id':f'edge-{i}','construction':False}
        if edge.geomType()=='LINE':result.append(dict(common,kind='line',start=point(edge.startPoint()),end=point(edge.endPoint())))
        elif edge.geomType()=='CIRCLE':
            c=point(edge.arcCenter());r=edge.radius()
            if edge.IsClosed():result.append(dict(common,kind='circle',center=c,radius=r))
            else:
                a,b,d=[point(edge.positionAt(t)) for t in [0,.5,1]]
                angles=[math.degrees(math.atan2(p['y']-c['y'],p['x']-c['x'])) for p in [a,b,d]]
                mid=(angles[1]-angles[0])%360;end=(angles[2]-angles[0])%360
                result.append(dict(common,kind='arc',center=c,radius=r,start_angle=angles[0],sweep=end if mid<end else end-360))
        else:unsupported+=1
    return result,unsupported
