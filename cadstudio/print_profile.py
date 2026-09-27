"""Opt-in, parameter-linked print allowances; no blind global scaling."""
import ast
from copy import deepcopy
from .models import Design, PrintProfile
from .parameters import binding_for, set_binding, numeric_node

PARAMETERS = {'hole': 'printer_hole', 'shaft': 'printer_shaft', 'gap': 'printer_gap'}


def profile_parameters(profile):
    p=PrintProfile.model_validate(profile)
    return {PARAMETERS[role]:format(value if p.enabled else 0,'.14g')
            for role,value in [('hole',p.hole_expansion),('shaft',p.shaft_reduction),('gap',p.gap)]}


def uses_profile(expression):
    if not expression:return False
    tree=ast.parse(expression,mode='eval')
    return any(isinstance(n,ast.Name) and n.id in PARAMETERS.values() for n in ast.walk(tree))


def nominal_expression(expression):
    """Restore the pre-link formula by setting only our allowance variables to 0."""
    class Restore(ast.NodeTransformer):
        def visit_Name(self,node):
            return ast.copy_location(ast.Constant(0),node) if node.id in PARAMETERS.values() else node
        def visit_BinOp(self,node):
            node=self.generic_visit(node)
            zero=lambda n:isinstance(n,ast.Constant) and n.value==0
            if isinstance(node.op,ast.Mult) and (zero(node.left) or zero(node.right)):return ast.Constant(0)
            if isinstance(node.op,(ast.Add,ast.Sub)) and zero(node.right):return node.left
            if isinstance(node.op,ast.Add) and zero(node.left):return node.right
            return node
    return ast.unparse(Restore().visit(ast.parse(expression,mode='eval')))


def print_targets(design):
    raw=design.model_dump() if isinstance(design,Design) else deepcopy(design)
    rows=[]
    def add(part,path,title,role,factor=1):
        node,key=numeric_node(raw,path)
        expr=binding_for(raw,path)
        rows.append(dict(path=path,part=part['id'],label=part['name']+' · '+title,
                         role=role,factor=factor,value=node[key]/factor,expression=expr,
                         linked=uses_profile(expr)))
    for part in raw.get('parts',[]):
        base=['parts',part['id'],'geometry'];g=part['geometry']
        # Thread support references and linked/constraint-driven profiles must be
        # edited at their source; don't offer a dimension that another solver owns.
        if part.get('source_part_id') or any(f.get('kind')=='thread' for f in part.get('features',[])):continue
        if not part.get('profile_sketch_id'):
            if g['kind']=='cylinder':
                add(part,base+['diameter'],'외경','shaft')
                if g.get('bore_diameter',0)>0:add(part,base+['bore_diameter'],'내경','hole')
            if g['kind'] in ('plate','link','bracket') and g.get('hole_count',1)>0 and g.get('hole_diameter',0)>0:
                add(part,base+['hole_diameter'],'구멍 지름','hole')
            if g['kind']=='extrusion':
                for i,hole in enumerate(g.get('holes',[])):
                    add(part,base+['holes',i,'diameter'],f'스케치 구멍 {i+1}','hole')
        for f in part.get('features',[]):
            sketch=f.get('sketch',{})
            if f.get('operation')!='cut' or f.get('suppressed') or f.get('sketch_id') or sketch.get('entity_constraints'):continue
            es=[e for e in sketch.get('entities',[]) if not e.get('construction')]
            # One analytic circle represents a hole, including repeated-hole features.
            if len(es)==1 and es[0]['kind']=='circle':
                add(part,['parts',part['id'],'features',f['id'],'sketch','entities',es[0]['id'],'radius'],f['name']+' · 구멍','hole',.5)
    return rows


def apply_print_profile(raw, profile, selected_paths):
    """Link selected dimensions once; unchecked links restore nominal formulas."""
    data=deepcopy(raw);p=PrintProfile.model_validate(profile)
    if not data.get('print_profile') and set(data.get('parameters',{})).intersection(PARAMETERS.values()):
        raise ValueError('printer_hole / printer_shaft / printer_gap 변수가 이미 있습니다. 기존 변수 이름을 먼저 바꾸세요.')
    rows=print_targets(data);known={tuple(r['path']) for r in rows};selected={tuple(v) for v in selected_paths}
    if not selected<=known:raise ValueError('지원하지 않거나 삭제된 보정 대상입니다. 목록을 다시 여세요.')
    data['print_profile']=p.model_dump();data['parameters']={**data.get('parameters',{}),**profile_parameters(p)}
    for row in rows:
        path=row['path'];expr=row['expression']
        if tuple(path) in selected:
            if row['linked']:continue
            if expr and len(expr)>180:raise ValueError('기존 치수 식이 너무 깁니다: '+row['label'])
            node,key=numeric_node(data,path);base=expr or format(node[key],'.14g')
            sign='-' if row['role']=='shaft' else '+'
            formula=f"({base}) {sign} {PARAMETERS[row['role']]} * {row['factor']:g}"
            set_binding(data,path,formula)
        elif row['linked']:
            set_binding(data,path,nominal_expression(expr))
    return Design.model_validate(data)


def link_print_parts(raw, identifiers):
    """New physical hardware explicitly opts into its project's print allowances."""
    if not raw.get('print_profile'):return Design.model_validate(raw)
    ids=set(identifiers);rows=print_targets(raw)
    selected=[r['path'] for r in rows if r['linked'] or r['part'] in ids]
    return apply_print_profile(raw,raw['print_profile'],selected)
