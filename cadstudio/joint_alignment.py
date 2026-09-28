"""Concentric joints bound to actual cylindrical faces, not face centroids."""
from copy import deepcopy
import math
import numpy as np
import cadquery as cq
from .models import Design
from .constraints import transform_matrix
from .threads import cylinder_reference, cylinder_records


def joint_face_plane(face,index=0,count=1):
    if face.geomType()=='CYLINDER':
        ref=cylinder_reference(face,index,count)
        return cq.Plane(origin=ref.frame.origin,xDir=ref.frame.x_direction,normal=ref.frame.normal)
    from .kernel import face_frame
    return face_frame(face)


def resolve_cylinder(shape,reference):
    """Inner/outer cylinders share centroids; discriminate using actual axes."""
    candidates=[];exact=[];axis=np.array(reference.frame.normal);origin=np.array(reference.frame.origin)
    for ref in cylinder_records(shape):
        delta=np.array(ref.frame.origin)-origin
        if ref.internal!=reference.internal or abs(abs(axis@ref.frame.normal)-1)>1e-6 or np.linalg.norm(np.cross(delta,axis))>1e-4:continue
        candidates.append(ref)
        if abs(ref.diameter-reference.diameter)<1e-5 and np.linalg.norm(delta)<1e-5:exact.append(ref)
    selected=exact if exact else candidates
    if len(selected)!=1:raise ValueError('관절 원통 면이 변경되었거나 후보가 여러 개입니다. 동심 정렬에서 원통 면을 다시 선택하세요.')
    ref=selected[0];return ref.index,shape.Faces()[ref.index]


def options(raw,mate_id):
    from .kernel import build,local_shape,KERNEL_LOCK
    with KERNEL_LOCK:
        design=Design.model_validate(deepcopy(raw));build(design)
        mate=next((m for m in design.mates if m.id==mate_id),None)
        if mate is None or mate.kind not in ('revolute','cylindrical'):raise ValueError('회전 또는 원통 관절을 선택하세요.')
        parts={p.id:p for p in design.parts}
        return [[r.model_dump() for r in cylinder_records(local_shape(design,parts[pid]))] for pid in (mate.parent,mate.child)]


def align(raw,mate_id,parent_face,child_face,*,gap=None,angle=None,flipped=False):
    """Return a new document; leave existing dimensions, limits and links intact.

    Gap defaults to the current axial displacement. Clocking is measured from
    the actual cylinder frames, never inferred from a part's Euler angles.
    """
    from .kernel import build,local_shape,KERNEL_LOCK
    from .topology import face_reference
    with KERNEL_LOCK:
        design=Design.model_validate(deepcopy(raw));build(design)
        mate=next((m for m in design.mates if m.id==mate_id),None)
        if mate is None or mate.kind not in ('revolute','cylindrical'):raise ValueError('회전 또는 원통 관절을 선택하세요.')
        if any(mate_id in loop.passive_joints for loop in design.loops):raise ValueError('폐루프 수동 관절은 폐루프 구성을 먼저 편집하세요.')
        if any(link.driven==mate_id for link in design.motion_links):raise ValueError('모션 연결로 구동되는 관절은 모션 연결을 먼저 편집하세요.')
        parts={p.id:p for p in design.parts};frames=[];world=[]
        for pid,index in ((mate.parent,parent_face),(mate.child,child_face)):
            part=parts[pid];shape=local_shape(design,part);faces=shape.Faces()
            if type(index) is not int or not 0<=index<len(faces):raise ValueError('원통 면을 다시 선택하세요.')
            ref=cylinder_reference(faces[index],index,len(faces));f=ref.frame
            frames.append(dict(face=index,face_count=len(faces),support_feature=part.features[-1].id if part.features else 'base',
                               **f.model_dump(),reference=face_reference(shape,index).model_dump(),cylinder=ref.model_dump()))
            r=transform_matrix(part.transform);basis=r@np.column_stack([f.x_direction,np.cross(f.normal,f.x_direction),f.normal])
            world.append((np.array([part.transform.x,part.transform.y,part.transform.z])+r@np.array(f.origin),basis))
        (pa,pb),(ca,cb)=world;delta=ca-pa;axial=float(delta@pb[:,2])
        radial=float(np.linalg.norm(delta-pb[:,2]*axial));tilt=math.degrees(math.acos(np.clip(abs(pb[:,2]@cb[:,2]),0,1)))
        if gap is None:gap=axial
        if angle is None:angle=math.degrees(math.atan2(cb[:,0]@pb[:,1],cb[:,0]@pb[:,0]))
        data=design.model_dump();m=next(m for m in data['mates'] if m['id']==mate_id)
        m.update(parent_anchor='origin',child_anchor='origin',x=0,y=0,z=gap,rx=0,ry=0,rz=angle)
        data['joint_frames']=[f for f in data.get('joint_frames',[]) if f['mate_id']!=mate_id]
        data['joint_frames'].append(dict(mate_id=mate_id,parent=frames[0],child=frames[1],flipped=flipped))
        result=Design.model_validate(data);build(result)
        return result,dict(offset_mm=radial,tilt_deg=tilt,gap_mm=gap,angle_deg=angle)


def find_cylinder(shape,spec):
    """AI selections use measured local axes; never nearest-face guessing."""
    if not isinstance(spec,dict) or set(spec)!={'center','direction','diameter'}:raise ValueError('Cylinder selection requires center [x,y,z], direction [x,y,z], diameter.')
    center=np.array(spec['center'],dtype=float);direction=np.array(spec['direction'],dtype=float)
    if center.shape!=(3,) or direction.shape!=(3,) or not np.all(np.isfinite([center,direction])) or abs(np.linalg.norm(direction)-1)>1e-5:raise ValueError('Cylinder center/direction must be finite 3-vectors; direction must be unit length.')
    matches=[]
    for ref in cylinder_records(shape):
        axis=np.array(ref.frame.normal);delta=center-np.array(ref.frame.origin)
        if abs(abs(axis@direction)-1)<1e-6 and np.linalg.norm(delta-axis*(delta@axis))<1e-4 and abs(ref.diameter-spec['diameter'])<1e-4:
            matches.append(ref.index)
    if len(matches)!=1:raise ValueError('Actual cylindrical axis/diameter does not match uniquely. Check the pad/hole center in the face bounding-box frame; do not invent or round the axis position.')
    return matches[0]
