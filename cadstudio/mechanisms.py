"""Closed-chain position constraints and reproducible four-bar mechanism."""
import numpy as np
from scipy.optimize import least_squares
from .constraints import anchors,transform_matrix,solve_assembly


def solve_closures(design):
    parts={p.id:p for p in design.parts};mates={m.id:m for m in design.mates}
    identifiers=list(dict.fromkeys(j for loop in design.loops for j in loop.passive_joints))
    if len({loop.id for loop in design.loops})!=len(design.loops):raise ValueError('폐루프 구속 ID가 중복되었습니다.')
    if any(j not in mates or mates[j].kind not in ('revolute','slider') for j in identifiers):
        raise ValueError('수동 관절은 실제 회전 또는 슬라이더 조인트를 선택하세요.')
    for loop in design.loops:
        if loop.parent not in parts or loop.child not in parts or loop.parent==loop.child:raise ValueError('폐루프에는 서로 다른 실제 부품이 필요합니다.')
        for identifier,key in ((loop.parent,loop.parent_anchor),(loop.child,loop.child_anchor)):
            if key not in anchors(parts[identifier].geometry):raise ValueError('폐루프의 기준점이 없습니다.')
        if loop.planar:
            normals=[transform_matrix(parts[p].transform)[:,2] for p in (loop.parent,loop.child)]
            if abs(np.dot(*normals))<1-1e-8:
                raise ValueError('평면 폐루프의 두 부품은 서로 평행한 스케치 평면을 가져야 합니다.')
    attributes=['rz' if mates[j].kind=='revolute' else 'z' for j in identifiers]
    bounds=[mates[j].limits.get(key,[-360,360] if key=='rz' else [-5000,5000]) for j,key in zip(identifiers,attributes)]
    if any(high-low<1e-9 for low,high in bounds):raise ValueError('폐루프 수동 관절의 운동 한계에는 움직일 수 있는 범위가 필요합니다.')
    lower=np.array([b[0] for b in bounds]);upper=np.array([b[1] for b in bounds])
    initial=np.clip([getattr(mates[j],key) for j,key in zip(identifiers,attributes)],lower,upper)
    def point(identifier,anchor):
        p=parts[identifier]
        return transform_matrix(p.transform)@np.array(anchors(p.geometry)[anchor])+[p.transform.x,p.transform.y,p.transform.z]
    def residual(values):
        for identifier,key,value in zip(identifiers,attributes,values):setattr(mates[identifier],key,float(value))
        solve_assembly(design,False)
        rows=[]
        for loop in design.loops:
            error=point(loop.child,loop.child_anchor)-point(loop.parent,loop.parent_anchor)-loop.offset
            # A planar closure is measured in its reference body's plane. This
            # stays invariant when a whole mechanism is tilted in world space.
            rows.extend((transform_matrix(parts[loop.parent].transform).T@error)[:2] if loop.planar else error)
        return np.array(rows)
    result=least_squares(residual,initial,bounds=(lower,upper),xtol=1e-11,ftol=1e-11,gtol=1e-11,max_nfev=250)
    error=float(np.max(np.abs(residual(result.x))))
    if not result.success or error>1e-4:
        residual(initial)
        raise ValueError(f'폐루프를 닫을 수 없습니다. 링크 길이·구동 각도·수동 관절을 확인하세요. 오차 {error:.4g} mm')
    rank=int(np.linalg.matrix_rank(result.jac,tol=1e-7))
    return {'loops':len(design.loops),'closure_error_mm':error,'closure_rank':rank,'passive_joints':identifiers}


def four_bar():
    from .models import Design,Part
    parts=[Part(id='ground',name='고정 베이스',fixed=True,geometry=dict(kind='plate',length=128,width=24,thickness=6,hole_count=2,hole_diameter=6,hole_pitch_x=100)),
           *[Part(id=identifier,name=name,geometry=dict(kind='link',length=distance+16,width=16,thickness=5,hole_spacing=distance,hole_diameter=6),color=color) for identifier,name,distance,color in [('crank','입력 링크',40,'#68c5b3'),('coupler','커플러',90,'#e6b45f'),('rocker','출력 링크',70,'#7ba9dc')]]]
    return Design(name='4절 링크 폐루프',mode='robot',parts=parts,mates=[
        dict(id='input',kind='revolute',parent='ground',child='crank',parent_anchor='hole_1_top',child_anchor='hole_1_bottom',z=1,rz=35),
        dict(id='passive-a',kind='revolute',parent='crank',child='coupler',parent_anchor='hole_2_top',child_anchor='hole_1_bottom',z=1,rz=10),
        dict(id='passive-b',kind='revolute',parent='coupler',child='rocker',parent_anchor='hole_2_top',child_anchor='hole_2_top',z=1,rz=70)],
        loops=[dict(id='closure',parent='ground',child='rocker',parent_anchor='hole_2_top',child_anchor='hole_1_bottom',passive_joints=['passive-a','passive-b'])])
