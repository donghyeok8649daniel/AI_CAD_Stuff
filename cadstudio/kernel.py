"""Only these audited constructors turn declarative dimensions into OCCT solids."""
from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from threading import RLock
from weakref import WeakValueDictionary

import cadquery as cq
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib

from .models import Design, Part
from .constraints import anchors, solve_sketch, solve_assembly
from .sketch_engine import extrude_regions, sketch_status, projected_face

KERNEL_LOCK = RLock()
from .preview_cache import MeshCache
from . import preview_quality
_preview_mesh_cache = MeshCache()
_part_mesh_cache = MeshCache(max_bytes=64*1024**2,max_entries=512,max_raw_bytes=16*1024**2)
_local_shape_session = ContextVar('local_shape_session', default=None)
_live_local_shapes = WeakValueDictionary()


def set_preview_quality(value):
    with KERNEL_LOCK:preview_quality.set_mode(value)


def _mesh_key(design):
    return sha256((preview_quality.mode()+'\0'+design.model_dump_json()).encode('utf-8')).digest()


@contextmanager
def local_shape_session():
    """Reuse up to 256 local BReps for one operation, releasing them on exit.

    Previews revisit local faces after their world build, and joint surveys
    can visit hundreds of poses beyond the persistent 32-shape cache. Keep
    unchanged geometry only for this operation. Relative boolean tools remain
    part of the key at every pose.
    """
    if _local_shape_session.get() is not None:
        yield
        return
    cache = {}
    token = _local_shape_session.set(cache)
    try:
        yield
    finally:
        cache.clear()
        _local_shape_session.reset(token)


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
    if g.kind=='spur_gear':
        from .gears import construct_gear
        return construct_gear(g)
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


def face_frame(face, origin_mode='face_center'):
    if face.geomType() != "PLANE":
        raise ValueError("면 스케치는 평평한 면에서만 시작할 수 있습니다.")
    normal=face.normalAt().normalized();origin=face.Center()
    if origin_mode=='face_bounds':
        b=exact_bounds(face);center=cq.Vector((b.xmin+b.xmax)/2,(b.ymin+b.ymax)/2,(b.zmin+b.zmax)/2)
        origin=center-normal.multiply((center-origin).dot(normal))
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
        plane=face_frame(face,feature.origin_mode)
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
    # Local BRep construction does not depend on the part's world pose. A
    # moving joint used to rebuild expensive gear teeth at every sample because
    # transform was included in this cache key. Boolean feature tools above
    # still include their relative placement in `tools`, so moving one against
    # the other invalidates the local result as it should.
    local_part=part.model_copy(update={'transform':type(part.transform)(),
                                      'id':'geometry','source_part_id':'','fixed':False,
                                      'material':None,'product':None,
                                      'name':'Geometry','color':'#AEB6BF','role':'unspecified',
                                      'mechanical_function':'unspecified'})
    key = (local_part.model_dump_json(), asset, tuple(tools))
    cache = _local_shape_session.get()
    if cache is not None and key in cache:
        return cache[key]
    # Hash checked construction inputs, not native pointers or bounding boxes.
    # The asset/tool hashes identify data already decoded/built above. Labels
    # and world pose are handled separately by the display payload cache.
    # A project-supplied SHA is not sufficient: changed bytes claiming an old
    # SHA must miss this cache and reach decode_shape's integrity validation.
    asset_key=(sha256(asset[0].encode('utf-8')).digest(),asset[1]) if asset else None
    input_key=sha256(repr((key[0],asset_key,
        tuple((identifier,value[1]) for identifier,value in tools))).encode('utf-8')).digest()
    shape=_live_local_shapes.get(input_key)
    if shape is None:
        shape=_part_cached(*key)
        shape._cadstudio_mesh_input_key=input_key
        _live_local_shapes[input_key]=shape
    if cache is not None and len(cache) < 256:
        cache[key] = shape
    return shape


@lru_cache(maxsize=2)
def _build_cached(canonical_json):
    design = Design.model_validate_json(canonical_json)
    shapes = []
    for p in design.parts:
        local = s = local_shape(design,p)
        t = p.transform
        for angle, axis in [(t.rx, (1, 0, 0)), (t.ry, (0, 1, 0)), (t.rz, (0, 0, 1))]:
            if angle:
                s = s.rotate((0, 0, 0), axis, angle)
        world=s.translate((t.x, t.y, t.z))
        # The two bounded build-cache entries own their source geometry. The
        # weak index itself owns nothing, so previous documents cannot create
        # an unbounded native-shape cache. A small edit reuses the other parts.
        world._cadstudio_local_shape=local
        world._cadstudio_world_pose_key=p.transform.model_dump_json()
        world._cadstudio_world_stamp=world.wrapped.Located(world.wrapped.Location())
        shapes.append(world)
    return shapes


def _resolve_assembly_pose(design):
    with KERNEL_LOCK:
        # Re-evaluate the selected local face before propagating a joint. This
        # makes a parent dimension edit move attached parts with the actual face.
        parts={p.id:p for p in design.parts};mates={m.id:m for m in design.mates}
        for binding in design.joint_frames:
            mate=mates[binding.mate_id]
            for identifier,frame in ((mate.parent,binding.parent),(mate.child,binding.child)):
                part=parts[identifier];shape=local_shape(design,part);faces=shape.Faces();support=part.features[-1].id if part.features else 'base'
                if frame.cylinder:
                    from .joint_alignment import resolve_cylinder
                    index,face=resolve_cylinder(shape,frame.cylinder)
                elif frame.reference:
                    from .topology import resolve_face
                    index,face=resolve_face(shape,frame.reference)
                else:
                    if len(faces)!=frame.face_count or frame.face>=len(faces) or support!=frame.support_feature:raise ValueError('면 조인트가 참조한 피처/면 구성이 변경되었습니다. 기준 면을 다시 선택하세요.')
                    index=frame.face;face=faces[index]
                from .joint_alignment import joint_face_plane
                plane=joint_face_plane(face,index,len(faces))
                if (plane.zDir-cq.Vector(*frame.normal)).Length>1e-5:
                    raise ValueError('면 조인트의 기준 방향이 변경되었습니다. 기준 면을 다시 선택하세요.')
                frame.origin=list(plane.origin.toTuple());frame.x_direction=list(plane.xDir.toTuple())
        solve_assembly(design)



def build(design: Design):
    with KERNEL_LOCK:
        _resolve_assembly_pose(design)
        return _build_cached(design.model_dump_json())


def _rigid_pose_shapes(base, base_shapes, current):
    """Reuse static world BReps only inside a checked identical local family."""
    with KERNEL_LOCK:
        if len(base_shapes)!=len(base.parts) or [p.id for p in base.parts]!=[p.id for p in current.parts]:
            raise ValueError('강체 재생의 부품 목록이 바뀌었습니다.')
        family=('assets','sketches','parameters','dimension_bindings','configurations')
        def unchanged_family():
            return (all(getattr(base,k)==getattr(current,k) for k in family)
                    and all(a.geometry==p.geometry and a.features==p.features and a.source_part_id==p.source_part_id
                            for a,p in zip(base.parts,current.parts)))
        if not unchanged_family():raise ValueError('강체 재생의 지역 형상 입력이 바뀌었습니다.')
        if any(getattr(f,'tool_part_id',None) and not f.suppressed for p in current.parts for f in p.features):
            raise ValueError('몸체 연산이 연결된 형상은 강체 재생에서 지원하지 않습니다.')
        _resolve_assembly_pose(current)
        if not unchanged_family():raise ValueError('구속 계산 중 지역 형상이 바뀌었습니다.')
        shapes=[]
        for old,part,original in zip(base.parts,current.parts,base_shapes):
            if part.transform==old.transform:shapes.append(original);continue
            shape=local_shape(current,part);t=part.transform
            for angle,axis in ((t.rx,(1,0,0)),(t.ry,(0,1,0)),(t.rz,(0,0,1))):
                if angle:shape=shape.rotate((0,0,0),axis,angle)
            shapes.append(shape.translate((t.x,t.y,t.z)))
        return shapes


def preview(design: Design,*,progress=None,previous=None):
    with KERNEL_LOCK, local_shape_session():
        if progress:progress(f'조립 형상 생성 · {len(design.parts)}개 부품')
        shapes = build(design)
        previous_meshes={}
        if previous is not None:
            baseline,old_result=previous
            from .preview_metadata import geometry_key
            if baseline is not None and old_result is not None and old_result.get('_geometry_key')==geometry_key(baseline):
                previous_meshes={mesh['id']:mesh for mesh in old_result.get('meshes',[])}
        # build still resolves current face references and assembly constraints.
        # Only display payload is reused; interference/readiness below stay live.
        mesh_key = _mesh_key(design)
        meshes = None if previous_meshes else _preview_mesh_cache.get(mesh_key)
        if meshes is None:
            meshes = _preview_meshes(design, shapes,progress=progress,previous_meshes=previous_meshes)
            if not previous_meshes:_preview_mesh_cache.put(mesh_key, meshes)
        return _preview_result(design, shapes, meshes,progress=progress)


def _preview_meshes(design, shapes, check=lambda:None,progress=None,previous_meshes=None):
        quality=preview_quality.mode()
        plan=[]
        for part,shape in zip(design.parts,shapes):
            check();local=local_shape(design,part)
            input_key=getattr(local,'_cadstudio_mesh_input_key',None)
            tolerance,angular=preview_quality.tolerances(quality,len(design.parts),part.geometry.kind)
            part_key=(input_key,part.transform.model_dump_json(),tolerance,angular) if input_key is not None else None
            plan.append((part,shape,local,part_key,tolerance,angular))
        _part_mesh_cache.retain({row[3] for row in plan if row[3] is not None})
        meshes = []
        for part,shape,local,part_key,tolerance,angular in plan:
            check()
            if progress:progress(f'화면용 메시 · {len(meshes)+1}/{len(plan)} · {part.name}')
            vertices,triangles,triangle_faces,face_info=[],[],[],[]
            token=sha256(repr(part_key).encode('utf-8')).hexdigest() if part_key is not None else None
            prior=(previous_meshes or {}).get(part.id)
            # Native transactions opt into sharing immutable bulk arrays with
            # their still-visible previous preview, avoiding a second assembly.
            cached=dict(prior) if token is not None and prior is not None and prior.get('_display_input_key')==token else None
            if cached is None:cached=_part_mesh_cache.get(part_key) if part_key is not None else None
            if cached is not None:
                # Cached trees are independent. Explicit previous-preview
                # sharing owns a new metadata shell around read-only arrays.
                cached.update(id=part.id,name=part.name,color=part.color,
                    anchors=anchors(part.geometry),
                    sketch_constraints=sketch_status(part.geometry) if part.geometry.kind=='extrusion' else None)
                meshes.append(cached);continue
            previous=getattr(shape,'_cadstudio_tessellation_settings',None)
            if previous is not None and previous!=(tolerance,angular):
                from OCP.BRepTools import BRepTools
                # Remove only old display triangulation when switching modes.
                # Topology, analytic surfaces and face order stay unchanged.
                BRepTools.Clean_s(shape.wrapped)
            shape._cadstudio_tessellation_settings=(tolerance,angular)
            local_faces=local.Faces()
            local_bounds=exact_bounds(local)
            for i,face in enumerate(shape.Faces()):
                check()
                vs,ts=face.tessellate(tolerance,angular)
                # Keep the final flat payload directly. Holding every native
                # Vector and per-triangle tuple until the whole part finishes
                # used several extra copies on imported, finely faceted parts.
                start=len(vertices)//3
                vertices.extend(round(c,7) for v in vs for c in v.toTuple())
                triangles.extend(idx+start for tri in ts for idx in tri);triangle_faces.extend([i]*len(ts))
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
                "_display_input_key":token,
                "id": part.id, "name": part.name, "color": part.color,
                "vertices": vertices,
                "triangles": triangles,
                "pick_edges":pick_edges,"pick_vertices":[list(v.Center().toTuple()) for v in shape.Vertices()],
                "triangle_faces":triangle_faces,"faces":face_info,"anchors":anchors(part.geometry),"sketch_constraints":sketch_info,
                "volume": shape.Volume() if shape.Solids() else 0, "area": shape.Area(), "valid": shape.isValid(),
                "solid":bool(shape.Solids()),
                "bounds": [bb.xlen, bb.ylen, bb.zlen],
            })
            if part_key is not None:
                # Do not let an over-budget sequential scan evict the very
                # same live parts just before their turn (LRU scan thrashing).
                check();_part_mesh_cache.put(part_key,meshes[-1],evict=False)
        return meshes


def _preview_result(design, shapes, meshes, *, checked_collisions=None, check=lambda:None,progress=None):
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
        from .interference import exact_collisions
        from .collision_policy import collision_exclusion_stats
        check()
        if checked_collisions is None and progress:
            total=len(shapes)*(len(shapes)-1)//2;count=0
            progress(f'간섭 검사 · 0/{total}쌍')
            def completed():
                nonlocal count
                count+=1
                if count%1024==0 or count==total:progress(f'간섭 검사 · {count}/{total}쌍')
            collisions=exact_collisions(design,shapes,check=check,completed=completed)
        else:collisions = exact_collisions(design, shapes, check=check) if checked_collisions is None else checked_collisions
        check()
        from .joint_readiness import joint_readiness
        from .preview_metadata import geometry_key
        if progress:progress('조립 구속 · 관절 지지 형상 확인 중')
        return {"_geometry_key":geometry_key(design),"_display_quality":preview_quality.mode(),"meshes": meshes, "sketches": saved_sketches, "stats": {
            "valid": all(m["valid"] for m in meshes), "parts": len(shapes),
            "volume": sum(m["volume"] for m in meshes),
            "bounds": [b-a for a,b in zip(minimum,maximum)],
            "min": minimum, "max": maximum,
            "triangles": sum(len(m["triangles"])//3 for m in meshes), "collisions": collisions,"assembly_constraints":solve_assembly(design),
            **collision_exclusion_stats(design),
            "joint_readiness":joint_readiness(design,shapes,collisions),
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
            from .mesh_export import export_stl
            export_stl(shapes,destination)


def _preview_same_checked_pose(design, shapes, checked_raw, collisions, check):
    if design.model_dump()!=checked_raw:raise ValueError('이미 검사한 미리보기 자세가 바뀌었습니다.')
    check()
    mesh_key=_mesh_key(design)
    meshes=_preview_mesh_cache.get(mesh_key)
    if meshes is None:
        meshes=_preview_meshes(design,shapes,check=check)
        check();_preview_mesh_cache.put(mesh_key,meshes)
    check()
    result=_preview_result(design,shapes,meshes,checked_collisions=collisions,check=check)
    if design.model_dump()!=checked_raw:raise ValueError('미리보기 구속 재계산이 이미 검사한 자세를 바꿨습니다.')
    check();return result
