"""Display-only sampling policy. Exact BReps, references and exports are unchanged."""
MODES=('auto','fine','fast')
_mode='auto'


def load(path):
    from pathlib import Path
    import json
    try:
        path=Path(path)
        if path.stat().st_size>4096:return 'auto'
        data=json.loads(path.read_text(encoding='utf-8'))
        return data['quality'] if isinstance(data,dict) and data.get('schema')=='display-quality-1' and data.get('quality') in MODES else 'auto'
    except (OSError,ValueError,KeyError):return 'auto'


def save(path,value):
    import json
    from .native.document import _atomic_project_write
    if value not in MODES:raise ValueError('Unknown display quality')
    _atomic_project_write(path,json.dumps(dict(schema='display-quality-1',quality=value)).encode('utf-8'))


def mode():return _mode


def set_mode(value):
    if value not in MODES:raise ValueError('Unknown display quality')
    global _mode
    _mode=value


def tolerances(policy,part_count,kind):
    if policy=='fast':return (.08,.24)
    if policy=='auto' and part_count>100 and kind=='sweep':return (.08,.24)
    return (.04,.12)
