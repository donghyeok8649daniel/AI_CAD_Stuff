"""Conservative current-pose shaft/bore checks on actual BRep cylinders.

Results are transient and regenerated with the preview, never persisted as a
certification. Kinematic constraints alone never turn a joint green.
"""
import numpy as np
from .constraints import anchors,transform_matrix
from .threads import cylinder_records

COLORS={'ready':(.35,.88,.56),'unverified':(1,.7,.25),'blocked':(.98,.32,.27),'rigid':(.58,.66,.75)}
TITLES={'ready':'지지 형상 확인 · 현재 자세','unverified':'구조 미확인','blocked':'간섭 / 구조 오류','rigid':'강체 연결'}


def joint_readiness(design,shapes,collisions):
    if not design.mates:return {}
    parts={p.id:p for p in design.parts};shape_by_id=dict(zip(parts,shapes));frames={f.mate_id:f for f in design.joint_frames}
    rigid={k:set() for k in parts};cache={};results={}
    for m in design.mates:
        if m.kind=='rigid':rigid[m.parent].add(m.child);rigid[m.child].add(m.parent)
    def cluster(start):
        found=set();pending=[start]
        while pending:
            key=pending.pop()
            if key in found:continue
            found.add(key);pending.extend(rigid[key]-found)
        return found
    def cylinders(ids):
        for key in sorted(ids):
            if key not in cache:cache[key]=cylinder_records(shape_by_id[key])
            for c in cache[key]:yield key,c
    for m in design.mates:
        a,b=cluster(m.parent),cluster(m.child);state='unverified';details=[];matches=[]
        if m.kind=='rigid':results[m.id]=dict(state='rigid',title=TITLES['rigid'],details=['고정 연결이며 회전 지지 구조 검사는 하지 않습니다.']);continue
        hits=[c for c in collisions if (c['a'] in a|b or c['b'] in a|b)]
        if hits:state='blocked';details.append('연결 부품에 현재 체적 간섭이 있습니다: '+', '.join(c['a']+' / '+c['b'] for c in hits[:4]))
        elif a&b:state='blocked';details.append('두 부품이 강체 경로로도 연결되어 자유 회전할 수 없습니다.')
        elif m.kind not in ('revolute','cylindrical'):details.append('이 관절 종류의 물리적 지지 형상은 자동 판정하지 않습니다.')
        else:
            parent=parts[m.parent];r=transform_matrix(parent.transform);frame=frames.get(m.id)
            if frame:
                f=frame.parent;basis=r@np.column_stack((f.x_direction,np.cross(f.normal,f.x_direction),f.normal));origin=np.asarray(f.origin)
            else:basis=r;origin=np.asarray(anchors(parent.geometry)[m.parent_anchor])
            axis=basis[:,2];center=np.array([parent.transform.x,parent.transform.y,parent.transform.z])+r@origin+basis@np.array([m.x,m.y,m.z])
            def on_axis(c):return abs(abs(np.dot(axis,c.frame.normal))-1)<1e-6 and np.linalg.norm(np.cross(np.asarray(c.frame.origin)-center,axis))<1e-4
            ca=[(k,c) for k,c in cylinders(a) if on_axis(c)];cb=[(k,c) for k,c in cylinders(b) if on_axis(c)]
            for ka,aa in ca:
                for kb,bb in cb:
                    if aa.internal==bb.internal:continue
                    hole,shaft=(aa,bb) if aa.internal else (bb,aa)
                    gap=hole.diameter-shaft.diameter
                    def interval(c):
                        z=np.dot(np.asarray(c.frame.origin)-center,axis);end=z+np.dot(c.frame.normal,axis)*c.length
                        return sorted((z,end))
                    u,v=interval(aa),interval(bb);overlap=min(u[1],v[1])-max(u[0],v[0])
                    # Reject merely coaxial distant surfaces or an enormous
                    # opening that cannot plausibly locate this shaft.
                    if 1e-5<gap<=min(2,shaft.diameter*.15) and overlap>.1:
                        matches.append(dict(parts=[ka,kb],clearance=gap,overlap=overlap))
            if matches:
                state='ready';best=min(matches,key=lambda v:v['clearance'])
                details.append(f"동심 축 / 구멍 · 지름 여유 {best['clearance']:.3f} mm · 지지 길이 {best['overlap']:.3f} mm")
            else:details.append('관절 축 위에 양의 지름 여유와 지지 길이를 가진 축 / 구멍 쌍을 찾지 못했습니다. 동심 정렬과 실제 부품을 확인하세요.')
        details.append('현재 자세 검사입니다. 전 구동 범위, 축 이탈 방지, 조립 경로와 하중 정격은 별도 확인이 필요합니다.')
        results[m.id]=dict(state=state,title=TITLES[state],details=details,matches=matches)
    return results
