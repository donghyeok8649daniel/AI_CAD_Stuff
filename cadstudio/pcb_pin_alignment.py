"""Bounded PCB adapter for the frozen proper-rigid r1 pin alignment core.

PCB pins remain footprint-local XY reference points (z=0), not verified contact
ends. An assembly pose is a separate preview. No reflection/height/roll is ever
flattened into an invalid 2D footprint placement; no pad or copper is rewritten.
"""
from copy import deepcopy
from datetime import date
from hashlib import sha256
import json
import math
from collections.abc import Mapping

from .pcb import PCBProject, inspect_layout
from .pcb_placement_aid import (_body_report, _signature, MAX_PADS, MAX_SEGMENTS,
    MAX_ZONE_VERTICES)
from ._pcb_pin_alignment_core_r1 import align_pins

CORE_SHA256 = '62f36a8230abb7b1cb7699e0589fb29c2a260336b08b34d3d5f74e7eb5353c34'
MAX_MAPPINGS = 32
MAX_MOUNTS = 8
EPS = 1e-7


def _bounded_input(value, name):
    text=json.dumps(value, ensure_ascii=False, allow_nan=False)
    if len(text)>32000:
        raise ValueError(name+' exceeds the 32,000 character adapter input budget.')
    return json.loads(text)


def _digest(raw):
    return sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _mv(rotation, point):
    return [sum(a*b for a,b in zip(row,point)) for row in rotation]


def _mm(left, right):
    return [[sum(left[i][k]*right[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _pose(value):
    if not isinstance(value, Mapping) or set(value) != {'rotation', 'translation_xyz_mm'}:
        raise ValueError('Pose needs rotation and translation_xyz_mm only.')
    rotation, translation = value['rotation'], value['translation_xyz_mm']
    if not isinstance(rotation,(list,tuple)) or len(rotation)!=3 or any(not isinstance(row,(list,tuple)) or len(row)!=3 for row in rotation):
        raise ValueError('Pose rotation must be a 3 by 3 proper rigid matrix.')
    if not isinstance(translation,(list,tuple)) or len(translation)!=3:
        raise ValueError('Pose translation must have three coordinates in mm.')
    numbers=[value for row in rotation for value in row]+list(translation)
    if any(isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) for value in numbers):
        raise ValueError('Pose values must be finite numbers.')
    transpose=[list(row) for row in zip(*rotation)]
    product=_mm(rotation,transpose)
    determinant=(rotation[0][0]*(rotation[1][1]*rotation[2][2]-rotation[1][2]*rotation[2][1])
        -rotation[0][1]*(rotation[1][0]*rotation[2][2]-rotation[1][2]*rotation[2][0])
        +rotation[0][2]*(rotation[1][0]*rotation[2][1]-rotation[1][1]*rotation[2][0]))
    if abs(determinant-1)>EPS or any(abs(product[i][j]-(i==j))>EPS for i in range(3) for j in range(3)):
        raise ValueError('Pose rotation must be proper: no scaling or reflection.')
    return dict(rotation=[list(map(float,row)) for row in rotation], translation_xyz_mm=list(map(float,translation)))


def pose_from_xyz_rpy(x,y,z,roll_deg,pitch_deg,yaw_deg):
    """Explicit mm coordinates and fixed-axis Rz*Ry*Rx angles; no inferred pose."""
    values=(x,y,z,roll_deg,pitch_deg,yaw_deg)
    if any(isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) for value in values):
        raise ValueError('All XYZ and roll/pitch/yaw fields require finite explicit numbers.')
    roll,pitch,yaw=map(math.radians,(roll_deg,pitch_deg,yaw_deg))
    cr,sr,cp,sp,cy,sy=math.cos(roll),math.sin(roll),math.cos(pitch),math.sin(pitch),math.cos(yaw),math.sin(yaw)
    rotation=_mm([[cy,-sy,0],[sy,cy,0],[0,0,1]],_mm([[cp,0,sp],[0,1,0],[-sp,0,cp]],[[1,0,0],[0,cr,-sr],[0,sr,cr]]))
    return _pose(dict(rotation=rotation,translation_xyz_mm=[x,y,z]))


def _planar(pose):
    rotation=pose['rotation']
    return abs(pose['translation_xyz_mm'][2])<=EPS and all(abs(rotation[i][j]-(1 if i==j==2 else 0))<=EPS for i,j in ((0,2),(1,2),(2,0),(2,1),(2,2)))


def _registration(value,target_project):
    value=_bounded_input(value,'target registration')
    allowed={'units','target_project_sha256','target_board_to_host','host_plane_verified','source_plane_verified','basis','reviewed_by','reviewed_date'}
    if not isinstance(value,Mapping) or set(value)-allowed:
        raise ValueError('External target registration contains unsupported fields.')
    if value.get('units') not in (None,'mm'):
        raise ValueError('Target registration units must be mm; no implicit conversion.')
    pose=_pose(value['target_board_to_host']) if value.get('target_board_to_host') is not None else None
    complete=True
    for key,limit in [('basis',1000),('reviewed_by',120),('reviewed_date',10)]:
        text=value.get(key,'')
        if not isinstance(text,str) or len(text)>limit:
            raise ValueError('Target registration review record is invalid.')
        complete=complete and bool(text.strip())
    if value.get('reviewed_date'):
        date.fromisoformat(value['reviewed_date'])
    digest=_digest(target_project.model_dump(mode='json'))
    declared=value.get('target_project_sha256')
    if declared is not None and (not isinstance(declared,str) or len(declared)!=64):
        raise ValueError('Target registration needs an exact target PCB digest.')
    matched=declared==digest
    planes=value.get('host_plane_verified') is True and value.get('source_plane_verified') is True
    status=('mismatch' if declared is not None and not matched else 'nonplanar' if pose is not None and not _planar(pose)
        else 'registered' if value.get('units')=='mm' and pose is not None and complete and matched and planes else 'unverified')
    return dict(status=status,record=value,target_project_sha256=digest,digest_matches=matched,
        planar_positive_z=bool(pose is not None and _planar(pose)),pose=pose,
        scope='User-declared external board frame -> host PCB XY/+Z frame. Not an independent survey or actual 3D mating qualification.')


def _component_pose(component):
    angle=math.radians(component.rotation_deg)
    c,s=math.cos(angle),math.sin(angle)
    return dict(rotation=[[c,-s,0],[s,c,0],[0,0,1]], translation_xyz_mm=[component.x_mm,component.y_mm,0])


def compose_target_pose(source_to_target, target_world_pose):
    """Compose body-local -> target-local -> world; never use it as a 2D edit."""
    local,world=_pose(source_to_target),_pose(target_world_pose)
    offset=_mv(world['rotation'],local['translation_xyz_mm'])
    return dict(rotation=_mm(world['rotation'],local['rotation']),
        translation_xyz_mm=[a+b for a,b in zip(offset,world['translation_xyz_mm'])])


def _delta(new,old):
    rotation=_mm(new['rotation'],[list(row) for row in zip(*old['rotation'])])
    rotated=_mv(rotation,old['translation_xyz_mm'])
    return dict(rotation=rotation,translation_xyz_mm=[a-b for a,b in zip(new['translation_xyz_mm'],rotated)])


def _complete_metadata(component):
    metadata=component.library_metadata
    return bool(metadata and metadata.geometry_complete_declared and metadata.pin1_number
        and metadata.mounted_side and metadata.orientation_reference
        and metadata.body_height_mm is not None and metadata.service_clearance_mm is not None
        and metadata.source_url and metadata.revision and metadata.reviewed_by
        and metadata.reviewed_date and metadata.review_note
        and metadata.footprint_review_state=='source_reviewed')


def _board(component, declaration):
    metadata=component.library_metadata
    specs={pin.number:pin for pin in metadata.pin_specs} if metadata else {}
    roles={'power_out':'drive','signal_out':'drive','power_in':'accept','signal_in':'accept',
        'ground':'ground','passive':'passive','bidirectional':'passive'}
    pins={}
    for pin in component.pins:
        spec=specs.get(pin.number)
        interval=[spec.operating_min_v,spec.operating_max_v] if spec and spec.operating_min_v is not None and spec.operating_max_v is not None else None
        pins[pin.number]=dict(xyz=[pin.x_mm,pin.y_mm,0],net=pin.net,
            voltage_role=roles.get(spec.role) if spec else None,voltage_range_v=interval)
    complete=_complete_metadata(component)
    result=dict(pins=pins,
        footprint_verified=complete and declaration.get('footprint_verified') is True,
        pin_map_verified=complete and declaration.get('pin_map_verified') is True)
    evidence=dict(geometry_complete_declared=bool(metadata and metadata.geometry_complete_declared),
        complete_source_review_metadata=complete,explicit_verification=deepcopy(declaration),
        source_url=metadata.source_url if metadata else '',revision=metadata.revision if metadata else '',
        coordinate_reference='Saved footprint-local pad XY at reference z=0; contact tip/mating height is not inferred.',
        gender='unknown',keying='unknown unless explicitly declared in mating',
        contact_height='unknown; explicit mating reference heights only')
    return result,evidence


def _inspection_budget(project):
    zone_vertices=sum(len(zone.outline)+sum(map(len,zone.holes))+
        sum(len(polygon.points)+sum(map(len,polygon.holes)) for polygon in zone.filled_polygons) for zone in project.zones)
    return (sum(len(component.pins) for component in project.components)<=MAX_PADS
        and sum(len(track.points)-1 for track in project.tracks)<=MAX_SEGMENTS and zone_vertices<=MAX_ZONE_VERTICES)


def align_components(project, source_ref, target_ref, mapping, *, mating=None, constraints=None,
        verification=None, net_equivalences=(), target_project=None, target_world_pose=None,
        source_world_pose=None, target_registration=None):
    """Return detached PCB/assembly previews, never apply/save or remove copper.

    ``target_project`` optionally supplies an external reference component. Its
    assembly preview is supported. A 2D candidate requires explicit mm
    ``target_registration`` with exact target digest, a proper planar board-to-
    host pose, both XY/+Z plane declarations and a dated user review record.
    Its pose is composed with the SAVED target component pose, never the origin.
    ``verification`` is {source/target: {footprint_verified, pin_map_verified}};
    flags require actual complete, source-reviewed saved library metadata too.
    Current catalog board_pins alone can never set these flags.
    """
    original=PCBProject.model_validate(project).model_dump(mode='json')
    base=PCBProject.model_validate(original)
    target_base=PCBProject.model_validate(target_project) if target_project is not None else base
    result=dict(status='blocked',core_status=None,base_sha256=_digest(original),candidate=None,
        can_apply=False,moved_refs=[],source_ref=source_ref,target_ref=target_ref,
        target_external=target_project is not None,core=None,source_local_to_target_local=None,
        source_assembly_world_pose=None,source_world_delta=None,source_pin_world_xyz_mm={},
        geometry_report=None,issues=[],declarations={},target_registration=None,preview_only=True,
        mechanical_mating_safety_verified=False,manufacturing_verified=False,physical_io=False,
        core_lineage=dict(revision='r1',sha256=CORE_SHA256),
        limits=['Rigid numerical preview only; no physical connector/gender/key/retention, strength or electrical-rating acceptance.',
            'Saved footprint pad XY uses reference z=0; manufacturer contact geometry is not inferred from catalog names or board_pins.',
            'Only proper coplanar Rz placement can become a 2D preview; copper and all local geometry/metadata remain unchanged.',
            'External registration is a user-declared board frame only. External target bodies are not part of host DRC; no parent-board/group move, whole-assembly interference or mechanical mating approval.'])
    def issue(code,message):result['issues'].append(dict(code=code,message=message))
    try:
        source=next((component for component in base.components if component.ref==source_ref),None)
        target=next((component for component in target_base.components if component.ref==target_ref),None)
        if source is None or target is None or target_project is None and source_ref==target_ref:
            raise ValueError('Choose two distinct existing components, or an explicit external target project.')
        if not isinstance(mapping,(list,tuple)) or not 1<=len(mapping)<=MAX_MAPPINGS:
            raise ValueError('Pin mapping budget is 1..32 pairs.')
        constraints={} if constraints is None else _bounded_input(constraints,'constraints')
        mating={} if mating is None else _bounded_input(mating,'mating')
        verification={} if verification is None else _bounded_input(verification,'verification')
        if not isinstance(constraints,Mapping) or not isinstance(mating,Mapping) or not isinstance(verification,Mapping):
            raise ValueError('Mating, constraints and verification must be mappings.')
        mounts=constraints.get('fixed_mounts',())
        if not isinstance(mounts,(list,tuple)) or len(mounts)>MAX_MOUNTS:
            raise ValueError('Fixed mounting constraint budget is 8 points.')
        if not isinstance(net_equivalences,(list,tuple)) or len(net_equivalences)>64:
            raise ValueError('Net equivalence budget is 64 declarations.')
        if set(verification)-{'source','target'}:
            raise ValueError('Verification contains an unknown component side.')
        for side in ('source','target'):
            declaration=verification.get(side,{})
            if not isinstance(declaration,Mapping) or set(declaration)-{'footprint_verified','pin_map_verified'} or any(type(value) is not bool for value in declaration.values()):
                raise ValueError('Explicit verification flags must be booleans, never catalog inferred.')
        sb,se=_board(source,verification.get('source',{}))
        tb,te=_board(target,verification.get('target',{}))
        result['declarations']=dict(source=se,target=te,mating=deepcopy(mating),constraints=deepcopy(constraints))
        target_pose=_pose(target_world_pose) if target_world_pose is not None else _component_pose(target)
        registration=None
        if target_registration is not None:
            if target_project is None:raise ValueError('Target registration requires an explicit external target PCB.')
            if target_world_pose is not None:raise ValueError('Use target registration or a custom target world pose, never both.')
            registration=_registration(target_registration,target_base)
            result['target_registration']=registration
            if registration['pose'] is not None:
                target_pose=compose_target_pose(_component_pose(target),registration['pose'])
        old_source_pose=_pose(source_world_pose) if source_world_pose is not None else _component_pose(source)
        core=align_pins(dict(units='mm',source=sb,target=tb,mapping=deepcopy(mapping),
            mating=mating,constraints=constraints,net_equivalences=deepcopy(net_equivalences)))
        result['core']=core;result['core_status']=core['status']
        local=core.get('transform')
        if local is None:
            result['status']=core['status'];return result
        local=_pose({key:local[key] for key in ('rotation','translation_xyz_mm')})
        world=compose_target_pose(local,target_pose)
        result['source_local_to_target_local']=local
        result['source_assembly_world_pose']=world
        result['source_world_delta']=_delta(world,old_source_pose)
        result['source_pin_world_xyz_mm']={number:[a+b for a,b in zip(_mv(world['rotation'],pin['xyz']),world['translation_xyz_mm'])] for number,pin in sb['pins'].items()}
        rotation=world['rotation'];planar=_planar(world)
        if core['status'] in ('rejected','constraint_unresolved'):
            result['status']=core['status'];return result
        if target_project is not None and (registration is None or registration['status']!='registered'):
            state=registration['status'] if registration else 'absent'
            result['status']='nonplanar_preview' if state=='nonplanar' else 'assembly_preview'
            issue('EXTERNAL_REGISTRATION_'+state.upper(),'External board registration is '+state+'; no host PCB placement candidate.');return result
        if not planar:
            result['status']='nonplanar_preview';issue('NOT_REPRESENTABLE_AS_2D_FOOTPRINT','Height, roll or flip cannot be flattened onto this host PCB.');return result
        if core['status']!='aligned_preview':
            result['status']=core['status'];return result
        if target_project is None and target_world_pose is not None:
            saved_target=_pose(_component_pose(target))
            if any(abs(a-b)>EPS for row,saved in zip(target_pose['rotation'],saved_target['rotation']) for a,b in zip(row,saved)) or any(abs(a-b)>EPS for a,b in zip(target_pose['translation_xyz_mm'],saved_target['translation_xyz_mm'])):
                result['status']='assembly_preview';issue('TARGET_HOST_POSE_UNDECLARED','Custom target assembly pose differs from the saved same-host target; 2D placement is withheld.');return result
        if not source.fitted or not target.fitted:
            issue('NOT_FITTED_COMPONENT','A non-fitted component cannot be accepted as a mating placement.');return result
        if base.zones or any(pin.net in {obj.net for obj in [*base.tracks,*base.vias]} for pin in source.pins if pin.net):
            issue('EXISTING_COPPER_LOCK','Moving a wired component or any component under existing zones is blocked.');return result
        if not _inspection_budget(base):
            issue('INSPECTION_BUDGET_EXCEEDED','Complete layout inspection exceeds this bounded preview budget.');return result
        if source_world_pose is not None and _digest(old_source_pose)!=_digest(_pose(_component_pose(source))):
            issue('SOURCE_HOST_POSE_UNDECLARED','A custom source assembly pose is preview-only without a host-board coordinate adapter.');return result
        raw=deepcopy(original)
        moved=next(component for component in raw['components'] if component['ref']==source_ref)
        moved['x_mm'],moved['y_mm']=world['translation_xyz_mm'][:2]
        moved['rotation_deg']=math.degrees(math.atan2(rotation[1][0],rotation[0][0]))
        candidate=PCBProject.model_validate(raw)
        before,after=inspect_layout(base),inspect_layout(candidate)
        before_bodies,after_bodies=_body_report(base),_body_report(candidate)
        result['geometry_report']=dict(before=before,after=after,before_bodies=before_bodies,after_bodies=after_bodies,
            scope='Host PCB declared 2D pad/copper and rotated body envelopes only. External target body/PCB is not included; no whole-assembly interference, parent-board/group move, actual 3D mating or manufacturing acceptance.')
        if not _signature(after['findings'])<=_signature(before['findings']) or not _signature(after_bodies)<=_signature(before_bodies) or any(source_ref in row['refs'] for row in after_bodies):
            issue('NEW_OR_MOVED_BODY_FINDING','Candidate adds a finding or fails the moved body envelope checks.');return result
        physical=[row for row in after['findings'] if row['code'] not in ('unrouted_net','drill_checks_partial','zone_fill_missing','zone_fill_unverified','zone_contour_checks_partial','layer_subset')]
        if any(row['severity']=='error' and source_ref in row['refs'] for row in physical):
            issue('MOVED_COMPONENT_GEOMETRY_ERROR','Moved component still has a geometric error.');return result
        output=candidate.model_dump(mode='json')
        expected=deepcopy(original)
        target_row=next(component for component in expected['components'] if component['ref']==source_ref)
        target_row.update(x_mm=moved['x_mm'],y_mm=moved['y_mm'],rotation_deg=moved['rotation_deg'])
        if output!=expected:raise ValueError('Alignment changed immutable component/pad/net/copper data.')
        result.update(status='aligned_preview',candidate=output,can_apply=True,moved_refs=[source_ref] if output!=original else [])
        return result
    except (ValueError,TypeError,KeyError) as error:
        result['status']='rejected';issue('ADAPTER_INPUT_INVALID',str(error));return result
