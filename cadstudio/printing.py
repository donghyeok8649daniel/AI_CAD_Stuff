"""Non-destructive build-plate preparation; STL output uses the preview solids."""
import os
from copy import deepcopy
import hashlib
import json
import math
import re
import time
import numpy as np
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED
import cadquery as cq
from .models import Design, Part
from .kernel import KERNEL_LOCK, build, exact_bounds, preview
from .imported import encode_shape
from .mechanical_functions import mechanical_function
from .preview_metadata import geometry_key


def prepare_print(raw, identifiers, *, rotation=(0,0,0), bed=(220,220,250), gap=5, placements=None):
    import math
    if len(bed)!=3 or any(not math.isfinite(x) or x<=0 for x in bed):raise ValueError('출력 크기는 양수 mm이어야 합니다.')
    if len(rotation)!=3 or any(not math.isfinite(x) for x in rotation) or not math.isfinite(gap) or gap<0:raise ValueError('출력 방향과 간격을 확인하세요.')
    design=Design.model_validate(deepcopy(raw)).model_copy(deep=True);ids=set(identifiers)
    if not ids or not ids<={p.id for p in design.parts}:raise ValueError('출력할 부품을 선택하세요.')
    placements=placements or {}
    if set(placements)-{p.id for p in design.parts}:raise ValueError('없는 부품의 출력 배치입니다.')
    for pose in placements.values():
        if set(pose)-{'x','y','rx','ry','rz'} or any(not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>10000 for v in pose.values()):raise ValueError('출력 배치는 유한한 위치·각도여야 합니다.')
    with KERNEL_LOCK:
        shapes=build(design);parts=[];assets={};x=y=row_height=0.;warnings=[];poses={}
        for part,shape in zip(design.parts,shapes):
            if part.id not in ids:continue
            if not shape.isValid() or not shape.Solids() or shape.Volume()<=0:raise ValueError('닫힌 솔리드만 출력할 수 있습니다: '+part.name)
            # Undo assembly placement, then apply output-only orientation.
            t=part.transform;shape=shape.translate((-t.x,-t.y,-t.z))
            for angle,axis in [(t.rz,(0,0,1)),(t.ry,(0,1,0)),(t.rx,(1,0,0))]:
                if angle:shape=shape.rotate((0,0,0),axis,-angle)
            pose=placements.get(part.id,{})
            angles=[pose.get(k,v) for k,v in zip(('rx','ry','rz'),rotation)]
            for angle,axis in zip(angles,[(1,0,0),(0,1,0),(0,0,1)]):
                if angle:shape=shape.rotate((0,0,0),axis,angle)
            b=exact_bounds(shape);width=b.xmax-b.xmin;length=b.ymax-b.ymin;height=b.zmax-b.zmin
            if x and x+width>bed[0]+1e-6:x=0;y+=row_height+gap;row_height=0
            cx=pose.get('x',x+width/2-bed[0]/2);cy=pose.get('y',y+length/2-bed[1]/2)
            if abs(cx)+width/2>bed[0]/2+1e-6 or abs(cy)+length/2>bed[1]/2+1e-6 or height>bed[2]+1e-6:
                warnings.append(part.name+' · 출력 영역을 벗어납니다.')
            placed=shape.translate((cx-(b.xmin+b.xmax)/2,cy-(b.ymin+b.ymax)/2,-b.zmin))
            poses[part.id]=dict(x=cx,y=cy,**dict(zip(('rx','ry','rz'),angles)))
            key='print-'+part.id;assets[key]=encode_shape(placed,part.name)
            parts.append(Part(id=part.id,name=part.name,color=part.color,geometry=dict(kind='imported',asset_id=key)))
            x+=width+gap;row_height=max(row_height,length)
        prepared=Design(name=design.name+' · 3D 프린팅',parts=parts,assets=assets)
        result=preview(prepared)
        result['print_placements']=poses
        if result['stats']['collisions']:warnings.append('출력 부품 사이에 간섭이 있습니다. 간격을 늘리세요.')
        return prepared,result,warnings


def export_print_stl(prepared, destination, *, tolerance=.025, cancelled=None):
    if tolerance not in (.1,.05,.025,.01):raise ValueError('STL 정밀도를 선택하세요.')
    target=Path(destination)
    if target.suffix.lower()!='.stl':raise ValueError('STL 파일 이름을 선택하세요.')
    temporary=target.with_name(target.name+'.'+uuid4().hex+'.tmp')
    try:
        _check_cancel(cancelled)
        with KERNEL_LOCK:
            shapes=build(prepared)
            if not shapes or any(not s.isValid() or not s.Solids() for s in shapes):raise ValueError('유효한 출력 솔리드가 필요합니다.')
            cq.exporters.export(cq.Compound.makeCompound(shapes),str(temporary),exportType='STL',tolerance=tolerance,angularTolerance=.1)
        _check_cancel(cancelled)
        os.replace(temporary,target)
    finally:temporary.unlink(missing_ok=True)
    return target

class PrintCancelled(RuntimeError):
    """A preview/export was cancelled before committing any output file."""


def _check_cancel(cancelled):
    if cancelled is not None and cancelled():
        raise PrintCancelled('3D 출력 작업이 취소되었습니다.')


def print_part_classification(part):
    """Explicit subtype first, or reversible, visibly unverified name hint.

    The broad 'fastener' purpose also covers retaining pins. On its own it
    remains unknown here. An explicit ProductSpec fastener_type identifies
    bolt/nut/retaining_pin/washer/other; conflicting declarations stay unknown.
    A standards head/hole dimension reference is not a bolt product identity.
    Name hints are only print-selection conveniences, never readiness claims.
    """
    function = mechanical_function(part)
    data = part if isinstance(part, dict) else part.model_dump()
    product = data.get('product') or {}
    kinds = set()
    values = {'bolt': 'bolt', '볼트': 'bolt', 'nut': 'nut', '너트': 'nut',
              'retaining_pin': 'other', '고정 핀': 'other', 'washer': 'other', '와셔': 'other', 'other': 'other'}
    for spec in product.get('specs', []):
        if spec['label'] in ('fastener_type', '체결 부품 종류'):
            kinds.add(values.get(spec.get('value'), 'unknown'))
    if product.get('catalog_namespace') == 'mechanical' and product.get('catalog_id'):
        from .mechanical_catalog import get_catalog_entry
        entry = get_catalog_entry(product['catalog_id'])
        if entry and entry.category in ('bolt', '볼트', 'nut', '너트'):
            kinds.add(values[entry.category])
    def result(kind, source, reason):
        return dict(kind=kind, source=source, reason=reason)
    if kinds:
        return result(next(iter(kinds)) if len(kinds) == 1 else 'unknown', 'explicit_metadata', '명시된 제품 종류 또는 카탈로그 분류입니다.' if len(kinds) == 1 else '제품 종류 지정이 서로 다릅니다.')
    # Underscores/hyphens are separators; letters/digits (including Hangul)
    # are not. Thus nutating, boltless and 볼트용 are not independent tokens.
    boundary = r'(?<![^\W_])({})(?![^\W_])'
    negative = boundary.format('washer|pin|screw|와셔|핀|나사')
    hint = boundary.format('bolt|nut|볼트|너트')
    names = (('part_name_hint', data.get('name', '')), ('product_name_hint', product.get('name', '')))
    for source, name in names:
        if re.search(negative, name, re.IGNORECASE):
            return result('other', source, '이름에 핀·와셔·나사 단서가 있어 볼트·너트로 자동 제외하지 않습니다.')
    for source, name in names:
        matches = {values[m.group(0).lower()] for m in re.finditer(hint, name, re.IGNORECASE)}
        if len(matches) == 1:
            return result(next(iter(matches)), source, '이름의 독립 단어 단서입니다. 실제 제품 식별은 미검증이며 선택을 직접 바꿀 수 있습니다.')
        if matches:
            return result('unknown', source, '이름에 볼트·너트 단서가 함께 있어 자동 제외하지 않습니다.')
    return result('unknown' if function in ('fastener', 'unspecified') else 'other', 'mechanical_function',
                  '체결 부품 또는 미지정 기능만으로 볼트·너트 종류를 알 수 없습니다.' if function in ('fastener', 'unspecified') else '저장된 기계 기능은 볼트·너트 지정이 아닙니다.')


def classify_print_part(part):
    return print_part_classification(part)['kind']


def _print_options(bed, rotation, gap):
    def finite(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if len(bed) != 3 or any(not finite(v) or v <= 0 for v in bed):
        raise ValueError('출력 크기는 양수 mm이어야 합니다.')
    if len(rotation) != 3 or any(not finite(v) for v in rotation) or not finite(gap) or gap < 0:
        raise ValueError('출력 방향과 간격을 확인하세요.')


def _copy_ids(parts, ids, copies):
    copies = copies or {}
    if set(copies) - ids or any(not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 256 for v in copies.values()):
        raise ValueError('선택 부품의 복사 수는 1~256 정수이어야 합니다.')
    if sum(copies.get(p.id, 1) for p in parts if p.id in ids) > 1024:
        raise ValueError('한 출력 작업은 최대 1024개 복사본입니다.')
    reserved = {p.id for p in parts}
    instances = []
    for part in parts:
        if part.id not in ids:
            continue
        for index in range(1, copies.get(part.id, 1) + 1):
            identifier = part.id
            if index > 1:
                salt = 0
                while True:
                    digest = hashlib.sha256(f'{part.id}:{salt}'.encode()).hexdigest()[:20]
                    identifier = f'printcopy-{digest}-{index}'
                    if identifier not in reserved:
                        break
                    salt += 1
                reserved.add(identifier)
            instances.append((part, identifier, index))
    return instances


def _rect_clear(rect, occupied, gap):
    x0, y0, x1, y1 = rect
    return all(x1 + gap <= a + 1e-6 or c + gap <= x0 + 1e-6 or
               y1 + gap <= b + 1e-6 or d + gap <= y0 + 1e-6 for a, b, c, d in occupied)


def _fit_rect(width, length, bed, occupied, gap):
    # Deterministic bounded lower-left packing. No optimal-packing claim.
    xs = sorted({0.0, *(r[2] + gap for r in occupied)})
    ys = sorted({0.0, *(r[3] + gap for r in occupied)})
    for y in ys:
        if y + length > bed[1] + 1e-6:
            continue
        for x in xs:
            rect = (x, y, x + width, y + length)
            if x + width <= bed[0] + 1e-6 and _rect_clear(rect, occupied, gap):
                return rect
    return None


def prepare_print_plates(raw, identifiers, *, rotation=(0, 0, 0), bed=(220, 220, 250),
                         gap=5, placements=None, plate_assignments=None, copies=None,
                         exclude_fasteners=False, cancelled=None):
    """Return (plates, previews, blocking warnings), leaving source data intact.

    XY positions are bed-centered; rotations affect only print geometry. Manual
    placements reserve space before automatic packing. Plate assignments pin
    an instance to a zero-based plate. Empty plates are compacted, so callers
    must use the returned assignments on their next preview. The first copy
    keeps the Part ID; print_instances identifies every additional copy.
    """
    _print_options(bed, rotation, gap)
    _check_cancel(cancelled)
    design = Design.model_validate(deepcopy(raw)).model_copy(deep=True)
    selected = set(identifiers)
    if not selected or not selected <= {p.id for p in design.parts}:
        raise ValueError('출력할 부품을 선택하세요.')
    if not isinstance(exclude_fasteners, bool):
        raise ValueError('체결 부품 제외 옵션을 확인하세요.')
    instances = _copy_ids(design.parts, selected, copies)
    all_instance_ids = {i for _, i, _ in instances}
    excluded = sorted(p.id for p in design.parts if p.id in selected and exclude_fasteners and classify_print_part(p) in ('bolt', 'nut'))
    excluded_details = [dict(id=p.id, name=p.name, **print_part_classification(p)) for p in design.parts if p.id in excluded]
    instances = [(p, i, n) for p, i, n in instances if p.id not in excluded]
    if not instances:
        raise ValueError('체결 부품 제외 후 출력할 부품이 없습니다. 선택을 확인하세요.')
    # Retain controls for currently unselected source bodies without applying
    # them. Unknown instance keys are rejected (stale removed copies too).
    allowed_ids = all_instance_ids | {p.id for p in design.parts}
    placements = deepcopy(placements or {})
    assignments = dict(plate_assignments or {})
    if set(placements) - allowed_ids or set(assignments) - allowed_ids:
        raise ValueError('없는 복사본의 출력 배치입니다.')
    for pose in placements.values():
        if not isinstance(pose, dict) or set(pose) - {'x', 'y', 'rx', 'ry', 'rz'} or any(
                not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or abs(v) > 10000 for v in pose.values()):
            raise ValueError('출력 배치는 유한한 위치·각도여야 합니다.')
    if any(not isinstance(v, int) or isinstance(v, bool) or not 0 <= v < 256 for v in assignments.values()):
        raise ValueError('출력판 번호는 0~255 정수이어야 합니다.')
    warnings = []
    with KERNEL_LOCK:
        _check_cancel(cancelled)
        # Evaluate the original complete dependency graph. A selected body's
        # boolean tools and linked geometry must not disappear through subset.
        shapes = dict(zip((p.id for p in design.parts), build(design)))
        local = {}
        for part, _, _ in instances:
            if part.id in local:
                continue
            _check_cancel(cancelled)
            shape = shapes[part.id]
            if not shape.isValid() or not shape.Solids() or shape.Volume() <= 0:
                raise ValueError('닫힌 솔리드만 출력할 수 있습니다: ' + part.name)
            t = part.transform
            shape = shape.translate((-t.x, -t.y, -t.z))
            for angle, axis in ((t.rz, (0, 0, 1)), (t.ry, (0, 1, 0)), (t.rx, (1, 0, 0))):
                if angle:
                    shape = shape.rotate((0, 0, 0), axis, -angle)
            local[part.id] = shape
        records = []
        for part, identifier, index in instances:
            _check_cancel(cancelled)
            pose = placements.get(identifier, {})
            angles = [pose.get(k, v) for k, v in zip(('rx', 'ry', 'rz'), rotation)]
            shape = local[part.id]
            for angle, axis in zip(angles, ((1, 0, 0), (0, 1, 0), (0, 0, 1))):
                if angle:
                    shape = shape.rotate((0, 0, 0), axis, angle)
            bounds = exact_bounds(shape)
            size = (bounds.xlen, bounds.ylen, bounds.zlen)
            records.append(dict(part=part, id=identifier, copy_index=index, shape=shape, bounds=bounds,
                                size=size, angles=angles, pose=pose, manual='x' in pose or 'y' in pose))
        buckets = {}
        def bucket(index):
            if index >= 256:
                raise ValueError('한 출력 작업은 최대 256개 출력판입니다.')
            return buckets.setdefault(index, dict(records=[], occupied=[], blocked=False))
        def place(record, index, rect):
            b = bucket(index)
            if len(b['records']) >= 256:
                raise ValueError('한 출력판은 최대 256개 부품입니다.')
            b['records'].append((record, rect))
            b['occupied'].append(rect)
        # Manual coordinates stay exactly as requested, even when invalid;
        # warnings prevent export instead of silently moving the user's part.
        for record in records:
            if not record['manual']:
                continue
            index = assignments.get(record['id'], 0)
            w, h, _ = record['size']
            pose = record['pose']
            cx, cy = pose.get('x', w / 2 - bed[0] / 2), pose.get('y', h / 2 - bed[1] / 2)
            place(record, index, (cx + bed[0] / 2 - w / 2, cy + bed[1] / 2 - h / 2,
                                  cx + bed[0] / 2 + w / 2, cy + bed[1] / 2 + h / 2))
        for record in records:
            if record['manual']:
                continue
            _check_cancel(cancelled)
            w, h, z = record['size']
            pinned = assignments.get(record['id'])
            oversized = any(size > limit + 1e-6 for size, limit in zip(record['size'], bed))
            choices = [pinned] if pinned is not None else list(range(max(buckets, default=-1) + 2))
            found = False
            for index in choices:
                b = bucket(index)
                if b['blocked'] or len(b['records']) >= 256:
                    continue
                rect = None if oversized else _fit_rect(w, h, bed, b['occupied'], gap)
                if rect is not None:
                    place(record, index, rect); found = True; break
                if not b['records'] and oversized:
                    place(record, index, ((bed[0] - w) / 2, (bed[1] - h) / 2, (bed[0] + w) / 2, (bed[1] + h) / 2))
                    b['blocked'] = True; found = True; break
            if not found:
                # Explicit plate membership is preserved even if it cannot
                # fit; show it outside the plate and block the batch export.
                if pinned is None:
                    raise ValueError('출력판 배치를 만들 수 없습니다.')
                b = bucket(pinned)
                if len(b['records']) >= 256:
                    raise ValueError('한 출력판은 최대 256개 부품입니다.')
                y = max((r[3] for r in b['occupied']), default=0.0) + gap
                place(record, pinned, (0, y, w, y + h))
        plates, results = [], []
        returned_assignments = {}
        for index, b in enumerate(v for _, v in sorted(buckets.items()) if v['records']):
            _check_cancel(cancelled)
            parts, assets, poses, members, plate_warnings = [], {}, {}, [], []
            for offset, (record, rect) in enumerate(b['records']):
                _check_cancel(cancelled)
                part, identifier, bounds = record['part'], record['id'], record['bounds']
                w, h, z = record['size']
                cx, cy = (rect[0] + rect[2] - bed[0]) / 2, (rect[1] + rect[3] - bed[1]) / 2
                if rect[0] < -1e-6 or rect[1] < -1e-6 or rect[2] > bed[0] + 1e-6 or rect[3] > bed[1] + 1e-6 or z > bed[2] + 1e-6:
                    plate_warnings.append(f'{part.name} · 출력판 {index + 1} 영역을 벗어납니다 ({w:g} × {h:g} × {z:g} mm). 부품을 임의로 자르지 않았습니다.')
                if not _rect_clear(rect, b['occupied'][:offset], gap):
                    plate_warnings.append(f'{part.name} · 출력판 {index + 1} 부품 사이 간격을 확인하세요.')
                placed = record['shape'].translate((cx - (bounds.xmin + bounds.xmax) / 2,
                                                    cy - (bounds.ymin + bounds.ymax) / 2, -bounds.zmin))
                key = 'print-' + identifier
                assets[key] = encode_shape(placed, part.name)
                parts.append(Part(id=identifier, name=part.name, color=part.color, geometry=dict(kind='imported', asset_id=key)))
                poses[identifier] = dict(x=cx, y=cy, **dict(zip(('rx', 'ry', 'rz'), record['angles'])))
                classification = print_part_classification(part)
                members.append(dict(id=identifier, source_part_id=part.id, copy_index=record['copy_index'], classification=classification['kind'],
                                    classification_source=classification['source'], classification_reason=classification['reason']))
                returned_assignments[identifier] = index
            prepared = Design(name=(design.name[:75] + f' · 3D 프린팅 {index + 1}'), parts=parts, assets=assets)
            result = preview(prepared)
            _check_cancel(cancelled)
            if result['stats']['collisions']:
                plate_warnings.append(f'출력판 {index + 1} 부품 사이에 간섭이 있습니다.')
            result.update(print_plate_index=index, print_placements=poses, print_instances=members,
                          print_bed=list(bed), print_gap=gap, print_warnings=plate_warnings,
                          print_excluded_ids=excluded, print_excluded_count=len(excluded), print_excluded_details=excluded_details)
            warnings.extend(plate_warnings)
            plates.append(prepared); results.append(result)
        for result in results:
            result['print_plate_assignments'] = dict(returned_assignments)
        return plates, results, warnings


def _print_rotation(angles):
    """The same Rx, then Ry, then Rz convention as manual print placement."""
    x, y, z = map(math.radians, angles)
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    return np.array(((cz*cy, cz*sy*sx-sz*cx, cz*sy*cx+sz*sx),
                     (sz*cy, sz*sy*sx+cz*cx, sz*sy*cx-cz*sx),
                     (-sy, cy*sx, cy*cx)))


def _print_angles(matrix):
    y = math.asin(max(-1., min(1., -float(matrix[2, 0]))))
    if abs(math.cos(y)) > 1e-10:
        x, z = math.atan2(matrix[2, 1], matrix[2, 2]), math.atan2(matrix[1, 0], matrix[0, 0])
    else:
        x, z = math.atan2(-matrix[1, 2], matrix[1, 1]), 0.
    return tuple(0. if abs(v) < 1e-9 else round(v, 10) for v in map(math.degrees, (x, y, z)))


def _contact_hull(points):
    """Convex support footprint; this is a tipping estimate, not adhesion."""
    points = sorted(set(map(tuple, np.round(points, 8))))
    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    def half(values):
        result = []
        for p in values:
            while len(result) >= 2 and cross(result[-2], result[-1], p) <= 0:
                result.pop()
            result.append(p)
        return result
    return half(points)[:-1] + half(reversed(points))[:-1] if len(points) > 2 else points


def _orientation_metrics(mesh, angles, bounds, bed, overhang_angle, contact_tolerance):
    rotation = _print_rotation(angles)
    vertices = mesh['vertices'] @ rotation.T
    triangles = vertices[mesh['triangles']]
    normals = mesh['normals'] @ rotation.T
    heights = triangles[:, :, 2] - bounds.zmin
    contact = (heights.max(axis=1) <= contact_tolerance + 1e-6) & (normals[:, 2] < -.5)
    downward = (normals[:, 2] < -math.cos(math.radians(overhang_angle))) & ~contact
    projected = mesh['areas'] * np.maximum(0., -normals[:, 2])
    overhang_area = float(projected[downward].sum())
    demand = float((projected[downward] * np.maximum(0., heights[downward].mean(axis=1))).sum())
    contact_area = float(projected[contact].sum())
    contact_points = triangles[contact, :, :2].reshape(-1, 2)
    hull = _contact_hull(contact_points)
    center = mesh['center'] @ rotation.T
    margin = None
    if len(hull) >= 3:
        distances = []
        for a, b in zip(hull, hull[1:] + hull[:1]):
            dx, dy = b[0]-a[0], b[1]-a[1]
            length = math.hypot(dx, dy)
            if length:
                distances.append((dx*(center[1]-a[1])-dy*(center[0]-a[0])) / length)
        margin = float(min(distances)) if distances else None
    spans = np.ptp(contact_points, axis=0).tolist() if len(contact_points) else [0., 0.]
    size = [bounds.xlen, bounds.ylen, bounds.zlen]
    ratio = min(1., contact_area / max(size[0]*size[1], 1e-9))
    stable = contact_area > 1e-6 and margin is not None and margin >= -1e-6
    narrow = min(spans)
    risk = 1. if not stable else min(1., .15*(1.-ratio) + .2*size[2]/max(narrow, .1))
    score = demand / mesh['volume'] + 2.*risk + .05*size[2]/max(max(size[:2]), .1)
    return dict(support_proxy_mm3=demand, overhang_area_mm2=overhang_area,
                contact_area_mm2=contact_area, contact_span_mm=spans,
                com_footprint_margin_mm=margin, stability_risk=risk, stable_contact=stable,
                fits_bed=all(v <= limit+1e-6 for v, limit in zip(size, bed)), size_mm=size, score=score)


def _orientation_candidates(mesh):
    candidates, seen = [], set()
    def add(angles):
        key = tuple(np.round(_print_rotation(angles).ravel(), 8))
        if key not in seen:
            seen.add(key); candidates.append(tuple(angles))
    for x in (0, 90, 180, 270):
        for y in (0, 90, 180, 270):
            for z in (0, 90, 180, 270):
                add((x, y, z))
    # Align substantial mesh surface directions with the bed, including
    # oblique planar faces. Curved face samples remain bounded candidates.
    groups = {}
    for normal, area in zip(np.round(mesh['normals'], 3), mesh['areas']):
        key = tuple(normal)
        groups[key] = groups.get(key, 0.) + float(area)
    for normal, _ in sorted(groups.items(), key=lambda item: (-item[1], item[0]))[:12]:
        up = -np.array(normal)
        up /= np.linalg.norm(up)
        axis = np.eye(3)[int(np.argmin(np.abs(up)))]
        right = np.cross(axis, up); right /= np.linalg.norm(right)
        matrix = np.array((right, np.cross(up, right), up))
        add(_print_angles(matrix))
        add(_print_angles(_print_rotation((0, 0, 90)) @ matrix))
    return candidates  # at most 24 axial + 24 surface candidates


def recommend_print_orientations(raw, identifiers, *, rotation=(0, 0, 0), bed=(220, 220, 250),
                                 gap=5, placements=None, copies=None, exclude_fasteners=False,
                                 cancelled=None, overhang_angle=45., max_seconds=30.):
    """Recommend output-only poses from bounded real surface geometry.

    Explicit invocation may replace selected rotations; XY and excluded poses
    are retained. Subsequent manual poses are honored by prepare_print_plates.
    The area-height proxy includes downward surfaces above the bed without
    ray tracing, layers, material, adhesion or actual support generation.
    Native build/tessellation cannot be interrupted mid-call; cancellation and
    the wall-time limit are checked before/after each native operation.
    """
    _print_options(bed, rotation, gap)
    if (not isinstance(overhang_angle, (int, float)) or isinstance(overhang_angle, bool) or
            not math.isfinite(overhang_angle) or not 20 <= overhang_angle <= 70 or
            not isinstance(max_seconds, (int, float)) or isinstance(max_seconds, bool) or
            not math.isfinite(max_seconds) or not .1 <= max_seconds <= 120):
        raise ValueError('자동 자세 각도·계산 시간 한도를 확인하세요.')
    deadline = time.monotonic() + max_seconds
    def check():
        _check_cancel(cancelled)
        if time.monotonic() >= deadline:
            raise ValueError('자동 자세 계산 시간 한도를 넘었습니다. 선택 부품 수를 줄이세요.')
    check()
    design = Design.model_validate(deepcopy(raw)).model_copy(deep=True)
    selected = set(identifiers)
    if not selected or not selected <= {p.id for p in design.parts}:
        raise ValueError('출력할 부품을 선택하세요.')
    if not isinstance(exclude_fasteners, bool):
        raise ValueError('체결 부품 제외 옵션을 확인하세요.')
    instances = _copy_ids(design.parts, selected, copies)
    allowed = {i for _, i, _ in instances} | {p.id for p in design.parts}
    poses = deepcopy(placements or {})
    if set(poses) - allowed:
        raise ValueError('없는 복사본의 출력 배치입니다.')
    for pose in poses.values():
        if not isinstance(pose, dict) or set(pose)-{'x','y','rx','ry','rz'} or any(
                not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or abs(v)>10000 for v in pose.values()):
            raise ValueError('출력 배치는 유한한 위치·각도여야 합니다.')
    excluded = sorted(p.id for p in design.parts if p.id in selected and exclude_fasteners and classify_print_part(p) in ('bolt','nut'))
    details = [dict(id=p.id, name=p.name, **print_part_classification(p)) for p in design.parts if p.id in excluded]
    instances = [(p, i, n) for p, i, n in instances if p.id not in excluded]
    if not instances:
        raise ValueError('체결 부품 제외 후 출력할 부품이 없습니다. 선택을 확인하세요.')
    acquired = False
    try:
        while not acquired:
            check(); acquired = KERNEL_LOCK.acquire(timeout=.05)
        shapes = dict(zip((p.id for p in design.parts), build(design)))
        check()
        meshes, local, candidates, evaluated = {}, {}, {}, {}
        total_triangles = 0
        diagnostics, warnings = {}, []
        for part, identifier, _ in instances:
            check()
            if part.id not in meshes:
                shape = shapes[part.id]
                if not shape.isValid() or not shape.Solids() or shape.Volume() <= 0:
                    raise ValueError('닫힌 솔리드만 출력할 수 있습니다: '+part.name)
                t = part.transform
                shape = shape.translate((-t.x, -t.y, -t.z))
                for angle, axis in ((t.rz,(0,0,1)),(t.ry,(0,1,0)),(t.rx,(1,0,0))):
                    if angle: shape = shape.rotate((0,0,0), axis, -angle)
                check()
                vertices, triangles = shape.tessellate(.1, .15)
                check()
                if not triangles or len(triangles)>50000 or total_triangles+len(triangles)>250000:
                    raise ValueError('자동 자세 표면 계산 한도를 넘었습니다. 선택 부품 수를 줄이세요.')
                total_triangles += len(triangles)
                vertices = np.array([v.toTuple() for v in vertices])
                triangles = np.array(triangles, dtype=int)
                faces = vertices[triangles]
                cross = np.cross(faces[:,1]-faces[:,0], faces[:,2]-faces[:,0])
                lengths = np.linalg.norm(cross, axis=1)
                valid = lengths > 1e-12
                if not valid.any(): raise ValueError('자동 자세에 유효한 표면이 필요합니다: '+part.name)
                mesh = dict(vertices=vertices, triangles=triangles[valid], normals=cross[valid]/lengths[valid,None],
                            areas=lengths[valid]/2, center=np.array(shape.Center().toTuple()), volume=shape.Volume())
                meshes[part.id], local[part.id] = mesh, shape
                candidates[part.id] = _orientation_candidates(mesh)
                evaluated[part.id] = {}
            current = tuple(poses.get(identifier, {}).get(k,v) for k,v in zip(('rx','ry','rz'),rotation))
            def evaluate(angles):
                check()
                key = tuple(angles)
                cache = evaluated[part.id]
                if key not in cache:
                    oriented = local[part.id]
                    for angle, axis in zip(angles, ((1,0,0),(0,1,0),(0,0,1))):
                        if angle: oriented = oriented.rotate((0,0,0), axis, angle)
                    bounds = exact_bounds(oriented)
                    check()
                    cache[key] = _orientation_metrics(meshes[part.id], angles, bounds, bed, overhang_angle, .1)
                return cache[key]
            baseline = evaluate(current)
            choices = [(current, baseline)] + [(angles, evaluate(angles)) for angles in candidates[part.id]]
            # Hard fit priority and real contact precede the numeric heuristic;
            # exact ties retain the current/manual rotation.
            chosen, recommended = min(choices, key=lambda item: (not item[1]['fits_bed'], not item[1]['stable_contact'], round(item[1]['score'], 10)))
            poses.setdefault(identifier, {}).update(zip(('rx','ry','rz'), chosen))
            diagnostics[identifier] = dict(baseline=deepcopy(baseline), recommended=deepcopy(recommended),
                                           chosen=dict(zip(('rx','ry','rz'),chosen)), candidates_evaluated=len(choices),
                                           mesh_triangles=len(meshes[part.id]['triangles']))
            if not recommended['fits_bed']:
                warnings.append(part.name+' · 후보 자세가 출력 영역에 맞지 않습니다. 부품을 임의로 자르지 않았습니다.')
            if not recommended['stable_contact']:
                warnings.append(part.name+' · 바닥 접촉·무게중심 안정성을 확인하세요.')
        check()
        return dict(placements=poses, diagnostics=diagnostics, excluded_ids=excluded, excluded_details=details, warnings=warnings,
                    method=dict(overhang_angle_deg=overhang_angle, contact_tolerance_mm=.1, mesh_tolerance_mm=.1,
                                angular_tolerance_rad=.15, max_candidates_per_instance=49, max_triangles_per_part=50000,
                                max_total_triangles=250000, max_seconds=max_seconds, estimated_only=True,
                                center_basis='uniform_density_geometric_volume',
                                stability_basis='convex_hull_of_near_bed_surface; no adhesion or dynamic-load model',
                                qualification='표면 면적×바닥 높이와 접촉·무게중심 추정입니다. 실제 서포트 체적·슬라이싱·출력 성공을 보장하지 않습니다.'))
    finally:
        if acquired: KERNEL_LOCK.release()


def export_print_stls(plates, results, destination, *, tolerance=.025, cancelled=None):
    """Atomically export separate STLs plus a portable relative-only ZIP index.

    Cancellation is checked between native mesh operations and immediately
    before replacement. A running single tessellation cannot be interrupted;
    its temporary result is discarded if cancellation arrives during it.
    """
    if tolerance not in (.1, .05, .025, .01):
        raise ValueError('STL 정밀도를 선택하세요.')
    target = Path(destination)
    if target.suffix.lower() != '.zip':
        raise ValueError('여러 출력판은 ZIP 파일 이름을 선택하세요.')
    if not plates or len(plates) != len(results) or len(plates) > 256:
        raise ValueError('검증된 출력판이 필요합니다.')
    prepared = [Design.model_validate(deepcopy(p)).model_copy(deep=True) for p in plates]
    results = deepcopy(results)
    for index, (plate, result) in enumerate(zip(prepared, results)):
        if not plate.parts or result.get('_geometry_key') != geometry_key(plate) or result.get('print_plate_index') != index:
            raise ValueError('출력판 미리보기가 변경되었습니다. 다시 확인하세요.')
        if result.get('print_warnings') or result['stats']['collisions'] or not result['stats']['valid']:
            raise ValueError('출력판 경고를 해결한 뒤 저장하세요.')
        if {r['id'] for r in result['print_instances']} != {p.id for p in plate.parts}:
            raise ValueError('출력판 복사본 정보를 확인하세요.')
        _print_options(result['print_bed'], (0, 0, 0), result['print_gap'])
    temporary = target.with_name(target.name + '.' + uuid4().hex + '.tmp')
    manifest = dict(schema_version=1, units='mm', format='stl', tolerance_mm=tolerance, plates=[])
    try:
        _check_cancel(cancelled)
        with KERNEL_LOCK, TemporaryDirectory(prefix='promptcad-print-', dir=target.parent) as scratch:
            with ZipFile(temporary, 'w', ZIP_DEFLATED) as archive:
                for index, (plate, result) in enumerate(zip(prepared, results)):
                    _check_cancel(cancelled)
                    shapes = build(plate)
                    bed, gap, occupied = result['print_bed'], result['print_gap'], []
                    for shape in shapes:
                        if not shape.isValid() or not shape.Solids() or shape.Volume() <= 0:
                            raise ValueError('유효한 출력 솔리드가 필요합니다.')
                        b = exact_bounds(shape)
                        rect = (b.xmin + bed[0] / 2, b.ymin + bed[1] / 2, b.xmax + bed[0] / 2, b.ymax + bed[1] / 2)
                        if b.zmin < -1e-6 or b.zmax > bed[2] + 1e-6 or rect[0] < -1e-6 or rect[1] < -1e-6 or rect[2] > bed[0] + 1e-6 or rect[3] > bed[1] + 1e-6 or not _rect_clear(rect, occupied, gap):
                            raise ValueError('출력 영역과 부품 간격을 다시 확인하세요.')
                        occupied.append(rect)
                    name = f'plate-{index + 1:03d}.stl'
                    path = Path(scratch) / name
                    cq.exporters.export(cq.Compound.makeCompound(shapes), str(path), exportType='STL', tolerance=tolerance, angularTolerance=.1)
                    _check_cancel(cancelled)
                    archive.write(path, name)
                    manifest['plates'].append(dict(index=index, file=name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                                  bed_mm=bed, gap_mm=gap, instances=result['print_instances'],
                                                  placements=result['print_placements']))
                archive.writestr('print-index.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        _check_cancel(cancelled)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest
