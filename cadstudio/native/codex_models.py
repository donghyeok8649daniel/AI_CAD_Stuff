"""Exact server-advertised model settings, shared by UI and request workers."""
from __future__ import annotations

import re
import threading

IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}')
EFFORT_LABELS = {'none': 'None', 'minimal': 'Minimal', 'low': 'Low',
    'medium': 'Medium', 'high': 'High', 'xhigh': 'Extra high', 'max': 'Max', 'ultra': 'Ultra'}


def effort_label(value):
    """Unknown future values remain exact; Max and Ultra are never aliases."""
    return EFFORT_LABELS.get(value, value)


def normalize_model(raw):
    if not isinstance(raw, dict): return None
    name = raw.get('model', '')
    if not isinstance(name, str) or not IDENTIFIER.fullmatch(name): return None
    efforts = []
    for item in raw.get('supportedReasoningEfforts') or []:
        value = item.get('reasoningEffort') if isinstance(item, dict) else None
        if isinstance(value, str) and value.strip() and len(value) <= 120 and value.isprintable() and value not in efforts:
            efforts.append(value)
    default = raw.get('defaultReasoningEffort')
    return dict(model=name, name=raw.get('displayName') or name,
        default=bool(raw.get('isDefault')), efforts=efforts,
        default_effort=default if default in efforts else None,
        input_modalities=[v for v in raw.get('inputModalities') or ['text', 'image'] if v in ('text', 'image', 'audio')])


def effort_options(model):
    return [(effort_label(value), value) for value in model.get('efforts', [])]


def validate_selection(catalog, model, effort):
    entry = next((item for item in catalog if item.get('model') == model), None)
    if entry is None:
        raise ValueError('선택한 모델을 현재 Codex 계정에서 찾을 수 없습니다. Codex 연결에서 모델 목록을 새로 찾으세요.')
    if effort not in entry.get('efforts', []):
        raise ValueError('선택한 모델은 이 추론 강도를 지원하지 않습니다. Codex 연결에서 모델과 추론 강도를 다시 선택하세요.')
    return entry


class CodexRuntimeSettings:
    """A GUI can update the next phase without mutating a streaming request.

    Each content phase captures one atomic pair. Retries keep that pair and
    input; a later phase samples the newest pair. This does not start inference.
    """
    def __init__(self, model, effort='medium'):
        self._lock = threading.Lock()
        self._model = model; self._effort = effort

    def update(self, *, model=None, effort=None):
        with self._lock:
            if model is not None: self._model = model
            if effort is not None: self._effort = effort

    def snapshot(self):
        with self._lock: return self._model, self._effort
