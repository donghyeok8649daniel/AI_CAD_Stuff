"""Parameter configurations preserve shared CAD definitions and feature history."""
from copy import deepcopy
from .models import Design


def apply_configuration(raw,name):
    raw=deepcopy(raw)
    if name not in raw.get('configurations',{}):raise ValueError('설계 구성을 찾을 수 없습니다.')
    raw['parameters'].update(raw['configurations'][name])
    return Design.model_validate(raw)
