"""Exact Open CASCADE sweep, loft and edge finishing from editable inputs."""
from copy import deepcopy
import math
import cadquery as cq
import numpy as np
from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
from .sketch_engine import profile_regions, edges_for_entity


def plane(frame):
    return cq.Plane(origin=frame.origin,xDir=frame.x_direction,normal=frame.normal)


def profile_wires(section, closed=True):
    g=section.sketch
    if g.sketch_mode=='entities':
        regions=profile_regions(g)
        if regions:
            selected=g.profiles or [0]
            if len(selected)!=1 or selected[0]>=len(regions):
                raise ValueError('스윕·로프트는 단면마다 닫힌 영역 하나를 선택하세요.')
            face=regions[selected[0]]
            wires=[face.outerWire(),*face.innerWires()]
        elif not closed:
            edges=[edge for e in g.entities if not e.construction for edge in edges_for_entity(e.model_dump())]
            wires=cq.Wire.combine(edges)
            if len(wires)!=1:raise ValueError('곡면 단면은 연결된 곡선 하나여야 합니다.')
        else:
            raise ValueError('솔리드 단면에 닫힌 영역이 없습니다.')
    else:
        outer=cq.Workplane('XY').polyline([(p.x,p.y) for p in g.points]).close().val()
        wires=[outer,*[cq.Wire.makeCircle(h.diameter/2,cq.Vector(h.x,h.y,0),cq.Vector(0,0,1)) for h in g.holes]]
    return [w.moved(cq.Location(plane(section.frame))) for w in wires]


def path_wire(path):
    if path.sketch:
        g=path.sketch
        if g.sketch_mode!='entities':
            points=[cq.Vector(p.x,p.y,0) for p in g.points]
            result=cq.Wire.makePolygon(points,close=True)
        else:
            edges=[edge for e in g.entities if not e.construction for edge in edges_for_entity(e.model_dump())]
            wires=cq.Wire.combine(edges)
            if len(wires)!=1:raise ValueError('스윕 경로는 분기 없이 연결된 곡선 하나여야 합니다.')
            result=wires[0]
        return result.moved(cq.Location(plane(path.frame)))
    points=[cq.Vector(*p) for p in path.points]
    if path.smooth and len(points)>2:return cq.Wire.assembleEdges([cq.Edge.makeSpline(points)])
    return cq.Wire.makePolygon(points)


def construct_sweep(g):
    path=path_wire(g.path)
    wires=profile_wires(g.profile,g.solid)
    if g.align_profile:
        start=path.startPoint();tangent=path.tangentAt(0).normalized()
        source=plane(g.profile.frame)
        x=cq.Vector(*g.profile.frame.x_direction)
        x=x-tangent.multiply(x.dot(tangent))
        if x.Length<1e-5:
            ref=cq.Vector(0,1,0) if abs(tangent.y)<.9 else cq.Vector(1,0,0)
            x=ref-tangent.multiply(ref.dot(tangent))
        target=cq.Plane(start,x.normalized(),tangent)
        wires=[w.moved(cq.Location(source).inverse).moved(cq.Location(target)) for w in wires]
    shape=cq.Solid.sweep(wires[0],wires[1:],path,makeSolid=g.solid,isFrenet=g.frenet,transitionMode='round')
    return validate_shape(shape,g.solid)


def construct_loft(g):
    sections=[profile_wires(section,g.solid) for section in g.sections]
    if any(len(wires)!=1 for wires in sections):
        raise ValueError('로프트는 구멍 없는 단면을 사용하세요. 완성 후 면 스케치로 절삭할 수 있습니다.')
    if any(math.dist(a[0].Center().toTuple(),b[0].Center().toTuple())<.01 for a,b in zip(sections,sections[1:])):
        raise ValueError('로프트 단면을 서로 다른 위치에 배치하세요.')
    builder=BRepOffsetAPI_ThruSections(g.solid,g.ruled,1e-6)
    builder.CheckCompatibility(True)
    for wires in sections:builder.AddWire(wires[0].wrapped)
    builder.Build()
    if not builder.IsDone():raise ValueError('단면 사이에 유효한 로프트를 만들 수 없습니다.')
    return validate_shape(cq.Shape.cast(builder.Shape()),g.solid)


def validate_shape(shape,solid):
    if not shape.isValid() or not shape.Faces() or (solid and (len(shape.Solids())!=1 or shape.Volume()<=1e-7)):
        raise ValueError('유효한 형상을 만들지 못했습니다. 경로 곡률·단면 크기·단면 순서를 확인하세요.')
    return shape


def edge_records(shape):
    records=[]
    from .kernel import exact_bounds
    box=exact_bounds(shape);low=(box.xmin,box.ymin,box.zmin);sizes=(box.xlen,box.ylen,box.zlen)
    for i,edge in enumerate(shape.Edges()):
        samples,_=edge.sample(40)
        if edge.IsClosed() and samples:samples.append(samples[0])
        center=list(edge.Center().toTuple())
        records.append(dict(index=i,length=edge.Length(),center=center,curve=edge.geomType(),points=[list(p.toTuple()) for p in samples],relative_center=[(v-a)/max(d,1e-9) for v,a,d in zip(center,low,sizes)],tangent=list(edge.tangentAt(.5).toTuple())))
    return records


def apply_edge_feature(shape,feature):
    if not shape.Solids():raise ValueError('3D 필렛·모따기는 솔리드에서 사용하세요.')
    edges=shape.Edges()
    if len(edges)!=feature.support_edge_count and not all(r.relative_center for r in feature.edges):raise ValueError('참조한 모서리 구성이 바뀌었습니다. 모서리를 다시 선택하세요.')
    selected=[]
    for ref in feature.edges:
        if ref.relative_center:
            from .topology import resolve_edge
            selected.append(resolve_edge(shape,ref)[1]);continue
        if ref.index>=len(edges):raise ValueError('선택한 모서리가 없습니다.')
        edge=edges[ref.index]
        if edge.geomType()!=ref.curve or abs(edge.Length()-ref.length)>1e-4 or math.dist(edge.Center().toTuple(),ref.center)>1e-4:
            raise ValueError('참조한 모서리 위치·치수가 바뀌었습니다. 모서리를 다시 선택하세요.')
        selected.append(edge)
    if len({r.index for r in feature.edges})!=len(selected):raise ValueError('같은 모서리를 중복 선택할 수 없습니다.')
    try:
        result=shape.fillet(feature.size,selected) if feature.kind=='fillet' else shape.chamfer(feature.size,None,selected)
    except Exception as exc:
        raise ValueError('이 반경으로 모서리를 처리할 수 없습니다. 크기를 줄이거나 모서리를 다시 선택하세요.') from exc
    return validate_shape(result,True)


def section_from_saved(design,saved):
    from .models import ModelSection,ModelFrame
    from .sketch_frames import context_frame
    origin,x,y=context_frame(saved.context,design);normal=np.cross(x,y)
    return ModelSection(sketch=saved.geometry.model_copy(deep=True),frame=ModelFrame(origin=origin.tolist(),normal=normal.tolist(),x_direction=x.tolist()),sketch_id=saved.id)


def resolved_geometry(design,part):
    """Follow saved sketch references, retaining the original inputs in history."""
    geometry=part.geometry.model_copy(deep=True)
    sections=[geometry.profile] if geometry.kind in ('sweep','revolve') else geometry.sections if geometry.kind=='loft' else []
    saved={s.id:s for s in design.sketches}
    for section in sections:
        if section.sketch_id:
            source=saved.get(section.sketch_id)
            if not source:raise ValueError('모델링에서 참조한 스케치가 삭제되었습니다.')
            if source.context.part_id==part.id:raise ValueError('자기 부품의 면 스케치를 기본 형상으로 참조할 수 없습니다.')
            # User placement stays editable; geometry follows the source sketch.
            section.sketch=source.geometry.model_copy(deep=True)
    if geometry.kind=='sweep' and geometry.path.sketch_id:
        source=saved.get(geometry.path.sketch_id)
        if not source:raise ValueError('스윕 경로 스케치가 삭제되었습니다.')
        if source.context.part_id==part.id:raise ValueError('스윕 경로에 순환 참조가 있습니다.')
        geometry.path.sketch=source.geometry.model_copy(deep=True)
    return geometry
