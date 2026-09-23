"""Only these audited constructors turn declarative dimensions into OCCT solids."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from threading import RLock

import cadquery as cq
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib

from .models import Design, Part
from .constraints import anchors, solve_sketch, solve_assembly
from .sketch_engine import extrude_regions, sketch_status, projected_face

KERNEL_LOCK = RLock()


def exact_bounds(shape):
    """Use analytic surfaces, never a tessellation's expanded bounding box."""
    bounds = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped, bounds, False, False)
    return cq.BoundBox(bounds)


def neck_profile(g, flat=False):
    length, gauge, transition = g.length, g.gauge_length, g.transition_length
    big = (g.grip_width if flat else g.grip_diameter) / 2
    small = (g.gauge_width if flat else g.gauge_diameter) / 2
    a, b = -gauge / 2 - transition, -gauge / 2
    c, d = gauge / 2, gauge / 2 + transition
    # Cubic Bezier shoulders have horizontal tangents at both ends.
    wp = cq.Workplane("XY").moveTo(-length/2, -big if flat else 0).lineTo(-length/2, big).lineTo(a, big)
    wp = wp.bezier([(a+transition/3, big), (b-transition/3, small), (b, small)], includeCurrent=True)
    wp = wp.lineTo(c, small).bezier([(c+transition/3, small), (d-transition/3, big), (d, big)], includeCurrent=True).lineTo(length/2, big)
    if flat:
        wp = wp.lineTo(length/2, -big).lineTo(d, -big)
        wp = wp.bezier([(d-transition/3, -big), (c+transition/3, -small), (c, -small)], includeCurrent=True)
        wp = wp.lineTo(b, -small).bezier([(b-transition/3, -small), (a+transition/3, -big), (a, -big)], includeCurrent=True)
        return wp.lineTo(-length/2, -big).close()
    return wp.lineTo(length/2, 0).close()


def construct(g):
    if g.kind=='sheetmetal':
        from .sheetmetal import construct_sheet
        return construct_sheet(g)
    if g.kind=='revolve':
        from .solid_tools import revolve
        return revolve(g)
    if g.kind in ('sweep','loft'):
        from .advanced_geometry import construct_sweep,construct_loft
        return construct_sweep(g) if g.kind=='sweep' else construct_loft(g)
    if g.kind == "round_specimen":
        obj = neck_profile(g).revolve(360, (0, 0), (1, 0))
    elif g.kind == "flat_specimen":
        obj = neck_profile(g, flat=True).extrude(g.thickness).translate((0, 0, -g.thickness/2))
    elif g.kind == "wafer":
        obj = cq.Workplane("XY").circle(g.diameter/2).extrude(g.thickness)
        if g.flat_depth:
            cutter = cq.Workplane("XY").box(g.diameter, g.diameter*2, g.thickness+2, centered=(False, True, False)).translate((g.diameter/2-g.flat_depth, 0, -1))
            obj = obj.cut(cutter)
    elif g.kind == "link":
        r, c = g.width/2, (g.length-g.width)/2
        obj = (cq.Workplane("XY").moveTo(-c, -r).lineTo(c, -r)
               .threePointArc((c+r, 0), (c, r)).lineTo(-c, r)
               .threePointArc((-c-r, 0), (-c, -r)).close().extrude(g.thickness))
        holes = cq.Workplane("XY").pushPoints([(-g.hole_spacing/2, 0), (g.hole_spacing/2, 0)]).circle(g.hole_diameter/2).extrude(g.thickness)
        obj = obj.cut(holes)
    elif g.kind == "plate":
        obj = cq.Workplane("XY").box(g.length, g.width, g.thickness, centered=(True, True, False))
        if g.hole_count:
            ys = [-g.hole_pitch_y/2, g.hole_pitch_y/2] if g.hole_count == 4 else [0]
            points = [(x, y) for x in (-g.hole_pitch_x/2, g.hole_pitch_x/2) for y in ys]
            holes = cq.Workplane("XY").pushPoints(points).circle(g.hole_diameter/2).extrude(g.thickness)
            obj = obj.cut(holes)
    elif g.kind == "bracket":
        base = cq.Workplane("XY").box(g.length, g.width, g.thickness, centered=(False, True, False))
        upright = cq.Workplane("XY").box(g.thickness, g.width, g.height, centered=(False, True, False))
        obj = base.union(upright)
        for y in (-g.width/4, g.width/4):
            vertical = cq.Solid.makeCylinder(g.hole_diameter/2, g.thickness+2, cq.Vector(g.length-g.hole_inset, y, -1), cq.Vector(0, 0, 1))
            horizontal = cq.Solid.makeCylinder(g.hole_diameter/2, g.thickness+2, cq.Vector(-1, y, g.height-g.hole_inset), cq.Vector(1, 0, 0))
            obj = obj.cut(vertical).cut(horizontal)
    elif g.kind == "extrusion":
        if g.sketch_mode == 'entities' or g.symmetric or g.reverse_depth or g.taper or g.thin_wall:
            shape = extrude_regions(g)
            if not shape.isValid() or not shape.Solids() or shape.Volume() <= 0:
                raise ValueError('스케치에서 유효한 솔리드를 만들지 못했습니다.')
            return shape
        obj = cq.Workplane("XY").polyline([(p.x, p.y) for p in g.points]).close().extrude(g.thickness*g.direction)
        for hole in g.holes:
            cutter = cq.Solid.makeCylinder(hole.diameter/2, g.thickness, cq.Vector(hole.x, hole.y, 0),cq.Vector(0,0,g.direction))
            obj = obj.cut(cutter)
    elif g.kind == "cylinder":
        obj = cq.Workplane("XY").circle(g.diameter/2)
        if g.bore_diameter:
            obj = obj.circle(g.bore_diameter/2)
        obj = obj.extrude(g.height)
    else:
        raise ValueError("지원하지 않는 형상입니다.")
    shape = obj.val()
    if not shape.isValid() or len(shape.Solids()) != 1 or shape.Volume() <= 0:
        raise ValueError("CAD 커널에서 유효한 단일 솔리드를 만들지 못했습니다. 치수를 확인하세요.")
    return shape


def face_frame(face):
    if face.geomType() != "PLANE":
        raise ValueError("면 스케치는 평평한 면에서만 시작할 수 있습니다.")
    normal=face.normalAt().normalized();origin=face.Center()
    reference=cq.Vector(1,0,0) if abs(normal.x)<.95 else cq.Vector(0,1,0)
    u=(reference-normal.multiply(reference.dot(normal))).normalized()
    return cq.Plane(origin=origin, xDir=u, normal=normal)


@lru_cache(maxsize=32)
def _part_cached(part_json,asset=None,tools=()):
    part=Part.model_validate_json(part_json)
    if part.geometry.kind=='imported':
        from .imported import decode_shape
        if not asset:raise ValueError('가져온 부품 데이터가 없습니다.')
        shape=decode_shape(*asset)
    else:shape=construct(part.geometry)
    tools=dict(tools)
    previous_feature="base"
    for feature in part.features:
        if feature.suppressed:previous_feature=feature.id;continue
        if feature.support_feature and feature.support_feature!=previous_feature:
            raise ValueError("면 스케치가 참조한 이전 피처가 변경되었습니다. 기준 면을 다시 선택하세요.")
        if getattr(feature,'kind',None) in ('fillet','chamfer'):
            from .advanced_geometry import apply_edge_feature
            shape=apply_edge_feature(shape,feature);previous_feature=feature.id;continue
        if getattr(feature,'kind',None)=='thread':
            from .threads import apply_thread
            shape=apply_thread(shape,feature);previous_feature=feature.id;continue
        if getattr(feature,'kind',None)=='solid':
            from .solid_tools import apply_operation
            from .imported import decode_shape
            tool=decode_shape(*tools[feature.id]) if feature.id in tools else None
            shape=apply_operation(shape,feature,tool);previous_feature=feature.id;continue
        if not shape.Solids():raise ValueError('곡면에는 솔리드 절삭·돌출을 적용할 수 없습니다.')
        faces=shape.Faces()
        if feature.reference:
            from .topology import resolve_face
            _,face=resolve_face(shape,feature.reference)
        elif feature.face >= len(faces) or (feature.support_face_count and len(faces)!=feature.support_face_count):
            raise ValueError("면 스케치의 기준 면 구성이 변경되었습니다. 피처를 제거하고 면을 다시 선택하세요.")
        else:face=faces[feature.face]
        plane=face_frame(face)
        if (plane.zDir-cq.Vector(*feature.normal)).Length > 1e-5:
            raise ValueError("면 스케치의 기준 방향이 변경되었습니다. 면을 다시 선택하세요.")
        g=feature.sketch
        if feature.end_face:
            from .topology import resolve_face
            target=resolve_face(shape,feature.end_face)[1]
            if target.geomType()!='PLANE' or abs(abs(target.normalAt().dot(plane.zDir))-1)>1e-6:raise ValueError('면까지 돌출은 기준 스케치와 평행한 평면을 선택하세요.')
            depth=(target.Center()-plane.origin).dot(plane.zDir)*(1 if feature.operation=='add' else -1)
            if depth<.01:raise ValueError('목표 면이 돌출 방향 앞에 없습니다. 방향이나 목표 면을 바꾸세요.')
            g=g.model_copy(update={'thickness':depth,'symmetric':False,'reverse_depth':0})
        if feature.through_all:
            if feature.operation!='cut':raise ValueError('전체 관통은 절삭에서만 사용할 수 있습니다.')
            bounds=exact_bounds(shape)
            depth=max(-(cq.Vector(x,y,z)-plane.origin).dot(plane.zDir) for x in (bounds.xmin,bounds.xmax) for y in (bounds.ymin,bounds.ymax) for z in (bounds.zmin,bounds.zmax))+.1
            g=g.model_copy(update={'thickness':max(.01,depth),'symmetric':False,'reverse_depth':0})
        if g.sketch_mode == 'entities' or g.symmetric or g.reverse_depth or g.taper or g.thin_wall:
            tool = extrude_regions(g,plane,1 if feature.operation=='add' else -1)
        else:
            profile=cq.Workplane(plane).polyline([(p.x,p.y) for p in g.points]).close()
            for hole in g.holes:
                profile=profile.moveTo(hole.x,hole.y).circle(hole.diameter/2)
            tool=profile.extrude(g.thickness if feature.operation=="add" else -g.thickness).val()
        if feature.hole_finish!='plain':
            from .holes import finish_tool
            tool=tool.fuse(finish_tool(feature,g,plane)).clean()
        previous=shape.Volume()
        previous_solids=len(shape.Solids())
        shape=shape.fuse(tool).clean() if feature.operation=="add" else shape.cut(tool).clean()
        difference=shape.Volume()-previous
        if not shape.isValid() or not shape.Solids() or len(shape.Solids())>previous_solids or shape.Volume()<=0:
            raise ValueError("면 스케치 피처가 분리되거나 유효하지 않은 솔리드를 만듭니다. 위치와 깊이를 확인하세요.")
        if (feature.operation=="add" and difference<=1e-7) or (feature.operation=="cut" and difference>=-1e-7):
            raise ValueError("면 스케치가 부품에 닿지 않거나 유효한 부피 변화를 만들지 않습니다.")
        previous_feature=feature.id
    return shape


def local_shape(design,part,_stack=()):
    if part.id in _stack:raise ValueError('부품 참조가 순환합니다.')
    if part.source_part_id:
        source=next(p for p in design.parts if p.id==part.source_part_id)
        return local_shape(design,source,(*_stack,part.id))
    if part.geometry.kind in ('sweep','loft','revolve'):
        from .advanced_geometry import resolved_geometry
        part=part.model_copy(update={'geometry':resolved_geometry(design,part)})
    asset=None
    if part.geometry.kind=='imported':
        source=design.assets.get(part.geometry.asset_id)
        if source is None:raise ValueError('가져온 부품의 원본 데이터를 찾을 수 없습니다.')
        asset=(source.data,source.sha256)
    tools=[]
    for f in part.features:
        if getattr(f,'kind',None)!='solid' or f.operation!='boolean' or f.suppressed:continue
        other=next((p for p in design.parts if p.id==f.tool_part_id),None)
        if other is None:raise ValueError('불리언 작업의 도구 부품이 삭제됐습니다.')
        tool=local_shape(design,other,(*_stack,part.id));t=other.transform
        for angle,axis in [(t.rx,(1,0,0)),(t.ry,(0,1,0)),(t.rz,(0,0,1))]:
            if angle:tool=tool.rotate((0,0,0),axis,angle)
        t2=part.transform;tool=tool.translate((t.x-t2.x,t.y-t2.y,t.z-t2.z))
        for angle,axis in [(t2.rz,(0,0,1)),(t2.ry,(0,1,0)),(t2.rx,(1,0,0))]:
            if angle:tool=tool.rotate((0,0,0),axis,-angle)
        from .imported import encode_shape
        encoded=encode_shape(tool,'tool');tools.append((f.id,(encoded.data,encoded.sha256)))
    return _part_cached(part.model_dump_json(),asset,tuple(tools))


@lru_cache(maxsize=8)
def _build_cached(canonical_json):
    design = Design.model_validate_json(canonical_json)
    shapes = []
    for p in design.parts:
        s = local_shape(design,p)
        t = p.transform
        for angle, axis in [(t.rx, (1, 0, 0)), (t.ry, (0, 1, 0)), (t.rz, (0, 0, 1))]:
            if angle:
                s = s.rotate((0, 0, 0), axis, angle)
        shapes.append(s.translate((t.x, t.y, t.z)))
    return shapes


def build(design: Design):
    with KERNEL_LOCK:
        # Re-evaluate the selected local face before propagating a joint. This
        # makes a parent dimension edit move attached parts with the actual face.
        parts={p.id:p for p in design.parts};mates={m.id:m for m in design.mates}
        for binding in design.joint_frames:
            mate=mates[binding.mate_id]
            for identifier,frame in ((mate.parent,binding.parent),(mate.child,binding.child)):
                part=parts[identifier];shape=local_shape(design,part);faces=shape.Faces();support=part.features[-1].id if part.features else 'base'
                if frame.reference:
                    from .topology import resolve_face
                    index,face=resolve_face(shape,frame.reference);plane=face_frame(face)
                else:
                    if len(faces)!=frame.face_count or frame.face>=len(faces) or support!=frame.support_feature:raise ValueError('면 조인트가 참조한 피처/면 구성이 변경되었습니다. 기준 면을 다시 선택하세요.')
                    plane=face_frame(faces[frame.face])
                if (plane.zDir-cq.Vector(*frame.normal)).Length>1e-5:
                    raise ValueError('면 조인트의 기준 방향이 변경되었습니다. 기준 면을 다시 선택하세요.')
                frame.origin=list(plane.origin.toTuple());frame.x_direction=list(plane.xDir.toTuple())
        solve_assembly(design)
        return _build_cached(design.model_dump_json())


def preview(design: Design):
    with KERNEL_LOCK:
        shapes = build(design)
        meshes = []
        for part, shape in zip(design.parts, shapes):
            vertices,triangles,triangle_faces,face_info=[],[],[],[]
            local=local_shape(design,part)
            local_faces=local.Faces()
            local_bounds=exact_bounds(local)
            for i,face in enumerate(shape.Faces()):
                vs,ts=face.tessellate(.04,.12)
                start=len(vertices);vertices.extend(vs)
                triangles.extend(tuple(idx+start for idx in tri) for tri in ts);triangle_faces.extend([i]*len(ts))
                lf=local_faces[i]
                info={"index":i,"planar":lf.geomType()=="PLANE"}
                from .topology import face_reference
                info['reference']=face_reference(local,i,local_bounds,local_faces).model_dump()
                if lf.geomType()=='CYLINDER':
                    from .threads import cylinder_reference
                    try:info['cylinder']=cylinder_reference(lf,i,len(local_faces)).model_dump()
                    except ValueError:pass
                if info["planar"]:
                    plane=face_frame(lf)
                    wires=[]
                    for edge in lf.Edges():
                        samples,_=edge.sample(20)
                        if edge.IsClosed() and samples:samples.append(samples[0])
                        wires.append([[round(plane.toLocalCoords(p).x,6),round(plane.toLocalCoords(p).y,6)] for p in samples])
                    info.update({"normal":[round(x,8) for x in plane.zDir.toTuple()],"origin":list(plane.origin.toTuple()),"x_direction":list(plane.xDir.toTuple()),"outline":wires,"face_count":len(local_faces)})
                    projected,unsupported=projected_face(lf,plane)
                    info.update(projected_entities=projected,projection_unsupported=unsupported)
                face_info.append(info)
            bb = exact_bounds(shape)
            sketch_info=sketch_status(part.geometry) if part.geometry.kind=="extrusion" else None
            from .advanced_geometry import edge_records
            pick_edges=edge_records(shape)
            meshes.append({
                "id": part.id, "name": part.name, "color": part.color,
                "vertices": [round(c, 7) for v in vertices for c in v.toTuple()],
                "triangles": [i for t in triangles for i in t],
                "pick_edges":pick_edges,"pick_vertices":[list(v.Center().toTuple()) for v in shape.Vertices()],
                "triangle_faces":triangle_faces,"faces":face_info,"anchors":anchors(part.geometry),"sketch_constraints":sketch_info,
                "volume": shape.Volume() if shape.Solids() else 0, "area": shape.Area(), "valid": shape.isValid(),
                "solid":bool(shape.Solids()),
                "bounds": [bb.xlen, bb.ylen, bb.zlen],
            })
        from .native.saved_sketches import preview_sketches
        saved_sketches = preview_sketches(design)
        points = [p for sketch in saved_sketches for row in sketch['lines'] for p in row]
        if shapes:
            compound = cq.Compound.makeCompound(shapes)
            bb = exact_bounds(compound)
            points.extend([[bb.xmin,bb.ymin,bb.zmin],[bb.xmax,bb.ymax,bb.zmax]])
        if not points: points = [[-25,-25,0],[25,25,0]]
        minimum = [min(p[i] for p in points) for i in range(3)]
        maximum = [max(p[i] for p in points) for i in range(3)]
        collisions = [];collision_bounds=[exact_bounds(s) for s in shapes]
        for i, a in enumerate(shapes):
            ba = collision_bounds[i]
            for j in range(i+1, len(shapes)):
                b = shapes[j]
                bc = collision_bounds[j]
                overlap = all(min(getattr(ba, axis+"max"), getattr(bc, axis+"max")) - max(getattr(ba, axis+"min"), getattr(bc, axis+"min")) > 1e-5 for axis in "xyz")
                if overlap and a.Solids() and b.Solids():
                    volume = a.intersect(b).Volume()
                    if volume > 1e-5:
                        collisions.append({"a": design.parts[i].id, "b": design.parts[j].id, "volume": volume})
        return {"meshes": meshes, "sketches": saved_sketches, "stats": {
            "valid": all(m["valid"] for m in meshes), "parts": len(shapes),
            "volume": sum(m["volume"] for m in meshes),
            "bounds": [b-a for a,b in zip(minimum,maximum)],
            "min": minimum, "max": maximum,
            "triangles": sum(len(m["triangles"])//3 for m in meshes), "collisions": collisions,"assembly_constraints":solve_assembly(design),
        }}


def export(design: Design, destination: Path, fmt: str):
    if fmt not in {"step", "stl"}:
        raise ValueError("STEP 또는 STL만 내보낼 수 있습니다.")
    with KERNEL_LOCK:
        shapes = build(design)
        if not shapes:
            raise ValueError("입체 형상이 없습니다. 스케치는 CAD 프로젝트로 저장하고 닫힌 영역을 돌출한 뒤 STEP/STL로 내보내세요.")
        if fmt == "step":
            assembly = cq.Assembly(name="PromptCAD")
            for part, shape in zip(design.parts, shapes):
                rgb = [int(part.color[i:i+2], 16)/255 for i in (1, 3, 5)]
                assembly.add(shape, name=part.id, color=cq.Color(*rgb))
            assembly.export(str(destination), "STEP")
        else:
            cq.exporters.export(cq.Compound.makeCompound(shapes), str(destination), exportType="STL", tolerance=0.025, angularTolerance=0.1)
