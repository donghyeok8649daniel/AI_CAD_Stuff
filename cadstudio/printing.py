"""Non-destructive build-plate preparation; STL output uses the preview solids."""
import os
from pathlib import Path
from uuid import uuid4
import cadquery as cq
from .models import Design, Part
from .kernel import KERNEL_LOCK, build, exact_bounds, preview
from .imported import encode_shape


def prepare_print(raw, identifiers, *, rotation=(0,0,0), bed=(220,220,250), gap=5, placements=None):
    import math
    if len(bed)!=3 or any(not math.isfinite(x) or x<=0 for x in bed):raise ValueError('출력 크기는 양수 mm이어야 합니다.')
    if len(rotation)!=3 or any(not math.isfinite(x) for x in rotation) or not math.isfinite(gap) or gap<0:raise ValueError('출력 방향과 간격을 확인하세요.')
    design=Design.model_validate(raw).model_copy(deep=True);ids=set(identifiers)
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


def export_print_stl(prepared, destination, *, tolerance=.025):
    if tolerance not in (.1,.05,.025,.01):raise ValueError('STL 정밀도를 선택하세요.')
    target=Path(destination)
    if target.suffix.lower()!='.stl':raise ValueError('STL 파일 이름을 선택하세요.')
    temporary=target.with_name(target.name+'.'+uuid4().hex+'.tmp')
    try:
        with KERNEL_LOCK:
            shapes=build(prepared)
            if not shapes or any(not s.isValid() or not s.Solids() for s in shapes):raise ValueError('유효한 출력 솔리드가 필요합니다.')
            cq.exporters.export(cq.Compound.makeCompound(shapes),str(temporary),exportType='STL',tolerance=tolerance,angularTolerance=.1)
        os.replace(temporary,target)
    finally:temporary.unlink(missing_ok=True)
    return target
