"""Optional native providers. The local endpoint is fixed to this PC."""
import json
import asyncio
import threading
import time
import math
from copy import deepcopy
import httpx
from pydantic import ValidationError
from ..planner import AIReply,SYSTEM_PROMPT,openai_draft,ai_design_context,parse_ai_reply
from ..kernel import preview,KERNEL_LOCK

def cloud_draft(request,client,model):
    from openai import APIError,AuthenticationError,RateLimitError,APITimeoutError
    try:return openai_draft(request,client=client,model=model)
    except AuthenticationError:raise ValueError('OpenAI API 키 인증에 실패했습니다. 키를 확인하세요.') from None
    except RateLimitError:raise ValueError('OpenAI 요청 한도 또는 API 잔액을 확인하세요.') from None
    except APITimeoutError:raise ValueError('OpenAI 응답 시간이 초과되었습니다. 더 작은 요청으로 시도하세요.') from None
    except APIError:raise ValueError('OpenAI API 요청에 실패했습니다. 네트워크와 모델 이름을 확인하세요.') from None

class DraftCancelled(Exception):
    pass


def validation_feedback(error):
    """Tell the model which dimensions failed without echoing whole input objects."""
    if isinstance(error,ValidationError):
        details=error.errors(include_url=False,include_input=False,include_context=False)
        return '\n'.join('.'.join(map(str,row['loc']))+': '+row['msg'] for row in details[:6])[:1800]
    return str(error)[:1800]


class DraftControl:
    """Cancel blocked async network reads, including before the first token."""
    def __init__(self):
        self.cancelled=threading.Event();self.lock=threading.Lock();self.loop=None;self.task=None
    def cancel(self):
        self.cancelled.set()
        with self.lock:
            if self.loop and not self.loop.is_closed():self.loop.call_soon_threadsafe(self.task.cancel)
    def check(self):
        if self.cancelled.is_set():raise DraftCancelled('설계 초안 생성을 취소했습니다.')
    async def execute(self,fn,deadline):
        self.check()
        with self.lock:self.loop=asyncio.get_running_loop();self.task=asyncio.current_task()
        try:
            self.check()
            return await asyncio.wait_for(fn(),timeout=deadline)
        except asyncio.CancelledError:raise DraftCancelled('설계 초안 생성을 취소했습니다.') from None
        except asyncio.TimeoutError:raise ValueError('로컬 AI가 제한 시간 안에 완료하지 못했습니다. 부품 하나와 치수부터 요청하거나 더 작은 모델을 선택하세요.') from None
        finally:
            with self.lock:self.loop=None;self.task=None


def ollama_context(design):
    """Rendering caches are not design instructions; keep the real dimensions."""
    def compact(value):
        if isinstance(value,dict):return {k:compact(v) for k,v in value.items() if v is not None and v!=[] and v!={}}
        if isinstance(value,list):return [compact(v) for v in value]
        return value
    data=ai_design_context(design)
    for sketch in data.get('sketches',[]):
        face=sketch.get('context',{}).get('face')
        if face:
            for key in ('outline','projected_entities','projection_unsupported'):face.pop(key,None)
    return compact(data)


def restore_sketch_display(result,current):
    if not current:return
    by_id={s.id:s for s in current.sketches}
    for sketch in result.sketches:
        source=by_id.get(sketch.id)
        if source is None:continue
        old_part=next((p for p in current.parts if p.id==source.context.part_id),None)
        new_part=next((p for p in result.parts if p.id==sketch.context.part_id),None)
        # Display caches are reusable only while their supporting shape stays
        # unchanged. A width edit can leave the face frame unchanged too.
        if old_part and (new_part is None or old_part.geometry!=new_part.geometry or old_part.features!=new_part.features):continue
        old=source.context.face;face=sketch.context.face
        if old and face and sketch.context.part_id==source.context.part_id and sketch.context.support_feature==source.context.support_feature:
            keys=('index','normal','origin','x_direction','face_count')
            if all(getattr(old,k)==getattr(face,k) for k in keys):
                face.outline=deepcopy(old.outline);face.projected_entities=deepcopy(old.projected_entities);face.projection_unsupported=old.projection_unsupported


def ollama_draft(request,model,transport=None,*,control=None,progress=None,deadline=600):
    control=control or DraftControl();progress=progress or (lambda message:None)
    if not model or len(model)>120:raise ValueError('Ollama에 설치된 모델 이름을 입력하세요.')
    if deadline is not None and (not isinstance(deadline,(int,float)) or not math.isfinite(deadline) or deadline<=0):raise ValueError('대기 시간은 양수 또는 무제한이어야 합니다.')
    from .cad_tools import execute_plan
    from .cad_schema import plan_schema
    from .cad_scope import Scope,scope_schema,scope_messages
    async def generate():
        # Selection and generation share one cancellable task, client and total
        # deadline. No blocking model call occurs on the GUI thread.
        async with httpx.AsyncClient(base_url='http://127.0.0.1:11434',timeout=httpx.Timeout(deadline,connect=4),trust_env=False,follow_redirects=False,transport=transport) as client:
            control.check();progress('요청에 필요한 CAD 도구 선택 중…')
            content=await _chat_content(client,_chat_body(model,scope_messages(request),scope_schema(),512,8192),control,progress,'도구 선택')
            try:scope=Scope.parse(content,request)
            except (ValueError,TypeError):
                # Invalid selection only broadens the available tools. It never
                # fabricates a design or hides network/cancellation failures.
                scope=Scope();progress('도구 선택을 해석하지 못해 전체 CAD 도구로 계획합니다…')
            control.check()
            result=await _ollama_reply(client,model,scope.plan_messages(request),control,progress,request.current,
                schema=plan_schema(scope.tools,scope.shapes,single_part=scope.intent=='part'),parser=lambda content:execute_plan(content,request,check=control.check,progress=progress,single_part=scope.intent=='part'),context_size=8192)
            result['planning']=dict(intent=scope.intent,tools=scope.tools,shapes=scope.shapes)
            return result
    result=asyncio.run(control.execute(generate,deadline))
    if request.current:
        from ..models import Design
        design=Design.model_validate(result['design']);restore_sketch_display(design,request.current);result['design']=design.model_dump()
    return result


def _chat_body(model,messages,schema,tokens,context_size):
    body={'model':model,'messages':messages,'stream':True,'format':schema,'options':{'temperature':0,'num_predict':tokens,'num_ctx':context_size}}
    if model.split(':')[0].split('/')[-1]=='qwen3':
        # Qwen's published non-thinking settings avoid repetitive greedy plans.
        body['think']=False
        body['options'].update(temperature=.7,top_p=.8,top_k=20,min_p=0)
    return body


async def _chat_content(client,body,control,progress,phase='설계 생성'):
    try:
        async with client.stream('POST','/api/chat',json=body) as response:
            if response.status_code==404:raise ValueError('Ollama에서 모델을 찾지 못했습니다. 설치된 모델 이름을 확인하세요.')
            if response.status_code!=200:raise ValueError('Ollama 요청에 실패했습니다. 실행 상태와 모델을 확인하세요.')
            chunks=[];size=0;done=False;last_notice=0;received=0;pending=b''
            def consume(line):
                nonlocal done,last_notice,received
                raw=json.loads(line)
                if raw.get('error'):raise ValueError('Ollama 생성 오류: '+str(raw['error'])[:300])
                content=raw.get('message',{}).get('content','')
                if not isinstance(content,str):raise TypeError('Expected text content')
                chunks.append(content);received+=len(content)
                if time.monotonic()-last_notice>.3:
                    progress(f'{phase} 중 · {received:,}자 수신' if received else f'{phase} 준비 중…');last_notice=time.monotonic()
                if raw.get('done'):
                    if raw.get('done_reason')=='length':raise ValueError('로컬 AI가 출력 길이를 초과했습니다. 부품을 나눠서 요청하세요.')
                    done=True
            async for chunk in response.aiter_bytes():
                control.check();size+=len(chunk);pending+=chunk
                if size>2_000_000:raise ValueError('로컬 AI 응답이 너무 큽니다. 설계를 작게 나눠주세요.')
                lines=pending.split(b'\n');pending=lines.pop()
                for line in lines:
                    if line.strip():consume(line)
                    if done:break
                if done:break
            if not done and pending.strip():consume(pending)
        if not done:raise ValueError('로컬 AI 응답이 생성 완료 전에 끊어졌습니다. 다시 시도하세요.')
        return ''.join(chunks)
    except httpx.ConnectError:raise ValueError('Ollama에 연결할 수 없습니다. 이 PC에서 Ollama를 실행하고 모델을 설치하세요.') from None
    except httpx.TimeoutException:raise ValueError('로컬 AI가 설정된 대기 시간 안에 응답하지 않았습니다. CPU에서 큰 모델은 준비 시간이 들 수 있습니다. AI 최대 대기를 늘리거나 부품 하나씩 요청하세요.') from None
    except httpx.HTTPError:raise ValueError('로컬 AI 연결에 실패했습니다.') from None
    except (json.JSONDecodeError,UnicodeDecodeError,AttributeError,TypeError):raise ValueError('Ollama에서 잘못된 응답을 받았습니다. 모델을 확인하고 다시 시도하세요.') from None


async def _ollama_reply(client,model,messages,control,progress,current=None,*,schema=None,parser=None,context_size=16384):
    for attempt in range(3):
        control.check();progress('CAD 작업 순서와 치수 생성 중…' if not attempt else '검증 오류 반영 후 설계 수정 재시도 중…')
        content=await _chat_content(client,_chat_body(model,messages,schema or AIReply.model_json_schema(),8192 if attempt else 4096,context_size),control,progress)
        try:
            control.check();progress('생성 완료 · 치수와 실제 CAD 형상 검증 중…')
            with KERNEL_LOCK:result=parser(content) if parser else parse_ai_reply(content,current);verified=preview(result.design)
            control.check()
            if verified['stats']['collisions']:result.assumptions.append('부품 사이에 체적 간섭이 있습니다. 배치를 확인하세요.')
            steps=getattr(result,'tool_actions',[])
            from .cad_tools import TOOL_LABELS
            return {**result.model_dump(),'changes':[f"{s['step']}. {TOOL_LABELS[s['tool']]} · {s['target']}" for s in steps],'provider':'ollama','attempts':attempt+1}
        except (ValueError,RuntimeError) as exc:
            reason=validation_feedback(exc)
            if attempt==2:raise ValueError('로컬 AI 설계가 3차례의 치수·형상 검증을 통과하지 못했습니다. 현재 설계는 변경되지 않았습니다.\n\n검증 원인:\n'+reason) from None
            messages=messages[:2]+[{'role':'assistant','content':content[:30000]},{'role':'user','content':'CAD 실행에서 다음 오류가 발생했습니다. 해당 작업의 필드와 치수 관계를 수정하세요. 원래 요청을 유지하고 처음부터 실행할 수정된 전체 actions 계획 JSON을 반환하세요. 이미 올바른 작업은 유지하고, 요청 없는 부품을 추가하지 마세요.\n'+reason}]
