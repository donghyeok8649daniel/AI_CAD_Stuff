"""Small transient display value helpers; no geometry or document state."""
import math


def checked_opacity(value):
    if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or not .1<=value<=1:
        raise ValueError('불투명도는 10~100% 사이의 유한한 값이어야 합니다.')
    return float(value)


def surviving_opacities(values, identifiers):
    ids=set(identifiers)
    return {key:checked_opacity(value) for key,value in values.items() if key in ids}
