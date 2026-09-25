"""Cancellable Responses API transport for the native transactional CAD planner."""
import asyncio
from copy import deepcopy
import json
import math
import time

from .cloud_connection import api_error_message, credentials, make_client

from ..kernel import KERNEL_LOCK, preview
from .cad_scope import Scope, scope_schema, scope_messages
from .cad_schema import plan_schema
from .cad_tools import execute_plan, TOOL_LABELS
from .local_ai import DraftControl, restore_sketch_display, validation_feedback


def response_schema(source):
    """Make optional CAD fields nullable without forcing invented dimensions.

    The sole arbitrary-key object (dimensions.values) uses lossless JSON values
    in a key/value list. Strict API schemas cannot have open dictionaries.
    """
    source = deepcopy(source)
    def convert(node):
        if not isinstance(node, dict):
            return [convert(v) for v in node] if isinstance(node, list) else node
        if node.get('type') == 'object' and node.get('additionalProperties') == {}:
            return dict(type='array', minItems=1, maxItems=24, items=dict(
                type='object', properties={'key': {'type':'string'}, 'value_json': {'type':'string'}},
                required=['key','value_json'], additionalProperties=False),
                description='Dimension changes as key/value_json entries. value_json is the JSON encoding of the value, e.g. 20 or true or a JSON array. Only existing geometry fields.')
        if not node:
            return {'type':'string'}  # Only used by an empty actions array.
        result = {k:convert(v) for k,v in node.items() if k not in ('default','title','discriminator','minLength','maxLength')}
        if 'const' in result:
            value=result.pop('const');result['enum']=[value]
            result['type']='boolean' if isinstance(value,bool) else 'number' if isinstance(value,(int,float)) else 'string'
        if 'oneOf' in result:result['anyOf']=result.pop('oneOf')
        if node.get('type') == 'object':
            required=set(node.get('required',[]))
            result['properties']={key: value if key in required else {'anyOf':[value,{'type':'null'}]}
                                  for key,value in result.get('properties',{}).items()}
            result['required']=list(result['properties']);result['additionalProperties']=False
        return result
    return convert(source)


def decode_plan(content):
    def clean(value):
        if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if v is not None}
        if isinstance(value,list):return [clean(v) for v in value]
        return value
    data=clean(json.loads(content))
    if not isinstance(data,dict):raise ValueError('CAD 작업 계획 객체가 필요합니다.')
    actions=data.get('actions',[])
    if not isinstance(actions,list):raise ValueError('actions는 CAD 작업 목록이어야 합니다.')
    for action in actions:
        if not isinstance(action,dict):raise ValueError('CAD 작업 객체가 필요합니다.')
        if action.get('tool')=='dimensions':
            values=action.get('args',{}).get('values')
            if isinstance(values,list):
                decoded={}
                for row in values:
                    if not isinstance(row,dict) or set(row)!={'key','value_json'} or not isinstance(row['key'],str) or not isinstance(row['value_json'],str):
                        raise ValueError('치수 변경에는 key/value_json 쌍이 필요합니다.')
                    if row['key'] in decoded:raise ValueError('치수 이름이 중복되었습니다: '+row['key'])
                    decoded[row['key']]=json.loads(row['value_json'])
                action['args']['values']=decoded
    return json.dumps(data,ensure_ascii=False)


async def _content(client, model, messages, schema, name, control, progress, effort, api_key=''):
    control.check()
    options=dict(model=model, input=messages, store=False, stream=True,
                 max_output_tokens=4096 if name=='cad_scope' else 16384,
                 text={'format':{'type':'json_schema','name':name,'strict':True,'schema':response_schema(schema)}})
    # Older explicitly chosen non-reasoning models remain usable.
    if model.startswith('gpt-6-'):
        options['reasoning']={'effort':effort}
    response=await client.responses.create(**options)
    chunks=[];size=0;last_notice=0;completed=False
    async with response:
        async for event in response:
            control.check()
            if event.type=='response.output_text.delta':
                size+=len(event.delta)
                if size>2_000_000:raise ValueError('OpenAI 응답이 너무 큽니다. 설계를 나누어 요청하세요.')
                chunks.append(event.delta)
                if time.monotonic()-last_notice>.3:
                    progress(f'OpenAI CAD 계획 수신 중 · {size:,}자');last_notice=time.monotonic()
            elif event.type=='response.refusal.delta':
                raise ValueError('OpenAI가 이 설계 요청에 응답하지 않았습니다. 요청 내용을 확인하세요.')
            elif event.type=='response.completed':
                if event.response.status!='completed':raise ValueError('OpenAI 설계 응답이 완료되지 않았습니다.')
                completed=True
            elif event.type=='response.incomplete':
                raise ValueError('OpenAI 출력이 제한에 도달해 완료되지 않았습니다. 요청을 나누거나 추론 강도를 낮추세요.')
            elif event.type in ('response.failed','error'):
                error=getattr(getattr(event,'response',None),'error',None) if event.type=='response.failed' else event
                body=error.model_dump() if hasattr(error,'model_dump') else {}
                raise ValueError(api_error_message(None,model,api_key=api_key,body=body))
    if not completed or not chunks:raise ValueError('OpenAI 응답이 완료 전에 끊어졌습니다. 현재 설계는 변경되지 않았습니다.')
    return ''.join(chunks)


def generate(request,model,*,api_key,control=None,progress=None,deadline=600,effort='medium',transport=None):
    from openai import APIError
    control=control or DraftControl();progress=progress or (lambda message:None)
    api_key,model=credentials(api_key,model)
    if effort not in ('low','medium','high','xhigh','max'):raise ValueError('지원되지 않는 추론 강도입니다.')
    if deadline is not None and (not isinstance(deadline,(int,float)) or not math.isfinite(deadline) or deadline<=0):
        raise ValueError('대기 시간은 양수 또는 무제한이어야 합니다.')
    async def run():
        async with make_client(api_key,deadline,transport) as client:
            progress('OpenAI · 요청의 부품과 CAD 도구 선택 중…')
            content=await _content(client,model,scope_messages(request),scope_schema(),'cad_scope',control,progress,effort,api_key)
            try:scope=Scope.parse(content,request)
            except (ValueError,TypeError):
                scope=Scope();progress('전체 CAD 도구로 계획합니다…')
            schema=plan_schema(scope.tools,scope.shapes,single_part=scope.intent=='part',connections=scope.connections,
                               new_parts=scope.new_parts,existing_parts=[p.id for p in request.current.parts] if request.current else ())
            messages=scope.plan_messages(request)
            messages[0]['content']+='\nFor this strict output schema: optional fields use null when unused. dimensions.args.values is an array of {key,value_json}; encode each actual dimension value as JSON text. Do not invent unused values.'
            for attempt in range(3):
                control.check();progress('OpenAI · CAD 작업 계획 생성 중…' if not attempt else 'OpenAI · CAD 검증 오류 수정 중…')
                content=await _content(client,model,messages,schema,'cad_plan',control,progress,effort,api_key)
                try:
                    control.check();progress('OpenAI 생성 완료 · 실제 CAD 형상 검증 중…')
                    with KERNEL_LOCK:
                        result=scope.validate_result(execute_plan(decode_plan(content),request,check=control.check,progress=progress,single_part=scope.intent=='part'))
                        verified=preview(result.design)
                    control.check()
                    if verified['stats']['collisions']:result.assumptions.append('부품 사이에 체적 간섭이 있습니다. 배치를 확인하세요.')
                    restore_sketch_display(result.design,request.current)
                    return {**result.model_dump(),'provider':'openai','attempts':attempt+1,
                            'changes':[f"{s['step']}. {TOOL_LABELS[s['tool']]} · {s['target']}" for s in result.tool_actions],
                            'planning':dict(intent=scope.intent,tools=scope.tools,shapes=scope.shapes,connections=scope.connections,new_parts=scope.new_parts)}
                except (ValueError,RuntimeError) as exc:
                    reason=validation_feedback(exc)
                    if attempt==2:raise ValueError('OpenAI 설계가 3차례의 치수·형상 검증을 통과하지 못했습니다. 현재 설계는 변경되지 않았습니다.\n\n검증 원인:\n'+reason) from None
                    messages=messages[:2]+[{'role':'assistant','content':content[:30000]},
                        {'role':'user','content':'CAD 검증 오류를 수정한 전체 계획을 반환하세요. 원래 요청과 올바른 작업을 유지하세요.\n'+reason}]
    try:
        return asyncio.run(control.execute(run,deadline,'OpenAI가 제한 시간 안에 완료하지 못했습니다. AI 최대 대기를 늘리거나 무제한으로 설정할 수 있습니다.'))
    except APIError as exc:raise ValueError(api_error_message(exc,model,api_key=api_key)) from None
