"""Rigid placement of a selection, preserving its internal assembly frames."""
from copy import deepcopy
import warnings

import numpy as np
from scipy.spatial.transform import Rotation

from .constraints import transform_matrix
from .models import Design, Transform


def placement_selection(raw, identifiers, connected=True):
    parts={p['id']:p for p in raw.get('parts',[])}
    chosen=set(identifiers)
    if not chosen or not chosen<=parts.keys():raise ValueError('이동할 실제 부품을 먼저 선택하세요.')
    edges=[(m['parent'],m['child']) for m in [*raw.get('mates',[]),*raw.get('loops',[])]]
    # Boolean operands are in world coordinates. Moving just one operand could
    # silently change a cut, so treat that dependency as a placement connection.
    edges.extend((p['id'],f['tool_part_id']) for p in parts.values() for f in p.get('features',[]) if f.get('tool_part_id'))
    while True:
        crossing=[(a,b) for a,b in edges if (a in chosen)!=(b in chosen)]
        if not crossing:break
        if not connected:raise ValueError('선택 밖의 부품과 조립 구속 또는 몸체 연산으로 연결되어 있습니다. 연결 부품 포함을 켜거나 필요한 부품을 함께 선택하세요.')
        before=len(chosen)
        chosen.update(v for edge in crossing for v in edge)
        if not chosen<=parts.keys():raise ValueError('연결된 부품을 찾을 수 없습니다.')
        if len(chosen)==before:break
    return [identifier for identifier in parts if identifier in chosen]


def move_selection(raw, identifiers, translation=(0,0,0), rotation=(0,0,0), pivot=(0,0,0), *, connected=True, allow_grounded=False):
    vectors=[np.asarray(v,dtype=float) for v in (translation,rotation,pivot)]
    if any(v.shape!=(3,) or not np.isfinite(v).all() for v in vectors):raise ValueError('이동·회전·중심에는 유한한 X/Y/Z 값 3개가 필요합니다.')
    translation,rotation,pivot=vectors
    if np.any(np.abs(translation)>5000) or np.any(np.abs(pivot)>5000) or np.any(np.abs(rotation)>360):
        raise ValueError('이동과 중심은 ±5,000 mm, 회전은 ±360° 범위여야 합니다.')
    data=Design.model_validate(deepcopy(raw)).model_dump();ids=placement_selection(data,identifiers,connected)
    if not np.any(translation) and not np.any(rotation):return data,ids
    chosen=set(ids);parts={p['id']:p for p in data['parts']}
    grounded=[parts[i]['name'] for i in ids if parts[i]['fixed']]
    if grounded and not allow_grounded:
        raise ValueError('고정된 부품이 포함되어 있습니다: '+', '.join(grounded)+'. 고정 부품 배치 변경을 켜면 이동 후에도 고정 상태를 유지합니다.')
    children={m['child'] for m in data['mates']}
    roots=chosen-children
    for binding in data.get('dimension_bindings',[]):
        path=binding['path']
        if len(path)>=4 and path[0]=='parts' and path[1] in roots and path[2]=='transform':
            raise ValueError('위치가 변수로 구속된 부품입니다. 변수 값을 편집하거나 위치의 변수 연결을 해제하세요: '+parts[path[1]]['name'])
    delta=Rotation.from_euler('xyz',rotation,degrees=True).as_matrix()
    for identifier in roots:
        old=Transform.model_validate(parts[identifier]['transform'])
        pos=delta@(np.array([old.x,old.y,old.z])-pivot)+pivot+translation
        matrix=delta@transform_matrix(old)
        # At gimbal lock Euler coordinates are nonunique; SciPy chooses a valid
        # equivalent rotation. Verify matrices, not the spelling of the angles.
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore',message='Gimbal lock detected.*')
            angles=Rotation.from_matrix(matrix).as_euler('xyz',degrees=True)
        parts[identifier]['transform']=Transform.model_validate(dict(zip(('x','y','z','rx','ry','rz'),map(float,[*pos,*angles])))).model_dump()
    for loop in data.get('loops',[]):
        if {loop['parent'],loop['child']}<=chosen:
            # Existing closure offsets are world vectors; rotate them with the
            # complete mechanism without changing their length or meaning.
            loop['offset']=(delta@np.array(loop['offset'])).tolist()
    moved=Design.model_validate(data)
    original={p.id:p for p in Design.model_validate(raw).parts}
    for part in moved.parts:
        if part.id not in chosen:continue
        old=original[part.id].transform;new=part.transform
        expected=delta@(np.array([old.x,old.y,old.z])-pivot)+pivot+translation
        if not np.allclose([new.x,new.y,new.z],expected,atol=1e-5,rtol=0) or not np.allclose(transform_matrix(new),delta@transform_matrix(old),atol=1e-6,rtol=0):
            raise ValueError('조립 구속이 요청한 배치와 충돌합니다. 관절·폐루프의 구속을 확인하세요.')
    return moved.model_dump(),ids
