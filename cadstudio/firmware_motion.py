"""Readonly kinematic replay of the positions produced by actual ARM firmware."""
from copy import deepcopy
import math
import numpy as np
from .firmware_drive import validate_drive,validate_trace


def checked_motion(design,image,result):
    from .firmware_emulation import FirmwareImage,validate_binding
    from .models import Design
    design=Design.model_validate(design);image=FirmwareImage.model_validate(image)
    if any(getattr(f,'tool_part_id',None) and not f.suppressed for p in design.parts for f in p.features):
        raise ValueError('Cross-body feature geometry can change during motion; rigid firmware replay is unsupported.')
    validate_binding(design.electrical,image);spec=validate_drive(design,image)
    if result.get('status')!='executed' or result.get('image_sha256')!=image.sha256:
        raise ValueError('Only a completed execution of this exact ELF can drive CAD replay.')
    trace,errors=validate_trace({'virtual_trace':result.get('virtual_motion_trace',[]),'virtual_faults':result.get('errors',[])},spec,result['scenario'])
    if errors:raise ValueError('; '.join(errors))
    return design,spec,trace


def pose_at(design,spec,row):
    from .models import Design
    from .assembly_motion import set_joint_motion
    if not math.isfinite(row['screw_angle_deg']) or abs(row['position_mm'])>spec.max_displacement_mm:
        raise ValueError('Motion sample lies outside its declared geometry envelope.')
    if not math.isclose(row['screw_angle_deg'],row['position_mm']*360/spec.screw_lead_mm_per_rev,rel_tol=1e-10,abs_tol=1e-8):
        raise ValueError('Position and screw-angle units disagree.')
    raw=deepcopy(design.model_dump(mode='json'))
    set_joint_motion(raw,spec.mate_id,{'rz':row['screw_angle_deg']})
    pose=Design.model_validate(raw)
    actual=next(m.rz for m in pose.mates if m.id==spec.mate_id)
    if not math.isclose(actual,row['screw_angle_deg'],rel_tol=0,abs_tol=1e-7):raise ValueError('A variable/constraint overrode the requested firmware joint angle.')
    if any(a.geometry!=b.geometry or a.features!=b.features or a.source_part_id!=b.source_part_id for a,b in zip(design.parts,pose.parts)) or any(getattr(design,k)!=getattr(pose,k) for k in ('assets','sketches','parameters','dimension_bindings','configurations')):
        raise ValueError('Local shape inputs changed; rigid firmware replay cannot display the new shape.')
    return pose


def world_matrix(transform):
    x,y,z=map(math.radians,(transform.rx,transform.ry,transform.rz))
    cx,sx=math.cos(x),math.sin(x);cy,sy=math.cos(y),math.sin(y);cz,sz=math.cos(z),math.sin(z)
    rotation=np.array([[cz,-sz,0],[sz,cz,0],[0,0,1]])@np.array([[cy,0,sy],[0,1,0],[-sy,0,cy]])@np.array([[1,0,0],[0,cx,-sx],[0,sx,cx]])
    matrix=np.eye(4);matrix[:3,:3]=rotation;matrix[:3,3]=[transform.x,transform.y,transform.z]
    return matrix


def actor_matrices(base,pose):
    old={part.id:part for part in base.parts}
    return {part.id:world_matrix(part.transform)@np.linalg.inv(world_matrix(old[part.id].transform)) for part in pose.parts}
