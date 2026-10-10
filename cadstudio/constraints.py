"""Bounded numerical sketch constraints and deterministic acyclic assembly mates."""
from __future__ import annotations
import math
import numpy as np


def solve_sketch(points, constraints):
    original = np.array([[p.x, p.y] for p in points], dtype=float).reshape(-1)
    count = len(points)
    for c in constraints:
        if c.a >= count or c.b >= count:
            raise ValueError("스케치 구속이 존재하지 않는 점을 참조합니다.")
        if c.kind != "fixed" and c.a == c.b:
            raise ValueError("구속의 두 점은 서로 달라야 합니다.")
        if c.kind == "distance" and c.value < .01:
            raise ValueError("거리 구속은 0.01 mm 이상이어야 합니다.")

    def residual(values):
        pts = values.reshape((-1, 2)); result = []
        for c in constraints:
            a, b = pts[c.a], pts[c.b]
            if c.kind == "fixed": result.extend(a-np.array([c.x,c.y]))
            elif c.kind == "horizontal": result.append(b[1]-a[1])
            elif c.kind == "vertical": result.append(b[0]-a[0])
            elif c.kind == "distance": result.append(np.linalg.norm(b-a)-c.value)
            elif c.kind == "coincident": result.extend(b-a)
            elif c.kind == "angle":
                angle = math.radians(c.value); direction = b-a
                result.append(direction[1]*math.cos(angle)-direction[0]*math.sin(angle))
                # Preserve the specified direction, rather than the antiparallel line.
                result.append(min(0, direction[0]*math.cos(angle)+direction[1]*math.sin(angle)))
        return np.asarray(result, dtype=float)

    if not constraints:
        return original.reshape((-1,2)).tolist(), {"dof":2*count,"rank":0,"max_error":0,"constraints":0}
    def objective(values):
        return np.concatenate((residual(values), (values-original)*1e-7))
    from scipy.optimize import least_squares
    result = least_squares(objective, original, bounds=(-1000,1000), max_nfev=250, ftol=1e-11, xtol=1e-11, gtol=1e-11)
    errors = residual(result.x)
    maximum = float(np.max(np.abs(errors)))
    if maximum > 1e-4:
        raise ValueError(f"스케치 구속이 충돌하거나 해를 찾지 못했습니다 (잔차 {maximum:.4g} mm). 고정 위치와 치수를 확인하세요.")
    jac = result.jac[:len(errors)]
    rank = int(np.linalg.matrix_rank(jac, tol=1e-6))
    return result.x.reshape((-1,2)).tolist(), {"dof":max(0,2*count-rank),"rank":rank,"max_error":maximum,"constraints":len(constraints)}


def anchors(geometry):
    g=geometry
    top = getattr(g,"height",getattr(g,"thickness",0))
    bottom=0
    if g.kind == "extrusion" and g.direction<0:top,bottom=0,-g.thickness
    if g.kind == "flat_specimen": top,bottom=g.thickness/2,-g.thickness/2
    if g.kind == "round_specimen":
        return {"origin":[0,0,0],"left":[-g.length/2,0,0],"right":[g.length/2,0,0]}
    out={"origin":[0,0,0],"top":[0,0,top],"bottom":[0,0,bottom]}
    holes=[]
    if g.kind == "link": holes=[(-g.hole_spacing/2,0),(g.hole_spacing/2,0)]
    elif g.kind == "plate" and g.hole_count:
        holes=[(x,y) for x in (-g.hole_pitch_x/2,g.hole_pitch_x/2) for y in ([-g.hole_pitch_y/2,g.hole_pitch_y/2] if g.hole_count==4 else [0])]
    elif g.kind == "extrusion": holes=[(h.x,h.y) for h in g.holes] if g.sketch_mode=='polygon' else [(e.center.x,e.center.y) for e in g.entities if e.kind=='circle' and not e.construction]
    for i,(x,y) in enumerate(holes,1):
        out[f"hole_{i}_bottom"]=[x,y,bottom];out[f"hole_{i}_top"]=[x,y,top]
    return out


def _compose_quaternion(p,q):
    px,py,pz,pw=p;qx,qy,qz,qw=q
    cross=(py*qz-pz*qy,pz*qx-px*qz,px*qy-py*qx)
    return (pw*qx+qw*px+cross[0],pw*qy+qw*py+cross[1],
            pw*qz+qw*pz+cross[2],pw*qw-px*qx-py*qy-pz*qz)


def _xyz_matrix(rx,ry,rz):
    """Extrinsic xyz degrees: scalar qz * qy * qx represents Rz @ Ry @ Rx.

    Preserve half-angle composition and matrix arithmetic order used by saved
    histories; direct full-angle products can amplify an ULP near gimbal lock.
    """
    angles=[value*(math.pi/180.) for value in (rx,ry,rz)]
    sx,sy,sz=(math.sin(a/2) for a in angles)
    cx,cy,cz=(math.cos(a/2) for a in angles)
    x,y,z,w=_compose_quaternion((0.,0.,sz,cz),_compose_quaternion((0.,sy,0.,cy),(sx,0.,0.,cx)))
    x2,y2,z2,w2=x*x,y*y,z*z,w*w
    xy,zw,xz,yw,yz,xw=x*y,z*w,x*z,y*w,y*z,x*w
    return np.array([[x2-y2-z2+w2,2*(xy-zw),2*(xz+yw)],
                     [2*(xy+zw),-x2+y2-z2+w2,2*(yz-xw)],
                     [2*(xz-yw),2*(yz+xw),-x2-y2+z2+w2]])


def _xyz_angles(matrix):
    """Canonical xyz degrees, with third angle zero at gimbal lock.

    Frames permit small axis errors. The polar factor preserves the previous
    nearest-rotation interpretation rather than biasing one axis with Gram-Schmidt.
    Scalar arithmetic also avoids a native rotation object for every history mate.
    """
    rows=[[float(value) for value in row] for row in matrix]
    if len(rows)!=3 or any(len(row)!=3 for row in rows) or not all(math.isfinite(v) for row in rows for v in row):
        raise ValueError('조립 회전 행렬은 유한한 3 × 3 행렬이어야 합니다.')

    def cofactors(m):
        (a,b,c),(d,e,f),(g,h,i)=m
        co=[[e*i-f*h,f*g-d*i,d*h-e*g],
            [c*h-b*i,a*i-c*g,b*g-a*h],
            [b*f-c*e,c*d-a*f,a*e-b*d]]
        return co,a*co[0][0]+b*co[0][1]+c*co[0][2]

    _,det=cofactors(rows)
    if det<=0:raise ValueError('조립 회전 기준은 오른손 좌표계여야 합니다.')
    gram=[[sum(rows[i][k]*rows[j][k] for k in range(3)) for j in range(3)] for i in range(3)]
    if any(abs(gram[i][j]-(i==j))>1e-12+(1e-5 if i==j else 0) for i in range(3) for j in range(3)):
        for _ in range(20):
            co,det=cofactors(rows)
            updated=[[.5*(rows[i][j]+co[i][j]/det) for j in range(3)] for i in range(3)]
            change=max(abs(updated[i][j]-rows[i][j]) for i in range(3) for j in range(3))
            rows=updated
            if change<=1e-15:break
        else:raise ValueError('조립 회전 기준의 직교화를 완료하지 못했습니다.')

    # Keep this association explicit: one trace ULP is amplified near gimbal lock.
    trace=rows[0][0]+(rows[1][1]+rows[2][2])
    choice=max(range(4),key=lambda i:rows[i][i] if i<3 else trace)
    if choice==3:
        q=[rows[2][1]-rows[1][2],rows[0][2]-rows[2][0],rows[1][0]-rows[0][1],1+trace]
    else:
        i=choice;j=(i+1)%3;k=(j+1)%3
        q=[0.,0.,0.,0.]
        q[i]=1-trace+2*rows[i][i]
        q[j]=rows[j][i]+rows[i][j]
        q[k]=rows[k][i]+rows[i][k]
        q[3]=rows[k][j]-rows[j][k]
    norm=math.sqrt(sum(value*value for value in q))
    x,y,z,w=(value/norm for value in q)
    a,b,c,d=w-y,x+z,y+w,z-x
    middle=2*math.atan2(math.hypot(c,d),math.hypot(a,b))
    half_sum,half_difference=math.atan2(b,a),math.atan2(d,c)
    if middle<=1e-7:
        first,third=2*half_sum,0.
    elif math.pi-middle<=1e-7:
        first,third=-2*half_difference,0.
    else:
        first,third=half_sum-half_difference,half_sum+half_difference
    angles=[first,middle-math.pi/2,third]
    for i,angle in enumerate(angles):
        if angle < -math.pi:angles[i]+=2*math.pi
        elif angle > math.pi:angles[i]-=2*math.pi
    return tuple(map(math.degrees,angles))


def transform_matrix(t):
    return _xyz_matrix(t.rx,t.ry,t.rz)


def solve_assembly(design,solve_loops=True):
    from .assembly_motion import resolve_motion,JOINT_AXES
    linked=resolve_motion(design)
    parts={p.id:p for p in design.parts}; driving={}; frames={f.mate_id:f for f in design.joint_frames}
    for mate in design.mates:
        if mate.parent not in parts or mate.child not in parts or mate.parent==mate.child:
            raise ValueError("조립 구속은 서로 다른 실제 부품 두 개를 참조해야 합니다.")
        if mate.child in driving:
            raise ValueError("한 부품에는 하나의 구동 조립 구속만 지정할 수 있습니다.")
        if parts[mate.child].fixed:
            raise ValueError("고정된 부품을 구속으로 이동할 수 없습니다. 먼저 고정을 해제하세요.")
        driving[mate.child]=mate
    completed=set();visiting=set()
    def resolve(identifier):
        if identifier in completed:return
        if identifier in visiting:raise ValueError("조립 구속에 순환 참조가 있습니다. 트리 형태로 연결하세요.")
        visiting.add(identifier)
        if identifier in driving:
            mate=driving[identifier];resolve(mate.parent)
            parent,child=parts[mate.parent],parts[mate.child]
            pa,ca=anchors(parent.geometry),anchors(child.geometry)
            if mate.parent_anchor not in pa or mate.child_anchor not in ca:
                raise ValueError("조립 구속의 기준점이 현재 형상에 없습니다.")
            parent_rotation=transform_matrix(parent.transform)
            relative=_xyz_matrix(mate.rx,mate.ry,mate.rz)
            parent_pos=np.array([parent.transform.x,parent.transform.y,parent.transform.z])
            frame=frames.get(mate.id)
            if frame:
                def basis(f):return np.column_stack([f.x_direction,np.cross(f.normal,f.x_direction),f.normal])
                parent_frame=parent_rotation@basis(frame.parent)
                align=np.diag([1,-1,-1]) if frame.flipped else np.eye(3)
                rotation=parent_frame@relative@align@basis(frame.child).T
                translation=parent_pos+parent_rotation@np.array(frame.parent.origin)+parent_frame@np.array([mate.x,mate.y,mate.z])-rotation@np.array(frame.child.origin)
            else:
                rotation=parent_rotation@relative
                translation=parent_pos+parent_rotation@(np.array(pa[mate.parent_anchor])+np.array([mate.x,mate.y,mate.z]))-rotation@np.array(ca[mate.child_anchor])
            angles=_xyz_angles(rotation)
            values=dict(zip(["x","y","z","rx","ry","rz"],map(float,[*translation,*angles])))
            child.transform=type(child.transform).model_validate(values)
        visiting.remove(identifier);completed.add(identifier)
    for identifier in parts:resolve(identifier)
    report={"mates":len(driving),"grounded":sum(p.fixed for p in parts.values()),"dof":max(0,sum((0 if p.fixed else 6) if p.id not in driving else len(JOINT_AXES[driving[p.id].kind]) for p in parts.values())-linked)}
    if solve_loops and design.loops:
        from .mechanisms import solve_closures
        details=solve_closures(design);report.update(details);report['dof']=max(0,report['dof']-details['closure_rank'])
    return report
