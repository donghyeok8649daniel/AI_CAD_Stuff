import math
from copy import deepcopy
import cadquery as cq
import pytest
from fastapi.testclient import TestClient
from cadstudio.models import Extrusion, EntityConstraint, SketchLine, SketchCircle, SketchPoint, SketchArc, SketchSpline
from cadstudio.sketch_engine import solve_entities, sketch_preview, profile_regions, extrude_regions, projected_face, values
from cadstudio.kernel import construct, face_frame
from cadstudio.server import app


def pt(x,y):return {'x':x,'y':y}
def ln(id,a,b,**kw):return SketchLine(id=id,start=pt(*a),end=pt(*b),**kw)
def circ(id,x=0,y=0,r=10,**kw):return SketchCircle(id=id,center=pt(x,y),radius=r,**kw)
def con(kind,a='a',b='',**kw):return EntityConstraint(id='c'+kind+str(len(kw)),kind=kind,a=a,b=b,**kw)


def test_origin_fixed_circle_stays_at_origin_when_dimension_changes():
    e=circ('a',5,7,8)
    cs=[con('fixed',a_point='center',x=0,y=0),con('diameter',value=30)]
    solved,status=solve_entities([e],cs)
    assert solved[0].center.x==pytest.approx(0,abs=1e-7)
    assert solved[0].center.y==pytest.approx(0,abs=1e-7)
    assert solved[0].radius==pytest.approx(15)
    assert status['dof']==0
    cs[1].value=44
    updated,_=solve_entities(solved,cs)
    assert updated[0].radius==pytest.approx(22)
    assert updated[0].center.x==pytest.approx(0,abs=1e-7)


def test_intersection_constraint_follows_two_fixed_curves():
    a=ln('h',(-20,3),(20,3));b=ln('v',(4,-20),(4,20));p=SketchPoint(id='p',position=pt(3.5,2))
    cs=[con('fixed',a='h',a_point='all',reference=values(a.model_dump())),EntityConstraint(id='fixv',kind='fixed',a='v',a_point='all',reference=values(b.model_dump())),con('point_on',a='p',b='h'),EntityConstraint(id='onv',kind='point_on',a='p',b='v')]
    solved,status=solve_entities([a,b,p],cs)
    assert solved[2].position.x==pytest.approx(4)
    assert solved[2].position.y==pytest.approx(3)
    assert status['dof']==0


@pytest.mark.parametrize('kind,a,b,kwargs',[
    ('horizontal',ln('a',(0,0),(10,0)),None,{}),
    ('vertical',ln('a',(0,0),(0,10)),None,{}),
    ('coincident',ln('a',(0,0),(10,0)),ln('b',(10,0),(10,20)),{'a_point':'end'}),
    ('distance',SketchPoint(id='a',position=pt(0,0)),SketchPoint(id='b',position=pt(3,4)),{'value':5}),
    ('dx',circ('a'),circ('b',4,6),{'a_point':'center','b_point':'center','value':4}),
    ('dy',circ('a'),circ('b',4,6),{'a_point':'center','b_point':'center','value':6}),
    ('angle',ln('a',(0,0),(0,10)),None,{'value':90}),
    ('radius',circ('a'),None,{'value':10}),
    ('parallel',ln('a',(0,0),(10,0)),ln('b',(0,5),(20,5)),{}),
    ('perpendicular',ln('a',(0,0),(10,0)),ln('b',(0,0),(0,20)),{}),
    ('equal',circ('a'),circ('b',5,7),{}),
    ('concentric',circ('a'),circ('b',r=20),{}),
    ('collinear',ln('a',(0,0),(10,0)),ln('b',(12,0),(20,0)),{}),
    ('tangent',circ('a'),ln('b',(-20,10),(20,10)),{}),
    ('midpoint',SketchPoint(id='a',position=pt(5,0)),ln('b',(0,0),(10,0)),{}),
    ('point_on',SketchPoint(id='a',position=pt(0,10)),circ('b'),{}),
    ('curvature',ln('a',(0,0),(10,0)),ln('b',(10,0),(20,0)),{'a_point':'end'}),
])
def test_constraint_residuals_and_rank(kind,a,b,kwargs):
    solved,status=solve_entities([a,*([b] if b else [])],[con(kind,b='b' if b else '',**kwargs)])
    assert status['max_error']<1e-6
    assert status['rank']>=1


def test_symmetry_and_conflicting_dimensions():
    a=circ('a',-5,0);b=circ('b',5,0);axis=ln('axis',(0,-10),(0,10))
    _,s=solve_entities([a,b,axis],[con('symmetry',b='b',c='axis',a_point='center',b_point='center')])
    assert s['rank']==2
    with pytest.raises(ValueError,match='충돌'):
        solve_entities([a],[con('radius',value=5),con('diameter',value=20)])
    with pytest.raises(ValueError,match='삭제'):
        solve_entities([a],[con('equal',b='missing')])


def test_exact_regions_holes_and_construction():
    entities=[ln('a',(-20,-10),(20,-10)),ln('b',(20,-10),(20,10)),ln('c',(20,10),(-20,10)),ln('d',(-20,10),(-20,-10)),circ('hole',r=5),ln('guide',(-25,0),(25,0),construction=True)]
    g=Extrusion(sketch_mode='entities',entities=entities,thickness=4)
    regions=profile_regions(g)
    assert len(regions)==2
    assert regions[0].Area()==pytest.approx(800-math.pi*25)
    assert construct(g).Volume()==pytest.approx((800-math.pi*25)*4)
    g.profiles=[0,1]
    assert construct(g).Volume()==pytest.approx(3200)
    preview=sketch_preview(g)
    hits=[p for p in preview['intersections'] if {p['a'],p['b']}=={'hole','guide'}]
    assert len(hits)==2
    assert sorted(p['x'] for p in hits)==pytest.approx([-5,5])


@pytest.mark.parametrize('style',['fit','control'])
def test_closed_spline_solid(style):
    g=Extrusion(sketch_mode='entities',entities=[{'id':'a','kind':'spline','points':[pt(-10,0),pt(0,10),pt(10,0),pt(0,-10)],'closed':True,'style':style}])
    s=construct(g)
    assert s.isValid() and s.Volume()>100
    assert len(sketch_preview(g)['regions'])==1


def test_ellipse_exact_area_multisolid_selection_and_transformed_plane():
    g=Extrusion(sketch_mode='entities',entities=[{'id':'a','kind':'ellipse','center':pt(0,0),'radius_x':8,'radius_y':15,'rotation':25},circ('b',x=50,r=2)],profiles=[0,1],thickness=3)
    shape=construct(g)
    assert len(shape.Solids())==2
    assert shape.Volume()==pytest.approx(math.pi*(8*15+4)*3)
    plane=cq.Plane(origin=(0,0,20),xDir=(1,0,0),normal=(0,0,1))
    transformed=extrude_regions(g,plane,-1)
    assert transformed.BoundingBox().zmin==pytest.approx(17)


def test_face_projection_is_exact_for_round_and_line_edges():
    face=cq.Workplane('XY').rect(40,30).circle(5).extrude(3).faces('>Z').val()
    items,unsupported=projected_face(face,face_frame(face))
    assert unsupported==0 and len(items)==5
    g=Extrusion(sketch_mode='entities',entities=items)
    assert profile_regions(g)[0].Area()==pytest.approx(1200-math.pi*25)


def test_sketch_api_open_geometry_and_intersections():
    with TestClient(app,headers={'X-CAD-Request':'1'}) as client:
        data=Extrusion(sketch_mode='entities',entities=[ln('a',(-10,0),(10,0)),circ('b',r=5)]).model_dump()
        r=client.post('/api/sketch/solve',json=data)
        assert r.status_code==200
        assert len(r.json()['preview']['intersections'])==2
        assert len(r.json()['preview']['regions'])==2
    with pytest.raises(ValueError,match='닫힌'):
        construct(Extrusion(sketch_mode='entities',entities=[ln('a',(0,0),(10,0))]))
