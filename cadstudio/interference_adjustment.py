"""Explicit pair resolution and conservative world-box placement suggestions.

Suggestions are candidates, never applied here. Exact preview/commit checks
remain authoritative. No geometry/clearance, mates, groups or fixed flags change.
"""
import math
from .placement import placement_selection
from .interference import VOLUME_EPS,pair


def selected_overlap(collisions,identifiers):
    ids=tuple(identifiers)
    if len(ids)!=2 or len(set(ids))!=2:raise ValueError('서로 다른 간섭 부품 두 개가 필요합니다.')
    target=tuple(sorted(ids));volume=0.
    for hit in collisions:
        if pair(hit)!=target:continue
        value=hit['volume']
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
            raise ValueError('선택 간섭 체적을 확인할 수 없습니다.')
        volume+=value
    return volume


def require_selected_clear(collisions,identifiers):
    volume=selected_overlap(collisions,identifiers)
    if volume>VOLUME_EPS:raise ValueError(f'선택한 부품 사이 간섭 {volume:.6g} mm³가 남아 있습니다. 미리보기에서 이동·치수를 더 조정하세요.')
    return volume


def separation_suggestion(raw,bounds,moving,target,axis,direction,clearance=.2,*,connected=True):
    if moving==target:raise ValueError('서로 다른 부품을 선택하세요.')
    if axis not in ('x','y','z') or type(direction) is not int or direction not in (-1,1):
        raise ValueError('X/Y/Z의 양 또는 음 방향을 선택하세요.')
    if isinstance(clearance,bool) or not isinstance(clearance,(int,float)) or not math.isfinite(clearance) or not 0<=clearance<=100:
        raise ValueError('분리 여유는 0~100 mm의 유한한 값이어야 합니다.')
    moved=placement_selection(raw,[moving],connected)
    if target in moved:
        raise ValueError('두 부품이 같은 조립·몸체 연산으로 연결돼 함께 움직입니다. 관절 구동 또는 치수/구속 배치를 조정하세요. 연결을 자동으로 해제하지 않습니다.')
    def box(identifier):
        value=bounds.get(identifier)
        if not isinstance(value,dict):raise ValueError('정확한 형상 경계가 없습니다. 간섭을 다시 검사하세요.')
        lo,hi=value.get('min'),value.get('max')
        if not isinstance(lo,(list,tuple)) or not isinstance(hi,(list,tuple)) or len(lo)!=3 or len(hi)!=3:
            raise ValueError('부품 경계를 확인할 수 없습니다.')
        if any(isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) for n in [*lo,*hi]) or any(a>b for a,b in zip(lo,hi)):
            raise ValueError('부품 경계가 유효하지 않습니다.')
        return lo,hi
    other_lo,other_hi=box(target);boxes=[box(identifier) for identifier in moved]
    k='xyz'.index(axis)
    low=min(lo[k] for lo,hi in boxes);high=max(hi[k] for lo,hi in boxes)
    delta=max(0.,other_hi[k]+clearance-low) if direction==1 else min(0.,other_lo[k]-clearance-high)
    if abs(delta)>5000:raise ValueError('제안 이동이 5,000 mm를 넘습니다. 배치나 치수를 직접 조정하세요.')
    translation=[0.,0.,0.];translation[k]=delta
    return {'translation':translation,'moving_ids':moved,'axis':axis,'direction':direction,'clearance_mm':clearance,
            'basis':'world_axis_aligned_exact_bounds','exact_clearance_verified':False}
