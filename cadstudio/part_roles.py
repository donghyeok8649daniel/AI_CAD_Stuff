"""Semantic display defaults, never a material assignment or collision exemption."""
COLORS={'structure':'#F2F2F2','electrical':'#FFD400','transmission':'#25A55F','specimen':'#AEB6BF'}
LABELS={'unspecified':'미지정 · 기존 색상','structure':'구조 / 보호 · 흰색','electrical':'전장 / 센서 · 노란색',
        'transmission':'구동 / 하중 전달 · 초록색','specimen':'시편 · 회색'}


def new_part_style(kind,role=None,color=None):
    role=role or ('specimen' if kind in ('round_specimen','flat_specimen','wafer') else 'transmission' if kind in ('spur_gear','link') else 'structure')
    if role not in LABELS:raise ValueError('알 수 없는 부품 역할입니다.')
    return dict(role=role,color=color or COLORS.get(role,'#70aebf'))


def assign_role(part,role,use_color=True):
    if role not in LABELS:raise ValueError('알 수 없는 부품 역할입니다.')
    part['role']=role
    if use_color and role in COLORS:part['color']=COLORS[role]
