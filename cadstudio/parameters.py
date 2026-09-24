"""Bounded arithmetic for persistent CAD dimensions; never eval/execute code."""
import ast
import math
import re
from copy import deepcopy

NAME=re.compile(r'^[^\W\d]\w{0,39}$',re.UNICODE)
FUNCTIONS={'abs':abs,'min':min,'max':max,'sqrt':math.sqrt}
CONSTANTS={'pi':math.pi,'mm':1.,'cm':10.,'m':1000.,'inch':25.4,'deg':1.}


def expression_value(expression,variables=None,resolve=None):
    expression=str(expression).strip().removeprefix('=').strip()
    if not expression or len(expression)>240:raise ValueError('치수 식은 1~240자로 입력하세요.')
    expression=re.sub(r'(?<=\d)\s*(mm|cm|m|inch|deg)\b',r'*\1',expression)
    try:root=ast.parse(expression,mode='eval')
    except SyntaxError:raise ValueError('치수 식의 괄호와 연산자를 확인하세요.') from None
    if len(list(ast.walk(root)))>100:raise ValueError('치수 식이 너무 복잡합니다.')
    variables=variables or {}
    def visit(node):
        if isinstance(node,ast.Expression):value=visit(node.body)
        elif isinstance(node,ast.Constant) and type(node.value) in (float,int):value=node.value
        elif isinstance(node,ast.Name):
            if node.id in CONSTANTS:value=CONSTANTS[node.id]
            elif resolve:value=resolve(node.id)
            elif node.id in variables:value=variables[node.id]
            else:raise ValueError(f'정의되지 않은 변수: {node.id}')
        elif isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):value=visit(node.operand)*(1 if isinstance(node.op,ast.UAdd) else -1)
        elif isinstance(node,ast.BinOp):
            a,b=visit(node.left),visit(node.right)
            if isinstance(node.op,ast.Add):value=a+b
            elif isinstance(node.op,ast.Sub):value=a-b
            elif isinstance(node.op,ast.Mult):value=a*b
            elif isinstance(node.op,ast.Div):value=a/b
            elif isinstance(node.op,ast.Pow) and abs(b)<=8:value=a**b
            else:raise ValueError('사용할 수 없는 치수 연산입니다.')
        elif isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in FUNCTIONS and not node.keywords and 1<=len(node.args)<=8:
            value=FUNCTIONS[node.func.id](*[visit(a) for a in node.args])
        else:raise ValueError('치수에는 숫자·변수·사칙연산·abs/min/max/sqrt만 사용할 수 있습니다.')
        if type(value) not in (float,int) or not math.isfinite(value) or abs(value)>1e9:raise ValueError('치수 계산 결과가 허용 범위를 벗어났습니다.')
        return float(value)
    try:return visit(root)
    except (ZeroDivisionError,OverflowError,TypeError):raise ValueError('0으로 나누거나 유효하지 않은 치수 계산입니다.') from None


def parameter_values(parameters):
    if len(parameters)>64:raise ValueError('변수는 프로젝트당 64개까지 사용할 수 있습니다.')
    values={};stack=[]
    def resolve(name):
        if name in values:return values[name]
        if name not in parameters:raise ValueError(f'정의되지 않은 변수: {name}')
        if not NAME.fullmatch(name) or name in CONSTANTS or name in FUNCTIONS:raise ValueError(f'사용할 수 없는 변수 이름: {name}')
        if name in stack:raise ValueError('변수가 서로 순환 참조합니다: '+' → '.join([*stack,name]))
        stack.append(name)
        try:values[name]=expression_value(parameters[name],resolve=resolve)
        finally:stack.pop()
        return values[name]
    for name in parameters:resolve(name)
    return values


def numeric_node(data,path):
    if not path or path[0] not in ('parts','sketches') or len(path)>20:raise ValueError('변수는 부품 또는 스케치 치수에 연결하세요.')
    node=data
    try:
        for key in path[:-1]:
            if type(key) is int:
                if not isinstance(node,list) or key<0:raise KeyError(key)
                node=node[key]
            elif isinstance(node,list):
                node=next(item for item in node if item.get('id')==key)
            else:node=node[key]
        key=path[-1]
        if type(key) is int and key<0:raise KeyError(key)
        if type(node[key]) not in (int,float):raise ValueError('변수 연결 대상은 숫자 치수여야 합니다.')
        if key in ('face','support_face_count','index','direction','hole_count'):raise ValueError('이 필드는 연속 치수가 아닙니다.')
        return node,key
    except (KeyError,IndexError,TypeError,StopIteration):raise ValueError('변수에 연결된 치수가 삭제되었습니다. 변수 창에서 연결을 해제하세요.') from None


def evaluate_design(data):
    if not isinstance(data,dict):return data
    raw=deepcopy(data)
    for key in ('parts','sketches'):
        if key in raw:
            if not isinstance(raw[key],list):raise ValueError('부품과 스케치는 목록이어야 합니다.')
            raw[key]=[item.model_dump() if hasattr(item,'model_dump') else item for item in raw[key]]
    values=parameter_values(raw.get('parameters',{}));seen=set()
    def sketch_expressions(node):
        if isinstance(node,list):
            for child in node:sketch_expressions(child)
        elif isinstance(node,dict):
            if node.get('kind')=='extrusion':
                if node.get('thickness_expression'):node['thickness']=expression_value(node['thickness_expression'],values)
                for c in node.get('entity_constraints',[]):
                    if c.get('expression'):c['value']=expression_value(c['expression'],values)
            for child in node.values():
                if isinstance(child,(dict,list)):sketch_expressions(child)
    sketch_expressions(raw.get('parts',[]));sketch_expressions(raw.get('sketches',[]))
    for binding in raw.get('dimension_bindings',[]):
        if hasattr(binding,'model_dump'):binding=binding.model_dump()
        path=binding['path'];node,key=numeric_node(raw,path);signature=(id(node),key)
        if signature in seen:raise ValueError('같은 치수에 변수 식을 두 번 연결할 수 없습니다.')
        seen.add(signature);node[key]=expression_value(binding['expression'],values)
    return raw


def _binding_target(data,path):
    try:return numeric_node(data,path)
    except ValueError:return None


def _same_target(data,path,other,target):
    if path==other:return True
    found=_binding_target(data,other)
    return target is not None and found is not None and target[0] is found[0] and target[1]==found[1]


def set_binding(data,path,expression):
    target=_binding_target(data,path)
    bindings=[b for b in data.get('dimension_bindings',[]) if not _same_target(data,path,b['path'],target)]
    if expression:
        value=expression_value(expression,parameter_values(data.get('parameters',{})))
        node,key=numeric_node(data,path);node[key]=value;bindings.append(dict(path=path,expression=expression))
    if bindings:data['dimension_bindings']=bindings
    else:data.pop('dimension_bindings',None)


def binding_for(data,path):
    target=_binding_target(data,path)
    return next((b['expression'] for b in data.get('dimension_bindings',[]) if _same_target(data,path,b['path'],target)),'')


def remove_bindings(data,*prefixes):
    remaining=[b for b in data.get('dimension_bindings',[]) if not any(b['path'][:len(prefix)]==list(prefix) for prefix in prefixes)]
    if remaining:data['dimension_bindings']=remaining
    else:data.pop('dimension_bindings',None)
