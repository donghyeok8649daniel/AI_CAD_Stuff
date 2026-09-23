"""Editable, cut helical threads with a simplified truncated 60-degree profile.

These are nominal metric dimensions, not certified ISO tolerance classes.
All frames are part-local; the kernel applies the assembly transform afterwards.
"""
import math
import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface
from .models import CylinderReference, ModelFrame

METRIC_PITCHES = ((2,.4),(2.5,.45),(3,.5),(4,.7),(5,.8),(6,1),(8,1.25),
                  (10,1.5),(12,1.75),(14,2),(16,2),(18,2.5),(20,2.5),
                  (24,3),(30,3.5),(36,4),(42,4.5),(48,5))
DEPTH_FACTOR = 5*math.sqrt(3)/16


def cylinder_reference(face, index, face_count):
    if face.geomType() != 'CYLINDER':
        raise ValueError('완전한 원통 면을 선택하세요.')
    u0,u1,v0,v1=face._uvBounds()
    if abs(u1-u0-2*math.pi)>1e-5:
        raise ValueError('잘리거나 이미 가공된 원통 면입니다. 나사 피처 이전의 원통 면을 선택하세요.')
    cylinder=BRepAdaptor_Surface(face.wrapped).Cylinder()
    if abs(face.Area()-2*math.pi*cylinder.Radius()*(v1-v0))>max(1e-4,face.Area()*1e-5):
        raise ValueError('옆 구멍이나 잘린 경계가 없는 완전한 원통 면을 선택하세요.')
    axis=cq.Vector(cylinder.Axis().Direction());location=cq.Vector(cylinder.Location())
    x=cq.Vector(cylinder.XAxis().Direction())
    # Orient the axis consistently even when OCCT reverses its parameterization.
    sign=1 if max(axis.toTuple(),key=abs)>0 else -1
    origin=location+axis.multiply(v0 if sign>0 else v1)
    axis=axis.multiply(sign)
    sample=face._geomAdaptor().Value((u0+u1)/2,(v0+v1)/2)
    delta=cq.Vector(sample)-location;radial=delta-axis.multiply(delta.dot(axis))
    internal=face.normalAt().dot(radial)<0
    return CylinderReference(index=index,face_count=face_count,diameter=2*cylinder.Radius(),
        length=v1-v0,frame=ModelFrame(origin=list(origin.toTuple()),normal=list(axis.toTuple()),x_direction=list(x.toTuple())),internal=internal)


def cylinder_records(shape):
    faces=shape.Faces();records=[]
    for index,face in enumerate(faces):
        try:records.append(cylinder_reference(face,index,len(faces)))
        except ValueError:continue
    return records


def suggested_size(ref):
    if ref.internal:
        return min(METRIC_PITCHES,key=lambda dp:abs(dp[0]-2*DEPTH_FACTOR*dp[1]-ref.diameter))
    d,p=min(METRIC_PITCHES,key=lambda dp:abs(dp[0]-ref.diameter))
    return ref.diameter,p


def thread_title(feature):
    return (f"{'암나사' if feature.cylinder.internal else '수나사'} M{feature.diameter:g} × {feature.pitch:g}"
            f" · {feature.length:g} mm · {'좌' if feature.handedness=='left' else '우'}")


def apply_thread(shape, feature):
    """Validate the face reference, sweep a groove, and cut only the axial interval."""
    ref=feature.cylinder;faces=shape.Faces()
    if len(faces)!=ref.face_count or ref.index>=len(faces):
        raise ValueError('나사산이 참조한 면 구성이 변경되었습니다. 원통 면을 다시 선택하세요.')
    actual=cylinder_reference(faces[ref.index],ref.index,len(faces))
    if (actual.internal!=ref.internal or abs(actual.diameter-ref.diameter)>1e-5 or
        abs(actual.length-ref.length)>1e-5 or any(math.dist(getattr(actual.frame,k),getattr(ref.frame,k))>1e-5 for k in ('origin','normal','x_direction'))):
        raise ValueError('나사산 기준 원통의 치수·위치가 변경되었습니다. 원통 면을 다시 선택하세요.')
    p=feature.pitch;depth=DEPTH_FACTOR*p;eps=min(.01,p*.01)
    major=feature.diameter/2 + (feature.clearance if ref.internal else -feature.clearance)
    minor=major-depth
    if minor<=.05:raise ValueError('나사 뿌리 지름이 너무 작습니다.')
    # The female groove lies half a pitch from the male groove. Quarter-turn
    # datums avoid aligning the sweep's cap with the cylinder's periodic seam.
    start=-1.75*p if ref.internal else -1.25*p;length=feature.length
    # External groove: wide at the crest. Internal groove: narrow at the root.
    if ref.internal:
        radii=[minor-eps,major,major,minor-eps]
        widths=[-3*p/8-eps/math.sqrt(3),-p/16,p/16,3*p/8+eps/math.sqrt(3)]
    else:
        radii=[minor,major+eps,major+eps,minor]
        widths=[-p/8,-7*p/16-eps/math.sqrt(3),7*p/16+eps/math.sqrt(3),p/8]
    wire=cq.Wire.makePolygon([cq.Vector(r,0,start+z) for r,z in zip(radii,widths)],close=True)
    path=cq.Wire.makeHelix(p,length+3*p,(major+minor)/2,center=(0,0,start),lefthand=feature.handedness=='left')
    axis=cq.Vector(*ref.frame.normal);origin=cq.Vector(*ref.frame.origin)
    if feature.reverse:origin=origin+axis.multiply(ref.length);axis=axis.multiply(-1)
    plane=cq.Plane(origin=origin+axis.multiply(feature.offset),xDir=ref.frame.x_direction,normal=axis)
    # Extend a tool into empty space at open ends. Blind-hole floors and
    # shoulders keep the exact limit; coincident end caps otherwise destabilize
    # OCCT's cut of a full-length thread.
    probe_r=0 if ref.internal else minor/2
    allowance=p*.001
    start_extra=allowance if feature.offset<1e-7 and not shape.isInside(plane.toWorldCoords((probe_r,0,-allowance))) else 0
    end_extra=allowance if abs(feature.offset+length-ref.length)<1e-7 and not shape.isInside(plane.toWorldCoords((probe_r,0,length+allowance))) else 0
    try:
        cutter=cq.Solid.sweep(wire,[],path,makeSolid=True,isFrenet=True)
        if ref.internal:
            # Fuse before clipping: coincident end caps on a clipped helix and
            # core can make OCCT discard the groove in otherwise valid solids.
            core=cq.Solid.makeCylinder(minor,length+6*p,cq.Vector(0,0,-3*p))
            cutter=cutter.fuse(core)
        elif feature.clearance:
            outer=cq.Solid.makeCylinder(ref.diameter/2+.1,length+6*p,cq.Vector(0,0,-3*p))
            inner=cq.Solid.makeCylinder(major,length+6*p,cq.Vector(0,0,-3*p))
            cutter=cutter.fuse(outer.cut(inner))
        limit=cq.Solid.makeCylinder(max(major,ref.diameter/2)+.1,length+start_extra+end_extra,cq.Vector(0,0,-start_extra))
        cutter=cutter.intersect(limit)
        cutter=cutter.moved(plane.location)
        result=shape.cut(cutter).clean()
    except Exception as exc:
        raise ValueError('나사산 형상을 만들지 못했습니다. 피치·길이·주변 벽 두께를 확인하세요.') from exc
    if (not result.isValid() or len(result.Solids())!=len(shape.Solids()) or
        result.Volume()<=0 or shape.Volume()-result.Volume()<1e-7):
        raise ValueError('나사산이 부품을 분리하거나 유효한 절삭을 만들지 못했습니다.')
    # Detect a silent OCCT no-op that only trims the clearance cylinder. The
    # swept trapezoid's angular fraction gives its analytic removed volume.
    slope=(-1 if ref.internal else 1)*2/(math.sqrt(3)*p)
    intercept=(.75 if ref.internal else .25)-slope*minor
    low=max(minor,ref.diameter/2) if ref.internal else minor
    integral=lambda r:intercept*r*r/2+slope*r*r*r/3
    groove=2*math.pi*length*(integral(major)-integral(low))
    annulus=math.pi*length*(max(0,minor**2-(ref.diameter/2)**2) if ref.internal else (ref.diameter/2)**2-major**2)
    removed=shape.Volume()-result.Volume()
    if abs(removed-groove-annulus)>max(.01,(groove+annulus)*.03):
        raise ValueError('나사 절삭량이 예상 형상과 다릅니다. 주변 벽 두께·내부 구멍 또는 나사 길이를 확인하세요.')
    return result
