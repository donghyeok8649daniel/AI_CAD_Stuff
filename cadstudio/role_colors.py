"""Application defaults only. Existing CAD colors/classifications are untouched."""
import json
import os
from pathlib import Path
import re
from uuid import uuid4
from .part_roles import COLORS

CONFIGURABLE_ROLES=('electrical','structure','transmission')
ROLE_TITLES={'electrical':'전장','structure':'구조','transmission':'동력전달'}


def normalize_colors(values=None):
    if values is not None and not isinstance(values,dict):raise ValueError('Role colors must be an object')
    result=dict(COLORS)
    for role,color in (values or {}).items():
        if role not in CONFIGURABLE_ROLES:raise ValueError('Unknown configurable role')
        if not isinstance(color,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',color):raise ValueError('Role colors require #RRGGBB')
        result[role]=color.upper()
    return result


def load_colors(path):
    return load_settings(path)[0]


def load_settings(path):
    path=Path(path)
    if not path.exists():return normalize_colors(),False
    raw=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(raw,dict) or raw.get('schema')!='cadstudio-role-colors-1' or not isinstance(raw.get('colors'),dict):raise ValueError('Invalid role color settings')
    enabled=raw.get('view_enabled',False)
    if not isinstance(enabled,bool):raise ValueError('Invalid role view setting')
    return normalize_colors(raw['colors']),enabled


def save_colors(path,values,*,view_enabled=False):
    if not isinstance(view_enabled,bool):raise ValueError('Invalid role view setting')
    colors=normalize_colors(values);path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    raw=dict(schema='cadstudio-role-colors-1',colors={role:colors[role] for role in CONFIGURABLE_ROLES},view_enabled=view_enabled)
    temp=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
    try:
        with temp.open('x',encoding='utf-8') as f:
            json.dump(raw,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        temp.unlink(missing_ok=True)
    return colors


def request_colors(colors):
    return {role:colors[role] for role in CONFIGURABLE_ROLES}
