"""Read-only sampled joint playback, independent of electrical qualification.

Exact solids are checked at every declared sample. The viewer reuses rigid
meshes; it never writes mates or clears a collision to permit animation.
This is not a continuous swept-volume or physical motor certification.
"""
from copy import deepcopy
from math import ceil,isfinite
import numpy as np
from .motion_budget import MotionInspectionBudget
from .models import Design
from .assembly_motion import motion_controls,set_joint_motion,JOINT_AXES
from .automatic_interference import design_digest
from .constraints import transform_matrix


def _sample_collision_hits(current,shapes,base,baseline_hits,check,baseline_bounds=None,baseline_solids=None,completed=lambda:None):
    """Reuse only exact unchanged static pairs already checked in the full start.

    The caller holds KERNEL_LOCK and verifies identical local geometry/features.
    No tolerance-based pose equality, visibility/group filter or new threshold.
    """
    from .kernel import exact_bounds
    from .interference import pair,VOLUME_EPS
    from .collision_policy import flexible_wire_part_ids
    if [p.id for p in current.parts]!=[p.id for p in base.parts] or len(shapes)!=len(current.parts):raise ValueError('구동 부품 목록이 바뀌었습니다.')
    excluded=set(flexible_wire_part_ids(current))
    if excluded!=set(flexible_wire_part_ids(base)):raise ValueError('간섭 검사 분류가 바뀌었습니다. 기준 자세부터 다시 검사하세요.')
    unchanged=[p.transform==q.transform for p,q in zip(current.parts,base.parts)]
    prior={pair(hit):hit for hit in baseline_hits}
    bounds=[baseline_bounds[i] if baseline_bounds is not None and unchanged[i] else exact_bounds(shape) for i,shape in enumerate(shapes)]
    solids=[baseline_solids[i] if baseline_solids is not None and unchanged[i] else bool(shape.Solids()) for i,shape in enumerate(shapes)]
    stationary={current.parts[i].id for i,value in enumerate(unchanged) if value}
    changed_indices=[i for i,value in enumerate(unchanged) if not value]
    hits=[hit for hit in baseline_hits if hit['a'] in stationary and hit['b'] in stationary and hit['a'] not in excluded and hit['b'] not in excluded]
    checked=0;reused=len(stationary)*(len(stationary)-1)//2
    for i,a in enumerate(shapes):
        candidates=(j for j in changed_indices if j>i) if unchanged[i] else range(i+1,len(shapes))
        for j in candidates:
            check()
            checked+=1
            if current.parts[i].id in excluded or current.parts[j].id in excluded:completed();continue
            if not solids[i] or not solids[j]:completed();continue
            ba,bb=bounds[i],bounds[j]
            if not all(min(getattr(ba,k+'max'),getattr(bb,k+'max'))-max(getattr(ba,k+'min'),getattr(bb,k+'min'))>1e-5 for k in 'xyz'):completed();continue
            volume=a.intersect(shapes[j]).Volume()
            if not isfinite(volume):raise ValueError('간섭 체적을 계산하지 못했습니다. 형상을 확인하세요.')
            if volume>VOLUME_EPS:hits.append(dict(a=current.parts[i].id,b=current.parts[j].id,volume=volume))
            completed()
    return hits,checked,reused


def pose_matrix(transform):
    matrix=np.eye(4);matrix[:3,:3]=transform_matrix(transform);matrix[:3,3]=[transform.x,transform.y,transform.z]
    return matrix


def compile_joint_playback(raw,targets,*,step_degrees=2.,check=lambda:None,seconds=None,progress=lambda report:None,wait_seconds=120.,segmented=False):
    from .kernel import KERNEL_LOCK,build,local_shape_session,exact_bounds,_rigid_pose_shapes,_preview_same_checked_pose
    from .interference import physical_collisions,exact_collisions,describe
    if type(step_degrees) not in (int,float) or not isfinite(step_degrees) or not .25<=step_degrees<=2:
        raise ValueError('회전 검사 간격은 0.25~2도입니다.')
    if seconds is None:seconds=180. if isinstance(raw,dict) and len(raw.get('parts',()))>256 else 120.
    if type(seconds) not in (int,float) or not isfinite(seconds) or not .01<=seconds<=300:raise ValueError('검사 시간 범위를 확인하세요.')
    if not isinstance(targets,list) or not 1<=len(targets)<=8:raise ValueError('회전 관절 1~8개를 선택하세요.')
    budget=MotionInspectionBudget(seconds,check,progress,wait_seconds,segmented=segmented);guard=budget.guard
    with budget.locked(KERNEL_LOCK),local_shape_session():
        budget.phase('base_validation');guard();base=Design.model_validate(deepcopy(raw));budget.checkpoint()
        budget.phase('base_build');base_shapes=build(base);budget.checkpoint();normalized=base.model_dump()
        # Cross-body cuts can change local geometry as joints move. The rigid
        # mesh player explicitly rejects these instead of showing stale meshes.
        if any(f.get('tool_part_id') and not f.get('suppressed',False) for p in normalized['parts'] for f in p['features']):
            raise ValueError('몸체 연산이 연결된 설계는 현재 강체 재생에서 지원하지 않습니다. 실제 피처 미리보기를 사용하세요.')
        ids=set();drives=[]
        for row in targets:
            if not isinstance(row,dict) or set(row)!= {'mate_id','end_degrees'}:raise ValueError('관절 ID와 종료 각도가 필요합니다.')
            mid=row['mate_id'];end=row['end_degrees']
            if mid in ids:raise ValueError('관절이 중복되었습니다.')
            controls=motion_controls(normalized,mid)
            mate=next(m for m in normalized['mates'] if m['id']==mid)
            if mate['kind'] not in ('revolute','cylindrical') or 'rz' not in controls or 'driven_by' in controls['rz']:
                raise ValueError('독립 회전 관절의 RZ를 선택하세요. 연결·수동 관절은 구동 관절을 따릅니다.')
            if type(end) not in (int,float) or not isfinite(end):raise ValueError('종료 각도는 유한한 값이어야 합니다.')
            lo,hi=controls['rz']['limits']
            if not lo<=end<=hi:raise ValueError(f'{mid}의 기존 각도 한계 {lo:g}~{hi:g}°를 유지하세요.')
            ids.add(mid);drives.append(dict(mate_id=mid,start=controls['rz']['value'],end=float(end)))
        distance=max(abs(d['end']-d['start']) for d in drives)
        if distance<1e-9:raise ValueError('각도 변화가 없습니다.')
        budget.phase('endpoint_validation');endpoint=deepcopy(normalized)
        for drive in drives:set_joint_motion(endpoint,drive['mate_id'],{'rz':drive['end']})
        endpoint=Design.model_validate(endpoint);budget.checkpoint();budget.phase('endpoint_build');build(endpoint);budget.checkpoint()
        old_mates={m.id:m for m in base.mates}
        def coordinate_steps(mate):
            prior=old_mates[mate.id]
            return [ceil(abs(getattr(mate,axis)-getattr(prior,axis))/(step_degrees if axis.startswith('r') else .5)) for axis in JOINT_AXES[mate.kind]]
        steps=max(ceil(distance/step_degrees),max((n for mate in endpoint.mates for n in coordinate_steps(mate)),default=0))
        if steps>720:raise ValueError('검사 자세는 최대721개입니다. 범위를 나누세요.')
        budget.phase('baseline_collisions',samples=steps+1);guard();start_hits=exact_collisions(base,base_shapes,check=guard,completed=budget.checkpoint);physical=physical_collisions(base,start_hits)
        if physical:raise ValueError('현재 자세에 체적 간섭이 남아 재생을 시작하지 않습니다.\n'+describe(base,physical))
        reference_only=[h for h in start_hits if h not in physical]
        budget.phase('baseline_bounds');guard();baseline_bounds=[exact_bounds(s) for s in base_shapes];baseline_solids=[bool(s.Solids()) for s in base_shapes];budget.checkpoint()
        initial={p.id:pose_matrix(p.transform) for p in base.parts};frames=[];moving=set();pair_checks=len(base_shapes)*(len(base_shapes)-1)//2;static_pairs_reused=0
        previous_coordinates=None;max_angular_step=0.;max_linear_step=0.
        for index in range(steps+1):
            budget.phase('sample_validation',sample=index+1);guard();fraction=index/steps;pose=deepcopy(normalized)
            values={d['mate_id']:d['start']+(d['end']-d['start'])*fraction for d in drives}
            for mid,value in values.items():set_joint_motion(pose,mid,{'rz':value})
            current=Design.model_validate(pose);budget.checkpoint();budget.phase('sample_shapes');shapes=base_shapes if index==0 else _rigid_pose_shapes(base,base_shapes,current);budget.checkpoint()
            budget.phase('sample_invariants')
            actual={m.id:m for m in current.mates}
            if any(abs(actual[mid].rz-value)>1e-7 for mid,value in values.items()):raise ValueError('변수·구속이 요청한 관절각을 바꿨습니다. 기존 구속을 먼저 확인하세요.')
            coordinates={(m.id,axis):getattr(m,axis) for m in current.mates for axis in JOINT_AXES[m.kind]}
            if previous_coordinates is not None:
                for key,value in coordinates.items():
                    delta=abs(value-previous_coordinates[key])
                    if key[1].startswith('r'):max_angular_step=max(max_angular_step,delta)
                    else:max_linear_step=max(max_linear_step,delta)
                if max_angular_step>step_degrees+1e-7 or max_linear_step>.5+1e-7:
                    raise ValueError('종속/폐루프 관절의 실제 표본 간격이 2° 또는 0.5 mm보다 큽니다. 요청 범위를 나누어 검사하세요.')
            previous_coordinates=coordinates
            if any(a.geometry!=p.geometry or a.features!=p.features or a.source_part_id!=p.source_part_id for a,p in zip(base.parts,current.parts)) or any(getattr(base,k)!=getattr(current,k) for k in ('assets','sketches','parameters','dimension_bindings','configurations')):
                raise ValueError('구동 중 지역 형상 입력이 달라졌습니다. 강체 메시 재생을 중단합니다.')
            budget.phase('sample_collisions')
            if index==0:hits=start_hits
            else:
                hits,checked,reused=_sample_collision_hits(current,shapes,base,start_hits,guard,baseline_bounds,baseline_solids,budget.checkpoint)
                pair_checks+=checked;static_pairs_reused+=reused
            physical=physical_collisions(current,hits)
            if physical:raise ValueError(f'재생 구간 {fraction:.3f}에서 체적 간섭이 발견되었습니다.\n'+describe(current,physical))
            budget.phase('frame_matrices');matrices={}
            for a,p in zip(base.parts,current.parts):
                if p.transform==a.transform:continue
                delta=pose_matrix(p.transform)@np.linalg.inv(initial[p.id])
                if not np.allclose(delta,np.eye(4),atol=1e-8,rtol=0):moving.add(p.id);matrices[p.id]=delta.tolist()
            frames.append(dict(fraction=fraction,joint_degrees=values,matrices=matrices))
            budget.checkpoint()
        if not moving:raise ValueError('실제로 움직이는 부품이 없습니다.')
        budget.phase('checked_preview');budget.checkpoint();result=_preview_same_checked_pose(base,base_shapes,normalized,start_hits,budget.checkpoint);budget.checkpoint()
        metrics=budget.finish()
        return dict(base_digest=design_digest(normalized),preview=result,frames=frames,moving_ids=sorted(moving),drives=drives,
                    samples=len(frames),step_degrees=max_angular_step,driver_step_degrees=distance/steps,max_linear_step_mm=max_linear_step,
                    pair_checks=pair_checks,static_pairs_reused=static_pairs_reused,static_pair_reuse='exact_same_pose_and_local_geometry_after_full_baseline_check',reference_only=reference_only,
                    can_loop=not frames[-1]['matrices'],scope='exact_current_and_sampled_poses_only_not_continuous_sweep',
                    actual_rpm=None,electrical_power_verified=False,hardware_motion_allowed=False,budget_seconds=seconds,
                    inspection_metrics=metrics)


def playback_frame_index(elapsed_s,rpm,drive_distance,frame_count,mode='loop'):
    for value in (elapsed_s,rpm,drive_distance):
        if type(value) not in (int,float) or not isfinite(value):raise ValueError('재생 시간·RPM·각도를 확인하세요.')
    if elapsed_s<0 or not 0<rpm<=30000 or drive_distance<=0 or type(frame_count) is not int or frame_count<2 or mode not in ('loop','bounce','once'):
        raise ValueError('재생 범위가 유효하지 않습니다.')
    progress=elapsed_s*rpm*6/drive_distance
    if mode=='loop':fraction=progress%1
    elif mode=='bounce':fraction=1-abs(1-(progress%2))
    else:fraction=min(1.,progress)
    return min(frame_count-1,int(fraction*(frame_count-1)+1e-9))
