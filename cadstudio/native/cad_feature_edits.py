"""Edit existing feature dimensions without replacing topology or relationships."""
import math

from ..parameters import numeric_node


COMMON = {'name', 'suppressed'}
SKETCH = {'depth', 'reverse_depth', 'symmetric', 'taper', 'thin_wall', 'through_all',
          'diameter', 'hole_finish', 'head_diameter', 'head_depth', 'head_angle'}
THREAD = {'diameter', 'pitch', 'length', 'offset', 'clearance', 'handedness', 'reverse'}
SOLID = {'shell': {'size'}, 'draft': {'angle'}, 'boolean': set(),
         'split': {'keep_side'}, 'mirror': {'keep_original'},
         'linear_pattern': {'count', 'count_y', 'spacing', 'keep_original'},
         'circular_pattern': {'count', 'angle', 'keep_original'}}
BOOLS = {'suppressed', 'symmetric', 'through_all', 'reverse', 'keep_original'}
TEXT = {'name', 'hole_finish', 'handedness', 'keep_side'}


def fields(feature):
    kind = feature.get('kind', 'sketch')
    return COMMON | (SKETCH if kind == 'sketch' else THREAD if kind == 'thread'
                     else {'size'} if kind in ('fillet', 'chamfer')
                     else SOLID.get(feature.get('operation'), set()))


def schema_fields():
    names = COMMON | SKETCH | THREAD | set().union(*SOLID.values())
    result = {key: {'type': 'boolean' if key in BOOLS else 'string' if key in TEXT
                    else 'integer' if key in ('count', 'count_y') else 'number'} for key in sorted(names)}
    result['spacing'] = dict(type='array', items={'type': 'number'}, minItems=3, maxItems=3)
    for key, values in [('hole_finish', ['plain', 'counterbore', 'countersink']),
                        ('handedness', ['right', 'left']), ('keep_side', ['all', 'positive', 'negative'])]:
        result[key]['enum'] = values
    return dict(feature_id={'type': 'string'}, entity_id={'type': 'string'}, **result)


def summary(feature):
    """Expose real dimensions, but omit potentially huge edge/face reference data."""
    data = feature.model_dump()
    result = {k: data[k] for k in ('id', 'name', 'kind', 'operation', 'support_feature') if k in data}
    result.setdefault('kind', 'sketch')
    result['suppressed'] = feature.suppressed
    result['editable'] = sorted(fields(data))
    result['dimensions'] = {k: data[k] for k in fields(data) - COMMON if k in data}
    if result['kind'] == 'sketch':
        sketch = feature.sketch
        result['dimensions'].update(depth=sketch.thickness, reverse_depth=sketch.reverse_depth,
            symmetric=sketch.symmetric, taper=sketch.taper, thin_wall=sketch.thin_wall,
            through_all=feature.through_all, hole_finish=feature.hole_finish)
        result['circles'] = [dict(id=e.id, diameter=2*e.radius, center=e.center.model_dump())
                             for e in sketch.entities if e.kind == 'circle' and not e.construction]
        if feature.sketch_id: result['profile_source_sketch'] = feature.sketch_id
        if feature.end_face: result['depth_driven_by_end_face'] = True
        if sketch.thickness_expression: result['depth_expression'] = sketch.thickness_expression
        if sketch.entity_constraints: result['profile_constraints'] = [c.model_dump(exclude_defaults=True) for c in sketch.entity_constraints]
    return result


def check_binding(raw, node, key):
    # Paths accept both IDs and indices. Compare resolved nodes, not path strings.
    for binding in raw.get('dimension_bindings', []):
        bound, bound_key = numeric_node(raw, binding['path'])
        if bound is node and bound_key == key:
            raise ValueError(f'변수 식 {binding["expression"]}에 연결된 치수입니다. parameter로 변수를 수정하세요.')


def check_replacement_bindings(raw, node, keys):
    def contains(value, target):
        if value is target: return True
        children = value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()
        return any(contains(child, target) for child in children if isinstance(child, (dict, list)))
    for binding in raw.get('dimension_bindings', []):
        bound, key = numeric_node(raw, binding['path'])
        if (bound is node and key in keys) or any(contains(node[k], bound) for k in keys):
            raise ValueError('변수와 연결된 치수입니다. parameter로 원래 변수를 수정하세요.')


def apply(raw, part, args):
    identifier = args.get('feature_id')
    feature = next((f for f in part['features'] if f['id'] == identifier), None)
    if feature is None:
        raise ValueError('기존 feature_id를 지정하세요. 사용 가능: ' + ', '.join(f['id'] for f in part['features']))
    changes = {k: v for k, v in args.items() if k not in ('feature_id', 'entity_id')}
    if not changes or set(changes) - fields(feature):
        raise ValueError('이 피처에서 편집 가능한 필드: ' + ', '.join(sorted(fields(feature))))
    if 'entity_id' in args and ('diameter' not in changes or feature.get('kind')):
        raise ValueError('entity_id는 스케치 원의 diameter를 편집할 때만 지정하세요.')
    for key, value in changes.items():
        if key in BOOLS:
            valid = type(value) is bool
        elif key in TEXT:
            valid = isinstance(value, str)
        elif key == 'spacing':
            valid = isinstance(value, list) and len(value) == 3 and all(type(v) in (int, float) and math.isfinite(v) for v in value)
        else:
            valid = type(value) in (int, float) and math.isfinite(value)
            if key in ('count', 'count_y'): valid = valid and type(value) is int
        if not valid: raise ValueError(f'{key} 값의 형식 또는 범위를 확인하세요.')
    if feature.get('kind') is None:
        sketch = feature['sketch']
        if set(changes) & {'depth', 'reverse_depth', 'symmetric'} and (feature.get('end_face') or changes.get('through_all', feature.get('through_all', False))):
            raise ValueError('깊이는 끝 면 또는 관통에 의해 결정됩니다. 관통을 끄려면 through_all=false와 depth를 함께 지정하세요. 끝 면 지정 피처는 수동 편집하세요.')
        if 'through_all' in changes and changes['through_all'] and feature['operation'] != 'cut':
            raise ValueError('관통은 절삭 피처에만 적용할 수 있습니다.')
        if any(k in changes for k in ('head_diameter', 'head_depth', 'head_angle')) and changes.get('hole_finish', feature.get('hole_finish', 'plain')) == 'plain':
            raise ValueError('머리 치수를 사용하려면 hole_finish를 counterbore 또는 countersink로 지정하세요.')
        finish = changes.get('hole_finish', feature.get('hole_finish', 'plain'))
        if (('hole_finish' in changes and finish != 'plain' and feature['operation'] != 'cut')
                or ('head_depth' in changes and finish != 'counterbore')
                or ('head_angle' in changes and finish != 'countersink')):
            raise ValueError('구멍 머리 종류와 치수가 맞지 않습니다. head_depth는 카운터보어, head_angle은 카운터싱크에 사용하세요.')
        if 'diameter' in changes:
            if feature.get('sketch_id'):
                raise ValueError('연결된 원본 스케치 '+feature['sketch_id']+'에서 지름을 편집하세요. 프로파일 연결을 보존했습니다.')
            circles = [e for e in sketch['entities'] if e['kind'] == 'circle' and not e.get('construction')
                       and ('entity_id' not in args or e['id'] == args['entity_id'])]
            if len(circles) != 1:
                raise ValueError('지름을 수정할 원 하나의 entity_id를 지정하세요. 여러 원은 각각 편집해야 합니다.')
            circle = circles[0]
            check_binding(raw, circle, 'radius')
            for constraint in sketch.get('entity_constraints', []):
                if circle['id'] not in [constraint.get(k) for k in ('a', 'b', 'c')]: continue
                # A dimensional radius/diameter remains a driving constraint;
                # all other relationships need the full sketch editor.
                if constraint['kind'] == 'fixed' and constraint.get('a_point') == 'center': continue
                if constraint['kind'] not in ('radius', 'diameter') or constraint.get('expression'):
                    raise ValueError('원이 스케치 구속 또는 식으로 제어됩니다. 구속/변수를 편집하세요.')
                check_binding(raw, constraint, 'value')
                constraint['value'] = changes['diameter'] / (2 if constraint['kind'] == 'radius' else 1)
            circle['radius'] = changes['diameter']/2
        for key in ('depth', 'reverse_depth', 'symmetric', 'taper', 'thin_wall'):
            if key not in changes: continue
            actual = 'thickness' if key == 'depth' else key
            if key == 'depth' and sketch.get('thickness_expression'):
                raise ValueError('깊이가 식으로 제어됩니다. parameter로 변수를 편집하세요.')
            check_binding(raw, sketch, actual)
            sketch[actual] = changes[key]
        changes = {k: v for k, v in changes.items() if k not in ('depth', 'reverse_depth', 'symmetric', 'taper', 'thin_wall', 'diameter')}
    for key, value in changes.items():
        if key == 'spacing':
            for i in range(3): check_binding(raw, feature['spacing'], i)
        else: check_binding(raw, feature, key)
        feature[key] = value
    if feature.get('suppressed'):
        return dict(detail='억제된 피처의 설정을 수정했습니다. 형상에 적용하려면 suppressed=false로 다시 켜세요.')
