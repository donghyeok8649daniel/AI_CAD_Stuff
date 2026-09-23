"""Exact CAD inspection; distance in mm, inertia in kg m²."""
import math
import cadquery as cq
import numpy as np
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp


def mass_properties(shape,density):
    if not shape.Solids():raise ValueError('질량 계산에는 닫힌 솔리드가 필요합니다.')
    if not 0<density<=30000:raise ValueError('밀도는 0 초과 30000 kg/m³ 이하여야 합니다.')
    prop=GProp_GProps();BRepGProp.VolumeProperties_s(shape.wrapped,prop);c=prop.CentreOfMass();tensor=prop.MatrixOfInertia()
    return dict(volume_mm3=prop.Mass(),area_mm2=shape.Area(),mass_kg=prop.Mass()*density*1e-9,center_mm=[c.X(),c.Y(),c.Z()],inertia_kg_m2=[[tensor.Value(i+1,j+1)*density*1e-15 for j in range(3)] for i in range(3)])


def angle_between(first,second):
    if isinstance(first,cq.Edge) and isinstance(second,cq.Edge):
        if first.geomType()!='LINE' or second.geomType()!='LINE':raise ValueError('각도 측정은 직선 모서리 두 개를 선택하세요.')
        a,b=first.tangentAt(),second.tangentAt()
    elif isinstance(first,cq.Face) and isinstance(second,cq.Face):
        if first.geomType()!='PLANE' or second.geomType()!='PLANE':raise ValueError('평면 두 개를 선택하세요.')
        a,b=first.normalAt(),second.normalAt()
    else:raise ValueError('같은 종류의 직선 두 개 또는 평면 두 개를 선택하세요.')
    return math.degrees(math.acos(float(np.clip(a.dot(b)/(a.Length*b.Length),-1,1))))


def minimum_distance(first,second):
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    distance=BRepExtrema_DistShapeShape(first.wrapped,second.wrapped)
    if not distance.IsDone() or distance.NbSolution()<1:raise ValueError('최소 간격을 계산할 수 없습니다.')
    a=distance.PointOnShape1(1);b=distance.PointOnShape2(1)
    return dict(distance_mm=distance.Value(),points=[[a.X(),a.Y(),a.Z()],[b.X(),b.Y(),b.Z()]])


def section(shape,origin,normal):
    from .kernel import exact_bounds
    direction=cq.Vector(*normal)
    if direction.Length<1e-9:raise ValueError('단면 방향을 지정하세요.')
    b=exact_bounds(shape);span=max(b.xlen,b.ylen,b.zlen,1)*8+cq.Vector(*origin).Length*2
    plane=cq.Face.makePlane(span,span,cq.Vector(*origin),direction.normalized());result=shape.intersect(plane)
    if not result.Faces():raise ValueError('단면 평면이 몸체 내부를 통과하지 않습니다.')
    return result
