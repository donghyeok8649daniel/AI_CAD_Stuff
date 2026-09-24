"""Explicit joint axes, bounded motion, and acyclic ratio links."""
import math

JOINT_AXES={'rigid':(), 'revolute':('rz',),'slider':('z',),'cylindrical':('rz','z'),'pin_slot':('rz','x'),'planar':('x','y','rz'),'ball':('rx','ry','rz')}
JOINT_TITLES={'rigid':'강체','revolute':'회전','slider':'슬라이더','cylindrical':'원통','pin_slot':'핀 슬롯','planar':'평면','ball':'볼'}


def motion_controls(raw, identifier):
    mate=next((m for m in raw.get('mates',[]) if m['id']==identifier),None)
    if mate is None:raise ValueError('관절 ID가 없습니다: '+str(identifier))
    passive=any(identifier in loop['passive_joints'] for loop in raw.get('loops',[]))
    linked={link['driven_axis']:link for link in raw.get('motion_links',[]) if link['driven']==identifier}
    axes={}
    for key in JOINT_AXES[mate['kind']]:
        control=dict(value=mate.get(key,0),unit='deg' if key.startswith('r') else 'mm',
                     limits=mate.get('limits',{}).get(key,[-360,360] if key.startswith('r') else [-5000,5000]))
        if passive:control['driven_by']='loop closure'
        elif key in linked:
            link=linked[key];control['driven_by']=f'{link["driver"]}.{link["driver_axis"]}'
            control['ratio']=link['ratio'];control['offset']=link['offset']
        axes[key]=control
    return axes


def set_joint_motion(raw, identifier, values):
    """Patch independent DOFs only; callers validate the resulting whole design."""
    controls=motion_controls(raw,identifier)
    if not isinstance(values,dict) or not values or set(values)-set(controls):
        raise ValueError('관절의 운동 축만 수정할 수 있습니다: '+(', '.join(controls) or '없음 · 강체 연결'))
    for key,value in values.items():
        if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('관절 값은 유한한 숫자여야 합니다.')
        control=controls[key]
        if 'driven_by' in control:
            raise ValueError(f'{identifier}.{key}는 {control["driven_by"]}가 계산합니다. 구동 관절을 수정하세요.')
        lo,hi=control['limits']
        if not lo<=value<=hi:raise ValueError(f'관절 {identifier}.{key} 운동 한계 {lo:g}~{hi:g} {control["unit"]}를 넘었습니다. 기존 한계를 유지하세요.')
    next(m for m in raw['mates'] if m['id']==identifier).update(values)


def prune_joint_references(raw):
    """Delete only references whose joints were explicitly removed by the user."""
    identifiers={m['id'] for m in raw.get('mates',[])}
    raw['joint_frames']=[f for f in raw.get('joint_frames',[]) if f['mate_id'] in identifiers]
    raw['loops']=[loop for loop in raw.get('loops',[]) if set(loop['passive_joints'])<=identifiers]
    if 'motion_links' in raw:raw['motion_links']=[link for link in raw['motion_links'] if link['driver'] in identifiers and link['driven'] in identifiers]
    return raw


def resolve_motion(design):
    mates={m.id:m for m in design.mates};links={};seen=set()
    for link in design.motion_links:
        if link.id in seen:raise ValueError('모션 연결 ID가 중복됩니다.')
        seen.add(link.id)
        for identifier,axis in [(link.driver,link.driver_axis),(link.driven,link.driven_axis)]:
            if identifier not in mates or axis not in JOINT_AXES[mates[identifier].kind]:raise ValueError('모션 연결은 존재하는 관절의 운동 축을 선택해야 합니다.')
        key=(link.driven,link.driven_axis)
        if key in links:raise ValueError('한 관절 축을 두 모션 연결로 구동할 수 없습니다.')
        if any(link.driven in loop.passive_joints for loop in design.loops):raise ValueError('폐루프 수동 관절을 모션 연결로 중복 구동할 수 없습니다.')
        links[key]=link
    done=set();visiting=set()
    def resolve(key):
        if key in done:return
        if key in visiting:raise ValueError('모션 연결이 순환합니다.')
        visiting.add(key)
        if key in links:
            link=links[key];resolve((link.driver,link.driver_axis));value=getattr(mates[link.driver],link.driver_axis)*link.ratio+link.offset
            limit=360 if link.driven_axis.startswith('r') else 5000
            if not -limit<=value<=limit:raise ValueError('모션 연결 결과가 좌표/각도 범위를 넘습니다.')
            setattr(mates[key[0]],key[1],value)
        visiting.remove(key);done.add(key)
    for key in links:resolve(key)
    for mate in design.mates:
        for axis,bounds in mate.limits.items():
            if not bounds[0]-1e-7<=getattr(mate,axis)<=bounds[1]+1e-7:raise ValueError(f'관절 {mate.id} {axis.upper()} 운동 한계 {bounds[0]:g}~{bounds[1]:g}를 넘었습니다.')
    return len(links)
