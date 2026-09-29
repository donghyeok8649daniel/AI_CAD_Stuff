"""External unshifted involute spur gears and an editable bearing-plate pair.

Flanks are interpolated involutes; root transitions are radial relief, not a
generated hob trochoid. This is geometry for prototyping, not a load rating.
"""
import math
from copy import deepcopy
from uuid import uuid4
import cadquery as cq
from .models import Design,SpurGear,Part


def construct_gear(g):
    rp=g.module*g.teeth/2;alpha=math.radians(g.pressure_angle)
    rb=rp*math.cos(alpha);ra=rp+g.module;rf=rp-1.25*g.module
    # Pair backlash is shared equally by its two gears at the pitch circles.
    half=math.pi/(2*g.teeth)-g.backlash/(4*rp)
    inv=math.tan(alpha)-alpha
    def angle(r):
        a=math.acos(min(1,rb/r));return half+inv-(math.tan(a)-a)
    def point(r,a):return cq.Vector(r*math.cos(a),r*math.sin(a),0)
    edges=[];start=max(rb,rf);pitch=2*math.pi/g.teeth
    def arc(r,a,b):return cq.Edge.makeThreePointArc(point(r,a),point(r,(a+b)/2),point(r,b))
    for i in range(g.teeth):
        c=i*pitch;root_angle=angle(start)
        if rf<start-1e-8:edges.append(cq.Edge.makeLine(point(rf,c-root_angle),point(start,c-root_angle)))
        radii=[start+(ra-start)*(j/20)**1.5 for j in range(21)]
        edges.append(cq.Edge.makeSpline([point(r,c-angle(r)) for r in radii],tol=1e-7))
        edges.append(arc(ra,c-angle(ra),c+angle(ra)))
        edges.append(cq.Edge.makeSpline([point(r,c+angle(r)) for r in reversed(radii)],tol=1e-7))
        if rf<start-1e-8:edges.append(cq.Edge.makeLine(point(start,c+root_angle),point(rf,c+root_angle)))
        edges.append(arc(rf,c+root_angle,c+pitch-root_angle))
    outer=cq.Wire.assembleEdges(edges)
    holes=[cq.Wire.makeCircle(g.bore_diameter/2,cq.Vector(),cq.Vector(0,0,1))] if g.bore_diameter else []
    solid=cq.Solid.extrudeLinear(outer,holes,cq.Vector(0,0,g.thickness))
    if g.shaft_length:
        shaft=cq.Solid.makeCylinder(g.shaft_diameter/2,g.shaft_length,cq.Vector(0,0,-g.shaft_length))
        solid=solid.fuse(shaft).clean()
    if not solid.isValid() or len(solid.Solids())!=1 or solid.Volume()<=0:raise ValueError('기어 솔리드 생성에 실패했습니다.')
    return solid


def add_gear_pair(raw=None,*,module=2,teeth_a=20,teeth_b=40,thickness=8,backlash=.2,clearance=.2,shaft_diameter=8,origin=(0,0,0),prefix=None):
    if not math.isfinite(clearance) or not .02<=clearance<=2:raise ValueError('축 지름 여유는 0.02~2 mm입니다.')
    if len(origin)!=3 or any(not math.isfinite(v) for v in origin):raise ValueError('배치 좌표를 확인하세요.')
    prefix=prefix or 'gear-'+uuid4().hex[:8]+'-';data=Design.model_validate(deepcopy(raw or {'name':'스퍼 기어 구동','parts':[]})).model_dump()
    specs=[SpurGear(module=module,teeth=z,thickness=thickness,backlash=backlash,shaft_diameter=shaft_diameter,shaft_length=10) for z in (teeth_a,teeth_b)]
    module=specs[0].module;teeth_a=specs[0].teeth;teeth_b=specs[1].teeth;shaft_diameter=specs[0].shaft_diameter
    a=module*(teeth_a+teeth_b)/2;pitch=360/teeth_b;phase=(180-180/teeth_b+pitch/2)%pitch-pitch/2;length=10.;gap=.2
    width=max(module*(teeth_a+2),module*(teeth_b+2))+10
    left=-module*(teeth_a+2)/2-5;right=a+module*(teeth_b+2)/2+5
    base=dict(kind='extrusion',thickness=length,sketch_mode='polygon',points=[dict(x=x,y=y) for x,y in [(left,-width/2),(right,-width/2),(right,width/2),(left,width/2)]],holes=[dict(x=x,y=0,diameter=shaft_diameter+clearance) for x in (0,a)])
    x,y,z=origin
    parts=[Part(id=prefix+'base',name='기어 축 지지판',geometry=base,fixed=True,transform=dict(x=x,y=y,z=z-length-gap),color='#58748a'),
           Part(id=prefix+'input',name=f'입력 기어 · {teeth_a}T',geometry=specs[0],transform=dict(x=x,y=y,z=z),color='#65bea9'),
           Part(id=prefix+'output',name=f'출력 기어 · {teeth_b}T',geometry=specs[1],transform=dict(x=x+a,y=y,z=z,rz=phase),color='#e3b367')]
    ids=[p.id for p in parts]
    if set(ids)&{p['id'] for p in data['parts']}:raise ValueError('기어 부품 ID가 중복됩니다.')
    data['parts'].extend(p.model_dump() for p in parts)
    travel=min(180,(360-abs(phase))/(teeth_a/teeth_b))
    data['mates'].extend([dict(id=prefix+'drive',kind='revolute',parent=ids[0],child=ids[1],z=length+gap,limits={'rz':[-travel,travel]}),dict(id=prefix+'driven',kind='revolute',parent=ids[0],child=ids[2],x=a,z=length+gap,rz=phase)])
    data.setdefault('motion_links',[]).append(dict(id=prefix+'ratio',driver=prefix+'drive',driven=prefix+'driven',ratio=-teeth_a/teeth_b,offset=phase))
    data.setdefault('part_groups',[]).append(dict(id=prefix+'group',name='스퍼 기어 구동',part_ids=ids))
    return Design.model_validate(data)
