"""Actual cylindrical and conical counterbores attached to analytic hole profiles."""
import math
import cadquery as cq


def finish_tool(feature,g,plane):
    circles=[e for e in g.entities if not e.construction]
    if feature.operation!='cut' or g.sketch_mode!='entities' or not circles or any(e.kind!='circle' for e in circles):raise ValueError('자리파기 / 접시머리 구멍은 원형 절삭 스케치에만 적용하세요.')
    tools=[]
    for e in circles:
        radius=feature.head_diameter/2
        if radius<=e.radius:raise ValueError('머리 지름은 기본 구멍 지름보다 커야 합니다.')
        depth=feature.head_depth if feature.hole_finish=='counterbore' else (radius-e.radius)/math.tan(math.radians(feature.head_angle/2))
        if depth>g.thickness+1e-7:raise ValueError('머리 자리 깊이가 구멍 깊이보다 큽니다.')
        origin=plane.toWorldCoords((e.center.x,e.center.y));direction=-plane.zDir
        tools.append(cq.Solid.makeCylinder(radius,depth,origin,direction) if feature.hole_finish=='counterbore' else cq.Solid.makeCone(radius,e.radius,depth,origin,direction))
    return cq.Compound.makeCompound(tools)
