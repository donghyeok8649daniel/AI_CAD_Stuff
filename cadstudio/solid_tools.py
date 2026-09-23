"""Validated solid modelling operations using Open CASCADE."""
import math
import cadquery as cq
from .topology import resolve_face


def validate(shape,solid=True):
    if not shape.isValid() or not shape.Faces() or (solid and (not shape.Solids() or shape.Volume()<=1e-8)):
        raise ValueError('유효한 형상을 만들 수 없습니다. 치수와 선택 면을 확인하세요.')
    return shape


def revolve(g):
    from .advanced_geometry import profile_wires
    direction=cq.Vector(*g.axis_direction)
    if direction.Length<1e-9:raise ValueError('회전축 방향을 지정하세요.')
    wires=profile_wires(g.profile);origin=cq.Vector(*g.axis_start)
    return validate(cq.Solid.revolve(wires[0],wires[1:],g.angle,origin,origin+direction))


def apply_operation(shape,f,tool=None):
    direction=cq.Vector(*f.direction).normalized();origin=cq.Vector(*f.origin);op=f.operation
    if op=='shell':
        if abs(f.size)<.01:raise ValueError('셸 두께는 0.01 mm 이상이어야 합니다.')
        if not f.faces:raise ValueError('열어 둘 면을 하나 이상 선택하세요.')
        faces=[resolve_face(shape,r)[1] for r in f.faces]
        result=cq.Workplane().newObject([shape]).newObject(faces).shell(-abs(f.size)).val()
    elif op=='draft':
        from OCP.BRepOffsetAPI import BRepOffsetAPI_DraftAngle
        from OCP.gp import gp_Dir,gp_Pln,gp_Pnt
        if not f.faces or abs(f.angle)<.01 or abs(f.angle)>=80:raise ValueError('구배 면과 0.01~80° 미만 각도를 지정하세요.')
        builder=BRepOffsetAPI_DraftAngle(shape.wrapped);axis=gp_Dir(*direction.toTuple());plane=gp_Pln(gp_Pnt(*origin.toTuple()),axis)
        for ref in f.faces:
            builder.Add(resolve_face(shape,ref)[1].wrapped,axis,math.radians(f.angle),plane,True)
            if not builder.AddDone():raise ValueError('선택 면에 구배를 만들 수 없습니다. 중립 평면과 방향을 확인하세요.')
        builder.Build()
        if not builder.IsDone():raise ValueError('구배 계산에 실패했습니다.')
        result=cq.Shape.cast(builder.Shape())
    elif op=='boolean':
        if tool is None or not tool.Solids():raise ValueError('솔리드 도구 부품을 선택하세요.')
        result={'union':shape.fuse,'cut':shape.cut,'intersect':shape.intersect}[f.boolean_mode](tool).clean()
        if f.boolean_mode=='cut' and abs(result.Volume()-shape.Volume())<1e-7:raise ValueError('도구 부품이 대상 부품과 겹치지 않습니다.')
    elif op=='split':
        from .kernel import exact_bounds
        b=exact_bounds(shape);span=max(b.xlen,b.ylen,b.zlen,1)*8+origin.Length*2
        cutter=cq.Face.makePlane(span,span,origin,direction);result=shape.split(cutter)
        solids=result.Solids()
        if len(solids)<=len(shape.Solids()):raise ValueError('분할 평면이 몸체를 가르지 않습니다.')
        if f.keep_side!='all':
            sign=1 if f.keep_side=='positive' else -1
            solids=[s for s in solids if (s.Center()-origin).dot(direction)*sign>1e-8]
        result=cq.Compound.makeCompound(solids)
    elif op=='mirror':
        mirrored=shape.mirror(direction,origin);result=cq.Compound.makeCompound([shape,mirrored]) if f.keep_original else mirrored
    elif op in ('linear_pattern','circular_pattern'):
        copies=[shape]
        if op=='linear_pattern':
            if abs(f.spacing[0])+abs(f.spacing[2])<.01:raise ValueError('X 방향 반복의 X 또는 Z 간격을 지정하세요.')
            if f.count_y>1 and abs(f.spacing[1])<.01:raise ValueError('Y 방향 반복 간격을 지정하세요.')
            copies=[shape.translate((i*f.spacing[0],j*f.spacing[1],i*f.spacing[2])) for i in range(f.count) for j in range(f.count_y)]
        else:
            if abs(f.angle)<.01:raise ValueError('패턴 각도를 지정하세요.')
            increment=f.angle/(f.count if abs(f.angle)==360 else f.count-1)
            copies.extend(shape.rotate(origin,origin+direction,i*increment) for i in range(1,f.count))
        result=cq.Compound.makeCompound(copies)
    else:raise ValueError('지원하지 않는 솔리드 작업입니다.')
    return validate(result)
